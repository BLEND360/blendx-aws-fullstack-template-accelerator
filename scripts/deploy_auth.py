"""Deploy the auth stack (the Cognito user pool) and configure the project to use it.

    uv run --project infra python scripts/deploy_auth.py

Needs `scripts/bootstrap.py` to have run once in the account and `scripts/setup.py` to have written
the .env files. Writes the pool and client ids into backend/api/.env and frontend/web/.env, makes sure
AUTH_JWT_SECRET exists, and turns LOCAL_AUTH_BYPASS off so sign-in is the real one. Idempotent: an
unchanged stack is a CloudFormation no-op. The pool is RETAINed, so deleting the stack never deletes users.
"""

import argparse
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "infra"))

import boto3  # noqa: E402

import config  # noqa: E402
import envfile  # noqa: E402
from awsutil import cdk, check_account, cli, load_config, outputs  # noqa: E402

BACKEND_ENV = ROOT / "backend" / "api" / ".env"
FRONTEND_ENV = ROOT / "frontend" / "web" / ".env"


def env_values(c: config.Config, out: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    """(backend, frontend) .env values, from the stack's outputs."""
    backend = {
        "COGNITO_USER_POOL_ID": out["UserPoolId"],
        "COGNITO_APP_CLIENT_ID": out["AppClientId"],
        # The bypass wins over any token, so leaving it on would hide the sign-in being set up here.
        "LOCAL_AUTH_BYPASS": "false",
    }
    frontend = {
        "VITE_COGNITO_REGION": c.aws_region,
        "VITE_COGNITO_USER_POOL_ID": out["UserPoolId"],
        "VITE_COGNITO_APP_CLIENT_ID": out["AppClientId"],
        "VITE_COGNITO_DOMAIN": out["Domain"],
    }
    return backend, frontend


@cli
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stack-only",
        action="store_true",
        help="deploy the auth stack without writing local .env files",
    )
    args = parser.parse_args(argv)
    c = load_config()
    session = boto3.Session(region_name=c.aws_region)
    check_account(c, session)

    cdk("deploy", c.auth_stack, "--exclusively", "--require-approval", "never")
    out = outputs(session, c.auth_stack)

    if args.stack_only:
        print(f"Sign-in stack deployed: {c.auth_stack}")
        return 0

    backend, frontend = env_values(c, out)
    try:
        if len(envfile.get(BACKEND_ENV, "AUTH_JWT_SECRET")) < 32:  # missing, or a placeholder
            backend["AUTH_JWT_SECRET"] = secrets.token_urlsafe(48)
        envfile.update(BACKEND_ENV, backend)
        envfile.update(FRONTEND_ENV, frontend, create=True)  # holds only derived values
    except FileNotFoundError as missing:
        print(f"\n{missing.filename} not found: run `python scripts/setup.py`, then deploy_auth.py again.", file=sys.stderr)
        return 1
    print("""
Done. Wrote the sign-in values to backend/api/.env and frontend/web/.env, and set LOCAL_AUTH_BYPASS=false
(set it back to true to skip sign-in locally). Restart the API and the web app, then create a user:

  uv run --project infra python scripts/create_user.py you@example.com
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
