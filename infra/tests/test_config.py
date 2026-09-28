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
    assert names["harness_output_prefix"] == "HarnessAssistant"
    for prop, value in names.items():
        if prop != "harness_output_prefix":
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
    ],
)
def test_invalid_values_rejected(tmp_path, old, new):
    with pytest.raises(ValueError):
        config.load(write(tmp_path, VALID.replace(old, new)))
