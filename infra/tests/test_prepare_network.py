import fnmatch
import importlib.util
import sys
from pathlib import Path

import pytest

import config
from tests.test_config import VALID, write

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))  # prepare_network imports network_check from its own folder, as it does when run
_spec = importlib.util.spec_from_file_location("prepare_network", SCRIPTS / "prepare_network.py")
prepare_network = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(prepare_network)

REGION = "eu-west-1"  # what VALID in tests/test_config.py configures; the project is "acme-portal"
VPC = "vpc-0123abcd"
IGW_ROUTE = {"DestinationCidrBlock": "0.0.0.0/0", "GatewayId": "igw-0abc", "State": "active"}


def tags(resource: dict) -> dict[str, str]:
    return {t["Key"]: t["Value"] for t in resource.get("Tags", [])}


class FakeEc2:
    """An account's EC2 in memory. It has creation calls and no deletion or modification ones, so any attempt to
    change or remove something that exists is an AttributeError; every write is recorded in `writes`."""

    def __init__(self, *, cidr="172.31.0.0/16", igw=True, public_zones=("a", "b", "c", "d", "e", "f"), default=True):
        self.writes: list[tuple] = []
        self.counter = 0
        self.vpcs = {VPC: {"VpcId": VPC, "CidrBlock": cidr, "IsDefault": default}}
        self.igw = igw
        self.subnets, self.tables, self.nats, self.addresses = [], [], [], []
        self.tables.append({"RouteTableId": "rtb-main", "VpcId": VPC, "Associations": [{"Main": True}], "Routes": [IGW_ROUTE], "Tags": []})
        for i, z in enumerate(public_zones):  # existing public subnets, 172.31.<16*i>.0/20 like a default VPC
            self.subnets.append({"SubnetId": f"subnet-pub{z}", "VpcId": VPC, "AvailabilityZone": f"{REGION}{z}",
                                 "CidrBlock": f"172.31.{16 * i}.0/20", "Tags": []})

    def _id(self, prefix):
        self.counter += 1
        return f"{prefix}-{self.counter:08x}"

    @staticmethod
    def _match(resource, filters):
        for f in filters or []:
            name, values = f["Name"], f["Values"]
            if name.startswith("tag:"):
                value = tags(resource).get(name[4:])
                if value is None or not any(fnmatch.fnmatchcase(value, pattern) for pattern in values):
                    return False
            elif name in ("vpc-id", "attachment.vpc-id"):
                if resource.get("VpcId") not in values:
                    return False
            elif name == "state":
                if resource.get("State") not in values:
                    return False
        return True

    # --- reads
    def describe_vpcs(self, VpcIds=None):
        return {"Vpcs": [v for v in self.vpcs.values() if not VpcIds or v["VpcId"] in VpcIds]}

    def describe_internet_gateways(self, Filters):
        return {"InternetGateways": [{"InternetGatewayId": "igw-0abc"}] if self.igw else []}

    def describe_subnets(self, Filters):
        return {"Subnets": [s for s in self.subnets if self._match(s, Filters)]}

    def describe_route_tables(self, Filters):
        return {"RouteTables": [t for t in self.tables if self._match(t, Filters)]}

    def describe_nat_gateways(self, Filter):
        return {"NatGateways": [n for n in self.nats if self._match(n, Filter)]}

    def describe_addresses(self, Filters):
        return {"Addresses": [a for a in self.addresses if self._match(a, Filters)]}

    def get_waiter(self, name):
        assert name == "nat_gateway_available"
        fake = self

        class Waiter:
            def wait(self, NatGatewayIds):
                for n in fake.nats:
                    if n["NatGatewayId"] in NatGatewayIds:
                        n["State"] = "available"

        return Waiter()

    # --- creations
    def _tagged(self, TagSpecifications):
        return [t for spec in TagSpecifications for t in spec["Tags"]]

    def create_subnet(self, VpcId, CidrBlock, AvailabilityZone, TagSpecifications):
        self.writes.append(("create_subnet", CidrBlock, AvailabilityZone))
        subnet = {"SubnetId": self._id("subnet"), "VpcId": VpcId, "AvailabilityZone": AvailabilityZone, "CidrBlock": CidrBlock,
                  "Tags": self._tagged(TagSpecifications)}
        self.subnets.append(subnet)
        return {"Subnet": subnet}

    def allocate_address(self, Domain, TagSpecifications):
        self.writes.append(("allocate_address",))
        address = {"AllocationId": self._id("eipalloc"), "Tags": self._tagged(TagSpecifications)}
        self.addresses.append(address)
        return {"AllocationId": address["AllocationId"]}

    def create_nat_gateway(self, SubnetId, AllocationId, TagSpecifications):
        self.writes.append(("create_nat_gateway", SubnetId, AllocationId))
        address = next(a for a in self.addresses if a["AllocationId"] == AllocationId)
        assert "AssociationId" not in address, "an address already held by another NAT cannot be used (Resource.AlreadyAssociated)"
        address["AssociationId"] = self._id("eipassoc")
        nat = {"NatGatewayId": self._id("nat"), "VpcId": VPC, "SubnetId": SubnetId, "State": "pending",
               "NatAddresses": [{"AllocationId": AllocationId}], "Tags": self._tagged(TagSpecifications)}
        self.nats.append(nat)
        return {"NatGateway": nat}

    def create_route_table(self, VpcId, TagSpecifications):
        self.writes.append(("create_route_table",))
        table = {"RouteTableId": self._id("rtb"), "VpcId": VpcId, "Associations": [], "Routes": [], "Tags": self._tagged(TagSpecifications)}
        self.tables.append(table)
        return {"RouteTable": table}

    def create_route(self, RouteTableId, DestinationCidrBlock, NatGatewayId):
        self.writes.append(("create_route", RouteTableId, DestinationCidrBlock, NatGatewayId))
        next(t for t in self.tables if t["RouteTableId"] == RouteTableId)["Routes"].append(
            {"DestinationCidrBlock": DestinationCidrBlock, "NatGatewayId": NatGatewayId, "State": "active"}
        )
        return {"Return": True}

    def replace_route(self, RouteTableId, DestinationCidrBlock, NatGatewayId):
        table = next(t for t in self.tables if t["RouteTableId"] == RouteTableId)
        assert tags(table).get("Project"), "only a route table this script created may have a route replaced"
        self.writes.append(("replace_route", RouteTableId, DestinationCidrBlock, NatGatewayId))
        table["Routes"] = [r for r in table["Routes"] if r["DestinationCidrBlock"] != DestinationCidrBlock]
        table["Routes"].append({"DestinationCidrBlock": DestinationCidrBlock, "NatGatewayId": NatGatewayId, "State": "active"})
        return {"Return": True}

    def associate_route_table(self, RouteTableId, SubnetId):
        self.writes.append(("associate_route_table", RouteTableId, SubnetId))
        next(t for t in self.tables if t["RouteTableId"] == RouteTableId)["Associations"].append({"Main": False, "SubnetId": SubnetId})
        return {"AssociationId": self._id("rtbassoc")}


