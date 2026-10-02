"""boto3 session and the readiness probes that use it.

The only place outside repositories/ and harness/ that talks to AWS. Each probe
satisfies services.ports.DependencyProbe and raises AppError, never a botocore
exception.
"""

from functools import cache
from typing import Any

import boto3
from botocore.config import Config

from app.core.config import settings
from app.core.errors import DATA, HARNESS, MisconfiguredError, classify_aws_error

# A probe that hangs is worse than one that fails: keep them short.
_PROBE_CONFIG = Config(connect_timeout=2, read_timeout=3, retries={"max_attempts": 1})


@cache
def session() -> boto3.Session:
    return boto3.Session(region_name=settings.aws_region)


def client(service: str, config: Config | None = None) -> Any:
    return session().client(service, config=config)


class HarnessProbe:
    """GetHarness on the configured ARN: proves it exists and the task can see it."""

    name = "harness"

    def __init__(self, harness_arn: str) -> None:
        self._arn = harness_arn

    def check(self) -> None:
        if not self._arn:
            raise MisconfiguredError(
                "No assistant is configured for this deployment.",
                dependency=HARNESS,
                detail="HARNESS_ARN is empty",
            )
        try:
            client("bedrock-agentcore-control", _PROBE_CONFIG).get_harness(harnessId=self._arn.rsplit("/", 1)[-1])
        except Exception as exc:
            raise classify_aws_error(exc, dependency=HARNESS) from exc


class TableProbe:
    """DescribeTable: the table exists and the task role can reach it."""

    def __init__(self, table_name: str) -> None:
        self._table = table_name
        self.name = f"table:{table_name}"

    def check(self) -> None:
        try:
            client("dynamodb", _PROBE_CONFIG).describe_table(TableName=self._table)
        except Exception as exc:
            raise classify_aws_error(exc, dependency=DATA) from exc
