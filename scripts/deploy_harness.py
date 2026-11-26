"""Deploy the starter harness and resolve the (ARN, endpoint) pair the app invokes.

    uv run --project infra python scripts/deploy_harness.py

When project.toml sets harness.arn, nothing is deployed and that ARN and
endpoint are passed through. Otherwise, following the platform's sequence:

  render config -> agentcore validate -> agentcore deploy -> read the version
  from the stack outputs -> point the endpoint at it -> wait for READY

Harness versions are immutable and endpoints are the alias. An unchanged
deploy is a CloudFormation no-op, so no new version is created, and the
endpoint is repointed at the version it already serves.

Needs the agentcore CLI (`npm i -g @aws/agentcore`), the AWS CLI, jq, and bash:
the endpoint steps run the platform's own scripts from scripts/harness/.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "infra"))

import boto3  # noqa: E402

import config  # noqa: E402
import envfile  # noqa: E402
import harness_files  # noqa: E402
from awsutil import cli, load_config, run  # noqa: E402
from harness_resolve import deployed_settings, find_accelerator_harness, stack_harness  # noqa: E402

PLATFORM_SCRIPTS = ROOT / "scripts" / "harness"
BACKEND_ENV = ROOT / "backend" / "api" / ".env"


def platform(script: str, *args: str) -> str:
    return run("bash", str(PLATFORM_SCRIPTS / script), *args, capture=True)


def deploy(c: config.Config) -> str:
    """Deploy the starter harness and point its endpoint at the new version. Returns the harness ARN."""
    harness_files.write(c)
    cdk_app = harness_files.HARNESS_DIR / "agentcore" / "cdk"
    if not (cdk_app / "node_modules").exists():
        run("npm", "ci", cwd=cdk_app)
    run("agentcore", "validate", cwd=harness_files.HARNESS_DIR)
    run("agentcore", "deploy", "-y", "-v", cwd=harness_files.HARNESS_DIR)

    info = json.loads(platform("get-harness-version.sh", c.harness_stack, c.harness_logical_name))
    print(f"{c.harness_stack}: harness {info['id']} at version {info['version']}")

    platform(
        "point-harness-alias.sh",
        "--alias", c.harness_endpoint, "--harness-id", info["id"], "--version", info["version"],
    )
    platform("wait-harness-ready.sh", "--harness-id", info["id"], "--alias", c.harness_endpoint)
    return info["arn"]


def wire_local_api(arn: str, endpoint: str, env: Path | None = None) -> bool:
    """Point the local API's .env at the harness. Returns False when there is no .env (CI, or setup.py not run)."""
    env = env or BACKEND_ENV  # resolved per call, so the file can be redirected
    if not env.exists():
        print(
            f"Not writing HARNESS_ARN to {env}: the file does not exist yet. Run scripts/setup.py first, "
            "then run this step again."
        )
        return False
    envfile.update(env, {"HARNESS_ARN": arn, "HARNESS_ENDPOINT": endpoint})
    print(f"Wrote HARNESS_ARN and HARNESS_ENDPOINT to {env}. Restart the API.")
    return True


def drift(session, c: config.Config, harness_id: str) -> list[str]:
    """The settings that differ between the live harness and this checkout, as readable lines."""
    rendered = harness_files.render(c)["app/assistant/harness.json"]
    want = {"allowedTools": sorted(rendered["allowedTools"]), "modelId": rendered["model"]["modelId"]}
    live = deployed_settings(session, harness_id)
    return [f"{key}: {live[key]!r} -> {want[key]!r}" for key in want if live[key] != want[key]]


def confirm(question: str) -> bool:
    return sys.stdin.isatty() and input(f"{question} [y/N] ").strip().lower() == "y"


@cli
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Deploy or reuse the starter harness, and wire the local API to it.")
    parser.add_argument(
        "--update", action="store_true",
        help="apply this checkout's harness settings to this project's own harness. Other projects that reuse it "
             "start using the new version too, so the changes are shown and must be confirmed.",
    )
    args = parser.parse_args(argv)

    c = load_config()
    session = boto3.Session(region_name=c.aws_region)
    own = stack_harness(c, session) if c.deploys_starter_harness else None

    if own and not args.update:
        print(f"This project's harness {own['arn']} is already deployed (version {own['version']}). Nothing changed. "
              "Run with --update to apply this checkout's settings.")
        arn = own["arn"]
    elif own:
        changes = drift(session, c, own["id"])
        if not changes:
            print(f"The harness {own['arn']} already matches this checkout. Nothing to apply.")
            arn = own["arn"]
        else:
            print(f"Applying these changes to {own['arn']}, which other projects may reuse:")
            print("\n".join(f"  {line}" for line in changes))
            if not confirm("Apply them?"):
                print("Not applied. Nothing was changed.")
                return 1
            arn = deploy(c)
    elif c.deploys_starter_harness and (shared := find_accelerator_harness(session)):
        print(f"This account already has the accelerator harness {shared}. Reusing it; nothing is deployed.")
        arn = shared
    elif c.deploys_starter_harness:
        arn = deploy(c)
    else:
        print(
            f"Skipping the starter harness: project.toml sets harness.arn = {c.harness_arn!r}. "
            "Nothing is deployed and no deployed harness is touched."
        )
        arn = c.harness_arn
    wire_local_api(arn, c.harness_endpoint)
    print(f"harness_arn={arn}\nharness_endpoint={c.harness_endpoint}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
