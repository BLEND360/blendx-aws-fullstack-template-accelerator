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

import config  # noqa: E402
import envfile  # noqa: E402
from awsutil import cdk, check_account, cli, load_config  # noqa: E402

BACKEND_ENV = ROOT / "backend" / "api" / ".env"
FRONTEND_ENV = ROOT / "frontend" / "web" / ".env"


def wire_local_names(c: config.Config, backend: Path | None = None, frontend: Path | None = None) -> None:
    """Keep the local .env files' project names in step with project.toml, so renaming the project needs no edit.

    setup.py writes these once and removes itself, so a later rename would leave them stale. Files that do not
    exist (setup not run yet) are skipped.
    """
    backend = backend or BACKEND_ENV
    frontend = frontend or FRONTEND_ENV
    if backend.exists():
        envfile.update(backend, {
            "PROJECT_NAME": c.name,
            "AWS_REGION": c.aws_region,
            "SESSIONS_TABLE_NAME": c.sessions_table,
            "ITEMS_TABLE_NAME": c.items_table,
        })
    if frontend.exists():
        envfile.update(frontend, {"VITE_COGNITO_REGION": c.aws_region})


@cli
def main() -> int:
    c = load_config()
    check_account(c, boto3.Session(region_name=c.aws_region))

    cdk("deploy", c.data_stack, "--exclusively", "--require-approval", "never")
    wire_local_names(c)
    print(f"""
Done. Tables: {c.sessions_table}, {c.items_table}
Local .env files now name this project and its tables. Set DATA_STORE=dynamodb in backend/api/.env to use them.
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
