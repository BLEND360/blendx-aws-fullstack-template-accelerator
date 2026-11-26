"""Show the read-only CDK template diff for the project and, when resolvable, the app stacks."""

import argparse
import dataclasses
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "infra"))

import boto3  # noqa: E402

import deploy_app  # noqa: E402
from awsutil import CDK, INFRA, DeployError, check_account, cli, load_config, run  # noqa: E402
from deployment import DeployInputs  # noqa: E402
from harness_resolve import HarnessResolveError  # noqa: E402
from network_check import NetworkCheckError  # noqa: E402


def command(stacks: list[str], inputs: DeployInputs | None = None) -> list[str]:
    args = ["diff", *stacks, "--method=template", "--exclusively"]
    if inputs:
        args.extend(arg for key, value in inputs.to_context().items() for arg in ("-c", f"{key}={value}"))
    return args


def write_summary(title: str, output: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as stream:
            stream.write(f"## {title}\n\n```diff\n{output.rstrip()}\n```\n\n")


def run_diff(title: str, stacks: list[str], inputs: DeployInputs | None = None) -> None:
    output = run(*CDK, *command(stacks, inputs), cwd=INFRA, capture=True)
    print(output)
    write_summary(title, output)


@cli
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", required=True, help="environment whose app stack will be diffed")
    args = parser.parse_args()

    c = load_config()
    c.sizing(args.env)
    session = boto3.Session(region_name=c.aws_region)
    check_account(c, session)
    run_diff("Identity, auth and data", [c.roles_stack, c.auth_stack, c.data_stack])

    try:
        inputs, _auth = deploy_app.gather(c, session, args.env, tools=())
        inputs = dataclasses.replace(inputs, image_tag=deploy_app.current_image_tag(c, session) or "")
    except (DeployError, HarnessResolveError, NetworkCheckError) as error:
        message = f"App diff skipped: {error}"
        print(message)
        write_summary("App diff skipped", message)
        return 0

    stacks = [] if c.uses_existing_network else [c.network_stack]
    stacks.append(c.app_stack)
    run_diff("Network and app", stacks, inputs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
