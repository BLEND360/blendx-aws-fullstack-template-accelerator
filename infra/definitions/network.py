"""Every network the template provisions. Add one by adding a NetworkSpec to the list network_specs
returns; NetworkStack needs no change.

The number of NAT gateways is not here: it depends on the environment (project.toml's
[environments]) and reaches the stack as a parameter.
"""

from config import MAX_NAT_GATEWAYS
from specs.network import NetworkSpec


def network_specs() -> list[NetworkSpec]:
    return [
        NetworkSpec(
            id="Network",
            vpc_cidr="10.0.0.0/16",
            max_azs=MAX_NAT_GATEWAYS,  # one NAT per zone is the most an environment can ask for
            description="The app's VPC: tasks and load balancer in private subnets, NAT gateways in public ones.",
        )
    ]
