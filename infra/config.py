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
# No wildcards: these go into the OIDC trust policy.
_GITHUB = re.compile(r"^[A-Za-z0-9._-]+$")

# Cognito accepts https, or http only for localhost; no wildcards, no fragments.
_CALLBACK_URL = re.compile(r"^(https://[^\s*#]+|http://localhost(:\d+)?(/[^\s*#]*)?)$")
# Cognito rejects these words in a hosted-UI domain prefix, and ours starts with the project name.
_COGNITO_RESERVED = ("aws", "amazon", "cognito")
# The SPA's dev server; always an allowed return address for sign-in and sign-out.
LOCAL_CALLBACK_URL = "http://localhost:5173/"

# Platform convention (README, Architecture): the harness lives at
# harness/app/assistant/ and its CloudFormation outputs are Harness<Pascal>*.
HARNESS_NAME = "assistant"
AGENTCORE_TARGET = "default"


# Fargate's supported CPU/memory pairs (MiB). The network spans two zones, so at most two NAT gateways.
_FARGATE_MEMORY = {
    256: (512, 1024, 2048),
    512: tuple(range(1024, 4097, 1024)),
    1024: tuple(range(2048, 8193, 1024)),
    2048: tuple(range(4096, 16385, 1024)),
    4096: tuple(range(8192, 30721, 1024)),
}
MAX_NAT_GATEWAYS = 2


@dataclass(frozen=True)
class Sizing:
    desired_count: int
    cpu: int
    memory: int
    nat_gateways: int = 1  # cost lever: one NAT is a single point of failure for egress, two is one per zone


@dataclass(frozen=True)
class Config:
    name: str
    aws_account: str
    aws_region: str
    github_org: str
    github_repo: str
    harness_arn: str
    harness_endpoint: str
    harness_model_id: str
    model_ids: tuple[str, ...]
    auth_callback_urls: tuple[str, ...]
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

    @property
    def network_stack(self) -> str:
        return f"{self.name}-network"

    def sizing(self, env: str) -> Sizing:
        if env not in self.environments:
            raise ValueError(f"environment {env!r} is not defined in project.toml; valid: {', '.join(self.environments)}")
        return self.environments[env]

    def role_arn(self, role_name: str) -> str:
        return f"arn:aws:iam::{self.aws_account}:role/{role_name}"

    # Sign-in (Cognito)
    @property
    def user_pool(self) -> str:
        return f"{self.name}-users"

    @property
    def app_client(self) -> str:
        return f"{self.name}-web"

    @property
    def cognito_domain_prefix(self) -> str:
        """Unique per region, so the account disambiguates, like the web bucket."""
        return f"{self.name}-{self.aws_account}"

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

    @property
    def load_balancer(self) -> str:
        return f"{self.name}-alb"

    @property
    def log_group(self) -> str:
        return f"/{self.name}/api"

    @property
    def auth_jwt_secret_name(self) -> str:
        return f"{self.name}/auth-jwt-secret"

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
    def harness_logical_name(self) -> str:
        """toPascalId(name): outputs are Harness<this>{Id,Arn,Status,Version,AgentRuntimeArn}."""
        return HARNESS_NAME.title().replace("_", "")

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
        github_repo=project["github_repo"],
        harness_arn=harness.get("arn", ""),
        harness_endpoint=harness["endpoint"],
        harness_model_id=harness["model_id"],
        model_ids=tuple(harness["model_ids"]),
        auth_callback_urls=tuple(raw.get("auth", {}).get("callback_urls", [])),
        environments={env: Sizing(**s) for env, s in raw["environments"].items()},
    )

    errors = []
    if not _NAME.match(config.name):
        errors.append(f"project.name {config.name!r}: 3-24 chars, lowercase letters, digits, single hyphens")
    if not _ACCOUNT.match(config.aws_account):
        errors.append(f"project.aws_account {config.aws_account!r}: must be 12 digits")
    if not _REGION.match(config.aws_region):
        errors.append(f"project.aws_region {config.aws_region!r}: not an AWS region")
    if not _GITHUB.match(config.github_org) or not _GITHUB.match(config.github_repo):
        errors.append("project.github_org / github_repo: letters, digits, '.', '_', '-' only")
    if any(word in config.name for word in _COGNITO_RESERVED):
        errors.append(f"project.name {config.name!r}: must not contain 'aws', 'amazon' or 'cognito' (Cognito domain rule)")
    for url in config.auth_callback_urls:
        if not _CALLBACK_URL.match(url):
            errors.append(f"auth.callback_urls {url!r}: use https://..., or http://localhost, with no '*' or '#'")
    if not config.model_ids:
        errors.append("harness.model_ids: must list at least one model")
    if config.deploys_starter_harness and config.harness_model_id not in config.model_ids:
        errors.append("harness.model_id: must be one of harness.model_ids")
    # The starter harness's endpoints are managed by the platform's
    # point-harness-alias.sh, which only knows these two.
    if config.deploys_starter_harness and config.harness_endpoint not in ("STAGING", "PROD"):
        errors.append("harness.endpoint: must be STAGING or PROD for the starter harness")
    if not config.harness_endpoint:
        errors.append("harness.endpoint: required")
    if not config.environments:
        errors.append("environments: define at least one")
    for env, size in config.environments.items():
        if size.memory not in _FARGATE_MEMORY.get(size.cpu, ()):
            errors.append(f"environments.{env}: cpu={size.cpu}, memory={size.memory} is not a Fargate combination")
        if not 1 <= size.nat_gateways <= MAX_NAT_GATEWAYS:
            errors.append(f"environments.{env}.nat_gateways {size.nat_gateways}: must be 1 to {MAX_NAT_GATEWAYS}")
    if errors:
        raise ValueError(f"{path}:\n  " + "\n  ".join(errors))
    return config
