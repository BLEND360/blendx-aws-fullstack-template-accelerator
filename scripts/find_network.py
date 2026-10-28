"""Find which VPC in the account can host the app, and print the `[network]` block for it.

    uv run --project infra python scripts/find_network.py

Read-only. For every VPC in the account and the region of project.toml it shows the subnets, their
zone, and whether each one gives the tasks a way out to the Internet (a route that is not an internet
gateway: the tasks have no public IP). A VPC with an internet gateway and usable subnets in two zones
gets a `[network]` block ready to paste into project.toml; this script never writes the file. If none
qualifies it says so and what the closest one lacks. It applies the same check as the deployment's own
verification (`network_check.egress_problem`), so what it offers the deployment accepts.
"""

import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "infra"))

import boto3  # noqa: E402

import config  # noqa: E402
from awsutil import check_account, cli, load_config, network_snippet  # noqa: E402
from network_check import egress_problem  # noqa: E402


@dataclass
class SubnetReport:
    subnet_id: str
    zone: str
    cidr: str
    reason: str  # why it cannot host the tasks; empty when it can

    @property
    def usable(self) -> bool:
        return not self.reason


@dataclass
class VpcReport:
    vpc_id: str
    name: str
    is_default: bool
    has_igw: bool
    subnets: list[SubnetReport] = field(default_factory=list)

    def usable_zones(self) -> dict[str, str]:
        """One usable subnet per zone."""
        zones: dict[str, str] = {}
        for subnet in sorted(self.subnets, key=lambda s: (s.zone, s.subnet_id)):
            if subnet.usable:
                zones.setdefault(subnet.zone, subnet.subnet_id)
        return zones


def discover(session) -> list[VpcReport]:
    ec2 = session.client("ec2")
    reports = []
    for vpc in ec2.describe_vpcs()["Vpcs"]:
        vpc_id = vpc["VpcId"]
        name = next((t["Value"] for t in vpc.get("Tags", []) if t["Key"] == "Name"), "")
        gateways = ec2.describe_internet_gateways(Filters=[{"Name": "attachment.vpc-id", "Values": [vpc_id]}])["InternetGateways"]
        tables = ec2.describe_route_tables(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}])["RouteTables"]
        subnets = ec2.describe_subnets(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}])["Subnets"]
        report = VpcReport(vpc_id, name, bool(vpc.get("IsDefault")), bool(gateways))
        for s in sorted(subnets, key=lambda s: (s["AvailabilityZone"], s["SubnetId"])):
            problem = egress_problem(tables, s["SubnetId"])
            report.subnets.append(SubnetReport(s["SubnetId"], s["AvailabilityZone"], s.get("CidrBlock", "(IPv6 only)"), _short(problem)))
        reports.append(report)
    return reports


def _short(problem: str | None) -> str:
    """The reason in a table cell: the check's sentence without the subnet id it repeats."""
    if problem is None:
        return ""
    if "internet gateway" in problem:
        return "public: its default route goes through an internet gateway"
    return "no route out to the Internet (needs a NAT)"


def snippet(report: VpcReport) -> str | None:
    """The `[network]` block, or None unless the VPC has an internet gateway and usable subnets in two zones."""
    zones = report.usable_zones()
    if not report.has_igw or len(zones) < 2:
        return None
    return network_snippet(report.vpc_id, dict(list(zones.items())[:2]))


def _lacks(report: VpcReport) -> list[str]:
    lacks = []
    if not report.has_igw:
        lacks.append("an internet gateway (CloudFront needs one to reach a private origin)")
    zones = report.usable_zones()
    if len(zones) < 2:
        lacks.append(
            f"private subnets with a NAT route in two zones (it has {len(zones)} usable zone{'s' if len(zones) != 1 else ''}; "
            "`prepare_network.py` can add them)"
        )
    return lacks


def report(c: config.Config, reports: list[VpcReport]) -> str:
    lines = [f"VPCs in account {c.aws_account}, {c.aws_region}:", ""]
    for r in reports:
        label = f"{r.vpc_id}" + (f" ({r.name})" if r.name else "") + (" [default]" if r.is_default else "")
        lines.append(f"{label}  internet gateway: {'yes' if r.has_igw else 'NO'}")
        for s in r.subnets:
            lines.append(f"  {s.subnet_id}  {s.zone:<12} {s.cidr:<16} {'usable' if s.usable else s.reason}")
        lines.append("")

    qualifying = [(r, snippet(r)) for r in reports if snippet(r)]
    if qualifying:
        best, block = qualifying[0]
        lines += [f"{best.vpc_id} can host the app. Add this to project.toml:", "", block]
    else:
        closest = max(reports, key=lambda r: (r.has_igw, len(r.usable_zones())), default=None)
        lines += [
            "No VPC can host the app as it is.",
            "- If your organization lets you create a VPC with an internet gateway, leave `[network]` out of "
            "project.toml and the template creates the network itself.",
            "- Otherwise run `uv run --project infra python scripts/prepare_network.py` to add private subnets "
            "and a NAT to an existing VPC.",
        ]
        if closest:
            lines.append(f"Closest: {closest.vpc_id} lacks " + " and ".join(_lacks(closest)) + ".")
    return "\n".join(lines)


@cli
def main() -> int:
    c = load_config()
    session = boto3.Session(region_name=c.aws_region)
    check_account(c, session)
    print(report(c, discover(session)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
