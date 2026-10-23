"""Prepare an existing VPC to host the app: private subnets with a way out to the Internet.

    uv run --project infra python scripts/prepare_network.py [--vpc-id vpc-...]           # the plan, nothing is created
    uv run --project infra python scripts/prepare_network.py [--vpc-id vpc-...] --create

For an organization that does not let you create a VPC (or an internet gateway), and an account whose
only VPC is the default one, whose subnets are all public. The app's tasks have no public IP, so they
need private subnets that reach out through a NAT gateway. This adds, to the VPC you point it at:

  - two private subnets, in two zones, in /24 ranges that overlap nothing;
  - an Elastic IP and a NAT gateway, in an existing public subnet;
  - a route table of its own (0.0.0.0/0 through the NAT), associated only with the two new subnets.

Everything it creates is tagged Project=<name>, and a second run finds those tags and creates nothing
twice. It never changes or removes anything that already existed: the existing subnets and route
tables stay as they are. It prints the `[network]` block to paste into project.toml and does not edit
the file. `scripts/destroy_app.py` removes what this created, found by the same tags.

Limits: it reads the VPC's primary IPv4 range only (a VPC with extra ranges is still prepared, from the
primary one), and a NAT gateway that is being deleted is not reused: run it again once it is gone.
"""

import argparse
import ipaddress
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "infra"))

import boto3  # noqa: E402

import config  # noqa: E402
from network_check import is_public  # noqa: E402

COST = (
    "A NAT gateway costs about 33 USD a month (0.045 USD an hour) plus 0.045 USD per GB it processes, "
    "for as long as it exists: `scripts/destroy_app.py` removes it."
)
PREFIX = 24  # a private subnet of 251 addresses is plenty for the tasks


class PrepareError(RuntimeError):
    pass


@dataclass
class Plan:
    vpc_id: str
    cidr: str
    private: dict[str, str]  # zone -> the range of its private subnet
    nat_subnet: str  # the existing public subnet the NAT goes in
    existing: list[str] = field(default_factory=list)  # what an earlier run already created


@dataclass
class Result:
    subnets: dict[str, str]  # zone -> subnet id
    nat: str
    address: str
    route_table: str


def _tags(resource: dict) -> dict[str, str]:
    return {t["Key"]: t["Value"] for t in resource.get("Tags", [])}


def _owned(c: config.Config, vpc_id: str, name: str) -> list[dict]:
    """In this VPC, tagged with the project AND named as this script names it: the project tag alone could match
    something another tool tagged, and this script changes a route in the table it finds."""
    return [{"Name": "vpc-id", "Values": [vpc_id]}, {"Name": "tag:Project", "Values": [c.name]}, {"Name": "tag:Name", "Values": [f"{c.name}-{name}"]}]


def _tag_spec(c: config.Config, kind: str, name: str) -> list[dict]:
    return [{"ResourceType": kind, "Tags": [{"Key": "Project", "Value": c.name}, {"Key": "Name", "Value": f"{c.name}-{name}"}]}]


