import importlib.util
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

import config
from tests.test_config import VALID, write

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
_spec = importlib.util.spec_from_file_location("network_check", SCRIPTS / "network_check.py")
network_check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(network_check)

VPC = "vpc-0123abcd"
A, B = "subnet-0a1b2c3d", "subnet-4e5f6a7b"
EXISTING = f'\n[network]\nvpc_id = "{VPC}"\nprivate_subnets = {{ eu-west-1a = "{A}", eu-west-1b = "{B}" }}\n'


def nat_route(target="nat-0abc"):
    return {"DestinationCidrBlock": "0.0.0.0/0", "NatGatewayId": target, "State": "active"}


def igw_route():
    return {"DestinationCidrBlock": "0.0.0.0/0", "GatewayId": "igw-0abc", "State": "active"}


def healthy() -> dict:
    """A VPC the check accepts: an internet gateway, and two private subnets that reach out through a NAT."""
    return {
        "vpcs": [VPC],
        "subnets": {A: (VPC, "eu-west-1a"), B: (VPC, "eu-west-1b")},
        "igws": ["igw-0abc"],
        "route_tables": [
            {"RouteTableId": "rtb-main", "Associations": [{"Main": True}], "Routes": [igw_route()]},
            {"RouteTableId": "rtb-a", "Associations": [{"Main": False, "SubnetId": A}], "Routes": [nat_route()]},
            {"RouteTableId": "rtb-b", "Associations": [{"Main": False, "SubnetId": B}], "Routes": [nat_route()]},
        ],
    }


class FakeEc2:
    def __init__(self, world: dict):
        self.world = world

    def describe_vpcs(self, VpcIds):
        if VPC not in self.world["vpcs"]:
            raise ClientError({"Error": {"Code": "InvalidVpcID.NotFound", "Message": "gone"}}, "DescribeVpcs")
        return {"Vpcs": [{"VpcId": VPC}]}

    def describe_subnets(self, Filters):
        wanted = Filters[0]["Values"]
        return {
            "Subnets": [
                {"SubnetId": s, "VpcId": v, "AvailabilityZone": z} for s, (v, z) in self.world["subnets"].items() if s in wanted
            ]
        }

    def describe_internet_gateways(self, Filters):
        return {"InternetGateways": [{"InternetGatewayId": i} for i in self.world["igws"]]}

    def describe_route_tables(self, Filters):
        return {"RouteTables": self.world["route_tables"]}


class FakeSession:
    def __init__(self, world):
        self.ec2 = FakeEc2(world)

    def client(self, name):
        assert name == "ec2"
        return self.ec2


@pytest.fixture
def c(tmp_path) -> config.Config:
    return config.load(write(tmp_path, VALID + EXISTING))


def problems(c, world) -> str:
    with pytest.raises(network_check.NetworkCheckError) as error:
        network_check.check(c, FakeSession(world))
    return str(error.value)


def test_a_vpc_that_meets_every_condition_passes(c):
    network_check.check(c, FakeSession(healthy()))


def test_a_vpc_that_does_not_exist_is_named(c):
    world = {**healthy(), "vpcs": []}
    assert VPC in problems(c, world) and "does not exist" in problems(c, world)


def test_a_vpc_without_an_internet_gateway_cannot_be_a_cloudfront_origin(c):
    message = problems(c, {**healthy(), "igws": []})
    assert VPC in message and "internet gateway" in message and "CloudFront" in message


def test_a_subnet_that_does_not_exist_is_named(c):
    world = healthy()
    del world["subnets"][B]
    assert B in problems(c, world) and "does not exist" in problems(c, world)


def test_a_subnet_of_another_vpc_is_named_with_both_vpcs(c):
    world = healthy()
    world["subnets"][A] = ("vpc-other", "eu-west-1a")
    message = problems(c, world)
    assert A in message and "vpc-other" in message and VPC in message


def test_a_subnet_in_another_zone_is_named_with_both_zones(c):
    world = healthy()
    world["subnets"][A] = (VPC, "eu-west-1c")
    message = problems(c, world)
    assert A in message and "eu-west-1c" in message and "eu-west-1a" in message


def test_a_subnet_that_reaches_the_internet_through_an_internet_gateway_is_refused(c):
    world = healthy()
    world["route_tables"][1]["Routes"] = [igw_route()]
    message = problems(c, world)
    assert A in message and "internet gateway" in message and "NAT" in message


def test_a_subnet_with_no_route_out_is_refused(c):
    world = healthy()
    world["route_tables"][2]["Routes"] = [{"DestinationCidrBlock": "10.0.0.0/16", "GatewayId": "local", "State": "active"}]
    message = problems(c, world)
    assert B in message and "no route" in message


def test_a_blackholed_route_does_not_count_as_a_way_out(c):
    world = healthy()
    world["route_tables"][1]["Routes"] = [{**nat_route(), "State": "blackhole"}]
    assert A in problems(c, world)


def test_a_subnet_without_its_own_route_table_uses_the_main_one(c):
    world = healthy()
    world["route_tables"] = [{"RouteTableId": "rtb-main", "Associations": [{"Main": True}], "Routes": [nat_route()]}]
    network_check.check(c, FakeSession(world))
    world["route_tables"][0]["Routes"] = [igw_route()]
    assert A in problems(c, world) and B in problems(c, world)


@pytest.mark.parametrize("target", ["TransitGatewayId", "NetworkInterfaceId"])
def test_any_other_way_out_than_an_internet_gateway_is_accepted(c, target):
    world = healthy()
    world["route_tables"][1]["Routes"] = [{"DestinationCidrBlock": "0.0.0.0/0", target: "x-0abc", "State": "active"}]
    network_check.check(c, FakeSession(world))


def test_every_problem_is_reported_at_once(c):
    world = healthy()
    world["igws"] = []
    world["route_tables"][1]["Routes"] = []
    message = problems(c, world)
    assert "internet gateway" in message and A in message


def test_it_does_nothing_when_the_template_creates_the_network(tmp_path):
    c = config.load(write(tmp_path, VALID))
    network_check.check(c, FakeSession({}))  # no VPC configured: nothing to verify, and nothing is called