class FakeSession:
    def __init__(self, ec2: FakeEc2, account: str = "111122223333"):
        self.ec2, self.account = ec2, account

    def client(self, name):
        if name == "sts":
            account = self.account
            return type("Sts", (), {"get_caller_identity": lambda self: {"Account": account}})()
        assert name == "ec2"
        return self.ec2


@pytest.fixture
def c(tmp_path) -> config.Config:
    return config.load(write(tmp_path, VALID))


def planned(c, ec2):
    return prepare_network.plan(c, FakeSession(ec2), VPC)


# ------------------------------------------------------------------ the plan: reads only


def test_the_plan_creates_nothing_and_chooses_two_zones_two_free_ranges_and_a_public_subnet_for_the_nat(c):
    ec2 = FakeEc2()
    plan = planned(c, ec2)
    assert ec2.writes == []
    assert list(plan.private) == [f"{REGION}a", f"{REGION}b"]
    assert list(plan.private.values()) == ["172.31.96.0/24", "172.31.97.0/24"]  # the first free /24s after the /20s
    assert plan.nat_subnet == "subnet-puba"
    assert plan.existing == []


def test_the_ranges_never_overlap_an_existing_subnet(c):
    ec2 = FakeEc2()
    ec2.subnets.append({"SubnetId": "subnet-big", "VpcId": VPC, "AvailabilityZone": f"{REGION}a", "CidrBlock": "172.31.96.0/23", "Tags": []})
    plan = planned(c, ec2)
    assert list(plan.private.values()) == ["172.31.98.0/24", "172.31.99.0/24"]


