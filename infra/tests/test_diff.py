import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import diff
from deployment import DeployInputs


def test_diff_always_uses_template_method_and_only_requested_stacks():
    args = diff.command(["acme-roles", "acme-auth"])
    assert args == ["diff", "acme-roles", "acme-auth", "--method=template", "--exclusively"]
    assert "deploy" not in args and "--change-set" not in args


def test_app_diff_passes_resolved_deploy_inputs_as_context():
    inputs = DeployInputs(
        env="dev",
        harness_arn="arn:aws:bedrock-agentcore:eu-west-1:111122223333:harness/assistant-AbC123",
        memory_arn="arn:aws:bedrock-agentcore:eu-west-1:111122223333:memory/assistant_mem-XyZ789",
        user_pool_id="eu-west-1_AbCdEf",
        app_client_id="clientid",
        cloudfront_prefix_list="pl-0123abcd",
        image_tag="a" * 40 + "-1",
    )
    args = diff.command(["acme-app"], inputs)
    assert args[:4] == ["diff", "acme-app", "--method=template", "--exclusively"]
    context = [args[index + 1] for index, value in enumerate(args[:-1]) if value == "-c"]
    assert dict(value.split("=", 1) for value in context) == inputs.to_context()


def test_diff_output_is_written_to_step_summary(monkeypatch, tmp_path):
    path = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(path))
    diff.write_summary("Roles", "Stack acme-roles\nNo changes.")
    assert path.read_text(encoding="utf-8") == "## Roles\n\n```diff\nStack acme-roles\nNo changes.\n```\n\n"
