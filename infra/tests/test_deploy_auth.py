import importlib.util
import sys
from pathlib import Path

import config

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def load_script(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))  # deploy_auth imports bootstrap from its own folder
    spec = importlib.util.spec_from_file_location("deploy_auth", SCRIPTS / "deploy_auth.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


OUT = {"UserPoolId": "us-east-1_abc", "AppClientId": "client-1", "Domain": "x.auth.us-east-1.amazoncognito.com"}


def test_env_values_hold_everything_both_apps_need_and_turn_the_bypass_off(monkeypatch):
    backend, frontend = load_script(monkeypatch).env_values(config.load(), OUT)
    assert backend == {
        "COGNITO_USER_POOL_ID": "us-east-1_abc",
        "COGNITO_APP_CLIENT_ID": "client-1",
        "LOCAL_AUTH_BYPASS": "false",
    }
    assert frontend == {
        "VITE_COGNITO_REGION": config.load().aws_region,
        "VITE_COGNITO_USER_POOL_ID": "us-east-1_abc",
        "VITE_COGNITO_APP_CLIENT_ID": "client-1",
        "VITE_COGNITO_DOMAIN": "x.auth.us-east-1.amazoncognito.com",
    }


def test_deploy_writes_both_env_files_and_creates_the_secret_once(monkeypatch, tmp_path):
    deploy_auth = load_script(monkeypatch)
    account = config.load().aws_account

    class Sts:
        def get_caller_identity(self):
            return {"Account": account}

    class Cfn:
        def describe_stacks(self, StackName):
            return {"Stacks": [{"Outputs": [{"OutputKey": k, "OutputValue": v} for k, v in OUT.items()]}]}

    class Session:
        def __init__(self, **_):
            pass

        def client(self, name):
            return Sts() if name == "sts" else Cfn()

    backend, frontend = tmp_path / "backend.env", tmp_path / "frontend.env"
    backend.write_text("LOCAL_AUTH_BYPASS=true\nCOGNITO_USER_POOL_ID=\nAUTH_JWT_SECRET=<secreto>\n")  # a placeholder is not a secret
    frontend.write_text("VITE_COGNITO_USER_POOL_ID=\n")
    monkeypatch.setattr(deploy_auth.boto3, "Session", Session)
    monkeypatch.setattr(deploy_auth, "cdk", lambda *a: None)
    monkeypatch.setattr(deploy_auth, "BACKEND_ENV", backend)
    monkeypatch.setattr(deploy_auth, "FRONTEND_ENV", frontend)

    assert deploy_auth.main() == 0
    text = backend.read_text()
    assert "LOCAL_AUTH_BYPASS=false" in text and "COGNITO_USER_POOL_ID=us-east-1_abc" in text
    secret = next(l for l in text.splitlines() if l.startswith("AUTH_JWT_SECRET=")).split("=", 1)[1]
    assert len(secret) >= 32
    assert "VITE_COGNITO_DOMAIN=x.auth.us-east-1.amazoncognito.com" in frontend.read_text()

    assert deploy_auth.main() == 0  # a second run keeps the secret
    assert f"AUTH_JWT_SECRET={secret}" in backend.read_text()


def test_a_foreign_account_deploys_nothing(monkeypatch, capsys):
    deploy_auth = load_script(monkeypatch)
    deployed = []

    class Sts:
        def get_caller_identity(self):
            return {"Account": "999999999999"}

    class Session:
        def __init__(self, **_):
            pass

        def client(self, name):
            return Sts()

    monkeypatch.setattr(deploy_auth.boto3, "Session", Session)
    monkeypatch.setattr(deploy_auth, "cdk", lambda *a: deployed.append(a))
    assert deploy_auth.main() == 1
    err = capsys.readouterr().err
    assert "999999999999" in err and config.load().aws_account in err
    assert deployed == []
