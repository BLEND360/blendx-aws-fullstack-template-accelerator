"""Every IAM role the template provisions. Add a role by adding a RoleSpec to the
list role_specs() returns; RolesStack needs no change.

Later tickets extend these roles in place, e.g. the tables grant the task role
access (ST-05).
"""

from aws_cdk import aws_iam as iam

from config import Config
from specs.role import RoleSpec

GITHUB_OIDC_HOST = "token.actions.githubusercontent.com"
# Default `cdk bootstrap` qualifier. Change both here and in bootstrap.py if a
# custom one is used.
CDK_QUALIFIER = "hnb659fds"


def github_oidc_principal(c: Config) -> iam.IPrincipal:
    """Trust GitHub Actions runs from this project's repository only.

    This org has GitHub's OIDC subject-claim customization enabled, which
    injects immutable owner and repository ids into `sub`
    ("repo:BLEND360@28543622/<repo>@1322111153:ref:refs/heads/main"), so a
    literal "repo:BLEND360/<repo>:*" never matches and every assume fails with
    "Not authorized to perform sts:AssumeRoleWithWebIdentity". The `*` after
    org and repo skip over those ids. `repository` is the uncustomized claim
    and does the real scoping; `sub` is kept because IAM rejects a GitHub OIDC
    trust policy without a `sub` or `job_workflow_ref` condition.
    """
    return iam.FederatedPrincipal(
        federated=f"arn:aws:iam::{c.aws_account}:oidc-provider/{GITHUB_OIDC_HOST}",
        conditions={
            "StringEquals": {
                f"{GITHUB_OIDC_HOST}:aud": "sts.amazonaws.com",
                f"{GITHUB_OIDC_HOST}:repository": f"{c.github_org}/{c.github_repo}",
            },
            "StringLike": {
                f"{GITHUB_OIDC_HOST}:sub": f"repo:{c.github_org}*/{c.github_repo}*:*",
            },
        },
        assume_role_action="sts:AssumeRoleWithWebIdentity",
    )


def ecs_tasks_principal(c: Config) -> iam.IPrincipal:
    return iam.ServicePrincipal(
        "ecs-tasks.amazonaws.com",
        conditions={"StringEquals": {"aws:SourceAccount": c.aws_account}},
    )


def manage_harness_endpoints(c: Config) -> list[iam.PolicyStatement]:
    """For point-harness-alias.sh and wait-harness-ready.sh, which call the API directly."""
    prefix = f"arn:aws:bedrock-agentcore:{c.aws_region}:{c.aws_account}"
    return [
        iam.PolicyStatement(
            sid="ManageHarnessEndpoints",
            actions=[
                "bedrock-agentcore:CreateHarnessEndpoint",
                "bedrock-agentcore:UpdateHarnessEndpoint",
                "bedrock-agentcore:GetHarnessEndpoint",
            ],
            resources=[f"{prefix}:harness/*"],
        ),
        # A harness endpoint operation drives the matching operation on the
        # runtime behind the harness; the platform found UpdateHarnessEndpoint
        # denied until these were granted too.
        iam.PolicyStatement(
            sid="ManageAgentRuntimeEndpoints",
            actions=[
                "bedrock-agentcore:CreateAgentRuntimeEndpoint",
                "bedrock-agentcore:UpdateAgentRuntimeEndpoint",
                "bedrock-agentcore:GetAgentRuntimeEndpoint",
            ],
            resources=[f"{prefix}:runtime/*"],
        ),
    ]


def invoke_harness(harness_arn: str) -> iam.PolicyStatement:
    """The task role's grant on the resolved harness, starter or configured.

    Attached by the app stack (ST-07), the first stack that knows the resolved
    ARN: the starter harness's id is assigned when it deploys, after this
    stack. Endpoints are addressed under the harness ARN.
    """
    return iam.PolicyStatement(
        sid="InvokeHarness",
        actions=["bedrock-agentcore:InvokeHarness"],
        resources=[harness_arn, f"{harness_arn}/*"],
    )


