import dataclasses
import importlib.util
import json
import re
import sys
from pathlib import Path

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Template

import config
import harness_files
from definitions.roles import role_specs
from stacks.roles import RolesStack
from tests.conftest import fixed_config

ROOT = Path(__file__).resolve().parents[2]
STARTER = fixed_config()
CONSUMER = dataclasses.replace(
    STARTER, harness_arn=f"arn:aws:bedrock-agentcore:{STARTER.aws_region}:{STARTER.aws_account}:harness/platform-abc"
)

sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("deploy_harness", ROOT / "scripts" / "deploy_harness.py")
deploy_harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy_harness)


def test_harness_json_is_model_memory_and_the_app_tools_only():
    harness = harness_files.render(STARTER)["app/assistant/harness.json"]
    assert harness == {
        "name": "assistant",
        "model": {"provider": "bedrock", "modelId": STARTER.harness_model_id},
        "executionRoleArn": STARTER.role_arn(STARTER.harness_execution_role),
        "memory": {"mode": "managed"},
        "allowedTools": ["current_time"],
    }


def test_allowed_tools_are_exactly_the_apps_tools():
    # The app declares its tools in backend/api/app/tools/builtin.py as Tool(id="..."). Read the ids
    # without importing the backend, whose dependencies this venv does not have.
    builtin = (ROOT / "backend" / "api" / "app" / "tools" / "builtin.py").read_text(encoding="utf-8")
    app_tools = set(re.findall(r'id="([a-zA-Z0-9_-]+)"', builtin))
    assert set(harness_files.ALLOWED_TOOLS) == app_tools


def test_agentcore_names_follow_platform_convention():
    files = harness_files.render(STARTER)
    project = files["agentcore/agentcore.json"]
    (target,) = files["agentcore/aws-targets.json"]
    # The vended CDK app names its stack AgentCore-<project>-<target>.
    assert STARTER.harness_stack == f"AgentCore-{project['name']}-{target['name']}"
    assert project["harnesses"] == [{"name": "assistant", "path": "app/assistant"}]
    assert (target["account"], target["region"]) == (STARTER.aws_account, STARTER.aws_region)


def test_write_is_stable(tmp_path):
    harness_files.write(STARTER, tmp_path)
    first = {p: p.read_text() for p in tmp_path.rglob("*.json")}
    harness_files.write(STARTER, tmp_path)
    assert first == {p: p.read_text() for p in tmp_path.rglob("*.json")}
    assert json.loads((tmp_path / "app/assistant/harness.json").read_text())["name"] == "assistant"


def test_wire_local_api_sets_harness_in_env(tmp_path):
    env = tmp_path / ".env"
    env.write_text("HARNESS_ARN=\nHARNESS_ENDPOINT=\nLOCAL_AUTH_BYPASS=true\n")
    assert deploy_harness.wire_local_api("arn:x", "PROD", env)
    assert env.read_text().splitlines() == ["HARNESS_ARN=arn:x", "HARNESS_ENDPOINT=PROD", "LOCAL_AUTH_BYPASS=true"]


def test_wire_local_api_skips_when_no_env(tmp_path):
    assert not deploy_harness.wire_local_api("arn:x", "PROD", tmp_path / ".env")
    assert not (tmp_path / ".env").exists()


def roles_template(c: config.Config) -> Template:
    stack = RolesStack(cdk.App(), c.roles_stack, specs=role_specs(c),
                       env=cdk.Environment(account=c.aws_account, region=c.aws_region))
    return Template.from_stack(stack)


def test_harness_role_present_only_without_configured_arn():
    name = STARTER.harness_execution_role
    assert roles_template(STARTER).find_resources("AWS::IAM::Role", {"Properties": {"RoleName": name}})
    assert not roles_template(CONSUMER).find_resources("AWS::IAM::Role", {"Properties": {"RoleName": name}})


def test_consumer_deploy_role_cannot_repoint_endpoints():
    policies = json.dumps(roles_template(CONSUMER).find_resources("AWS::IAM::Policy"))
    assert "HarnessEndpoint" not in policies
    assert "UpdateHarnessEndpoint" in json.dumps(roles_template(STARTER).find_resources("AWS::IAM::Policy"))


@pytest.fixture
def calls(monkeypatch, tmp_path):
    log = []
    monkeypatch.setattr(deploy_harness, "BACKEND_ENV", tmp_path / "no-such.env")  # never touch the real backend .env
    monkeypatch.setattr(deploy_harness, "run", lambda *cmd, **kw: log.append(cmd) or "")
    monkeypatch.setattr(
        deploy_harness, "platform",
        lambda script, *args: log.append((script, *args))
        or json.dumps({"id": "h-1", "arn": "arn:h-1", "version": "3"}),
    )
    monkeypatch.setattr(harness_files, "HARNESS_DIR", tmp_path)
    return log


