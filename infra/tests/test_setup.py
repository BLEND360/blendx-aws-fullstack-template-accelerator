"""Runs scripts/setup.py against a throwaway copy of the repo."""

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import config

ROOT = Path(__file__).resolve().parents[2]
SETUP = ROOT / "scripts" / "setup.py"

pytestmark = pytest.mark.skipif(not SETUP.exists(), reason="setup.py already ran in this clone")


@pytest.fixture
def clone(tmp_path):
    for rel in ("project.toml", "infra/config.py", "infra/harness_files.py", "scripts/setup.py"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / rel, tmp_path / rel)
    return tmp_path


def run(clone):
    return subprocess.run(
        [sys.executable, "scripts/setup.py"], cwd=clone, capture_output=True, text=True
    )


def test_writes_env_files_and_removes_itself(clone):
    result = run(clone)
    assert result.returncode == 0, result.stderr
    backend = (clone / "backend/api/.env").read_text()
    assert f"SESSIONS_TABLE_NAME={config.load().sessions_table}" in backend
    assert "CORS" not in backend
    assert "COGNITO_USER_POOL_ID=" in backend.splitlines() and "COGNITO_APP_CLIENT_ID=" in backend.splitlines()
    secret = next(l for l in backend.splitlines() if l.startswith("AUTH_JWT_SECRET=")).split("=", 1)[1]
    assert len(secret) >= 32
    assert (clone / "frontend/web/.env").read_text().startswith("#")
    assert (clone / "harness/app/assistant/harness.json").exists()
    assert not (clone / "scripts/setup.py").exists()


def test_second_run_reports_complete(clone):
    run(clone)
    shutil.copy(SETUP, clone / "scripts/setup.py")
    before = (clone / "backend/api/.env").read_text()

    result = run(clone)

    assert result.returncode == 0
    assert "already complete" in result.stdout
    assert (clone / "backend/api/.env").read_text() == before


def test_only_the_missing_env_file_is_written_so_edits_and_the_secret_survive(clone):
    run(clone)
    shutil.copy(SETUP, clone / "scripts/setup.py")
    backend = clone / "backend/api/.env"
    backend.write_text("EDITED=1\n")
    (clone / "frontend/web/.env").unlink()

    assert run(clone).returncode == 0

    assert backend.read_text() == "EDITED=1\n"
    assert (clone / "frontend/web/.env").read_text().startswith("#")


def test_invalid_project_toml_fails_and_keeps_script(clone):
    toml = clone / "project.toml"
    toml.write_text(re.sub(r'aws_account\s*=\s*"\d+"', 'aws_account = "nope"', toml.read_text()))

    result = run(clone)

    assert result.returncode == 1
    assert "aws_account" in result.stderr
    assert (clone / "scripts/setup.py").exists()
    assert not (clone / "backend/api/.env").exists()
