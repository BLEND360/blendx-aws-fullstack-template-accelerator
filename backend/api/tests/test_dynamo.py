"""What only the DynamoDB adapter can get wrong: what lands in the table, and how failures read."""

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from app.core.errors import AppError
from app.repositories.dynamo import DynamoSessionStore
from test_store_contract import session

ALLOWED_ATTRIBUTES = {"owner_id", "session_id", "status", "config", "memory", "created_at", "updated_at", "revision"}


def test_a_session_row_holds_metadata_only_never_conversation_content(dynamo):
    table = dynamo.Table("test-sessions")
    DynamoSessionStore(table).create(session())
    (row,) = table.scan()["Items"]
    assert set(row) == ALLOWED_ATTRIBUTES
    assert set(row["memory"]) == {"runtime_session_id", "actor_id"}  # coordinates into the harness's memory, not its content
    assert not any(word in set(row) for word in ("messages", "text", "content", "history"))


def test_the_row_is_keyed_by_owner_and_session(dynamo):
    table = dynamo.Table("test-sessions")
    DynamoSessionStore(table).create(session("abc", owner="alice"))
    assert table.get_item(Key={"owner_id": "alice", "session_id": "abc"}).get("Item")
    assert not table.get_item(Key={"owner_id": "bob", "session_id": "abc"}).get("Item")


def test_a_missing_table_is_a_deployment_fault_not_a_client_error():
    with mock_aws():  # no tables created
        store = DynamoSessionStore(boto3.resource("dynamodb", region_name="us-east-1").Table("test-sessions"))
        with pytest.raises(AppError) as raised:
            store.get("alice", "s1")
    assert raised.value.code == "data_misconfigured"
    assert raised.value.http_status == 500


def test_throttling_is_retryable_and_says_nothing_about_the_table(dynamo):
    class Throttled:
        def get_item(self, **_):
            raise ClientError({"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "arn:aws:dynamodb:secret"}}, "GetItem")

    with pytest.raises(AppError) as raised:
        DynamoSessionStore(Throttled()).get("alice", "s1")
    assert raised.value.code == "data_throttled" and raised.value.retryable
    assert "arn:" not in raised.value.message