def test_configured_arn_deploys_nothing(calls, monkeypatch, capsys):
    monkeypatch.setattr(config, "load", lambda *_: CONSUMER)
    assert deploy_harness.main() == 0
    assert calls == []
    out = capsys.readouterr().out
    assert "harness.arn" in out and CONSUMER.harness_arn in out
    assert f"harness_endpoint={CONSUMER.harness_endpoint}" in out


def test_starter_reuses_an_accelerator_harness_already_in_the_account(calls, monkeypatch, capsys):
    monkeypatch.setattr(config, "load", lambda *_: STARTER)
    monkeypatch.setattr(deploy_harness, "stack_exists", lambda *_: False)
    monkeypatch.setattr(deploy_harness, "find_accelerator_harness", lambda *_: "arn:shared")
    assert deploy_harness.main() == 0
    assert calls == []  # nothing deployed, no endpoint touched
    assert "harness_arn=arn:shared" in capsys.readouterr().out


def test_starter_deploys_in_platform_order(calls, monkeypatch, capsys):
    monkeypatch.setattr(config, "load", lambda *_: STARTER)
    monkeypatch.setattr(deploy_harness, "stack_exists", lambda *_: False)
    monkeypatch.setattr(deploy_harness, "find_accelerator_harness", lambda *_: None)
    assert deploy_harness.main() == 0
    steps = [c[0] if c[0] != "agentcore" else f"agentcore {c[1]}" for c in calls]
    assert steps == [
        "npm",
        "agentcore validate",
        "agentcore deploy",
        "get-harness-version.sh",
        "point-harness-alias.sh",
        "wait-harness-ready.sh",
    ]
    assert calls[3][1:] == (STARTER.harness_stack, STARTER.harness_logical_name)
    assert "--version" in calls[4] and "3" in calls[4]
    assert "harness_arn=arn:h-1" in capsys.readouterr().out


def shared(monkeypatch, arn="arn:shared", own_stack=False):
    monkeypatch.setattr(config, "load", lambda *_: STARTER)
    monkeypatch.setattr(deploy_harness, "stack_exists", lambda *_: own_stack)
    monkeypatch.setattr(deploy_harness, "find_accelerator_harness", lambda *_: arn)


def test_rerunning_with_the_projects_own_stack_deploys_in_place_and_never_searches(calls, monkeypatch):
    shared(monkeypatch, own_stack=True)
    monkeypatch.setattr(deploy_harness, "find_accelerator_harness", lambda *_: pytest.fail("searched with its own stack"))
    assert deploy_harness.main() == 0
    assert ("agentcore", "deploy", "-y", "-v") in calls


def test_reusing_twice_gives_the_same_harness_and_deploys_nothing(calls, monkeypatch, capsys):
    shared(monkeypatch)
    assert deploy_harness.main() == 0
    assert deploy_harness.main() == 0
    assert calls == []
    assert capsys.readouterr().out.count("harness_arn=arn:shared") == 2


def test_reusing_writes_the_shared_arn_into_the_local_env(calls, monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text("HARNESS_ARN=\nHARNESS_ENDPOINT=\n")
    monkeypatch.setattr(deploy_harness, "BACKEND_ENV", env)
    shared(monkeypatch)
    assert deploy_harness.main() == 0
    assert env.read_text().splitlines() == ["HARNESS_ARN=arn:shared", "HARNESS_ENDPOINT=PROD"]


def test_a_missing_local_env_is_said_out_loud_not_skipped_silently(calls, monkeypatch, capsys):
    shared(monkeypatch)  # BACKEND_ENV is redirected to a file that does not exist, by the calls fixture
    assert deploy_harness.main() == 0
    assert "scripts/setup.py" in capsys.readouterr().out


def test_a_failed_lookup_stops_and_never_deploys_a_second_harness(calls, monkeypatch):
    from awsutil import DeployError

    monkeypatch.setattr(config, "load", lambda *_: STARTER)
    monkeypatch.setattr(deploy_harness, "stack_exists", lambda *_: False)

    def denied(*_):
        raise DeployError("Cannot read the harness (AccessDeniedException).")

    monkeypatch.setattr(deploy_harness, "find_accelerator_harness", denied)
    assert deploy_harness.main() != 0  # @cli reports the error and exits non-zero
    assert calls == []
