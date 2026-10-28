import aws_cdk as cdk
import pytest

import app as infra_app
import config
from tests.test_app_definitions import INPUTS
from tests.test_config import VALID, write

SUBNETS = '{ eu-west-1a = "subnet-0a1b2c3d", eu-west-1b = "subnet-4e5f6a7b" }'
EXISTING = f'\n[network]\nvpc_id = "vpc-0123abcd"\nprivate_subnets = {SUBNETS}\n'
PREFIX = "arn:aws:bedrock-agentcore:eu-west-1:111122223333"
CONTEXT = {
    "env": "dev",
    "harness_arn": f"{PREFIX}:harness/assistant-AbC123",
    "memory_arn": f"{PREFIX}:memory/assistant_mem-XyZ789",
    "user_pool_id": "eu-west-1_AbCdEf",
    "app_client_id": "1example23456789",
    "cloudfront_prefix_list": "pl-4fa04526",
    "image_tag": "0123456789ab",
}


def stacks(c: config.Config, context: dict | None = None):
    app = cdk.App(context=context or {})
    infra_app.build(app, c)
    return {s.stack_name: s for s in app.synth().stacks}


@pytest.fixture
def creating(tmp_path) -> config.Config:
    return config.load(write(tmp_path, VALID))


@pytest.fixture
def existing(tmp_path) -> config.Config:
    return config.load(write(tmp_path, VALID + EXISTING))


def test_without_an_environment_only_the_identity_and_data_stacks_exist(creating):
    assert set(stacks(creating)) == {creating.roles_stack, creating.auth_stack, creating.data_stack}


def test_with_an_environment_the_network_and_the_app_join_them(creating):
    assert set(stacks(creating, CONTEXT)) == {
        creating.roles_stack, creating.auth_stack, creating.data_stack, creating.network_stack, creating.app_stack,
    }


def test_the_app_stack_depends_on_the_network_it_created(creating):
    found = stacks(creating, CONTEXT)
    assert creating.network_stack in [d.id for d in found[creating.app_stack].dependencies]


def test_the_environment_decides_the_number_of_nat_gateways(tmp_path):
    body = VALID.replace("memory = 512", "memory = 512\nnat_gateways = 2")
    c = config.load(write(tmp_path, body))
    template = stacks(c, CONTEXT)[c.network_stack].template
    assert sum(r["Type"] == "AWS::EC2::NatGateway" for r in template["Resources"].values()) == 2


def test_with_an_existing_vpc_there_is_no_network_stack(existing):
    found = stacks(existing, CONTEXT)
    assert set(found) == {existing.roles_stack, existing.auth_stack, existing.data_stack, existing.app_stack}


def test_with_an_existing_vpc_the_app_runs_in_its_subnets_without_public_ips(existing):
    resources = stacks(existing, CONTEXT)[existing.app_stack].template["Resources"]
    (service,) = [r for r in resources.values() if r["Type"] == "AWS::ECS::Service"]
    network = service["Properties"]["NetworkConfiguration"]["AwsvpcConfiguration"]
    assert network["Subnets"] == ["subnet-0a1b2c3d", "subnet-4e5f6a7b"]
    assert network["AssignPublicIp"] == "DISABLED"
    assert not any(r["Type"] in ("AWS::EC2::VPC", "AWS::EC2::Subnet", "AWS::EC2::NatGateway") for r in resources.values())


def test_with_an_existing_vpc_the_environments_nat_gateways_are_ignored(tmp_path):
    body = VALID.replace("memory = 512", "memory = 512\nnat_gateways = 2") + EXISTING
    c = config.load(write(tmp_path, body))
    assert c.network_stack not in stacks(c, CONTEXT)


def test_an_environment_with_missing_inputs_names_them(creating):
    with pytest.raises(ValueError, match=r"(?s)harness_arn.*memory_arn"):
        stacks(creating, {"env": "dev"})


def test_an_unknown_environment_lists_the_valid_ones(creating):
    with pytest.raises(ValueError, match=r"'qa'.*valid: dev"):
        stacks(creating, {**CONTEXT, "env": "qa"})
