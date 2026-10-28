"""Find the harness the app will invoke, and the memory it keeps conversations in.

The deploy script needs both ARNs to scope the task role's permissions to exactly them. The harness
comes from project.toml (`harness.arn`) or, for the starter harness, from its stack's outputs; the
memory is whatever the harness says it uses, found the way the backend finds it (GetHarness). If
either cannot be found it raises and names what is missing: a permission is never widened to cope.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "infra"))

from botocore.exceptions import ClientError  # noqa: E402

import config  # noqa: E402
from awsutil import DeployError  # noqa: E402

_MEMORY_ARN = re.compile(r"^arn:aws:bedrock-agentcore:[a-z0-9-]+:\d{12}:memory/[A-Za-z0-9_-]+$")


class HarnessResolveError(DeployError):
    pass


def resolve(c: config.Config, session) -> tuple[str, str]:
    """(harness_arn, memory_arn)."""
    harness_arn = c.harness_arn or starter_harness_arn(c, session)
    return harness_arn, _memory_arn(session, harness_arn)


def starter_harness_arn(c: config.Config, session) -> str:
    try:
        stack = session.client("cloudformation").describe_stacks(StackName=c.harness_stack)["Stacks"][0]
    except ClientError as e:
        if "does not exist" in e.response["Error"]["Message"]:
            raise HarnessResolveError(
                f"The starter harness stack {c.harness_stack} does not exist: deploy it first with "
                "`uv run --project infra python scripts/deploy_harness.py` (or set harness.arn in project.toml)."
            ) from e
        raise HarnessResolveError(f"Cannot read the stack {c.harness_stack}: {e.response['Error']['Code']}") from e
    # The agentcore CDK construct nests its outputs, so the key is <Scope>Harness<Name>ArnOutput<hash>,
    # as scripts/harness/get-harness-version.sh matches it. AgentRuntimeArn is a different output.
    needle = f"Harness{c.harness_logical_name}ArnOutput"
    outputs = {o["OutputKey"]: o["OutputValue"] for o in stack.get("Outputs", [])}
    for key, value in outputs.items():
        if needle in key:
            return value
    raise HarnessResolveError(
        f"The stack {c.harness_stack} has no output containing {needle!r}. Its outputs: {', '.join(outputs) or 'none'}."
    )


def _memory_arn(session, harness_arn: str) -> str:
    try:
        harness = session.client("bedrock-agentcore-control").get_harness(harnessId=harness_arn.rsplit("/", 1)[-1])["harness"]
    except ClientError as e:
        code = e.response["Error"]["Code"]
        hint = " The operator needs bedrock-agentcore:GetHarness." if code.startswith("AccessDenied") else ""
        raise HarnessResolveError(f"Cannot read the harness {harness_arn} ({code}).{hint}") from e
    configuration = harness.get("memory") or {}
    for kind in ("managedMemoryConfiguration", "agentCoreMemoryConfiguration"):
        arn = (configuration.get(kind) or {}).get("arn", "")
        if arn and not _MEMORY_ARN.match(arn):
            raise HarnessResolveError(f"The harness {harness_arn} reports a memory that is not a concrete memory ARN: {arn!r}.")
        if arn:
            return arn
    raise HarnessResolveError(f"The harness {harness_arn} has no memory (configured: {', '.join(configuration) or 'none'}).")
