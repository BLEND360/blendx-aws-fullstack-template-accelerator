import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "bootstrap", Path(__file__).resolve().parents[2] / "scripts" / "bootstrap.py"
)
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
