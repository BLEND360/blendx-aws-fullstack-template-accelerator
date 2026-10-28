import importlib.util
import sys
from pathlib import Path

import config
from tests.conftest import fixed_config

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
EMAIL = "you@example.com"


class Idp:
    class exceptions:
        class UsernameExistsException(Exception):
            pass

        class InvalidPasswordException(Exception):
            response = {"Error": {"Message": "Password did not conform with policy"}}

    def __init__(self, *, exists=False, reject=False):
        self.exists, self.reject, self.calls = exists, reject, []

    def admin_create_user(self, **kw):
        if self.exists:
            raise self.exceptions.UsernameExistsException()
        self.calls.append(("create", kw["Username"]))

    def admin_set_user_password(self, **kw):
        if self.reject:
            raise self.exceptions.InvalidPasswordException()
        assert kw["Permanent"] is True
        self.calls.append(("password", kw["Password"]))

    def admin_add_user_to_group(self, **kw):
        self.calls.append(("group", kw["GroupName"]))


def run(monkeypatch, *args, idp=None, outputs=None):
    c = fixed_config()
    monkeypatch.setattr(config, "load", lambda *a: c)
    spec = importlib.util.spec_from_file_location("create_user", SCRIPTS / "create_user.py")
    create_user = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(create_user)
    idp = idp or Idp()
    outputs = [{"OutputKey": "UserPoolId", "OutputValue": "pool-1"}] if outputs is None else outputs

    class Session:
        def client(self, name):
            return {
                "sts": type("Sts", (), {"get_caller_identity": lambda self: {"Account": c.aws_account}})(),
                "cloudformation": type("Cfn", (), {"describe_stacks": lambda self, StackName: {"Stacks": [{"Outputs": outputs}]}})(),
                "cognito-idp": idp,
            }[name]

    monkeypatch.setattr(create_user.boto3, "Session", lambda **_: Session())
    monkeypatch.setattr(sys, "argv", ["create_user.py", EMAIL, *args])
    return create_user.main(), idp


def test_a_new_user_without_a_password_gets_a_generated_one_that_is_printed(monkeypatch, capsys):
    code, idp = run(monkeypatch)
    out = capsys.readouterr().out
    password = dict(idp.calls)["password"]
    assert code == 0 and ("create", EMAIL) in idp.calls and ("group", "admin") in idp.calls and f"Password: {password}" in out


def test_an_existing_user_is_not_given_a_new_password_unless_one_is_supplied(monkeypatch, capsys):
    code, idp = run(monkeypatch, idp=Idp(exists=True))
    assert code == 0 and idp.calls == [("group", "admin")] and "unchanged" in capsys.readouterr().out
    code, idp = run(monkeypatch, "--password", "Str0ng!Passw0rd", idp=Idp(exists=True))
    assert code == 0 and ("password", "Str0ng!Passw0rd") in idp.calls and ("group", "admin") in idp.calls


def test_a_password_the_pool_rejects_is_a_message_and_says_how_to_go_on(monkeypatch, capsys):
    code, _ = run(monkeypatch, "--password", "short", idp=Idp(reject=True))
    err = capsys.readouterr().err
    assert code == 1 and "did not conform" in err and "run this again" in err


def test_a_stack_without_the_pool_output_is_a_message_not_a_traceback(monkeypatch, capsys):
    code, idp = run(monkeypatch, outputs=[])
    assert code == 1 and "UserPoolId" in capsys.readouterr().err and idp.calls == []
