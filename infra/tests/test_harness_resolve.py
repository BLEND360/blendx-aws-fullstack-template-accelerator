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

        self._clients = {"cloudformation": Cfn(), "bedrock-agentcore-control": Control()}

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