def test_a_vpc_without_an_internet_gateway_stops_the_plan(c):
    with pytest.raises(prepare_network.PrepareError, match="internet gateway"):
        planned(c, FakeEc2(igw=False))


def test_public_subnets_in_fewer_than_two_zones_stop_the_plan(c):
    with pytest.raises(prepare_network.PrepareError, match="two zones"):
        planned(c, FakeEc2(public_zones=("a",)))


def test_a_vpc_with_no_free_range_stops_the_plan(c):
    ec2 = FakeEc2(cidr="172.31.0.0/20", public_zones=("a", "b"))
    ec2.subnets[0]["CidrBlock"] = "172.31.0.0/21"
    ec2.subnets[1]["CidrBlock"] = "172.31.8.0/21"
    with pytest.raises(prepare_network.PrepareError, match="free"):
        planned(c, ec2)


def test_the_plan_states_the_monthly_cost_of_the_nat():
    assert "USD" in prepare_network.COST and "month" in prepare_network.COST


# ------------------------------------------------------------------ creating


def apply(c, ec2):
    return prepare_network.apply(c, FakeSession(ec2), planned(c, ec2))


def test_it_creates_the_subnets_the_address_the_nat_and_a_route_table_of_its_own_in_that_order(c):
    ec2 = FakeEc2()
    apply(c, ec2)
    assert [w[0] for w in ec2.writes] == [
        "create_subnet", "create_subnet", "allocate_address", "create_nat_gateway",
        "create_route_table", "create_route", "associate_route_table", "associate_route_table",
    ]


def test_the_nat_sits_in_an_existing_public_subnet_and_the_route_goes_through_it(c):
    ec2 = FakeEc2()
    apply(c, ec2)
    (nat,) = ec2.nats
    assert nat["SubnetId"] == "subnet-puba" and nat["State"] == "available"
    (table,) = [t for t in ec2.tables if t["RouteTableId"] != "rtb-main"]
    assert table["Routes"] == [{"DestinationCidrBlock": "0.0.0.0/0", "NatGatewayId": nat["NatGatewayId"], "State": "active"}]


def test_the_route_table_is_associated_only_with_the_new_subnets_never_the_existing_ones(c):
    ec2 = FakeEc2()
    apply(c, ec2)
    new = {s["SubnetId"] for s in ec2.subnets if tags(s).get("Project")}
    (table,) = [t for t in ec2.tables if t["RouteTableId"] != "rtb-main"]
    assert {a["SubnetId"] for a in table["Associations"]} == new and len(new) == 2
    assert ec2.tables[0]["Associations"] == [{"Main": True}]  # the main table is untouched


def test_everything_it_creates_is_tagged_with_the_project_and_a_name(c):
    ec2 = FakeEc2()
    apply(c, ec2)
    created = [r for r in [*ec2.subnets, *ec2.addresses, *ec2.nats, *ec2.tables] if tags(r).get("Project")]
    assert len(created) == 2 + 1 + 1 + 1
    assert all(tags(r)["Project"] == c.name and tags(r)["Name"].startswith(f"{c.name}-") for r in created)
    assert sorted(tags(s)["Name"] for s in ec2.subnets if tags(s).get("Project")) == [f"{c.name}-private-a", f"{c.name}-private-b"]


def test_nothing_that_existed_is_modified_or_removed(c):
    ec2 = FakeEc2()
    before = [dict(s) for s in ec2.subnets]
    apply(c, ec2)  # a call to anything that changes or deletes would raise: FakeEc2 has no such method
    assert ec2.subnets[: len(before)] == before


