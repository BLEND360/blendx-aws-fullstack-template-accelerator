"""One-time AWS account setup. Run with your own credentials, once per account:

    uv run --project infra python scripts/bootstrap.py

Resolves the ordering problem CI cannot: the deploy workflow assumes the GitHub
OIDC deploy role, and that role is created by the same CDK app the workflow
deploys. This creates it from your machine instead.

  1. checks your credentials point at project.toml's account
  2. `cdk bootstrap`
  3. creates the GitHub OIDC provider if the account has none
  4. deploys the roles stack
  5. prints the GitHub repository variables to set

Every step is idempotent; re-running changes nothing that is already in place.
"""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INFRA = ROOT / "infra"
sys.path.insert(0, str(INFRA))

import boto3  # noqa: E402

import config  # noqa: E402
from definitions.roles import GITHUB_OIDC_HOST  # noqa: E402

CDK = ["npx", "--yes", "aws-cdk@2"]


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


def cdk(*args: str) -> None:
    npx = shutil.which(CDK[0])
    if not npx:
        sys.exit("npx not found: install Node.js 20+ to run the CDK CLI.")
    subprocess.run([npx, *CDK[1:], *args], cwd=INFRA, check=True)


def main() -> int:
    c = config.load()
    session = boto3.Session(region_name=c.aws_region)

    caller = session.client("sts").get_caller_identity()["Account"]
    if caller != c.aws_account:
        print(
            f"Your credentials are for account {caller}, but project.toml says "
            f"{c.aws_account}. Switch profile or fix project.toml.",
            file=sys.stderr,
        )
        return 1

    print(f"[1/3] cdk bootstrap aws://{c.aws_account}/{c.aws_region}")
    cdk("bootstrap", f"aws://{c.aws_account}/{c.aws_region}")

    print("[2/3] GitHub OIDC provider")
    ensure_oidc_provider(session.client("iam"))

    print(f"[3/3] deploy {c.roles_stack}")
    cdk("deploy", c.roles_stack, "--exclusively", "--require-approval", "never")

    repo = f"{c.github_org}/{c.github_repo}"
    print(f"""
Done. Set these repository variables, then push to deploy:

  gh variable set AWS_DEPLOY_ROLE_ARN --repo {repo} --body {c.role_arn(c.deploy_role)}
  gh variable set AWS_REGION          --repo {repo} --body {c.aws_region}
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
