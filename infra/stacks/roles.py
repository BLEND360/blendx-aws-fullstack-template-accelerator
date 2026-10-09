from aws_cdk import Duration, Stack
from aws_cdk import aws_iam as iam
from constructs import Construct

from specs.role import RoleSpec


class RolesStack(Stack):
    """Provisions every RoleSpec it is given. Roles are added in definitions/roles.py, not here."""

    def __init__(self, scope: Construct, construct_id: str, specs: list[RoleSpec], **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        for spec in specs:
            role = iam.Role(
                self,
                spec.id,
                role_name=spec.role_name,
                description=spec.description,
                assumed_by=spec.assumed_by,
                managed_policies=spec.managed_policies,
                max_session_duration=Duration.hours(spec.max_session_hours),
            )
            for statement in spec.statements:
                role.add_to_policy(statement)
