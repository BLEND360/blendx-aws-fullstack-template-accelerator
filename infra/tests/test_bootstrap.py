import importlib.util
import sys
from pathlib import Path

from tests.conftest import fixed_config

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))  # bootstrap imports awsutil from its own folder, as it does when run
spec = importlib.util.spec_from_file_location("bootstrap", SCRIPTS / "bootstrap.py")
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


class FakeIam:
    def __init__(self, arns):
        self.arns, self.created = list(arns), 0

    def list_open_id_connect_providers(self):
        return {"OpenIDConnectProviderList": [{"Arn": a} for a in self.arns]}

    def create_open_id_connect_provider(self, **kwargs):
        self.created += 1
        arn = f"arn:aws:iam::1:oidc-provider/{kwargs['Url'].removeprefix('https://')}"
        self.arns.append(arn)
        return {"OpenIDConnectProviderArn": arn}


def test_oidc_provider_created_once():
    iam = FakeIam(["arn:aws:iam::1:oidc-provider/accounts.google.com"])
    first = bootstrap.ensure_oidc_provider(iam)
    second = bootstrap.ensure_oidc_provider(iam)
    assert first == second
    assert first.endswith("oidc-provider/token.actions.githubusercontent.com")
    assert iam.created == 1


def test_roles_only_skips_account_bootstrap_and_oidc_provider(monkeypatch, capsys):
    c = fixed_config()
    calls = []

    class Sts:
        def get_caller_identity(self):
            return {"Account": c.aws_account}

    class Session:
        def __init__(self, **_):
            pass

        def client(self, name):
            assert name == "sts"
            return Sts()

    monkeypatch.setattr(bootstrap, "load_config", lambda: c)
    monkeypatch.setattr(bootstrap.boto3, "Session", Session)
    monkeypatch.setattr(bootstrap, "cdk", lambda *args: calls.append(args))
    monkeypatch.setattr(bootstrap, "ensure_oidc_provider", lambda *_: (_ for _ in ()).throw(AssertionError()))

    assert bootstrap.main(["--roles-only"]) == 0
    assert calls == [("deploy", c.roles_stack, "--exclusively", "--require-approval", "never")]
    assert "[1/1] deploy" in capsys.readouterr().out
