import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Template

import config
from definitions.network import network_specs
from specs.network import NetworkSpec
from stacks.network import NetworkStack

C = config.load()
ENV = cdk.Environment(account=C.aws_account, region=C.aws_region)


def synth(nat_gateways: int = 1, specs: list[NetworkSpec] | None = None) -> Template:
    stack = NetworkStack(cdk.App(), C.network_stack, specs=specs or network_specs(), nat_gateways=nat_gateways, env=ENV)
    return Template.from_stack(stack)


def subnets(template: Template) -> list[dict]:
    return [r["Properties"] for r in template.find_resources("AWS::EC2::Subnet").values()]


def is_public(subnet: dict) -> bool:
    return any(t["Key"] == "aws-cdk:subnet-type" and t["Value"] == "Public" for t in subnet["Tags"])


def test_two_private_and_two_public_subnets():
    found = subnets(synth())
    assert len([s for s in found if is_public(s)]) == 2
    assert len([s for s in found if not is_public(s)]) == 2


def test_nothing_launched_in_a_public_subnet_gets_a_public_ip():
    assert all(s["MapPublicIpOnLaunch"] is False for s in subnets(synth()) if is_public(s))


@pytest.mark.parametrize("nat", [1, 2])
def test_one_nat_gateway_per_requested_unit(nat):
    synth(nat).resource_count_is("AWS::EC2::NatGateway", nat)


def test_s3_and_dynamodb_traffic_stays_inside_aws():
    template = synth()
    endpoints = template.find_resources("AWS::EC2::VPCEndpoint")
    assert len(endpoints) == 2
    assert all(e["Properties"]["VpcEndpointType"] == "Gateway" for e in endpoints.values())
    services = "".join(str(e["Properties"]["ServiceName"]) for e in endpoints.values())
    assert ".s3" in services and ".dynamodb" in services


def test_the_vpc_is_exposed_to_the_app_stack():
    stack = NetworkStack(cdk.App(), C.network_stack, specs=network_specs(), nat_gateways=1, env=ENV)
    assert set(stack.vpcs) == {spec.id for spec in network_specs()}


def test_the_network_spec_carries_the_cidr_and_zones():
    synth_template = synth()
    synth_template.has_resource_properties("AWS::EC2::VPC", {"CidrBlock": network_specs()[0].vpc_cidr})


def test_a_second_spec_adds_a_second_vpc_without_touching_the_stack():
    other = NetworkSpec(id="Other", vpc_cidr="10.1.0.0/16", max_azs=2, description="Another network.")
    synth(specs=[*network_specs(), other]).resource_count_is("AWS::EC2::VPC", 2)


def test_private_subnets_reach_the_internet_through_a_nat_gateway():
    routes = synth().find_resources("AWS::EC2::Route", {"Properties": {"DestinationCidrBlock": "0.0.0.0/0"}})
    assert sum("NatGatewayId" in r["Properties"] for r in routes.values()) == 2
