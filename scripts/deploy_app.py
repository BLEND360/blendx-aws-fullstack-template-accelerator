"""Deploy the app (network, API service, SPA, CloudFront) and print its public URL.

    uv run --project infra python scripts/deploy_app.py --env dev

Needs the roles, data and auth stacks and a harness deployed (`bootstrap.py`, `deploy_data.py`,
`deploy_auth.py`, `deploy_harness.py`), plus Docker and npm. Everything is checked
before anything is created. Then, in order: the stacks (the first time without an image, so the
repository exists), the API image, the stacks again with the image, the SPA, and the public URL as a
sign-in return address (which redeploys auth). Idempotent: run again with nothing changed and it
creates, modifies and invalidates nothing. Needs an AWS account per environment: names carry none.
"""

import argparse
import base64
import hashlib
import mimetypes
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "infra"))

import boto3  # noqa: E402
from botocore.exceptions import ClientError  # noqa: E402

import config  # noqa: E402
import harness_resolve  # noqa: E402
import network_check  # noqa: E402
import projecttoml  # noqa: E402
from bootstrap import cdk  # noqa: E402
from definitions.app import APP_ID  # noqa: E402
from deployment import DeployInputs  # noqa: E402

PROJECT_TOML = config.PROJECT_TOML
WEB = ROOT / "frontend" / "web"
CLOUDFRONT_PREFIX_LIST = "com.amazonaws.global.cloudfront.origin-facing"
# Who deploys what, to tell the operator what to run when a stack they need is not there.
PREREQUISITES = (("roles_stack", "bootstrap.py"), ("data_stack", "deploy_data.py"), ("auth_stack", "deploy_auth.py"))


class DeployError(RuntimeError):
    pass


def run(*cmd: str, cwd: Path = ROOT, env: dict[str, str] | None = None, capture: bool = False, input: str | None = None) -> str:
    exe = shutil.which(cmd[0])
    if not exe:
        raise DeployError(f"{cmd[0]} not found on PATH")
    result = subprocess.run(
        [exe, *cmd[1:]], cwd=cwd, env={**os.environ, **env} if env else None, check=True, input=input, text=True,
        stdout=subprocess.PIPE if capture else None,
    )
    return result.stdout or ""


def outputs(session, stack: str) -> dict[str, str]:
    described = session.client("cloudformation").describe_stacks(StackName=stack)["Stacks"][0]
    return {o["OutputKey"]: o["OutputValue"] for o in described.get("Outputs", [])}


# --- validations and what is resolved from AWS (nothing is created yet) -----------------------------------------


def check_account(c: config.Config, session) -> None:
    caller = session.client("sts").get_caller_identity()["Account"]
    if caller != c.aws_account:
        raise DeployError(
            f"Your credentials are for account {caller}, but project.toml says {c.aws_account}. "
            "Switch profile or fix project.toml."
        )


def require_stacks(c: config.Config, session) -> dict[str, str]:
    """The auth stack's outputs; every prerequisite stack must exist."""
    for attribute, script in PREREQUISITES:
        stack = getattr(c, attribute)
        try:
            found = outputs(session, stack)
        except ClientError as e:
            if "does not exist" not in e.response["Error"]["Message"]:
                raise
            raise DeployError(f"The stack {stack} does not exist yet: run `uv run --project infra python scripts/{script}` first.") from e
        if attribute == "auth_stack":
            auth = found
    return auth


def cloudfront_prefix_list(session) -> str:
    lists = session.client("ec2").describe_managed_prefix_lists(
        Filters=[{"Name": "prefix-list-name", "Values": [CLOUDFRONT_PREFIX_LIST]}]
    )["PrefixLists"]
    if not lists:
        raise DeployError(f"The managed prefix list {CLOUDFRONT_PREFIX_LIST} was not found in this region: CloudFront VPC origins may not be available here.")
    return lists[0]["PrefixListId"]


def require_tools() -> None:
    for tool in ("docker", "npm"):
        if not shutil.which(tool):
            raise DeployError(f"{tool} not found on PATH: it is needed to build and publish the app.")


