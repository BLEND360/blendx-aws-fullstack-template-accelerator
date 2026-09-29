"""Renders the starter harness's agentcore config from project.toml.

The agentcore CLI reads three JSON files under harness/. They are derived, like
the .env files, so they are gitignored and rendered by setup.py and again by
the deploy step: project.toml stays the only place their values live.
"""

import json
from pathlib import Path

from config import AGENTCORE_TARGET, HARNESS_NAME, Config

HARNESS_DIR = Path(__file__).resolve().parent.parent / "harness"


def render(c: Config) -> dict[str, dict | list]:
    """Relative path under harness/ -> file content."""
    return {
        "agentcore/agentcore.json": {
            "$schema": "https://schema.agentcore.aws.dev/v1/agentcore.json",
            "name": c.agentcore_project,
            "version": 1,
            "managedBy": "CDK",
            "tags": {"agentcore:created-by": "agentcore-cli", "agentcore:project-name": c.name},
            "runtimes": [],
            "memories": [],
            "knowledgeBases": [],
            "credentials": [],
            "evaluators": [],
            "onlineEvalConfigs": [],
            "agentCoreGateways": [],
            "policyEngines": [],
            "configBundles": [],
            "abTests": [],
            "harnesses": [{"name": HARNESS_NAME, "path": f"app/{HARNESS_NAME}"}],
            "datasets": [],
            "payments": [],
        },
        "agentcore/aws-targets.json": [
            {
                "name": AGENTCORE_TARGET,
                "description": f"{c.name} ({c.aws_region})",
                "account": c.aws_account,
                "region": c.aws_region,
            }
        ],
        # A model and managed memory, nothing else: no tools, skills or gateways.
        f"app/{HARNESS_NAME}/harness.json": {
            "name": HARNESS_NAME,
            "model": {"provider": "bedrock", "modelId": c.harness_model_id},
            "executionRoleArn": c.role_arn(c.harness_execution_role),
            "memory": {"mode": "managed"},
        },
    }


def write(c: Config, root: Path = HARNESS_DIR) -> None:
    for rel, content in render(c).items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(content, indent=2) + "\n", encoding="utf-8")