def plan(c: config.Config, session, vpc_id: str) -> Plan:
    """Read-only. Raises PrepareError, naming the cause, when the VPC cannot be prepared."""
    ec2 = session.client("ec2")
    vpcs = ec2.describe_vpcs(VpcIds=[vpc_id])["Vpcs"]
    if not vpcs:
        raise PrepareError(f"The VPC {vpc_id} does not exist.")
    if not ec2.describe_internet_gateways(Filters=[{"Name": "attachment.vpc-id", "Values": [vpc_id]}])["InternetGateways"]:
        raise PrepareError(
            f"The VPC {vpc_id} has no internet gateway attached. A NAT gateway needs one, and so does CloudFront "
            "to reach a private origin; this script cannot create it (your organization may forbid it)."
        )
    tables = ec2.describe_route_tables(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}])["RouteTables"]
    subnets = ec2.describe_subnets(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}])["Subnets"]
    ours = ec2.describe_subnets(Filters=_owned(c, vpc_id, "private-*"))["Subnets"]
    ours_ids = {s["SubnetId"] for s in ours}

    public = [s for s in subnets if s["SubnetId"] not in ours_ids and is_public(tables, s["SubnetId"])]
    zones = sorted({s["AvailabilityZone"] for s in public})
    if len(zones) < 2:
        raise PrepareError(f"The VPC {vpc_id} needs public subnets in at least two zones, and has them in {len(zones)}.")

    existing_by_zone = {s["AvailabilityZone"]: s for s in ours}
    chosen = sorted(existing_by_zone)[:2]  # keep what an earlier run made...
    chosen += [z for z in zones if z not in chosen][: 2 - len(chosen)]  # ...and complete it to two zones
    cidr = vpcs[0]["CidrBlock"]
    ranges = iter(_free_ranges(cidr, [s["CidrBlock"] for s in subnets]))
    private: dict[str, str] = {}
    for zone in chosen:
        if zone in existing_by_zone:
            private[zone] = existing_by_zone[zone]["CidrBlock"]
            continue
        try:
            private[zone] = next(ranges)
        except StopIteration:
            raise PrepareError(f"The VPC {vpc_id} ({cidr}) has no free /{PREFIX} range left for a private subnet.") from None

    by_id = sorted(public, key=lambda s: s["SubnetId"])
    nat_subnet = next((s["SubnetId"] for s in by_id if s["AvailabilityZone"] == chosen[0]), by_id[0]["SubnetId"])
    return Plan(vpc_id, cidr, private, nat_subnet, [f"subnet {s['SubnetId']} ({z})" for z, s in sorted(existing_by_zone.items())])


def _free_ranges(vpc_cidr: str, taken: list[str]):
    used = [ipaddress.ip_network(t) for t in taken]
    for candidate in ipaddress.ip_network(vpc_cidr).subnets(new_prefix=PREFIX):
        if not any(candidate.overlaps(u) for u in used):
            yield str(candidate)


def apply(c: config.Config, session, plan: Plan) -> Result:
    """Create what is missing, in dependency order; find the rest by its tags. Nothing existing is modified."""
    ec2 = session.client("ec2")
    vpc = plan.vpc_id

    prepared = {s["AvailabilityZone"]: s["SubnetId"] for s in ec2.describe_subnets(Filters=_owned(c, vpc, "private-*"))["Subnets"]}
    subnets: dict[str, str] = {}
    for zone, cidr in plan.private.items():
        if zone not in prepared:
            created = ec2.create_subnet(
                VpcId=vpc, CidrBlock=cidr, AvailabilityZone=zone, TagSpecifications=_tag_spec(c, "subnet", f"private-{zone[-1]}")
            )
            prepared[zone] = created["Subnet"]["SubnetId"]
        subnets[zone] = prepared[zone]

    nats = ec2.describe_nat_gateways(Filter=[*_owned(c, vpc, "nat"), {"Name": "state", "Values": ["pending", "available"]}])["NatGateways"]
    if nats:
        nat = nats[0]["NatGatewayId"]
        address = (nats[0].get("NatAddresses") or [{}])[0].get("AllocationId", "")
    else:
        # An address tagged with the project may be held by a NAT elsewhere (another VPC, or the template's own network):
        # only a free one is reused, otherwise a new one is allocated, and only now that a NAT has to be created.
        free = [a for a in ec2.describe_addresses(Filters=[{"Name": "tag:Project", "Values": [c.name]}, {"Name": "tag:Name", "Values": [f"{c.name}-nat"]}])["Addresses"] if not a.get("AssociationId")]
        address = free[0]["AllocationId"] if free else ec2.allocate_address(Domain="vpc", TagSpecifications=_tag_spec(c, "elastic-ip", "nat"))["AllocationId"]
        nat = ec2.create_nat_gateway(SubnetId=plan.nat_subnet, AllocationId=address, TagSpecifications=_tag_spec(c, "natgateway", "nat"))["NatGateway"]["NatGatewayId"]
    ec2.get_waiter("nat_gateway_available").wait(NatGatewayIds=[nat])

    owned_tables = ec2.describe_route_tables(Filters=_owned(c, vpc, "private"))["RouteTables"]
    table = owned_tables[0] if owned_tables else ec2.create_route_table(VpcId=vpc, TagSpecifications=_tag_spec(c, "route-table", "private"))["RouteTable"]
    default = next((r for r in table.get("Routes", []) if r.get("DestinationCidrBlock") == "0.0.0.0/0"), None)
    if default is None:
        ec2.create_route(RouteTableId=table["RouteTableId"], DestinationCidrBlock="0.0.0.0/0", NatGatewayId=nat)
    elif default.get("NatGatewayId") != nat or default.get("State", "active") != "active":
        # Only ever its own table: a NAT that was replaced leaves a blackhole behind, and this repairs it.
        ec2.replace_route(RouteTableId=table["RouteTableId"], DestinationCidrBlock="0.0.0.0/0", NatGatewayId=nat)
    associated = {a.get("SubnetId") for a in table.get("Associations", [])}
    for subnet_id in subnets.values():
        if subnet_id not in associated:
            ec2.associate_route_table(RouteTableId=table["RouteTableId"], SubnetId=subnet_id)
    return Result(subnets, nat, address, table["RouteTableId"])


