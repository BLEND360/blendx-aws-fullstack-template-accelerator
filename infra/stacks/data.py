from aws_cdk import RemovalPolicy, Stack
from aws_cdk import aws_dynamodb as dynamodb
from constructs import Construct

from specs.table import TableSpec


class DataStack(Stack):
    """Provisions every TableSpec it is given. Tables are added in definitions/tables.py, not here.

    Its own stack so an application rollback can never reach user data, and RETAIN so deleting the
    stack does not delete the tables either.
    """

    def __init__(self, scope: Construct, construct_id: str, specs: list[TableSpec], **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        for spec in specs:
            dynamodb.Table(
                self,
                spec.id,
                table_name=spec.table_name,
                partition_key=dynamodb.Attribute(name=spec.partition_key, type=dynamodb.AttributeType.STRING),
                sort_key=dynamodb.Attribute(name=spec.sort_key, type=dynamodb.AttributeType.STRING),
                billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
                removal_policy=RemovalPolicy.RETAIN,
            )
