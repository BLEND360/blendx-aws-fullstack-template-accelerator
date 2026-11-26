import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("envfile", Path(__file__).resolve().parents[2] / "scripts" / "envfile.py")
envfile = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(envfile)


def test_updates_in_place_appends_missing_and_keeps_comments(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# keep\nA=1\nLOCAL_AUTH_BYPASS=true\nCOGNITO_USER_POOL_ID=\n")
    envfile.update(env, {"LOCAL_AUTH_BYPASS": "false", "COGNITO_USER_POOL_ID": "pool", "NEW": "x"})
    assert env.read_text() == "# keep\nA=1\nLOCAL_AUTH_BYPASS=false\nCOGNITO_USER_POOL_ID=pool\nNEW=x\n"


def test_get_returns_empty_for_missing_or_blank(tmp_path):
    env = tmp_path / ".env"
    env.write_text("A=1\nB=\n")
    assert (envfile.get(env, "A"), envfile.get(env, "B"), envfile.get(env, "C")) == ("1", "", "")


def test_no_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        envfile.update(tmp_path / "nope", {"A": "1"})


def test_create_makes_a_missing_file_with_the_values(tmp_path):
    env = tmp_path / "web" / ".env"
    envfile.update(env, {"A": "1"}, create=True)
    assert "A=1" in env.read_text().splitlines()
