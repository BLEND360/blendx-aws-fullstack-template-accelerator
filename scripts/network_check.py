"""Check that an existing VPC can host the app, before anything is created.

The template deploys into a VPC it does not own when project.toml has a [network] section, so it
cannot fix what is wrong with it: it verifies and, if something is missing, says exactly what. The
conditions are the ones the app depends on:

- the VPC and every listed subnet exist, the subnets belong to the VPC and sit in the listed zone;
- the VPC has an internet gateway attached (CloudFront requires one to reach a private origin);
- every subnet has a default route out that is not an internet gateway: the tasks have no public
  IP, so only a NAT (or similar) gives them a way to reach Cognito's keys, Bedrock and ECR.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "infra"))

from botocore.exceptions import ClientError  # noqa: E402

import config  # noqa: E402
from awsutil import DeployError  # noqa: E402

DEFAULT_ROUTE = "0.0.0.0/0"


class NetworkCheckError(DeployError):
    pass


def check(c: config.Config, session) -> None:
    """Nothing to verify when the template creates the network. Raises NetworkCheckError listing every problem."""
    network = c.existing_network
    if network is None:
        return
    ec2 = session.client("ec2")
    problems: list[str] = []

    try:
        ec2.describe_vpcs(VpcIds=[network.vpc_id])
    except ClientError as e:
        if e.response["Error"]["Code"] == "InvalidVpcID.NotFound":
            raise NetworkCheckError(f"The VPC {network.vpc_id} does not exist in {c.aws_region} (account {c.aws_account}).") from e
        raise

    found = {
        s["SubnetId"]: s
        for s in ec2.describe_subnets(Filters=[{"Name": "subnet-id", "Values": list(network.private_subnets.values())}])["Subnets"]
    }
    usable: list[str] = []
    for zone, subnet_id in network.private_subnets.items():
        subnet = found.get(subnet_id)
        if subnet is None:
            problems.append(f"Subnet {subnet_id} ({zone}) does not exist.")
        elif subnet["VpcId"] != network.vpc_id:
            problems.append(f"Subnet {subnet_id} belongs to {subnet['VpcId']}, not to {network.vpc_id}.")
        elif subnet["AvailabilityZone"] != zone:
            problems.append(f"Subnet {subnet_id} is in {subnet['AvailabilityZone']}, but project.toml lists it under {zone}.")
        else:
            usable.append(subnet_id)

    gateways = ec2.describe_internet_gateways(Filters=[{"Name": "attachment.vpc-id", "Values": [network.vpc_id]}])
    if not gateways["InternetGateways"]:
        problems.append(
            f"The VPC {network.vpc_id} has no internet gateway attached. CloudFront needs one to use a private origin "
            "(the app itself stays private)."
        )

    tables = ec2.describe_route_tables(Filters=[{"Name": "vpc-id", "Values": [network.vpc_id]}])["RouteTables"]
    problems += _egress_problems(tables, usable)

    if problems:
        raise NetworkCheckError(f"The VPC {network.vpc_id} cannot host the app:\n  " + "\n  ".join(problems))


def _live_default_routes(tables: list[dict], subnet_id: str) -> tuple[list[dict], list[dict]]:
    """(all default routes, the active ones) of the table the subnet uses: its own, or else the main one."""
    explicit = {a["SubnetId"]: t for t in tables for a in t.get("Associations", []) if a.get("SubnetId")}
    main = next((t for t in tables for a in t.get("Associations", []) if a.get("Main")), None)
    table = explicit.get(subnet_id, main)
    routes = [r for r in (table or {}).get("Routes", []) if r.get("DestinationCidrBlock") == DEFAULT_ROUTE]
    return routes, [r for r in routes if r.get("State", "active") == "active"]


def is_public(tables: list[dict], subnet_id: str) -> bool:
    """Whether the subnet's default route goes through an internet gateway."""
    _, live = _live_default_routes(tables, subnet_id)
    return any(str(r.get("GatewayId", "")).startswith("igw-") for r in live)


def egress_problem(tables: list[dict], subnet_id: str) -> str | None:
    """Why this subnet cannot give the tasks a way out to the Internet, or None when it can.

    The single check behind both the deploy-time verification and `find_network.py`, so what the
    one offers the other always accepts.
    """
    routes, live = _live_default_routes(tables, subnet_id)
    if not live:
        why = "its default route is a blackhole" if routes else f"it has no route to the Internet ({DEFAULT_ROUTE})"
        return f"Subnet {subnet_id}: {why}. The tasks need a NAT route to reach Cognito, Bedrock and ECR."
    if is_public(tables, subnet_id):
        return (
            f"Subnet {subnet_id} routes {DEFAULT_ROUTE} through an internet gateway. The tasks have no public IP, "
            "so use a subnet whose route goes through a NAT."
        )
    return None


def _egress_problems(tables: list[dict], subnet_ids: list[str]) -> list[str]:
    return [problem for subnet_id in subnet_ids if (problem := egress_problem(tables, subnet_id))]
