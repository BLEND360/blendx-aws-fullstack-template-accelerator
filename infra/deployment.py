"""What is only known when the app is deployed, gathered and validated in one place.

scripts/deploy_app.py resolves these from AWS and hands them to the CDK app as context
(`to_context`); infra/app.py reads them back (`from_context`). Passing them as plain
context, not CloudFormation exports, keeps the stacks deployable in any order.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass

from config import Config

_PREFIX_LIST = re.compile(r"^pl-[0-9a-f]+$")
# A docker tag: no spaces, at most 128 characters.
_IMAGE_TAG = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")
# A concrete resource, never a wildcard: these end up in IAM policies.
_RESOURCE_ID = r"[A-Za-z0-9_-]+"


@dataclass(frozen=True)
class DeployInputs:
    env: str
    harness_arn: str
    memory_arn: str
    user_pool_id: str
    app_client_id: str
    cloudfront_prefix_list: str
    image_tag: str = ""  # empty: the service is created with no tasks until an image exists

    @classmethod
    def from_context(cls, c: Config, get: Callable[[str], object]) -> "DeployInputs":
        def text(key: str) -> str:
            value = get(key)
            return "" if value is None else str(value)

        values = {key: text(key) for key in cls.__dataclass_fields__}
        prefix = f"arn:aws:bedrock-agentcore:{c.aws_region}:{c.aws_account}"
        errors = []

        if not values["env"]:
            errors.append("env: required (the environment to deploy, e.g. -c env=dev)")
        else:
            try:
                c.sizing(values["env"])
            except ValueError as e:
                errors.append(f"env: {e}")
        for key, kind in (("harness_arn", "harness"), ("memory_arn", "memory")):
            if not re.fullmatch(rf"{re.escape(prefix)}:{kind}/{_RESOURCE_ID}", values[key]):
                errors.append(f"{key}: expected {prefix}:{kind}/<id>, got {values[key]!r}")
        for key in ("user_pool_id", "app_client_id"):
            if not values[key]:
                errors.append(f"{key}: required (an output of the {c.auth_stack} stack)")
        if not _PREFIX_LIST.match(values["cloudfront_prefix_list"]):
            errors.append(f"cloudfront_prefix_list: expected a managed prefix list id (pl-...), got {values['cloudfront_prefix_list']!r}")
        if values["image_tag"] and not _IMAGE_TAG.match(values["image_tag"]):
            errors.append(f"image_tag: not a valid image tag: {values['image_tag']!r}")

        if errors:
            raise ValueError("invalid deployment inputs:\n  " + "\n  ".join(errors))
        return cls(**values)

    def to_context(self) -> dict[str, str]:
        """CDK context pairs (`-c key=value`); an empty image tag is left out, since `-c key=` is not valid."""
        return {key: value for key, value in vars(self).items() if value}
