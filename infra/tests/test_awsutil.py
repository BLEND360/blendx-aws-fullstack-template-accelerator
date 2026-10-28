import subprocess
import sys
from pathlib import Path

import pytest
from botocore.exceptions import ClientError, NoCredentialsError

from tests.conftest import fixed_config

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import awsutil  # noqa: E402


def failing(error):
    @awsutil.cli
    def main() -> int:
        raise error

    return main


@pytest.mark.parametrize(
    "error,shown",
    [
        (awsutil.DeployError("no good"), "no good"),
        (ValueError("bad toml"), "bad toml"),
        (ClientError({"Error": {"Code": "ExpiredToken", "Message": "token expired"}}, "Op"), "ExpiredToken (token expired)"),
        (NoCredentialsError(), "NoCredentialsError"),
        (subprocess.CalledProcessError(3, ["cdk", "deploy"]), "`cdk deploy` failed (exit 3)"),
    ],
)
def test_an_expected_failure_is_a_message_and_exit_code_1_not_a_traceback(error, shown, capsys):
    assert failing(error)() == 1
    assert shown in capsys.readouterr().err


def test_a_bug_is_not_hidden(capsys):
    with pytest.raises(KeyError):
        failing(KeyError("UserPoolId"))()


def test_a_project_toml_that_is_missing_or_incomplete_is_a_message(tmp_path):
    with pytest.raises(awsutil.DeployError, match="not found"):
        awsutil.load_config(tmp_path / "project.toml")
    (tmp_path / "project.toml").write_text("[project]\nname = 'x'\n")
    with pytest.raises(awsutil.DeployError, match="missing"):
        awsutil.load_config(tmp_path / "project.toml")


def test_credentials_for_another_account_are_refused_with_the_switch_profile_hint():
    c = fixed_config()
    session = type("S", (), {"client": lambda self, name: type("Sts", (), {"get_caller_identity": lambda self: {"Account": "999999999999"}})()})()
    with pytest.raises(awsutil.DeployError, match="999999999999.*Switch profile"):
        awsutil.check_account(c, session)
