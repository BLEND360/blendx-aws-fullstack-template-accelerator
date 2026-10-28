"""Deploy the whole project with one command.

    uv run --project infra python scripts/deploy.py --env dev

In order: the account setup (CDK bootstrap, OIDC provider, roles), the data, the sign-in, the starter
harness (skipped when project.toml points at an existing one) and the app, ending with the public URL.
Each step is the script you could run on its own, and each is idempotent, so on a project that is
already deployed this changes nothing, and after a failure you run the same command again.

Before the first step it asks the account (a dry-run, nothing is created) whether this user can create an
internet gateway. Some organizations forbid it; then the template cannot create its own VPC, and you are
told to use an existing one (`find_network.py` to find it, `prepare_network.py` to make it fit) before
anything has been deployed.
"""

import argparse
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(ROOT / "infra"))

import boto3  # noqa: E402
from botocore.exceptions import ClientError  # noqa: E402

import config  # noqa: E402
from awsutil import DeployError, cli, load_config, outputs  # noqa: E402
from definitions.app import APP_ID  # noqa: E402


def steps(c: config.Config, env: str) -> list[tuple[str, list[str]]]:
    """(script, its arguments), in the order they run."""
    plan = [("bootstrap.py", []), ("deploy_data.py", []), ("deploy_auth.py", [])]
    if c.deploys_starter_harness:
        plan.append(("deploy_harness.py", []))
    plan.append(("deploy_app.py", ["--env", env]))
    return plan


def can_create_network(c: config.Config, session) -> bool:
    """Whether the template can create its VPC here. A project that uses an existing VPC never needs to."""
    if c.uses_existing_network:
        return True
    try:
        session.client("ec2").create_internet_gateway(DryRun=True)  # a dry-run: it only reports whether it would be allowed
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code == "DryRunOperation":
            return True
        if code == "UnauthorizedOperation":  # the only answer that means "forbidden"; anything else (an expired token) says nothing about it
            return False
        raise
    return True


@cli
def main(argv: list[str] | None = None, *, cfg: config.Config | None = None, session=None, runner: Callable = subprocess.run) -> int:
    parser = argparse.ArgumentParser(description="Deploy the whole project.")
    parser.add_argument("--env", required=True, help="the environment in project.toml's [environments] to deploy")
    args = parser.parse_args(argv)

    c = cfg if cfg is not None else load_config()
    session = session or boto3.Session(region_name=c.aws_region)
    c.sizing(args.env)
    if not can_create_network(c, session):
        raise DeployError(
            "Your organization does not let this user create an internet gateway, so the template cannot create its own VPC.\n"
            "Use a VPC that already exists:\n"
            "  1. uv run --project infra python scripts/find_network.py       # which VPC and subnets can host the app\n"
            "  2. uv run --project infra python scripts/prepare_network.py    # if none can, adds private subnets and a NAT to one\n"
            "  3. put the [network] block they print in project.toml, then run this command again."
        )
    for script, extra in steps(c, args.env):
        print(f"\n=== {script} ===", flush=True)
        done = runner([sys.executable, str(SCRIPTS / script), *extra], cwd=ROOT)
        if done.returncode != 0:
            raise DeployError(
                f"{script} failed (exit {done.returncode}). Fix the cause and run the same command again: the steps that "
                f"finished change nothing.\n  uv run --project infra python scripts/deploy.py --env {args.env}\n"
                f"or only this step:\n  uv run --project infra python scripts/{script} {' '.join(extra)}".rstrip()
            )
    url = outputs(session, c.app_stack).get(f"{APP_ID}PublicUrl")
    if url is None:
        raise DeployError(f"The stack {c.app_stack} has no {APP_ID}PublicUrl output, so there is no URL to show.")

    print(f"""
All steps done. The app is at {url}

Create a user to sign in with:

  uv run --project infra python scripts/create_user.py you@example.com

To see what deleting would remove (it deletes nothing without --confirm), and what it saves per day:

  uv run --project infra python scripts/destroy_app.py

then add `--confirm <project-name>` to delete the app and its network, and `--everything` to delete as well the
data, users, harness and roles.
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
