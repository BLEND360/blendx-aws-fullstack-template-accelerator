import importlib.util
import sys
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

import config
from tests.test_config import VALID, write

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))  # the script imports awsutil from its own folder, as it does when run
_spec = importlib.util.spec_from_file_location("harness_resolve", SCRIPTS / "harness_resolve.py")
harness_resolve = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(harness_resolve)

PREFIX = "arn:aws:bedrock-agentcore:eu-west-1:111122223333"
HARNESS = f"{PREFIX}:harness/assistant-AbC123"
MEMORY = f"{PREFIX}:memory/assistant_mem-XyZ789"


def error(code: str, message: str = "boom") -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": message}}, "Op")


class NoTags:
    """The tagging API with no accelerator harnesses in the account."""

    def get_paginator(self, operation):
        return self

    def paginate(self, **kwargs):
        yield {"ResourceTagMappingList": []}


class FakeSession:
    """Records every client it is asked for and the calls made on it."""

    def __init__(self, outputs=None, stack_error=None, harness=None, harness_error=None):
        self.requested: list[str] = []
        self.harness_ids: list[str] = []
        session = self

        class Cfn:
            def describe_stacks(self, StackName):
                if stack_error:
                    raise stack_error
                return {"Stacks": [{"Outputs": [{"OutputKey": k, "OutputValue": v} for k, v in (outputs or {}).items()]}]}

        class Control:
            def get_harness(self, harnessId):
                session.harness_ids.append(harnessId)
                if harness_error:
                    raise harness_error
                return {"harness": harness if harness is not None else {"memory": {"managedMemoryConfiguration": {"arn": MEMORY}}}}

        self._clients = {
            "cloudformation": Cfn(),
            "bedrock-agentcore-control": Control(),
            "resourcegroupstaggingapi": NoTags(),
        }

    def client(self, name):
        self.requested.append(name)
        return self._clients[name]


@pytest.fixture
def starter(tmp_path) -> config.Config:
    return config.load(write(tmp_path, VALID))


@pytest.fixture
def consumed(tmp_path) -> config.Config:
    return config.load(write(tmp_path, VALID.replace('arn = ""', f'arn = "{HARNESS}"')))


OUTPUTS = {
    "ApplicationHarnessAssistantArnOutputAB12CD": HARNESS,
    "ApplicationHarnessAssistantAgentRuntimeArnOutput99": f"{PREFIX}:runtime/assistant_rt-1",
    "ApplicationHarnessAssistantVersionOutputEF34": "3",
}


def test_the_starter_harness_arn_comes_from_its_stack_outputs_not_the_runtime_arn(starter):
    assert harness_resolve.resolve(starter, FakeSession(outputs=OUTPUTS)) == (HARNESS, MEMORY)


def test_a_configured_harness_is_used_and_the_starter_stack_is_never_read(consumed):
    session = FakeSession()
    assert harness_resolve.resolve(consumed, session) == (HARNESS, MEMORY)
    assert "cloudformation" not in session.requested


def test_the_memory_is_read_from_the_harness_id(starter):
    session = FakeSession(outputs=OUTPUTS)
    harness_resolve.resolve(starter, session)
    assert session.harness_ids == ["assistant-AbC123"]


def test_a_memory_configured_the_other_way_is_found_too(starter):
    other = {"memory": {"agentCoreMemoryConfiguration": {"arn": MEMORY}}}
    assert harness_resolve.resolve(starter, FakeSession(outputs=OUTPUTS, harness=other))[1] == MEMORY


def test_a_missing_starter_stack_says_to_deploy_the_harness_first(starter):
    session = FakeSession(stack_error=error("ValidationError", "Stack with id AgentCore-x does not exist"))
    with pytest.raises(harness_resolve.HarnessResolveError, match=r"deploy_harness\.py"):
        harness_resolve.resolve(starter, session)


def test_a_starter_stack_without_the_arn_output_lists_what_it_has(starter):
    with pytest.raises(harness_resolve.HarnessResolveError, match="HarnessAssistantArnOutput.*ApplicationOther"):
        harness_resolve.resolve(starter, FakeSession(outputs={"ApplicationOther": "x"}))


def test_a_harness_without_memory_stops_and_never_returns_a_wildcard(starter):
    with pytest.raises(harness_resolve.HarnessResolveError, match="no memory"):
        harness_resolve.resolve(starter, FakeSession(outputs=OUTPUTS, harness={"memory": {}}))


def test_a_memory_arn_that_is_not_a_concrete_memory_is_refused(starter):
    wild = {"memory": {"managedMemoryConfiguration": {"arn": f"{PREFIX}:memory/*"}}}
    with pytest.raises(harness_resolve.HarnessResolveError, match="memory"):
        harness_resolve.resolve(starter, FakeSession(outputs=OUTPUTS, harness=wild))


