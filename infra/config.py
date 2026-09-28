"""Reads project.toml and derives every resource name.

Stacks, scripts and CI take names from here; no resource name is written
literally anywhere else.
"""

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

PROJECT_TOML = Path(__file__).resolve().parent.parent / "project.toml"

# Lowercase, hyphenated, short enough that the longest derived name (the S3
# bucket) stays under 63 chars.
_NAME = re.compile(r"^[a-z](?!.*--)[a-z0-9-]{1,22}[a-z0-9]$")
_ACCOUNT = re.compile(r"^\d{12}$")
_REGION = re.compile(r"^[a-z]{2}(-[a-z]+)+-\d$")

# Platform convention (01-technical-proposal.md §2.4): the harness lives at
# harness/app/assistant/ and its CloudFormation outputs are Harness<Pascal>*.
HARNESS_NAME = "assistant"
AGENTCORE_TARGET = "default"


@dataclass(frozen=True)
class Sizing:
    desired_count: int
    cpu: int
    memory: int


@dataclass(frozen=True)
class Config:
    name: str
    aws_account: str
    aws_region: str
    github_org: str
    harness_arn: str
    harness_endpoint: str
    harness_model_id: str
    model_ids: tuple[str, ...]
    environments: dict[str, Sizing]

    # Stacks
    @property
    def roles_stack(self) -> str:
        return f"{self.name}-roles"

    @property
    def auth_stack(self) -> str:
        return f"{self.name}-auth"

    @property
    def data_stack(self) -> str:
        return f"{self.name}-data"

    @property
    def app_stack(self) -> str:
        return f"{self.name}-app"

    # Compute
    @property
    def ecr_repository(self) -> str:
        return self.name

    @property
    def cluster(self) -> str:
        return f"{self.name}-cluster"

    @property
    def service(self) -> str:
        return f"{self.name}-api"

    # Data
    @property
    def sessions_table(self) -> str:
        return f"{self.name}-sessions"

    @property
    def items_table(self) -> str:
        return f"{self.name}-items"

    # IAM
    @property
    def deploy_role(self) -> str:
        return f"{self.name}-github-deploy"

    @property
    def task_role(self) -> str:
        return f"{self.name}-task"

    @property
    def execution_role(self) -> str:
        return f"{self.name}-execution"

    @property
    def harness_execution_role(self) -> str:
        return f"{self.name}-harness-execution"

    # Frontend. Bucket names are global, so account and region disambiguate.
    @property
    def web_bucket(self) -> str:
        return f"{self.name}-web-{self.aws_account}-{self.aws_region}"

    # Starter harness, named per the platform convention
    @property
    def agentcore_project(self) -> str:
        return self.name.replace("-", "")  # agentcore.json names are alphanumeric

    @property
    def harness_stack(self) -> str:
        return f"AgentCore-{self.agentcore_project}-{AGENTCORE_TARGET}"

    @property
    def harness_output_prefix(self) -> str:
        return "Harness" + HARNESS_NAME.title().replace("_", "")

    @property
    def deploys_starter_harness(self) -> bool:
        return not self.harness_arn


def load(path: Path = PROJECT_TOML) -> Config:
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    project, harness = raw["project"], raw["harness"]

    config = Config(
        name=project["name"],
        aws_account=str(project["aws_account"]),
        aws_region=project["aws_region"],
        github_org=project["github_org"],
        harness_arn=harness.get("arn", ""),
        harness_endpoint=harness["endpoint"],
        harness_model_id=harness["model_id"],
        model_ids=tuple(harness["model_ids"]),
        environments={env: Sizing(**s) for env, s in raw["environments"].items()},
    )

    errors = []
    if not _NAME.match(config.name):
        errors.append(f"project.name {config.name!r}: 3-24 chars, lowercase letters, digits, single hyphens")
    if not _ACCOUNT.match(config.aws_account):
        errors.append(f"project.aws_account {config.aws_account!r}: must be 12 digits")
    if not _REGION.match(config.aws_region):
        errors.append(f"project.aws_region {config.aws_region!r}: not an AWS region")
    if not config.model_ids:
        errors.append("harness.model_ids: must list at least one model")
    if config.deploys_starter_harness and config.harness_model_id not in config.model_ids:
        errors.append("harness.model_id: must be one of harness.model_ids")
    if not config.environments:
        errors.append("environments: define at least one")
    if errors:
        raise ValueError(f"{path}:\n  " + "\n  ".join(errors))
    return config
