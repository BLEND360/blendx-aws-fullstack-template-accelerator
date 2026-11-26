import pytest

import config

VALID = """
[project]
name = "acme-portal"
aws_account = "111122223333"
aws_region = "eu-west-1"
github_org = "ACME"
github_repo = "portal"

[harness]
arn = ""
endpoint = "PROD"
model_id = "model-a"
model_ids = ["model-a", "model-b"]

[environments.dev]
desired_count = 1
cpu = 256
memory = 512
"""


def write(tmp_path, text):
    path = tmp_path / "project.toml"
    path.write_text(text)
    return path


def test_repo_project_toml_is_valid():
    config.load()


def test_every_name_derives_from_project_name(tmp_path):
    c = config.load(write(tmp_path, VALID))
    names = {
        p: getattr(c, p)
        for p, v in vars(config.Config).items()
        if isinstance(v, property) and isinstance(getattr(c, p), str)
    }
    assert names["sessions_table"] == "acme-portal-sessions"
    assert names["web_bucket"] == "acme-portal-web-111122223333-eu-west-1"
    assert names["harness_stack"] == "AgentCore-acmeportal-default"
    assert names["harness_logical_name"] == "Assistant"
    for prop, value in names.items():
        if prop != "harness_logical_name":
            assert "acme-portal" in value or "acmeportal" in value, prop


def test_starter_harness_skipped_when_arn_set(tmp_path):
    c = config.load(write(tmp_path, VALID.replace('arn = ""', 'arn = "arn:aws:x"')))
    assert not c.deploys_starter_harness
    assert config.load(write(tmp_path, VALID)).deploys_starter_harness


def test_environments_parsed(tmp_path):
    c = config.load(write(tmp_path, VALID))
    assert c.environments == {"dev": config.Sizing(1, 256, 512)}


@pytest.mark.parametrize(
    "old,new",
    [
        ('name = "acme-portal"', 'name = "Acme_Portal"'),
        ('name = "acme-portal"', 'name = "a--b"'),
        ('name = "acme-portal"', 'name = "' + "a" * 25 + '"'),
        ('aws_account = "111122223333"', 'aws_account = "123"'),
        ('aws_region = "eu-west-1"', 'aws_region = "europe"'),
        ('github_repo = "portal"', 'github_repo = "*"'),
        ('model_ids = ["model-a", "model-b"]', "model_ids = []"),
        ('model_id = "model-a"', 'model_id = "model-z"'),
        ('endpoint = "PROD"', 'endpoint = "LIVE"'),
    ],
)
def test_invalid_values_rejected(tmp_path, old, new):
    with pytest.raises(ValueError):
        config.load(write(tmp_path, VALID.replace(old, new)))


def test_unknown_sizing_key_is_a_validation_error(tmp_path):
    with pytest.raises(ValueError, match=r"environments\.dev: unknown keys \['nat_gateway'\]"):
        config.load(write(tmp_path, VALID + "nat_gateway = 2\n"))


def test_missing_sizing_key_is_a_validation_error(tmp_path):
    with pytest.raises(ValueError, match=r"environments\.dev"):
        config.load(write(tmp_path, VALID.replace("cpu = 256\n", "")))


def test_scalar_model_ids_is_rejected_not_split_into_characters(tmp_path):
    with pytest.raises(ValueError, match="model_ids: must be a list"):
        config.load(write(tmp_path, VALID.replace('model_ids = ["model-a", "model-b"]', 'model_ids = "model-a"')))


def test_auth_names_and_default_callbacks(tmp_path):
    c = config.load(write(tmp_path, VALID))
    assert (c.user_pool, c.app_client) == ("acme-portal-users", "acme-portal-web")
    assert c.cognito_domain_prefix == "acme-portal-111122223333"
    assert c.auth_callback_urls == ()


def test_extra_callback_urls_are_read(tmp_path):
    text = VALID + '\n[auth]\ncallback_urls = ["https://app.acme.test/", "http://localhost:3000/"]\n'
    assert config.load(write(tmp_path, text)).auth_callback_urls == ("https://app.acme.test/", "http://localhost:3000/")


@pytest.mark.parametrize("url", ["http://app.acme.test/", "https://*.acme.test/", "https://app.acme.test/#x", "ftp://x"])
def test_invalid_callback_url_is_rejected_naming_it(tmp_path, url):
    with pytest.raises(ValueError, match="callback_urls"):
        config.load(write(tmp_path, VALID + f'\n[auth]\ncallback_urls = ["{url}"]\n'))


@pytest.mark.parametrize("name", ["my-aws-app", "cognito-demo", "amazon-shop"])
def test_name_cognito_cannot_put_in_a_domain_is_rejected(tmp_path, name):
    with pytest.raises(ValueError, match="Cognito"):
        config.load(write(tmp_path, VALID.replace("acme-portal", name)))