def test_denied_access_names_the_permission_the_operator_lacks(starter):
    session = FakeSession(outputs=OUTPUTS, harness_error=error("AccessDeniedException"))
    with pytest.raises(harness_resolve.HarnessResolveError, match="bedrock-agentcore:GetHarness"):
        harness_resolve.resolve(starter, session)


def test_any_other_aws_error_is_named_by_its_code(starter):
    session = FakeSession(outputs=OUTPUTS, harness_error=error("ResourceNotFoundException"))
    with pytest.raises(harness_resolve.HarnessResolveError, match="ResourceNotFoundException"):
        harness_resolve.resolve(starter, session)


class AccountSession:
    """An account with the given harness ARNs carrying the accelerator tags, and no stack of this project.

    `created` gives each live harness's creation time; an ARN missing from it no longer exists (GetHarness says so).
    """

    def __init__(self, harness_arns=(), own_stack=False, created=None):
        self.harness_arns = list(harness_arns)
        self.own_stack = own_stack
        self.created = created if created is not None else {arn: "2026-11-10T00:00:00+00:00" for arn in harness_arns}

    def client(self, name):
        session = self

        class Tagging:
            def get_paginator(self, operation):
                assert operation == "get_resources"
                return self

            def paginate(self, TagFilters, ResourceTypeFilters):
                assert {"Key": "blendx:template", "Values": ["accelerator"]} in TagFilters
                assert ResourceTypeFilters == ["bedrock-agentcore"]
                yield {"ResourceTagMappingList": [{"ResourceARN": arn} for arn in session.harness_arns]}

        class Control:
            def get_harness(self, harnessId):
                match = [a for a in session.created if a.endswith(f"/{harnessId}")]
                if not match:
                    raise error("ResourceNotFoundException", f"Agent with name {harnessId} not found")
                return {"harness": {"createdAt": session.created[match[0]]}}

        class Cfn:
            def describe_stacks(self, StackName):
                if not session.own_stack:
                    raise error("ValidationError", f"Stack with id {StackName} does not exist")
                return {"Stacks": [{}]}

        return {"resourcegroupstaggingapi": Tagging(), "bedrock-agentcore-control": Control(), "cloudformation": Cfn()}[name]


def test_no_accelerator_harness_means_none():
    assert harness_resolve.find_accelerator_harness(AccountSession()) is None


def test_one_accelerator_harness_is_found():
    assert harness_resolve.find_accelerator_harness(AccountSession([HARNESS])) == HARNESS


def test_several_accelerator_harnesses_reuse_the_newest():
    older, newer = HARNESS, f"{PREFIX}:harness/assistant-Newer9"
    session = AccountSession(
        [older, newer],
        created={older: "2026-11-09T10:00:00+00:00", newer: "2026-11-10T00:05:40+00:00"},
    )
    assert harness_resolve.find_accelerator_harness(session) == newer


def test_a_tag_left_behind_by_a_deleted_harness_is_ignored():
    gone, live = f"{PREFIX}:harness/assistant-Gone1", HARNESS
    session = AccountSession([gone, live], created={live: "2026-11-10T00:05:40+00:00"})
    assert harness_resolve.find_accelerator_harness(session) == live


def test_endpoints_of_a_harness_are_not_mistaken_for_harnesses():
    endpoint = f"{HARNESS}/harness-endpoint/DEFAULT"
    assert harness_resolve.find_accelerator_harness(AccountSession([endpoint, HARNESS])) == HARNESS


def test_a_project_without_its_stack_reuses_the_accelerator_harness(tmp_path):
    from tests.test_config import VALID, write

    c = config.load(write(tmp_path, VALID))
    assert harness_resolve.starter_harness_arn(c, AccountSession([HARNESS])) == HARNESS


def test_a_project_with_its_own_stack_never_reuses_another_harness(tmp_path):
    from tests.test_config import VALID, write

    c = config.load(write(tmp_path, VALID))
    session = AccountSession([HARNESS], own_stack=True)  # its stack exists but has no outputs
    with pytest.raises(harness_resolve.HarnessResolveError, match="no output containing"):
        harness_resolve.starter_harness_arn(c, session)


def test_without_a_stack_or_an_accelerator_harness_the_error_names_the_stack(tmp_path):
    from tests.test_config import VALID, write

    c = config.load(write(tmp_path, VALID))
    with pytest.raises(harness_resolve.HarnessResolveError, match="does not exist"):
        harness_resolve.starter_harness_arn(c, AccountSession())
