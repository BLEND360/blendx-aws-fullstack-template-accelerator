from dataclasses import dataclass, field

from aws_cdk import aws_iam as iam


@dataclass(frozen=True)
class RoleSpec:
    """One IAM role: who can assume it and what it can do."""

    id: str
    role_name: str
    description: str
    assumed_by: iam.IPrincipal
    managed_policies: list[iam.IManagedPolicy] = field(default_factory=list)
    statements: list[iam.PolicyStatement] = field(default_factory=list)
    max_session_hours: int = 1