def gather(c: config.Config, session, env: str) -> tuple[DeployInputs, dict[str, str]]:
    require_tools()
    check_account(c, session)
    network_check.check(c, session)  # a VPC that is not ours is verified, never fixed
    auth = require_stacks(c, session)
    harness_arn, memory_arn = harness_resolve.resolve(c, session)
    inputs = DeployInputs(
        env=env,
        harness_arn=harness_arn,
        memory_arn=memory_arn,
        user_pool_id=auth["UserPoolId"],
        app_client_id=auth["AppClientId"],
        cloudfront_prefix_list=cloudfront_prefix_list(session),
    )
    return inputs, auth


# --- infrastructure and image ----------------------------------------------------------------------------------


def deploy_stacks(c: config.Config, inputs: DeployInputs) -> None:
    stacks = [] if c.uses_existing_network else [c.network_stack]
    context = [arg for k, v in inputs.to_context().items() for arg in ("-c", f"{k}={v}")]
    cdk("deploy", *stacks, c.app_stack, "--exclusively", "--require-approval", "never", *context)


def repository_exists(c: config.Config, session) -> bool:
    try:
        session.client("ecr").describe_repositories(repositoryNames=[c.ecr_repository])
    except ClientError as e:
        if e.response["Error"]["Code"] == "RepositoryNotFoundException":
            return False
        raise
    return True


def build_and_push(c: config.Config, session) -> str:
    """The image's tag is the start of its id: the same build gives the same tag, and a tag already in the repository is not pushed."""
    image = run("docker", "build", "--platform", "linux/amd64", "-q", ".", capture=True).strip()
    tag = image.split(":")[-1][:12]
    registry = f"{c.aws_account}.dkr.ecr.{c.aws_region}.amazonaws.com"
    reference = f"{registry}/{c.ecr_repository}:{tag}"
    ecr = session.client("ecr")
    try:
        ecr.describe_images(repositoryName=c.ecr_repository, imageIds=[{"imageTag": tag}])
        print(f"  image {tag} is already in {c.ecr_repository}")
        return tag
    except ClientError as e:
        if e.response["Error"]["Code"] != "ImageNotFoundException":
            raise
    token = ecr.get_authorization_token()["authorizationData"][0]["authorizationToken"]
    user, password = base64.b64decode(token).decode().split(":", 1)
    run("docker", "login", "--username", user, "--password-stdin", registry, input=password)  # never on the command line
    run("docker", "tag", image, reference)
    run("docker", "push", reference)
    return tag


# --- the SPA, the return address, the end -----------------------------------------------------------------------


# What a browser needs to run or render the bundle, fixed here because on Windows `mimetypes` reads the
# registry, where a program may have registered .js as text/plain (browsers refuse that as a module script).
CONTENT_TYPES = {".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".woff2": "font/woff2", ".map": "application/json"}


def content_type(key: str) -> str:
    return CONTENT_TYPES.get(Path(key).suffix.lower()) or mimetypes.guess_type(key)[0] or "application/octet-stream"


IMMUTABLE = "public,max-age=31536000,immutable"  # hashed bundles never change under the same name
REVALIDATE = "no-cache"  # everything else, the entry page above all


def sync_bucket(session, bucket: str, source: Path) -> bool:
    """Make the bucket hold exactly `source`. True when anything was uploaded or deleted.

    Compares content (the object's MD5 ETag), not modification times: every build rewrites every file,
    so a time-based sync would upload the whole site on a run that changed nothing. The entry page goes
    up last, so nobody is handed a page that points at bundles that are not there yet.
    """
    s3 = session.client("s3")
    remote = {
        obj["Key"]: obj["ETag"].strip('"')
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket)
        for obj in page.get("Contents", [])
    }
    local = {path.relative_to(source).as_posix(): path for path in source.rglob("*") if path.is_file()}
    changed = False
    for key in sorted(local, key=lambda k: (k == "index.html", k)):
        body = local[key].read_bytes()
        if remote.get(key) == hashlib.md5(body).hexdigest():
            continue
        s3.put_object(
            Bucket=bucket, Key=key, Body=body,
            ContentType=content_type(key),
            CacheControl=IMMUTABLE if key.startswith("assets/") else REVALIDATE,
        )
        changed = True
    for key in sorted(remote.keys() - local.keys()):
        s3.delete_object(Bucket=bucket, Key=key)
        changed = True
    return changed


