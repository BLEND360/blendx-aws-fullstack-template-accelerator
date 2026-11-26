"""The clock and id source services default to; tests inject their own."""

import uuid
from datetime import UTC, datetime


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def new_id() -> str:
    return uuid.uuid4().hex
