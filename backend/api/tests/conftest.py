"""Test environment. Set before `app` is imported, since settings validate at import.

Nothing here reaches AWS: probes and ports are replaced with stand-ins, and
credentials are pointed at nothing so an accidental real call fails loudly.
"""

import os

TEST_ENV = {
    "PROJECT_NAME": "test-project",
    "AWS_REGION": "us-east-1",
    "SESSIONS_TABLE_NAME": "test-sessions",
    "ITEMS_TABLE_NAME": "test-items",
    "HARNESS_ARN": "",
    "HARNESS_ENDPOINT": "PROD",
    "ALLOWED_MODEL_IDS": '["model-a"]',
    "LOCAL_AUTH_BYPASS": "false",
    # Blank, not absent: a variable in the environment wins over the developer's own .env, which holds the real
    # Cognito ids once scripts/deploy_auth.py has run and would turn sign-in on under every test.
    "COGNITO_USER_POOL_ID": "",
    "COGNITO_APP_CLIENT_ID": "",
    "AUTH_JWT_SECRET": "",
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
    "AWS_CONFIG_FILE": os.devnull,
    "AWS_SHARED_CREDENTIALS_FILE": os.devnull,
}
os.environ.update(TEST_ENV)
for var in ("AWS_PROFILE", "ECS_CONTAINER_METADATA_URI_V4", "ECS_CONTAINER_METADATA_URI", "AWS_EXECUTION_ENV"):
    os.environ.pop(var, None)

import pytest  # noqa: E402  (after the environment is set)


@pytest.fixture
def dynamo():
    """The two tables, created the way infra/ defines them, inside moto: no AWS, no network."""
    import boto3
    from moto import mock_aws

    with mock_aws():
        db = boto3.resource("dynamodb", region_name="us-east-1")
        for name, sort_key in (("test-sessions", "session_id"), ("test-items", "item_id")):
            db.create_table(
                TableName=name,
                KeySchema=[{"AttributeName": "owner_id", "KeyType": "HASH"}, {"AttributeName": sort_key, "KeyType": "RANGE"}],
                AttributeDefinitions=[
                    {"AttributeName": "owner_id", "AttributeType": "S"},
                    {"AttributeName": sort_key, "AttributeType": "S"},
                ],
                BillingMode="PAY_PER_REQUEST",
            )
        yield db