def publish_spa(c: config.Config, session, auth: dict[str, str], app: dict[str, str], *, invalidate: bool = False) -> bool:
    """Build the SPA with the sign-in values, sync the bucket, and clear the CDN's cache if something changed.

    `invalidate` clears it regardless: for when an earlier run published the site but could not clear the cache.
    """
    if not (WEB / "node_modules").exists():
        run("npm", "ci", cwd=WEB)
    run(
        "npm", "run", "build", cwd=WEB,
        env={  # a process variable wins over frontend/web/.env, so a local file cannot leak into the build
            "VITE_COGNITO_REGION": c.aws_region,
            "VITE_COGNITO_USER_POOL_ID": auth["UserPoolId"],
            "VITE_COGNITO_APP_CLIENT_ID": auth["AppClientId"],
            "VITE_COGNITO_DOMAIN": auth["Domain"],
        },
    )
    changed = sync_bucket(session, app[f"{APP_ID}SpaBucket"], WEB / "dist")
    if changed or invalidate:
        try:
            session.client("cloudfront").create_invalidation(
                DistributionId=app[f"{APP_ID}DistributionId"],
                InvalidationBatch={"Paths": {"Quantity": 1, "Items": ["/*"]}, "CallerReference": str(uuid.uuid4())},
            )
        except ClientError as e:
            # The next run finds nothing to upload, so it would not try again: say how to.
            raise DeployError(
                f"The site was published but the CDN's cache could not be cleared ({e.response['Error']['Code']}). "
                "Run the script again with --invalidate."
            ) from e
    return changed


def sign_in_allows(session, auth: dict[str, str], url: str) -> bool:
    """Whether Cognito, not project.toml, already accepts `url`: a failed run can leave the file ahead of the pool."""
    client = session.client("cognito-idp").describe_user_pool_client(UserPoolId=auth["UserPoolId"], ClientId=auth["AppClientId"])
    return url in client["UserPoolClient"].get("CallbackURLs", [])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Deploy the app and print its public URL.")
    parser.add_argument("--env", required=True, help="the environment in project.toml's [environments] to deploy")
    parser.add_argument("--invalidate", action="store_true", help="clear the CDN's cache even if the site did not change")
    args = parser.parse_args(argv)

    try:
        c = config.load(PROJECT_TOML)
        c.sizing(args.env)
        session = boto3.Session(region_name=c.aws_region)
        inputs, auth = gather(c, session, args.env)

        first_time = not repository_exists(c, session)
        if first_time:
            print("First deployment: creating the repository before there is an image to run.")
            deploy_stacks(c, inputs)
        tag = build_and_push(c, session)
        inputs = DeployInputs(**{**vars(inputs), "image_tag": tag})
        deploy_stacks(c, inputs)

        app = outputs(session, c.app_stack)
        publish_spa(c, session, auth, app, invalidate=args.invalidate)

        public_url = app[f"{APP_ID}PublicUrl"]
        return_url = f"{public_url}/"
        if projecttoml.add_callback_url(PROJECT_TOML, return_url):
            print(f"Added {return_url} to [auth] callback_urls in project.toml.")
        if not sign_in_allows(session, auth, return_url):  # asked of Cognito itself, so a failed earlier run heals
            print("Redeploying sign-in so Cognito accepts it.")
            cdk("deploy", c.auth_stack, "--exclusively", "--require-approval", "never")
    except projecttoml.ProjectTomlError as e:
        print(f"{e}\nThen run `uv run --project infra python scripts/deploy_auth.py`.", file=sys.stderr)
        return 1
    except (DeployError, ValueError, KeyError, harness_resolve.HarnessResolveError, network_check.NetworkCheckError) as e:
        print(e, file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as e:
        print(f"`{' '.join(map(str, e.cmd))}` failed (exit {e.returncode}).", file=sys.stderr)
        return 1

    print(f"""
Done. The app is at {public_url}

Create a user to sign in with:

  uv run --project infra python scripts/create_user.py you@example.com
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
