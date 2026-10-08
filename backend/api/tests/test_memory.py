"""AgentCoreMemory against stubbed boto3 clients (no AWS)."""

from datetime import UTC, datetime

import pytest
from botocore.exceptions import ClientError

from app.core.errors import AppError
from app.core.models import MemoryRef
from app.harness.memory import AgentCoreMemory

HARNESS_ARN = "arn:aws:bedrock-agentcore:us-east-1:123456789012:harness/h-1234567890"
MEMORY_ARN = "arn:aws:bedrock-agentcore:us-east-1:123456789012:memory/mem-secret-1234567890"
MEM = MemoryRef("s-" + "a" * 32, "u-" + "b" * 32)
SECRET = MEMORY_ARN + " is not authorized"


def aws_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": SECRET}}, "Op")


def event(event_id: str, role: str | None, text: str | None, second: int = 0) -> dict:
    payload = [{"conversational": {"role": role, "content": {"text": text}}}] if role else [{"blob": {"x": 1}}]
    return {"eventId": event_id, "eventTimestamp": datetime(2026, 10, 8, 10, 0, second, tzinfo=UTC), "payload": payload}


class FakeControl:
    def __init__(self, memory=None):
        self.memory = {"managedMemoryConfiguration": {"arn": MEMORY_ARN}} if memory is None else memory
        self.calls = []

    def get_harness(self, **kwargs):
        self.calls.append(kwargs)
        return {"harness": {"memory": self.memory}}


class FakeData:
    def __init__(self, pages):
        self.pages, self.list_calls, self.deleted, self.delete_errors = pages, [], [], {}

    def list_events(self, **kwargs):
        self.list_calls.append(kwargs)
        index = 0 if "nextToken" not in kwargs else int(kwargs["nextToken"])
        page = {"events": self.pages[index]}
        if index + 1 < len(self.pages):
            page["nextToken"] = str(index + 1)
        return page

    def delete_event(self, **kwargs):
        if kwargs["eventId"] in self.delete_errors:
            raise self.delete_errors[kwargs["eventId"]]
        self.deleted.append(kwargs)


def memory_with(control, data, harness_arn=HARNESS_ARN) -> AgentCoreMemory:
    return AgentCoreMemory(harness_arn, client_factory=lambda service: control if "control" in service else data)


def test_the_memory_is_found_through_the_harness_and_remembered():
    control, data = FakeControl(), FakeData([[event("1#a", "USER", "hi")]])
    memory = memory_with(control, data)
    list(memory.list_events(MEM))
    list(memory.list_events(MEM))
    assert control.calls == [{"harnessId": "h-1234567890"}]  # the id inside the harness ARN, asked once
    assert data.list_calls[0]["memoryId"] == "mem-secret-1234567890"


def test_a_memory_configured_by_the_consumer_is_found_too():
    control = FakeControl({"agentCoreMemoryConfiguration": {"arn": MEMORY_ARN}})
    assert [e.text for e in memory_with(control, FakeData([[event("1#a", "USER", "hi")]])).list_events(MEM)] == ["hi"]


def test_every_page_is_read_and_the_session_and_actor_are_passed_through():
    pages = [[event("1#a", "USER", "one")], [event("2#b", "ASSISTANT", "two")], [event("3#c", "USER", "three")]]
    data = FakeData(pages)
    events = list(memory_with(FakeControl(), data).list_events(MEM))
    assert [e.text for e in events] == ["one", "two", "three"]
    assert [e.role for e in events] == ["USER", "ASSISTANT", "USER"]
    assert len(data.list_calls) == 3
    assert all(c["sessionId"] == MEM.runtime_session_id and c["actorId"] == MEM.actor_id for c in data.list_calls)
    assert all(c["includePayloads"] is True and c["maxResults"] == 100 for c in data.list_calls)
    assert events[0].timestamp == "2026-10-08T10:00:00+00:00"


def test_a_payload_that_is_not_conversational_has_no_text():
    (reduced,) = memory_with(FakeControl(), FakeData([[event("1#a", None, None)]])).list_events(MEM)
    assert (reduced.role, reduced.text) == ("OTHER", None)


def test_purge_lists_without_payloads_then_deletes_every_event():
    data = FakeData([[event("1#a", "USER", "x")], [event("2#b", "ASSISTANT", "y")]])
    memory_with(FakeControl(), data).purge(MEM)
    assert [c["includePayloads"] for c in data.list_calls] == [False, False]
    assert [d["eventId"] for d in data.deleted] == ["1#a", "2#b"]
    assert all(d["memoryId"] == "mem-secret-1234567890" and d["actorId"] == MEM.actor_id for d in data.deleted)


def test_an_event_already_gone_does_not_fail_the_purge():
    data = FakeData([[event("1#a", "USER", "x"), event("2#b", "USER", "y")]])
    data.delete_errors["1#a"] = aws_error("ResourceNotFoundException")
    memory_with(FakeControl(), data).purge(MEM)
    assert [d["eventId"] for d in data.deleted] == ["2#b"]


def test_a_failure_while_deleting_is_a_retryable_memory_error_without_the_services_text():
    data = FakeData([[event("1#a", "USER", "x"), event("2#b", "USER", "y")]])
    data.delete_errors["2#b"] = aws_error("ServiceException")
    with pytest.raises(AppError) as raised:
        memory_with(FakeControl(), data).purge(MEM)
    assert (raised.value.code, raised.value.retryable) == ("memory_unavailable", True)
    assert "mem-secret" not in raised.value.message
    assert [d["eventId"] for d in data.deleted] == ["1#a"]  # what was deleted stays deleted


def test_a_failure_while_listing_is_classified():
    class Failing(FakeData):
        def list_events(self, **kwargs):
            raise aws_error("ThrottledException")

    with pytest.raises(AppError) as raised:
        list(memory_with(FakeControl(), Failing([])).list_events(MEM))
    assert (raised.value.code, raised.value.retryable) == ("memory_throttled", True)


def test_a_harness_without_memory_is_a_configuration_error():
    with pytest.raises(AppError) as raised:
        list(memory_with(FakeControl({"disabled": {}}), FakeData([[]])).list_events(MEM))
    assert (raised.value.code, raised.value.retryable) == ("memory_misconfigured", False)


def test_an_unconfigured_harness_is_a_configuration_error():
    with pytest.raises(AppError) as raised:
        list(memory_with(FakeControl(), FakeData([[]]), harness_arn="").list_events(MEM))
    assert raised.value.code == "memory_misconfigured"


def test_a_failing_get_harness_is_classified():
    class Failing(FakeControl):
        def get_harness(self, **kwargs):
            raise aws_error("AccessDeniedException")

    with pytest.raises(AppError) as raised:
        list(memory_with(Failing(), FakeData([[]])).list_events(MEM))
    assert raised.value.code == "memory_misconfigured"
    assert "arn:aws" not in raised.value.message
