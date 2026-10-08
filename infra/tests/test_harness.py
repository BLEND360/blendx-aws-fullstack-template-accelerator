import dataclasses
import importlib.util
import json
from pathlib import Path

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Template

import config
import harness_files
from definitions.roles import role_specs
from stacks.roles import RolesStack

ROOT = Path(__file__).resolve().parents[2]
STARTER = config.load()
CONSUMER = dataclasses.replace(
    STARTER, harness_arn=f"arn:aws:bedrock-agentcore:{STARTER.aws_region}:{STARTER.aws_account}:harness/platform-abc"
)

spec = importlib.util.spec_from_file_location("deploy_harness", ROOT / "scripts" / "deploy_harness.py")
deploy_harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy_harness)


def test_harness_json_is_model_and_managed_memory_only():
    harness = harness_files.render(STARTER)["app/assistant/harness.json"]
    assert harness == {
        "name": "assistant",
        "model": {"provider": "bedrock", "modelId": STARTER.harness_model_id},
        "executionRoleArn": STARTER.role_arn(STARTER.harness_execution_role),
        "memory": {"mode": "managed"},
    }


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
    monkeypatch.setattr(deploy_harness, "run", lambda *cmd, **kw: log.append(cmd) or "")
    monkeypatch.setattr(
        deploy_harness, "platform",
        lambda script, *args: log.append((script, *args))
        or json.dumps({"id": "h-1", "arn": "arn:h-1", "version": "3"}),
    )
    monkeypatch.setattr(harness_files, "HARNESS_DIR", tmp_path)
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    return log


def test_configured_arn_deploys_nothing(calls, monkeypatch, capsys):
    monkeypatch.setattr(config, "load", lambda: CONSUMER)
    assert deploy_harness.main() == 0
    assert calls == []
    out = capsys.readouterr().out
    assert "harness.arn" in out and CONSUMER.harness_arn in out
    assert f"harness_endpoint={CONSUMER.harness_endpoint}" in out


def test_starter_deploys_in_platform_order(calls, monkeypatch, capsys):
    monkeypatch.setattr(config, "load", lambda: STARTER)
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
