import importlib.util
import sys
from pathlib import Path

import pytest

import config
from tests.test_config import VALID, write

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))  # find_network imports network_check from its own folder, as it does when run


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


network_check = load("network_check")
find_network = load("find_network")

REGION = "eu-west-1"  # the region VALID in tests/test_config.py configures


def nat():
    return {"DestinationCidrBlock": "0.0.0.0/0", "NatGatewayId": "nat-0abc", "State": "active"}


def igw():
    return {"DestinationCidrBlock": "0.0.0.0/0", "GatewayId": "igw-0abc", "State": "active"}


def vpc(vpc_id, *, name="", default=False, igw_attached=True, subnets):
    """subnets: {subnet_id: (zone, cidr, route)}; every subnet gets its own route table."""
    return {
        "id": vpc_id, "name": name, "default": default, "igw": igw_attached,
        "subnets": {s: (z, cidr) for s, (z, cidr, _) in subnets.items()},
        "tables": [
            {"RouteTableId": f"rtb-{s}", "Associations": [{"Main": False, "SubnetId": s}], "Routes": [route]}
            for s, (_, _, route) in subnets.items()
        ],
    }


class ReadOnlyEc2:
    """Only the read calls exist: any attempt to create or change something is an AttributeError."""

    def __init__(self, vpcs):
        self.vpcs = {v["id"]: v for v in vpcs}

    def describe_vpcs(self, **_):
        return {"Vpcs": [
            {"VpcId": v["id"], "IsDefault": v["default"], "Tags": [{"Key": "Name", "Value": v["name"]}] if v["name"] else []}
            for v in self.vpcs.values()
        ]}

    def describe_subnets(self, Filters):
        name, values = Filters[0]["Name"], Filters[0]["Values"]
        return {"Subnets": [
            {"SubnetId": s, "VpcId": v["id"], "AvailabilityZone": z, "CidrBlock": cidr}
            for v in self.vpcs.values() for s, (z, cidr) in v["subnets"].items()
            if (v["id"] in values if name == "vpc-id" else s in values)
        ]}

    def describe_internet_gateways(self, Filters):
        v = self.vpcs[Filters[0]["Values"][0]]
        return {"InternetGateways": [{"InternetGatewayId": "igw-0abc"}] if v["igw"] else []}

    def describe_route_tables(self, Filters):
        return {"RouteTables": self.vpcs[Filters[0]["Values"][0]]["tables"]}


class FakeSession:
    def __init__(self, vpcs):
        self.ec2 = ReadOnlyEc2(vpcs)

    def client(self, name):
        assert name == "ec2"
        return self.ec2


@pytest.fixture
def c(tmp_path) -> config.Config:
    return config.load(write(tmp_path, VALID))


DEFAULT_VPC = vpc("vpc-0defa001", default=True, subnets={
    "subnet-aaa1": (f"{REGION}a", "172.31.0.0/20", igw()),
    "subnet-bbb1": (f"{REGION}b", "172.31.16.0/20", igw()),
})
GOOD_VPC = vpc("vpc-0900d001", name="shared", subnets={
    "subnet-0a1b2c3d": (f"{REGION}a", "10.0.1.0/24", nat()),
    "subnet-4e5f6a7b": (f"{REGION}b", "10.0.2.0/24", nat()),
    "subnet-1234abcd": (f"{REGION}b", "10.0.3.0/24", igw()),
})


def test_it_lists_every_vpc_with_its_subnets_zones_and_how_each_one_reaches_out(c):
    reports = find_network.discover(c, FakeSession([DEFAULT_VPC, GOOD_VPC]))
    assert [r.vpc_id for r in reports] == ["vpc-0defa001", "vpc-0900d001"]
    default, good = reports
    assert default.is_default and default.has_igw and not good.is_default
    assert [(s.subnet_id, s.zone, s.cidr) for s in good.subnets][0] == ("subnet-0a1b2c3d", f"{REGION}a", "10.0.1.0/24")
    assert good.name == "shared"


def test_a_subnet_is_usable_when_it_reaches_out_without_an_internet_gateway_and_says_why_not_otherwise(c):
    good = next(r for r in find_network.discover(c, FakeSession([GOOD_VPC])))
    by_id = {s.subnet_id: s for s in good.subnets}
    assert by_id["subnet-0a1b2c3d"].usable and by_id["subnet-0a1b2c3d"].reason == ""
    assert not by_id["subnet-1234abcd"].usable and "internet gateway" in by_id["subnet-1234abcd"].reason


def test_the_default_vpc_has_no_usable_subnet_and_no_block_is_offered(c):
    (default,) = find_network.discover(c, FakeSession([DEFAULT_VPC]))
    assert not any(s.usable for s in default.subnets)
    assert find_network.snippet(default) is None


def test_a_vpc_with_two_usable_zones_gets_a_block_that_the_configuration_accepts(c, tmp_path):
    (good,) = find_network.discover(c, FakeSession([GOOD_VPC]))
    block = find_network.snippet(good)
    assert block.startswith("[network]") and "vpc-0900d001" in block
    accepted = config.load(write(tmp_path, VALID + "\n" + block))
    assert accepted.existing_network.private_subnets == {f"{REGION}a": "subnet-0a1b2c3d", f"{REGION}b": "subnet-4e5f6a7b"}


def test_one_usable_zone_is_not_enough_for_a_block(c):
    one = vpc("vpc-0e0e0e01", subnets={
        "subnet-0a1b2c3d": (f"{REGION}a", "10.0.1.0/24", nat()),
        "subnet-4e5f6a7b": (f"{REGION}a", "10.0.2.0/24", nat()),  # same zone twice
    })
    (report,) = find_network.discover(c, FakeSession([one]))
    assert find_network.snippet(report) is None


def test_a_vpc_without_an_internet_gateway_gets_no_block_even_with_usable_subnets(c):
    nogw = vpc("vpc-0a0b0c01", igw_attached=False, subnets={
        "subnet-0a1b2c3d": (f"{REGION}a", "10.0.1.0/24", nat()),
        "subnet-4e5f6a7b": (f"{REGION}b", "10.0.2.0/24", nat()),
    })
    (report,) = find_network.discover(c, FakeSession([nogw]))
    assert not report.has_igw and find_network.snippet(report) is None


def test_the_report_prints_the_block_for_the_vpc_that_qualifies(c):
    text = find_network.report(c, find_network.discover(c, FakeSession([DEFAULT_VPC, GOOD_VPC])))
    assert "vpc-0900d001" in text and "[network]" in text and "private_subnets" in text


def test_when_none_qualifies_it_says_the_template_can_create_the_network_and_what_the_closest_one_lacks(c):
    text = find_network.report(c, find_network.discover(c, FakeSession([DEFAULT_VPC])))
    assert "[network]" not in text.replace("`[network]`", "")
    assert "prepare_network.py" in text and "vpc-0defa001" in text
    assert "private" in text and "NAT" in text
    assert "creates" in text or "create" in text


def test_it_reads_and_never_writes(c):
    find_network.report(c, find_network.discover(c, FakeSession([DEFAULT_VPC, GOOD_VPC])))  # ReadOnlyEc2 has no write methods


def test_the_check_that_verifies_a_vpc_and_the_one_that_discovers_it_never_disagree(c, tmp_path):
    """The block it offers must pass the deployment's own verification (Requirement 12.6)."""
    (good,) = find_network.discover(c, FakeSession([GOOD_VPC]))
    accepted = config.load(write(tmp_path, VALID + "\n" + find_network.snippet(good)))
    network_check.check(accepted, FakeSession([GOOD_VPC]))
