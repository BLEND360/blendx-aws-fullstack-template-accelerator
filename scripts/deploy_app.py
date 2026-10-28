"""Deploy the app (network, API service, SPA, CloudFront) and print its public URL.

    uv run --project infra python scripts/deploy_app.py --env dev

Needs the roles, data and auth stacks and a harness deployed (`bootstrap.py`, `deploy_data.py`,
`deploy_auth.py`, `deploy_harness.py`). A full run needs Docker and npm; individual steps check only their tool. Everything is checked
before anything is created. Then, in order: the stacks (the first time without an image, so the
repository exists), the API image, the stacks again with the image, the SPA, and the public URL as a
sign-in return address (which redeploys auth). Idempotent: run again with nothing changed and it
creates, modifies and invalidates nothing. `--env` selects the sizing only: names carry no environment, so
there is one deployed environment per project.toml and account.
"""

import argparse
import dataclasses
import hashlib
import json
import mimetypes
import os
import re
import shutil
import sys
import tempfile
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
from awsutil import DeployError, cdk, check_account, cli, load_config, outputs, run  # noqa: E402
from definitions.app import APP_ID  # noqa: E402
from deployment import DeployInputs  # noqa: E402

PROJECT_TOML = config.PROJECT_TOML
WEB = ROOT / "frontend" / "web"
CLOUDFRONT_PREFIX_LIST = "com.amazonaws.global.cloudfront.origin-facing"
_IMAGE_TAG = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")


# --- validations and what is resolved from AWS (nothing is created yet) -----------------------------------------


def require_stacks(c: config.Config, session) -> dict[str, str]:
    """The auth stack's outputs; every prerequisite stack must exist."""
    found = {}
    for stack, script in ((c.roles_stack, "bootstrap.py"), (c.data_stack, "deploy_data.py"), (c.auth_stack, "deploy_auth.py")):
        try:
            found[stack] = outputs(session, stack)
        except ClientError as e:
            if "does not exist" not in e.response["Error"]["Message"]:
                raise
            raise DeployError(f"The stack {stack} does not exist yet: run `uv run --project infra python scripts/{script}` first.") from e
    return found[c.auth_stack]


def cloudfront_prefix_list(session) -> str:
    lists = session.client("ec2").describe_managed_prefix_lists(
        Filters=[{"Name": "prefix-list-name", "Values": [CLOUDFRONT_PREFIX_LIST]}]
    )["PrefixLists"]
    if not lists:
        raise DeployError(f"The managed prefix list {CLOUDFRONT_PREFIX_LIST} was not found in this region: CloudFront VPC origins may not be available here.")
    return lists[0]["PrefixListId"]


def require_tools(*tools: str) -> None:
    for tool in tools:
        if not shutil.which(tool):
            raise DeployError(f"{tool} not found on PATH: it is needed to build and publish the app.")


def gather(
    c: config.Config, session, env: str, *, tools: tuple[str, ...] = ("docker", "npm")
) -> tuple[DeployInputs, dict[str, str]]:
    require_tools(*tools)
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


def build_and_push(c: config.Config, session, image_tag: str | None = None) -> str:
    """The image's tag follows its layers: the same code gives the same tag, and a tag already in the repository is not pushed.

    Not the image id: BuildKit stamps every image with its build time, so the id changes on every build
    even when nothing did, and a repeat run would redeploy the service (seen on the first real deployment).
    """
    if image_tag and not _IMAGE_TAG.fullmatch(image_tag):
        raise DeployError(f"Invalid image tag: {image_tag!r}.")
    image = run("docker", "build", "--platform", "linux/amd64", "-q", ".", capture=True).strip()
    layers = json.loads(run("docker", "image", "inspect", "--format", "{{json .RootFS.Layers}}", image, capture=True))
    tag = image_tag or hashlib.sha256("\n".join(layers).encode()).hexdigest()[:12]
    registry = f"{c.aws_account}.dkr.ecr.{c.aws_region}.amazonaws.com"
    reference = f"{registry}/{c.ecr_repository}:{tag}"
    ecr = session.client("ecr")
    try:
        ecr.describe_images(repositoryName=c.ecr_repository, imageIds=[{"imageTag": tag}])
        if image_tag:
            raise DeployError(f"Image tag {tag} already exists in {c.ecr_repository}; refusing to overwrite it.")
        print(f"  image {tag} is already in {c.ecr_repository}")
        return tag
    except ClientError as e:
        if e.response["Error"]["Code"] != "ImageNotFoundException":
            raise
    token = ecr.get_authorization_token()["authorizationData"][0]["authorizationToken"]  # already base64("AWS:<password>")
    run("docker", "tag", image, reference)
    # No `docker login`: it stores the token in the user's credential store, and Windows' caps a credential at
    # 2560 bytes while an ECR token is longer ("error storing credentials"). Docker reads `auths` straight from
    # a config file, so a throwaway one holds the token for the push and is deleted with it.
    with tempfile.TemporaryDirectory(prefix="docker-config-") as config_dir:
        Path(config_dir, "config.json").write_text(json.dumps({"auths": {registry: {"auth": token}}}), encoding="utf-8")
        run("docker", "push", reference, env={"DOCKER_CONFIG": config_dir})
    return tag


