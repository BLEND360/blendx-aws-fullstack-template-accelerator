import importlib.util
import sys
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

import config
from tests.test_config import VALID, write

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
_spec = importlib.util.spec_from_file_location("deploy_entrypoint", SCRIPTS / "deploy.py")
deploy = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(deploy)

EXISTING = '\n[network]\nvpc_id = "vpc-0123abcd"\nprivate_subnets = { eu-west-1a = "subnet-0a1b2c3d", eu-west-1b = "subnet-4e5f6a7b" }\n'
HARNESS_ARN = "arn:aws:bedrock-agentcore:eu-west-1:111122223333:harness/someone-elses-XyZ789"
URL = "https://d111111abcdef8.cloudfront.net"


class Ec2:
    """Answers the dry-run that asks whether the account lets this user create an internet gateway."""

    def __init__(self, allowed: bool, error: str | None = None):
        self.allowed, self.calls, self.error = allowed, [], error

    def create_internet_gateway(self, DryRun):
        assert DryRun is True  # asking must never create one
        self.calls.append("create_internet_gateway")
        code = self.error or ("DryRunOperation" if self.allowed else "UnauthorizedOperation")
        raise ClientError({"Error": {"Code": code, "Message": "x"}}, "CreateInternetGateway")


class Session:
    def __init__(self, *, allowed=True, error=None, outputs=None):
        self.ec2 = Ec2(allowed, error)
        self.outputs = [{"OutputKey": "AppPublicUrl", "OutputValue": URL}] if outputs is None else outputs

    def client(self, name):
        if name == "ec2":
            return self.ec2
        outputs = self.outputs
        return type("Cfn", (), {"describe_stacks": lambda self, StackName: {"Stacks": [{"Outputs": outputs}]}})()


class Runner:
    def __init__(self, *, fail_on: str | None = None, code: int = 1):
        self.commands: list[list[str]] = []
        self.fail_on, self.code = fail_on, code

    def __call__(self, command, **_):
        self.commands.append(command)
        failed = self.fail_on is not None and self.fail_on in command[1]
        return type("Done", (), {"returncode": self.code if failed else 0})()

    def scripts(self) -> list[str]:
        return [Path(cmd[1]).name for cmd in self.commands]


def go(tmp_path, *args, toml=VALID, runner=None, session=None):
    c = config.load(write(tmp_path, toml))
    runner = runner or Runner()
    code = deploy.main(["--env", "dev", *args], cfg=c, session=session or Session(), runner=runner)
    return code, runner


def test_the_environment_is_a_required_argument():
    with pytest.raises(SystemExit) as stop:
        deploy.main([])
    assert stop.value.code == 2


def test_it_runs_the_account_data_sign_in_harness_and_app_steps_in_that_order(tmp_path):
    code, runner = go(tmp_path)
    assert code == 0
    assert runner.scripts() == ["bootstrap.py", "deploy_data.py", "deploy_auth.py", "deploy_harness.py", "deploy_app.py"]


def test_each_step_runs_with_the_same_python_so_the_projects_dependencies_are_the_same(tmp_path):
    _, runner = go(tmp_path)
    assert {cmd[0] for cmd in runner.commands} == {sys.executable}


def test_only_the_app_step_gets_the_environment(tmp_path):
    _, runner = go(tmp_path)
    assert runner.commands[-1][2:] == ["--env", "dev"]
    assert all(len(cmd) == 2 for cmd in runner.commands[:-1])


def test_a_harness_that_already_exists_is_not_deployed(tmp_path):
    code, runner = go(tmp_path, toml=VALID.replace('arn = ""', f'arn = "{HARNESS_ARN}"'))
    assert code == 0 and "deploy_harness.py" not in runner.scripts()
    assert runner.scripts()[-1] == "deploy_app.py"


def test_a_failing_step_stops_everything_after_it_and_says_which_one_and_how_to_go_on(tmp_path, capsys):
    code, runner = go(tmp_path, runner=Runner(fail_on="deploy_auth.py", code=3))
    err = capsys.readouterr().err
    assert code == 1
    assert runner.scripts() == ["bootstrap.py", "deploy_data.py", "deploy_auth.py"]  # nothing after the failure
    assert "deploy_auth.py" in err and "exit 3" in err
    assert "deploy.py --env dev" in err  # run it again: the steps that finished change nothing


def test_an_unknown_environment_stops_before_any_step(tmp_path, capsys):
    c = config.load(write(tmp_path, VALID))
    runner = Runner()
    assert deploy.main(["--env", "qa"], cfg=c, session=Session(), runner=runner) == 1
    assert runner.commands == [] and "valid: dev" in capsys.readouterr().err


def test_it_ends_with_the_public_url_and_how_to_create_a_user(tmp_path, capsys):
    go(tmp_path)
    out = capsys.readouterr().out
    assert URL in out and "create_user.py" in out


def test_an_organization_that_forbids_internet_gateways_is_caught_before_anything_is_deployed(tmp_path, capsys):
    session = Session(allowed=False)
    code, runner = go(tmp_path, session=session)
    err = capsys.readouterr().err
    assert code == 1 and runner.commands == []
    assert "prepare_network.py" in err and "find_network.py" in err and "[network]" in err


def test_the_question_is_only_asked_never_acted_on(tmp_path):
    session = Session(allowed=True)
    go(tmp_path, session=session)
    assert session.ec2.calls == ["create_internet_gateway"]  # one dry-run, which creates nothing


def test_with_an_existing_vpc_the_question_is_not_even_asked(tmp_path):
    session = Session(allowed=False)  # irrelevant: the template will not create a network
    code, runner = go(tmp_path, toml=VALID + EXISTING, session=session)
    assert code == 0 and session.ec2.calls == [] and runner.scripts()[-1] == "deploy_app.py"


@pytest.mark.parametrize("code", ["ExpiredToken", "AuthFailure", "RequestExpired"])
def test_expired_or_invalid_credentials_are_not_mistaken_for_an_organization_policy(tmp_path, capsys, code):
    """Only UnauthorizedOperation means the organization forbids it; anything else says nothing about internet gateways."""
    code_, runner = go(tmp_path, session=Session(error=code))
    err = capsys.readouterr().err
    assert code_ == 1 and runner.commands == []
    assert code in err and "internet gateway" not in err and "login" in err


def test_a_missing_public_url_output_is_a_message_not_a_traceback(tmp_path, capsys):
    code, _ = go(tmp_path, session=Session(outputs=[]))
    assert code == 1 and "AppPublicUrl" in capsys.readouterr().err


def test_the_closing_line_about_deleting_is_accurate(tmp_path, capsys):
    go(tmp_path)
    out = capsys.readouterr().out
    assert "destroy_app.py" in out and "--confirm" in out and "--everything" in out