def snippet(vpc_id: str, subnets: dict[str, str]) -> str:
    listed = ", ".join(f'{zone} = "{subnet}"' for zone, subnet in subnets.items())
    return f'[network]\nvpc_id          = "{vpc_id}"\nprivate_subnets = {{ {listed} }}\n'


def _vpc_id(args, c: config.Config, session) -> str:
    if args.vpc_id:
        return args.vpc_id
    if c.existing_network:
        return c.existing_network.vpc_id
    defaults = [v["VpcId"] for v in session.client("ec2").describe_vpcs()["Vpcs"] if v.get("IsDefault")]
    if len(defaults) == 1:
        return defaults[0]
    raise PrepareError("Say which VPC to prepare with --vpc-id (`scripts/find_network.py` lists them).")


def main(argv: list[str] | None = None, *, cfg: config.Config | None = None, session=None) -> int:
    parser = argparse.ArgumentParser(description="Prepare an existing VPC to host the app.")
    parser.add_argument("--vpc-id", help="the VPC to prepare; by default the one in project.toml's [network], else the default VPC")
    parser.add_argument("--create", action="store_true", help="create it; without this only the plan is shown")
    args = parser.parse_args(argv)

    c = cfg if cfg is not None else config.load()
    session = session or boto3.Session(region_name=c.aws_region)
    try:
        caller = session.client("sts").get_caller_identity()["Account"]
        if caller != c.aws_account:
            raise PrepareError(f"Your credentials are for account {caller}, but project.toml says {c.aws_account}. Switch profile or fix project.toml.")
        the_plan = plan(c, session, _vpc_id(args, c, session))
        _print_plan(the_plan)
        if not args.create:
            print(f"\n{COST}\nNothing was created. Run again with --create to create it.")
            return 0
        result = apply(c, session, the_plan)
    except PrepareError as e:
        print(e, file=sys.stderr)
        return 1
    print(f"\nReady: NAT {result.nat}, route table {result.route_table}. {COST}\n")
    print(f"Add this to project.toml (this script does not edit it):\n\n{snippet(the_plan.vpc_id, result.subnets)}")
    return 0


def _print_plan(p: Plan) -> None:
    print(f"VPC {p.vpc_id} ({p.cidr}). It would have:")
    for zone, cidr in p.private.items():
        print(f"  private subnet {cidr} in {zone}")
    print(f"  a NAT gateway (with an Elastic IP) in the public subnet {p.nat_subnet}")
    print("  a route table of its own, 0.0.0.0/0 through the NAT, associated only with the new subnets")
    if p.existing:
        print("Already there from an earlier run (kept, not created again): " + ", ".join(p.existing))


if __name__ == "__main__":
    sys.exit(main())
