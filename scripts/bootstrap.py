"""One-time AWS account setup. Run with your own credentials, once per account:

    uv run --project infra python scripts/bootstrap.py

Resolves the ordering problem CI cannot: the deploy workflow assumes the GitHub
OIDC deploy role, and that role is created by the same CDK app the workflow
deploys. This creates it from your machine instead.

It first checks your credentials point at project.toml's account, then:

  1. `cdk bootstrap`
  2. creates the GitHub OIDC provider if the account has none
  3. deploys the roles stack

and ends by printing the GitHub variables needed by the workflows.

Every step is idempotent; re-running changes nothing that is already in place.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "infra"))

import boto3  # noqa: E402

from awsutil import cdk, check_account, cli, load_config  # noqa: E402
from definitions.roles import GITHUB_OIDC_HOST  # noqa: E402


def ensure_oidc_provider(iam) -> str:
    """Return the account's GitHub OIDC provider ARN, creating it if absent.

    Created here and not in CDK: the provider is an account-wide singleton that
    other repositories in the same account may already have created, and a
    stack that tried to own it would fail on those accounts.
    """
    for provider in iam.list_open_id_connect_providers()["OpenIDConnectProviderList"]:
        if provider["Arn"].endswith(f"oidc-provider/{GITHUB_OIDC_HOST}"):
            print(f"  OIDC provider exists: {provider['Arn']}")
            return provider["Arn"]
    arn = iam.create_open_id_connect_provider(
        Url=f"https://{GITHUB_OIDC_HOST}",
        ClientIDList=["sts.amazonaws.com"],
    )["OpenIDConnectProviderArn"]
    print(f"  OIDC provider created: {arn}")
    return arn


@cli
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--roles-only",
        action="store_true",
        help="deploy only the roles stack; the account bootstrap and OIDC provider must already exist",
    )
    args = parser.parse_args(argv)
    c = load_config()
    session = boto3.Session(region_name=c.aws_region)
    check_account(c, session)

    if not args.roles_only:
        print(f"[1/3] cdk bootstrap aws://{c.aws_account}/{c.aws_region}")
        cdk("bootstrap", f"aws://{c.aws_account}/{c.aws_region}")

        print("[2/3] GitHub OIDC provider")
        ensure_oidc_provider(session.client("iam"))

    step = "1/1" if args.roles_only else "3/3"
    print(f"[{step}] deploy {c.roles_stack}")
    cdk("deploy", c.roles_stack, "--exclusively", "--require-approval", "never")

    if args.roles_only:
        print(f"Roles updated: {c.roles_stack}")
        return 0

    repo = f"{c.github_org}/{c.github_repo}"
    print(f"""
Done. Set the diff role and region as repository variables. Set the deploy role and region in each GitHub Environment:

  gh variable set AWS_DIFF_ROLE_ARN --repo {repo} --body {c.role_arn(c.diff_role)}
  gh variable set AWS_REGION          --repo {repo} --body {c.aws_region}
  gh variable set AWS_DEPLOY_ROLE_ARN --repo {repo} --env dev  --body {c.role_arn(c.deploy_role)}
  gh variable set AWS_REGION          --repo {repo} --env dev  --body {c.aws_region}
  gh variable set AWS_DEPLOY_ROLE_ARN --repo {repo} --env prod --body {c.role_arn(c.deploy_role)}
  gh variable set AWS_REGION          --repo {repo} --env prod --body {c.aws_region}

Restrict both environments to the `main` branch. Require reviewers for `prod`.
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
