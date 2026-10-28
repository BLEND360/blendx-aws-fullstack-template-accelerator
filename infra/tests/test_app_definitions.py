import importlib.util
import json
import sys
from pathlib import Path

import pytest

from definitions.app import APP_ID, app_specs
from deployment import DeployInputs
from tests.conftest import fixed_config
from tests.test_deployment_inputs import GOOD

ROOT = Path(__file__).resolve().parents[2]
SETUP = ROOT / "scripts" / "setup.py"
C = fixed_config()
PREFIX = f"arn:aws:bedrock-agentcore:{C.aws_region}:{C.aws_account}"
INPUTS = DeployInputs(
    **{
        **GOOD,
        "harness_arn": f"{PREFIX}:harness/assistant-AbC123",
        "memory_arn": f"{PREFIX}:memory/assistant_mem-XyZ789",
        "env": "dev",
    }
)
EXPECTED_VARIABLES = {
    "PROJECT_NAME": C.name,
    "AWS_REGION": C.aws_region,
    "SESSIONS_TABLE_NAME": C.sessions_table,
    "ITEMS_TABLE_NAME": C.items_table,
    "HARNESS_ARN": INPUTS.harness_arn,
    "HARNESS_ENDPOINT": C.harness_endpoint,
    "ALLOWED_MODEL_IDS": json.dumps(list(C.model_ids)),
    "COGNITO_USER_POOL_ID": INPUTS.user_pool_id,
    "COGNITO_APP_CLIENT_ID": INPUTS.app_client_id,
}


def spec(inputs: DeployInputs = INPUTS):
    (only,) = app_specs(C, inputs)
    return only


def test_the_task_receives_the_nine_variables_setup_py_writes():
    assert spec().api.environment == EXPECTED_VARIABLES


@pytest.mark.skipif(not SETUP.exists(), reason="setup.py already ran in this clone")
def test_the_variables_match_the_ones_setup_py_generates_for_local_runs():
    sys.path.insert(0, str(ROOT / "infra"))
    module = importlib.util.spec_from_file_location("setup_script", SETUP)
    setup = importlib.util.module_from_spec(module)
    module.loader.exec_module(setup)
    local = dict(l.split("=", 1) for l in setup.backend_env(C).splitlines() if "=" in l and not l.startswith("#"))
    deployed = set(spec().api.environment)
    assert deployed == set(local) - {"LOCAL_AUTH_BYPASS", "AUTH_JWT_SECRET"}
    for key in deployed - {"HARNESS_ARN", "COGNITO_USER_POOL_ID", "COGNITO_APP_CLIENT_ID"}:
        assert spec().api.environment[key] == local[key], key


@pytest.mark.parametrize("local_only", ["LOCAL_AUTH_BYPASS", "DATA_STORE", "HARNESS_REPLAY", "AUTH_JWT_SECRET"])
def test_variables_that_must_not_reach_a_deployed_task_are_absent(local_only):
    assert local_only not in spec().api.environment


def test_the_session_secret_is_named_from_the_project_not_given_as_a_value():
    assert spec().api.jwt_secret_name == C.auth_jwt_secret_name


def test_names_and_roles_derive_from_the_configuration():
    api = spec().api
    assert (api.repository, api.cluster, api.service) == (C.ecr_repository, C.cluster, C.service)
    assert api.load_balancer == C.load_balancer and api.log_group == C.log_group
    assert api.task_role_arn == C.role_arn(C.task_role)
    assert api.execution_role_arn == C.role_arn(C.execution_role)
    assert spec().web.bucket == C.web_bucket


def test_the_environment_decides_size():
    api = spec().api
    dev = C.sizing("dev")
    assert (api.cpu, api.memory) == (dev.cpu, dev.memory)
    prod = spec(DeployInputs(**{**vars(INPUTS), "env": "prod"})).api
    assert (prod.cpu, prod.memory, prod.desired_count) == (C.sizing("prod").cpu, C.sizing("prod").memory, 2)


def test_with_an_image_the_service_runs_the_configured_number_of_tasks():
    api = spec().api
    assert api.image_tag == INPUTS.image_tag and api.desired_count == C.sizing("dev").desired_count


def test_without_an_image_the_service_has_no_tasks():
    api = spec(DeployInputs(**{**vars(INPUTS), "image_tag": ""})).api
    assert api.desired_count == 0 and api.image_tag == ""


def test_the_three_harness_grants_are_scoped_to_the_resolved_arns():
    statements = [s.to_statement_json() for s in spec().api.task_statements]
    by_sid = {s["Sid"]: s for s in statements}
    assert set(by_sid) == {"InvokeHarness", "GetHarness", "HarnessMemoryEvents"}
    assert by_sid["InvokeHarness"]["Resource"] == [INPUTS.harness_arn, f"{INPUTS.harness_arn}/*"]
    assert by_sid["GetHarness"]["Resource"] == INPUTS.harness_arn
    assert by_sid["HarnessMemoryEvents"]["Resource"] == INPUTS.memory_arn


def test_the_web_entry_routes_the_two_reserved_prefixes_to_the_api():
    web = spec().web
    assert web.api_paths == ("/api/*", "/auth/*")
    assert web.origin_read_timeout_seconds == 60 and web.spa_fallback


def test_the_load_balancer_admits_only_the_prefix_list():
    assert spec().api.cloudfront_prefix_list == INPUTS.cloudfront_prefix_list


def test_the_app_spec_has_a_stable_id():
    assert spec().id == APP_ID
