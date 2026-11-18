import dataclasses
import importlib.util
import sys
from pathlib import Path

from tests.conftest import fixed_config

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
_spec = importlib.util.spec_from_file_location("deploy_data", ROOT / "scripts" / "deploy_data.py")
deploy_data = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(deploy_data)


def test_a_renamed_project_rewrites_the_names_in_the_local_env(tmp_path):
    backend = tmp_path / ".env"
    frontend = tmp_path / "frontend.env"
    backend.write_text("PROJECT_NAME=my-app\nSESSIONS_TABLE_NAME=my-app-sessions\nLOCAL_AUTH_BYPASS=true\n")
    frontend.write_text("VITE_COGNITO_REGION=us-west-2\n")
    c = dataclasses.replace(fixed_config(), name="renamed-project")

    deploy_data.wire_local_names(c, backend, frontend)

    lines = backend.read_text().splitlines()
    assert "PROJECT_NAME=renamed-project" in lines
    assert f"SESSIONS_TABLE_NAME={c.sessions_table}" in lines
    assert f"ITEMS_TABLE_NAME={c.items_table}" in lines
    assert "LOCAL_AUTH_BYPASS=true" in lines  # keys it does not own are kept
    assert frontend.read_text() == f"VITE_COGNITO_REGION={c.aws_region}\n"


def test_missing_env_files_are_skipped_without_creating_them(tmp_path):
    c = fixed_config()
    deploy_data.wire_local_names(c, tmp_path / ".env", tmp_path / "frontend.env")
    assert list(tmp_path.iterdir()) == []
