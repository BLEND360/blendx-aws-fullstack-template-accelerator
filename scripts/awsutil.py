"""What the scripts share: the account check, running tools, the error handling around `main`, the `[network]` block."""

import functools
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INFRA = ROOT / "infra"
sys.path.insert(0, str(INFRA))

from botocore.exceptions import BotoCoreError, ClientError  # noqa: E402

import config  # noqa: E402

CDK = ["npx", "--yes", "aws-cdk@2"]

# Approximate list prices in USD, to give an idea of what a resource costs; not a quote.
NAT_PER_HOUR = 0.045
NAT_PER_DAY = NAT_PER_HOUR * 24
NAT_PER_GB = 0.045
APP_PER_DAY = 0.85  # load balancer and one small Fargate task


class DeployError(RuntimeError):
    """A failure with a message for the operator: `cli` prints it without a traceback."""


def cli(main: Callable[..., int]) -> Callable[..., int]:
    """Turn the failures a script can expect into a message on stderr and exit code 1."""

    @functools.wraps(main)
    def wrapper(*args, **kwargs) -> int:
        try:
            return main(*args, **kwargs)
        except (DeployError, ValueError) as e:
            print(e, file=sys.stderr)
        except subprocess.CalledProcessError as e:
            print(f"`{' '.join(map(str, e.cmd))}` failed (exit {e.returncode}).", file=sys.stderr)
        except (ClientError, BotoCoreError) as e:
            what = f"{e.response['Error']['Code']} ({e.response['Error']['Message']})" if isinstance(e, ClientError) else type(e).__name__
            print(f"AWS answered {what}. If your credentials expired or are missing, run `aws login` (or `aws sso login`) and try again.", file=sys.stderr)
        return 1

    return wrapper


def load_config(path: Path = config.PROJECT_TOML) -> config.Config:
    try:
        return config.load(path)
    except FileNotFoundError as e:
        raise DeployError(f"{e.filename} not found.") from e
    except KeyError as e:
        raise DeployError(f"{path.name} is missing {e}.") from e


def check_account(c: config.Config, session) -> None:
    caller = session.client("sts").get_caller_identity()["Account"]
    if caller != c.aws_account:
        raise DeployError(
            f"Your credentials are for account {caller}, but project.toml says {c.aws_account}. "
            "Switch profile or fix project.toml."
        )


def run(*cmd: str, cwd: Path = ROOT, env: dict[str, str] | None = None, capture: bool = False) -> str:
    exe = shutil.which(cmd[0])
    if not exe:
        raise DeployError(f"{cmd[0]} not found on PATH")
    result = subprocess.run(
        [exe, *cmd[1:]], cwd=cwd, env={**os.environ, **env} if env else None, check=True, text=True,
        stdout=subprocess.PIPE if capture else None,
    )
    return result.stdout or ""


def cdk(*args: str) -> None:
    if not shutil.which(CDK[0]):
        raise DeployError("npx not found: install Node.js 20+ to run the CDK CLI.")
    run(*CDK, *args, cwd=INFRA)


def outputs(session, stack: str) -> dict[str, str]:
    described = session.client("cloudformation").describe_stacks(StackName=stack)["Stacks"][0]
    return {o["OutputKey"]: o["OutputValue"] for o in described.get("Outputs", [])}


def network_snippet(vpc_id: str, subnets: dict[str, str]) -> str:
    listed = ", ".join(f'{zone} = "{subnet}"' for zone, subnet in subnets.items())
    return f'[network]\nvpc_id          = "{vpc_id}"\nprivate_subnets = {{ {listed} }}\n'


def owned_filters(c: config.Config, name: str, vpc_id: str | None = None) -> list[dict]:
    """EC2 filters for what `prepare_network.py` creates: the project tag AND the name it gives the resource
    (`name` may use `*`), inside `vpc_id` when given. The project tag alone could match something another tool
    tagged, and both scripts change or delete what they find."""
    filters = [{"Name": "tag:Project", "Values": [c.name]}, {"Name": "tag:Name", "Values": [f"{c.name}-{name}"]}]
    return [{"Name": "vpc-id", "Values": [vpc_id]}, *filters] if vpc_id else filters
