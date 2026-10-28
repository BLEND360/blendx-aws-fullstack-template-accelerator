"""Deploy the data stack (the DynamoDB tables) from your machine.

    uv run --project infra python scripts/deploy_data.py

Needs `scripts/bootstrap.py` to have run once in the account. Idempotent: an
unchanged stack is a CloudFormation no-op. Tables are RETAINed, so deleting the
stack never deletes data.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "infra"))

import boto3  # noqa: E402

from awsutil import cdk, check_account, cli, load_config  # noqa: E402


@cli
def main() -> int:
    c = load_config()
    check_account(c, boto3.Session(region_name=c.aws_region))

    cdk("deploy", c.data_stack, "--exclusively", "--require-approval", "never")
    print(f"""
Done. Tables: {c.sessions_table}, {c.items_table}
To use them locally, set DATA_STORE=dynamodb in backend/api/.env.
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
