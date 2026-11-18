import pytest

import config
from deployment import DeployInputs
from tests.test_config import VALID, write

PREFIX = "arn:aws:bedrock-agentcore:eu-west-1:111122223333"
GOOD = {
    "env": "dev",
    "harness_arn": f"{PREFIX}:harness/assistant-AbC123",
    "memory_arn": f"{PREFIX}:memory/assistant_mem-XyZ789",
    "user_pool_id": "eu-west-1_AbCdEf",
    "app_client_id": "1example23456789",
    "cloudfront_prefix_list": "pl-4fa04526",
    "image_tag": "0123456789ab",
}


@pytest.fixture
def c(tmp_path) -> config.Config:
    return config.load(write(tmp_path, VALID))


def load(c, values):
    return DeployInputs.from_context(c, values.get)


def test_complete_context_loads(c):
    inputs = load(c, GOOD)
    assert inputs.env == "dev" and inputs.image_tag == "0123456789ab"


def test_context_round_trips(c):
    inputs = load(c, GOOD)
    assert load(c, inputs.to_context()) == inputs


def test_missing_image_tag_means_a_service_without_tasks(c):
    inputs = load(c, {k: v for k, v in GOOD.items() if k != "image_tag"})
    assert inputs.image_tag == ""
    assert "image_tag" not in inputs.to_context()


@pytest.mark.parametrize("key", [k for k in GOOD if k != "image_tag"])
def test_each_missing_value_is_named(c, key):
    with pytest.raises(ValueError, match=key):
        load(c, {k: v for k, v in GOOD.items() if k != key})


def test_every_problem_is_reported_at_once(c):
    with pytest.raises(ValueError) as error:
        load(c, {"env": "dev"})
    for key in ("harness_arn", "memory_arn", "user_pool_id", "app_client_id", "cloudfront_prefix_list"):
        assert key in str(error.value)


@pytest.mark.parametrize(
    "key,value",
    [
        ("harness_arn", f"{PREFIX}:memory/not-a-harness"),
        ("harness_arn", "arn:aws:bedrock-agentcore:us-east-1:999999999999:harness/other-account"),
        ("memory_arn", f"{PREFIX}:harness/not-a-memory"),
        ("memory_arn", f"{PREFIX}:memory/*"),
        ("cloudfront_prefix_list", "not-a-prefix-list"),
        ("image_tag", "has space"),
    ],
)
def test_malformed_values_are_rejected_by_name(c, key, value):
    with pytest.raises(ValueError, match=key):
        load(c, {**GOOD, key: value})


def test_unknown_environment_lists_the_valid_ones(c):
    with pytest.raises(ValueError, match=r"'qa'.*valid: dev"):
        load(c, {**GOOD, "env": "qa"})