def current_image_tag(c: config.Config, session) -> str | None:
    """Return the tag used by the service, or None when it has no deployable image."""
    ecs = session.client("ecs")
    try:
        response = ecs.describe_services(cluster=c.cluster, services=[c.service])
    except ClientError as error:
        if error.response["Error"]["Code"] in {"ClusterNotFoundException", "ServiceNotFoundException"}:
            return None
        raise
    services = response.get("services", [])
    if len(services) != 1 or not services[0].get("taskDefinition"):
        return None
    task = ecs.describe_task_definition(taskDefinition=services[0]["taskDefinition"])["taskDefinition"]
    containers = task.get("containerDefinitions", [])
    if len(containers) != 1:
        return None
    image = containers[0].get("image", "")
    tag = image.rsplit(":", 1)[-1] if ":" in image else ""
    return tag if tag and tag != "pending" else None


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


def emit_output(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as stream:
            stream.write(f"{name}={value}\n")


def deploy_spa(c: config.Config, session, auth: dict[str, str], *, invalidate: bool) -> str:
    app = outputs(session, c.app_stack)
    publish_spa(c, session, auth, app, invalidate=invalidate)
    public_url = app[f"{APP_ID}PublicUrl"]
    return_url = f"{public_url}/"
    if projecttoml.add_callback_url(PROJECT_TOML, return_url):
        print(f"Added {return_url} to [auth] callback_urls in project.toml.")
    if not sign_in_allows(session, auth, return_url):
        print("Redeploying sign-in so Cognito accepts it.")
        cdk("deploy", c.auth_stack, "--exclusively", "--require-approval", "never")
    return public_url


@cli
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Deploy the app and print its public URL.")
    parser.add_argument("--env", required=True, help="the environment in project.toml's [environments] to deploy")
    parser.add_argument("--invalidate", action="store_true", help="clear the CDN's cache even if the site did not change")
    parser.add_argument("--step", action="append", choices=("image", "stack", "spa"), help="run only these steps, in image/stack/spa order")
    parser.add_argument("--image-tag", help="use this image tag for the image and/or stack step")
    parser.add_argument("--keep-image", action="store_true", help="keep the image tag currently used by ECS during the stack step")
    args = parser.parse_args(argv)

    try:
        c = load_config(PROJECT_TOML)
        c.sizing(args.env)
        session = boto3.Session(region_name=c.aws_region)
        steps = ["image", "stack", "spa"] if not args.step else [name for name in ("image", "stack", "spa") if name in args.step]
        if args.keep_image and (args.step is None or "stack" not in steps or "image" in steps or args.image_tag):
            raise DeployError("--keep-image requires the stack step and cannot be combined with --image-tag.")
        if args.image_tag and not _IMAGE_TAG.fullmatch(args.image_tag):
            raise DeployError(f"Invalid image tag: {args.image_tag!r}.")
        if args.step and "stack" in steps and "image" not in steps and not args.image_tag and not args.keep_image:
            raise DeployError("The stack step requires --image-tag or --keep-image.")

        tools = tuple(tool for step, tool in (("image", "docker"), ("spa", "npm")) if step in steps)
        inputs, auth = gather(c, session, args.env, tools=tools)
        image_tag = args.image_tag
        public_url = None

        for step in steps:
            if step == "image":
                if not repository_exists(c, session):
                    print("First deployment: creating the repository before there is an image to run.")
                    deploy_stacks(c, inputs)
                image_tag = build_and_push(c, session, image_tag)
                emit_output("image_tag", image_tag)
            elif step == "stack":
                if args.keep_image:
                    image_tag = current_image_tag(c, session)
                    if not image_tag:
                        raise DeployError("The ECS service has no deployable image; run the image step or a full deployment first.")
                if not image_tag:
                    raise DeployError("The stack step requires an image tag; pass --image-tag or --keep-image.")
                inputs = dataclasses.replace(inputs, image_tag=image_tag)
                deploy_stacks(c, inputs)
            else:
                public_url = deploy_spa(c, session, auth, invalidate=args.invalidate)
    except projecttoml.ProjectTomlError as e:
        print(f"{e}\nThen run `uv run --project infra python scripts/deploy_auth.py`.", file=sys.stderr)
        return 1

    if public_url:
        print(f"App public URL: {public_url}")
    if not args.step:
        print(f"\nDone. The app is at {public_url}\n\nCreate a user to sign in with:\n\n  uv run --project infra python scripts/create_user.py you@example.com")
    return 0


if __name__ == "__main__":
    sys.exit(main())
