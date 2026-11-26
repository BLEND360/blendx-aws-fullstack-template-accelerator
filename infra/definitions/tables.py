"""Every DynamoDB table the template provisions. Add a table by adding a TableSpec to the list
table_specs returns; DataStack needs no change.

Both tables are partitioned by owner_id: a query is always for one owner, so one user cannot read
another user's rows by construction. Table names are derived here from project.toml and handed to
the app as plain strings (never as a CloudFormation export, which would make deploy order rigid).
"""

from config import Config
from specs.table import TableSpec

OWNER_KEY = "owner_id"


def table_specs(c: Config) -> list[TableSpec]:
    return [
        TableSpec(
            id="SessionsTable",
            table_name=c.sessions_table,
            partition_key=OWNER_KEY,
            sort_key="session_id",
            description="Conversation metadata: owner, frozen runtime config, memory reference. Never message content.",
        ),
        TableSpec(
            id="ItemsTable",
            table_name=c.items_table,
            partition_key=OWNER_KEY,
            sort_key="item_id",
            description="The example domain table: one owner's items.",
        ),
    ]
