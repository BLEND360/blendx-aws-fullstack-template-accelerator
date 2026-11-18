from dataclasses import dataclass


@dataclass(frozen=True)
class NetworkSpec:
    """One VPC: private subnets for the workloads, public ones only for the NAT gateways."""

    id: str
    vpc_cidr: str
    max_azs: int
    description: str
