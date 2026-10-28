import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from changed_paths import classify, plan

SHA = "a" * 40


def test_frontend_only_skips_image():
    assert classify(["frontend/web/src/App.tsx"]) == (False, True)


def test_backend_only_skips_spa():
    assert classify(["backend/api/app/main.py"]) == (True, False)


def test_changes_in_both_apps_run_both_steps():
    assert classify(["frontend/web/src/App.tsx", "backend/api/app/main.py"]) == (True, True)


def test_non_app_paths_run_both_steps():
    assert classify(["contract/sse-turns.json"]) == (True, True)
    assert classify(["infra/stacks/app.py"]) == (True, True)


def test_no_changed_paths_skips_both_steps():
    assert classify([]) == (False, False)


def test_unknown_or_unavailable_deployed_commit_runs_full_deploy():
    assert plan(None, SHA, None) == (True, True)
    assert plan("layerhash", SHA, None) == (True, True)
    assert plan(f"{SHA}-1", "b" * 40, None, commit_exists=False) == (True, True)


def test_same_commit_skips_image_and_spa_for_idempotent_retry():
    assert plan(f"{SHA}-3", SHA, None) == (False, False)


def test_paths_from_the_running_image_decide_which_artifact_changes():
    assert plan(f"{SHA}-1", "b" * 40, ["frontend/web/src/App.tsx"]) == (False, True)
    assert plan(f"{SHA}-1", "b" * 40, ["backend/api/app/main.py"]) == (True, False)