def test_running_it_again_creates_nothing(c):
    ec2 = FakeEc2()
    first = apply(c, ec2)
    ec2.writes.clear()
    assert apply(c, ec2) == first
    assert ec2.writes == []


def test_a_run_that_stopped_halfway_resumes_where_it_left_off(c):
    ec2 = FakeEc2()
    apply(c, ec2)
    ec2.tables[:] = [t for t in ec2.tables if t["RouteTableId"] == "rtb-main"]  # the route table is lost
    ec2.writes.clear()
    apply(c, ec2)
    assert [w[0] for w in ec2.writes] == ["create_route_table", "create_route", "associate_route_table", "associate_route_table"]


def test_the_block_it_prints_names_the_new_subnets_and_the_configuration_accepts_it(c, tmp_path):
    ec2 = FakeEc2()
    result = apply(c, ec2)
    block = prepare_network.network_snippet(VPC, result.subnets)
    loaded = config.load(write(tmp_path, VALID + "\n" + block))
    assert loaded.existing_network.private_subnets == result.subnets
    assert set(result.subnets) == {f"{REGION}a", f"{REGION}b"}


# ------------------------------------------------------------------ the command


def run(c, ec2, *args, account="111122223333"):
    session = FakeSession(ec2, account)
    return prepare_network.main(["--vpc-id", VPC, *args], cfg=c, session=session)


def test_without_confirmation_it_shows_the_plan_and_the_cost_and_creates_nothing(c, capsys):
    ec2 = FakeEc2()
    assert run(c, ec2) == 0
    out = capsys.readouterr().out
    assert ec2.writes == [] and "172.31.96.0/24" in out and "USD" in out and "--create" in out


def test_with_confirmation_it_creates_and_prints_the_block_without_touching_project_toml(c, capsys, tmp_path):
    ec2 = FakeEc2()
    toml = write(tmp_path, VALID)
    before = toml.read_bytes()
    assert run(c, ec2, "--create") == 0
    out = capsys.readouterr().out
    assert ec2.writes and "[network]" in out and "private_subnets" in out
    assert toml.read_bytes() == before


def test_credentials_for_another_account_stop_it_before_anything_is_read_or_created(c, capsys):
    ec2 = FakeEc2()
    assert run(c, ec2, "--create", account="999999999999") == 1
    assert ec2.writes == [] and "999999999999" in capsys.readouterr().err


def test_a_vpc_that_cannot_be_prepared_stops_with_the_reason_and_creates_nothing(c, capsys):
    ec2 = FakeEc2(igw=False)
    assert run(c, ec2, "--create") == 1
    assert ec2.writes == [] and "internet gateway" in capsys.readouterr().err


# ------------------------------------------------------------------ what a review of the first version found


def tagged_address(ec2, *, associated=False):
    address = {"AllocationId": f"eipalloc-{len(ec2.addresses):04x}", "Tags": [{"Key": "Project", "Value": "acme-portal"}, {"Key": "Name", "Value": "acme-portal-nat"}]}
    if associated:
        address["AssociationId"] = "eipassoc-other"
    ec2.addresses.append(address)
    return address["AllocationId"]


def test_an_address_the_project_already_uses_for_another_nat_is_never_taken(c):
    ec2 = FakeEc2()
    taken = tagged_address(ec2, associated=True)  # tagged with the project, but held by a NAT elsewhere
    result = apply(c, ec2)
    assert [w for w in ec2.writes if w[0] == "allocate_address"]  # a new one was allocated
    assert result.address != taken


def test_a_free_address_of_the_project_is_reused_instead_of_allocating_another(c):
    ec2 = FakeEc2()
    free = tagged_address(ec2)
    result = apply(c, ec2)
    assert result.address == free and not [w for w in ec2.writes if w[0] == "allocate_address"]


def test_no_address_is_allocated_when_the_nat_already_exists(c):
    ec2 = FakeEc2()
    apply(c, ec2)
    ec2.addresses[:] = []  # the tag on the address is lost, but the NAT still holds it
    ec2.writes.clear()
    apply(c, ec2)
    assert not [w for w in ec2.writes if w[0] == "allocate_address"]


