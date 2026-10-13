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

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "infra"))

import config  # noqa: E402
import harness_files  # noqa: E402

PLATFORM_SCRIPTS = ROOT / "scripts" / "harness"


def run(*cmd: str, cwd: Path = ROOT, capture: bool = False) -> str:
    exe = shutil.which(cmd[0])
    if not exe:
        sys.exit(f"{cmd[0]} not found on PATH")
    stdout = subprocess.PIPE if capture else None
    return subprocess.run([exe, *cmd[1:]], cwd=cwd, check=True, stdout=stdout, text=True).stdout


def platform(script: str, *args: str) -> str:
    return run("bash", str(PLATFORM_SCRIPTS / script), *args, capture=True)


def emit(arn: str, endpoint: str) -> None:
    """Hand the resolved pair to the next pipeline step."""
    print(f"harness_arn={arn}\nharness_endpoint={endpoint}")
    if out := os.environ.get("GITHUB_OUTPUT"):
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"harness_arn={arn}\nharness_endpoint={endpoint}\n")


def main() -> int:
    c = config.load()

    if not c.deploys_starter_harness:
        print(
            f"Skipping the starter harness: project.toml sets harness.arn = {c.harness_arn!r}. "
            "Nothing is deployed and no deployed harness is touched."
        )
        emit(c.harness_arn, c.harness_endpoint)
        return 0

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

    emit(info["arn"], c.harness_endpoint)
    return 0


if __name__ == "__main__":
    sys.exit(main())
