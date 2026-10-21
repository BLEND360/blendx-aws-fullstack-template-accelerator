"""Create a user in the project's Cognito pool and put it in a group (its roles in the API).

    uv run --project infra python scripts/create_user.py you@example.com [--name "You"] [--group admin|user] [--password ...]

Without --password one is generated and printed. The account is usable immediately (no invitation
email, no forced password change). Re-running for an existing user only adds it to the group.
"""

import argparse
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "infra"))

import boto3  # noqa: E402

import config  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("email")
    parser.add_argument("--name", default="")
    parser.add_argument("--group", default="admin", choices=["admin", "user"])
    parser.add_argument("--password", default="")
    args = parser.parse_args()

    c = config.load()
    session = boto3.Session(region_name=c.aws_region)
    caller = session.client("sts").get_caller_identity()["Account"]
    if caller != c.aws_account:
        print(f"Your credentials are for account {caller}, but project.toml says {c.aws_account}.", file=sys.stderr)
        return 1

    stack = session.client("cloudformation").describe_stacks(StackName=c.auth_stack)["Stacks"][0]
    pool = next(o["OutputValue"] for o in stack["Outputs"] if o["OutputKey"] == "UserPoolId")
    idp = session.client("cognito-idp")

    # Meets Cognito's default password policy (length, upper, lower, digit, symbol).
    password = args.password or f"{secrets.token_urlsafe(12)}Aa1!"
    attributes = [{"Name": "email", "Value": args.email}, {"Name": "email_verified", "Value": "true"}]
    if args.name:
        attributes.append({"Name": "name", "Value": args.name})
    created = True
    try:
        idp.admin_create_user(UserPoolId=pool, Username=args.email, UserAttributes=attributes, MessageAction="SUPPRESS")
        idp.admin_set_user_password(UserPoolId=pool, Username=args.email, Password=password, Permanent=True)
    except idp.exceptions.UsernameExistsException:
        created = False
    idp.admin_add_user_to_group(UserPoolId=pool, Username=args.email, GroupName=args.group)

    if created:
        print(f"Created {args.email} in group '{args.group}'.\nPassword: {password}")
    else:
        print(f"{args.email} already existed; added to group '{args.group}'. Password unchanged.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
