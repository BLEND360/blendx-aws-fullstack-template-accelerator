"""Create a user in the project's Cognito pool and put it in a group (its roles in the API).

    uv run --project infra python scripts/create_user.py you@example.com [--name "You"] [--group admin|user] [--password ...]

The password is asked for (hidden) unless --password is given, which is for non-interactive use: it shows in
the shell history and the process list. Empty means a generated one, printed for a new user. The account is
usable immediately (no invitation email, no forced password change). Re-running for an existing user adds it
to the group, and sets the password only if one was given.
"""

import argparse
import getpass
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "infra"))

import boto3  # noqa: E402

from awsutil import DeployError, check_account, cli, load_config, outputs  # noqa: E402


@cli
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("email")
    parser.add_argument("--name", default="")
    parser.add_argument("--group", default="admin", choices=["admin", "user"])
    parser.add_argument("--password", default="", help="visible in the shell history; leave it out to be asked")
    args = parser.parse_args()

    c = load_config()
    session = boto3.Session(region_name=c.aws_region)
    check_account(c, session)

    pool = outputs(session, c.auth_stack).get("UserPoolId")
    if not pool:
        raise DeployError(f"The stack {c.auth_stack} has no UserPoolId output: run `scripts/deploy_auth.py` first.")
    idp = session.client("cognito-idp")

    supplied = args.password or (
        getpass.getpass("Password (empty: generate one for a new user, keep the current one otherwise): ") if sys.stdin.isatty() else ""
    )
    # The generated one meets Cognito's default password policy (length, upper, lower, digit, symbol).
    password = supplied or f"{secrets.token_urlsafe(12)}Aa1!"
    attributes = [{"Name": "email", "Value": args.email}, {"Name": "email_verified", "Value": "true"}]
    if args.name:
        attributes.append({"Name": "name", "Value": args.name})
    created = True
    try:
        idp.admin_create_user(UserPoolId=pool, Username=args.email, UserAttributes=attributes, MessageAction="SUPPRESS")
    except idp.exceptions.UsernameExistsException:
        created = False
    if created or supplied:
        try:
            idp.admin_set_user_password(UserPoolId=pool, Username=args.email, Password=password, Permanent=True)
        except idp.exceptions.InvalidPasswordException as e:
            raise DeployError(
                f"Cognito rejected the password: {e.response['Error']['Message']}\n"
                f"{args.email} exists but cannot sign in yet: run this again with a password that meets the pool's policy."
            ) from e
    idp.admin_add_user_to_group(UserPoolId=pool, Username=args.email, GroupName=args.group)

    if created:
        print(f"Created {args.email} in group '{args.group}'." + ("" if supplied else f"\nPassword: {password}"))
    else:
        print(f"{args.email} already existed; added to group '{args.group}'. Password {'set' if supplied else 'unchanged'}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
