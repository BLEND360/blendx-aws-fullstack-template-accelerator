from dataclasses import dataclass


@dataclass(frozen=True)
class TableSpec:
    """One DynamoDB table. Every table is keyed by its owner first, so ownership is the key, not a filter."""

    id: str
    table_name: str
    partition_key: str  # the owner
    sort_key: str  # the thing owned
    description: str