def deploy_role(c: Config) -> RoleSpec:
    account, region = c.aws_account, c.aws_region
    return RoleSpec(
        id="GithubDeployRole",
        role_name=c.deploy_role,
        description="Assumed by GitHub Actions (OIDC) to deploy this project.",
        assumed_by=github_oidc_principal(c),
        statements=[
            # `cdk deploy` and `agentcore deploy` reach CloudFormation through
            # the bootstrap roles, so the deploy role itself never holds
            # resource-creation permissions.
            iam.PolicyStatement(
                sid="AssumeCdkBootstrapRoles",
                actions=["sts:AssumeRole"],
                resources=[f"arn:aws:iam::{account}:role/cdk-{CDK_QUALIFIER}-*"],
            ),
            # The pipeline reads names and ids from stack outputs instead of
            # duplicating them as workflow variables.
            iam.PolicyStatement(
                sid="ReadStackOutputs",
                actions=["cloudformation:DescribeStacks"],
                resources=[
                    f"arn:aws:cloudformation:{region}:{account}:stack/{c.name}-*/*",
                    f"arn:aws:cloudformation:{region}:{account}:stack/{c.harness_stack}/*",
                ],
            ),
            iam.PolicyStatement(
                sid="EcrLogin",
                actions=["ecr:GetAuthorizationToken"],
                resources=["*"],  # account-level action; no resource scoping
            ),
            iam.PolicyStatement(
                sid="PushApiImage",
                actions=[
                    "ecr:BatchCheckLayerAvailability",
                    "ecr:CompleteLayerUpload",
                    "ecr:DescribeImages",
                    "ecr:InitiateLayerUpload",
                    "ecr:PutImage",
                    "ecr:UploadLayerPart",
                ],
                resources=[f"arn:aws:ecr:{region}:{account}:repository/{c.ecr_repository}"],
            ),
            iam.PolicyStatement(
                sid="PublishSpa",
                actions=["s3:ListBucket", "s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
                resources=[f"arn:aws:s3:::{c.web_bucket}", f"arn:aws:s3:::{c.web_bucket}/*"],
            ),
            iam.PolicyStatement(
                sid="InvalidateCdn",
                actions=["cloudfront:CreateInvalidation"],
                # The distribution id is assigned at creation, after this role exists.
                resources=[f"arn:aws:cloudfront::{account}:distribution/*"],
            ),
            # Only when this project owns its harness: a deploy role that
            # consumes a platform harness must not be able to repoint its endpoints.
            *(manage_harness_endpoints(c) if c.deploys_starter_harness else []),
        ],
    )


def harness_execution_role(c: Config) -> RoleSpec:
    """Assumed by AgentCore to run the starter harness: a model and managed memory.

    The platform's harness role minus what tools need (gateway invoke, S3
    skills); ST-13 adds those back when it gives the harness tools.
    """
    account, region = c.aws_account, c.aws_region
    return RoleSpec(
        id="HarnessExecutionRole",
        role_name=c.harness_execution_role,
        description="Assumed by Bedrock AgentCore to run this project's starter harness.",
        assumed_by=iam.ServicePrincipal(
            "bedrock-agentcore.amazonaws.com",
            conditions={
                "StringEquals": {"aws:SourceAccount": account},
                "ArnLike": {"aws:SourceArn": f"arn:aws:bedrock-agentcore:{region}:{account}:*"},
            },
        ),
        statements=[
            iam.PolicyStatement(
                sid="InvokeModels",
                actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                resources=[
                    "arn:aws:bedrock:*::foundation-model/*",
                    f"arn:aws:bedrock:{region}:{account}:inference-profile/*",
                ],
            ),
            # Third-party models (Anthropic included) are enabled through a
            # Marketplace subscription the first time they are invoked.
            iam.PolicyStatement(
                sid="SubscribeToModels",
                actions=["aws-marketplace:ViewSubscriptions", "aws-marketplace:Subscribe"],
                resources=["*"],
            ),
            iam.PolicyStatement(
                sid="ManagedMemory",
                actions=[
                    "bedrock-agentcore:CreateEvent",
                    "bedrock-agentcore:GetEvent",
                    "bedrock-agentcore:ListEvents",
                    "bedrock-agentcore:ListSessions",
                    "bedrock-agentcore:RetrieveMemoryRecords",
                ],
                resources=[f"arn:aws:bedrock-agentcore:{region}:{account}:memory/*"],
            ),
            # Runtime plumbing every AgentCore harness needs, per the platform role.
            iam.PolicyStatement(
                sid="RuntimePlumbing",
                actions=[
                    "ecr-public:GetAuthorizationToken",
                    "sts:GetServiceBearerToken",
                    "xray:GetSamplingRules",
                    "xray:GetSamplingTargets",
                    "xray:PutTelemetryRecords",
                    "xray:PutTraceSegments",
                ],
                resources=["*"],
            ),
            iam.PolicyStatement(
                sid="RuntimeLogs",
                actions=[
                    "logs:CreateLogGroup",
                    "logs:DescribeLogStreams",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                ],
                resources=[
                    f"arn:aws:logs:{region}:{account}:log-group:/aws/bedrock-agentcore/runtimes/*",
                    f"arn:aws:logs:{region}:{account}:log-group:/aws/bedrock-agentcore/runtimes/*:log-stream:*",
                ],
            ),
            iam.PolicyStatement(
                sid="DescribeLogGroups",
                actions=["logs:DescribeLogGroups"],
                resources=[f"arn:aws:logs:{region}:{account}:log-group:*"],
            ),
            iam.PolicyStatement(
                sid="RuntimeMetrics",
                actions=["cloudwatch:PutMetricData"],
                resources=["*"],
                conditions={"StringEquals": {"cloudwatch:namespace": "bedrock-agentcore"}},
            ),
        ],
    )


def execution_role(c: Config) -> RoleSpec:
    return RoleSpec(
        id="EcsExecutionRole",
        role_name=c.execution_role,
        description="Used by ECS itself to pull the API image and write its logs.",
        assumed_by=ecs_tasks_principal(c),
        managed_policies=[
            iam.ManagedPolicy.from_aws_managed_policy_name(
                "service-role/AmazonECSTaskExecutionRolePolicy"
            )
        ],
    )


def task_role(c: Config) -> RoleSpec:
    return RoleSpec(
        id="EcsTaskRole",
        role_name=c.task_role,
        description="Assumed by the running API container.",
        assumed_by=ecs_tasks_principal(c),
        statements=[
            iam.PolicyStatement(
                sid="EcsExec",
                actions=[
                    "ssmmessages:CreateControlChannel",
                    "ssmmessages:CreateDataChannel",
                    "ssmmessages:OpenControlChannel",
                    "ssmmessages:OpenDataChannel",
                ],
                resources=["*"],  # ssmmessages has no resource-level scoping
            ),
        ],
    )


def role_specs(c: Config) -> list[RoleSpec]:
    specs = [deploy_role(c), execution_role(c), task_role(c)]
    if c.deploys_starter_harness:
        specs.append(harness_execution_role(c))
    return specs
