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
    "CORS_ORIGINS": "http://localhost:5173",
    "LOCAL_AUTH_BYPASS": "false",
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
    "AWS_CONFIG_FILE": os.devnull,
    "AWS_SHARED_CREDENTIALS_FILE": os.devnull,
}
os.environ.update(TEST_ENV)
for var in ("AWS_PROFILE", "ECS_CONTAINER_METADATA_URI_V4", "ECS_CONTAINER_METADATA_URI", "AWS_EXECUTION_ENV"):
    os.environ.pop(var, None)
