from aws_cdk import Stack
from aws_cdk import aws_ec2 as ec2
from constructs import Construct

from specs.network import NetworkSpec


class NetworkStack(Stack):
    """Provisions every NetworkSpec it is given. Networks are added in definitions/network.py, not here.

    Its own stack so an app rollback or deletion never reaches the network; the app stack's reference
    to the VPC also stops this one being deleted while the app uses it.
    """

    def __init__(self, scope: Construct, construct_id: str, specs: list[NetworkSpec], nat_gateways: int, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        self.vpcs: dict[str, ec2.Vpc] = {}
        for spec in specs:
            self.vpcs[spec.id] = ec2.Vpc(
                self,
                spec.id,
                ip_addresses=ec2.IpAddresses.cidr(spec.vpc_cidr),
                max_azs=spec.max_azs,
                nat_gateways=nat_gateways,
                subnet_configuration=[
                    # The public subnets only host the NAT gateways: nothing launched there gets a public IP.
                    ec2.SubnetConfiguration(
                        name="public", subnet_type=ec2.SubnetType.PUBLIC, cidr_mask=24, map_public_ip_on_launch=False
                    ),
                    ec2.SubnetConfiguration(name="private", subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS, cidr_mask=22),
                ],
                # Free, and keeps DynamoDB and S3 (image layers) traffic off the NAT gateways.
                gateway_endpoints={
                    "S3": ec2.GatewayVpcEndpointOptions(service=ec2.GatewayVpcEndpointAwsService.S3),
                    "DynamoDb": ec2.GatewayVpcEndpointOptions(service=ec2.GatewayVpcEndpointAwsService.DYNAMODB),
                },
            )
