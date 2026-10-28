import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Template

import config
from stacks.network import import_vpc
from tests.test_config import VALID, write

SUBNETS = '{ eu-west-1a = "subnet-0a1b2c3d", eu-west-1b = "subnet-4e5f6a7b" }'


def with_network(tmp_path, body: str) -> config.Config:
    return config.load(write(tmp_path, VALID + "\n[network]\n" + body))


def test_no_network_section_means_the_template_creates_the_vpc(tmp_path):
    c = config.load(write(tmp_path, VALID))
    assert not c.uses_existing_network and c.existing_network is None


def test_an_empty_network_section_is_an_incomplete_one_not_none(tmp_path):
    with pytest.raises(ValueError, match=r"network\.vpc_id"):
        config.load(write(tmp_path, VALID + "\n[network]\n"))


def test_a_valid_section_describes_the_existing_vpc(tmp_path):
    c = with_network(tmp_path, f'vpc_id = "vpc-0123abcd"\nprivate_subnets = {SUBNETS}\n')
    assert c.uses_existing_network
    assert c.existing_network == config.ExistingNetwork(
        "vpc-0123abcd", {"eu-west-1a": "subnet-0a1b2c3d", "eu-west-1b": "subnet-4e5f6a7b"}
    )


@pytest.mark.parametrize("vpc_id", ["", "not-a-vpc", "vpc-XYZ", "subnet-0123abcd"])
def test_a_malformed_vpc_id_is_named(tmp_path, vpc_id):
    with pytest.raises(ValueError, match=r"network\.vpc_id"):
        with_network(tmp_path, f'vpc_id = "{vpc_id}"\nprivate_subnets = {SUBNETS}\n')


def test_missing_vpc_id_is_named(tmp_path):
    with pytest.raises(ValueError, match=r"network\.vpc_id"):
        with_network(tmp_path, f"private_subnets = {SUBNETS}\n")


def test_no_subnets_is_named(tmp_path):
    with pytest.raises(ValueError, match=r"network\.private_subnets"):
        with_network(tmp_path, 'vpc_id = "vpc-0123abcd"\n')


def test_a_single_zone_is_rejected(tmp_path):
    with pytest.raises(ValueError, match=r"network\.private_subnets.*two"):
        with_network(tmp_path, 'vpc_id = "vpc-0123abcd"\nprivate_subnets = { eu-west-1a = "subnet-0a1b2c3d" }\n')


def test_a_zone_of_another_region_is_rejected(tmp_path):
    bad = '{ eu-west-1a = "subnet-0a1b2c3d", us-east-1b = "subnet-4e5f6a7b" }'
    with pytest.raises(ValueError, match=r"network\.private_subnets.*us-east-1b"):
        with_network(tmp_path, f'vpc_id = "vpc-0123abcd"\nprivate_subnets = {bad}\n')


def test_a_malformed_subnet_id_is_named(tmp_path):
    bad = '{ eu-west-1a = "subnet-0a1b2c3d", eu-west-1b = "nope" }'
    with pytest.raises(ValueError, match=r"network\.private_subnets.*eu-west-1b"):
        with_network(tmp_path, f'vpc_id = "vpc-0123abcd"\nprivate_subnets = {bad}\n')


# --- importing the existing VPC ---

EXISTING = config.ExistingNetwork("vpc-0123abcd", {"eu-west-1a": "subnet-0a1b2c3d", "eu-west-1b": "subnet-4e5f6a7b"})


def importing_stack() -> tuple[cdk.Stack, object]:
    stack = cdk.Stack(cdk.App(), "Importer", env=cdk.Environment(account="111122223333", region="eu-west-1"))
    return stack, import_vpc(stack, EXISTING)


def test_importing_adds_no_resource_to_the_template():
    stack, _ = importing_stack()
    assert Template.from_stack(stack).to_json().get("Resources", {}) == {}


def test_the_vpc_and_its_private_subnets_are_exactly_the_configured_ones():
    _, vpc = importing_stack()
    assert vpc.vpc_id == EXISTING.vpc_id
    assert [s.subnet_id for s in vpc.private_subnets] == list(EXISTING.private_subnets.values())
    assert [s.availability_zone for s in vpc.private_subnets] == list(EXISTING.private_subnets)
    assert vpc.public_subnets == []


def test_the_zones_come_from_the_configuration():
    other = config.ExistingNetwork("vpc-0123abcd", {"eu-west-1b": "subnet-0a1b2c3d", "eu-west-1c": "subnet-4e5f6a7b"})
    stack = cdk.Stack(cdk.App(), "Other", env=cdk.Environment(account="111122223333", region="eu-west-1"))
    assert [s.availability_zone for s in import_vpc(stack, other).private_subnets] == ["eu-west-1b", "eu-west-1c"]