def test_a_single_subnet_from_an_earlier_run_is_kept_and_completed_with_a_second_zone(c):
    ec2 = FakeEc2()
    ec2.subnets.append({"SubnetId": "subnet-earlier", "VpcId": VPC, "AvailabilityZone": f"{REGION}e", "CidrBlock": "172.31.96.0/24",
                        "Tags": [{"Key": "Project", "Value": c.name}, {"Key": "Name", "Value": f"{c.name}-private-e"}]})
    result = apply(c, ec2)
    assert result.subnets[f"{REGION}e"] == "subnet-earlier" and len(result.subnets) == 2
    assert [w for w in ec2.writes if w[0] == "create_subnet"].__len__() == 1  # only the missing one


def test_a_prepared_subnet_in_a_zone_with_no_public_subnet_does_not_crash_the_plan(c):
    ec2 = FakeEc2(public_zones=("a", "b"))
    for z in ("x", "y"):
        ec2.subnets.append({"SubnetId": f"subnet-{z}", "VpcId": VPC, "AvailabilityZone": f"{REGION}{z}", "CidrBlock": f"172.31.{200 + ord(z) - 120}.0/24",
                            "Tags": [{"Key": "Project", "Value": c.name}, {"Key": "Name", "Value": f"{c.name}-private-{z}"}]})
    assert planned(c, ec2).nat_subnet in {"subnet-puba", "subnet-pubb"}


@pytest.mark.parametrize("state", ["blackhole", "other-nat"])
def test_a_default_route_of_its_own_table_that_no_longer_leads_through_its_nat_is_repaired(c, state):
    ec2 = FakeEc2()
    result = apply(c, ec2)
    table = next(t for t in ec2.tables if t["RouteTableId"] == result.route_table)
    table["Routes"] = [{"DestinationCidrBlock": "0.0.0.0/0", "NatGatewayId": "nat-gone" if state == "blackhole" else "nat-other",
                        "State": "blackhole" if state == "blackhole" else "active"}]
    ec2.writes.clear()
    apply(c, ec2)
    assert [w[0] for w in ec2.writes] == ["replace_route"]
    assert table["Routes"] == [{"DestinationCidrBlock": "0.0.0.0/0", "NatGatewayId": result.nat, "State": "active"}]


def test_a_route_table_that_only_shares_the_project_tag_is_not_taken_for_its_own(c):
    """Another tool may tag its tables with Project too. This script changes a route in the table it finds, so it
    only trusts one tagged with the project and also named the way this script names it."""
    ec2 = FakeEc2()
    ec2.tables.append({"RouteTableId": "rtb-someone-elses", "VpcId": VPC, "Associations": [], "Tags": tags_of(c.name, "someone-elses-table"),
                       "Routes": [{"DestinationCidrBlock": "0.0.0.0/0", "NatGatewayId": "nat-theirs", "State": "active"}]})
    result = apply(c, ec2)
    assert result.route_table != "rtb-someone-elses"
    theirs = next(t for t in ec2.tables if t["RouteTableId"] == "rtb-someone-elses")
    assert theirs["Routes"] == [{"DestinationCidrBlock": "0.0.0.0/0", "NatGatewayId": "nat-theirs", "State": "active"}] and theirs["Associations"] == []


def test_a_subnet_or_nat_that_only_shares_the_project_tag_is_not_taken_for_its_own(c):
    ec2 = FakeEc2()
    ec2.subnets.append({"SubnetId": "subnet-foreign", "VpcId": VPC, "AvailabilityZone": f"{REGION}a", "CidrBlock": "172.31.200.0/24", "Tags": tags_of(c.name, "other-thing")})
    ec2.nats.append({"NatGatewayId": "nat-foreign", "VpcId": VPC, "SubnetId": "subnet-puba", "State": "available", "Tags": tags_of(c.name, "other-nat")})
    result = apply(c, ec2)
    assert "subnet-foreign" not in result.subnets.values() and result.nat != "nat-foreign"


def tags_of(project, name):
    return [{"Key": "Project", "Value": project}, {"Key": "Name", "Value": name}]
