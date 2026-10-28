"""Every IAM role the template provisions. Add a role by adding a RoleSpec to the
list role_specs() returns; RolesStack needs no change.

The harness grants (invoke_harness, get_harness, harness_memory) take resolved
ARNs, so the app stack attaches them.
"""

import re

from aws_cdk import aws_iam as iam

from config import Config
from specs.role import RoleSpec

GITHUB_OIDC_HOST = "token.actions.githubusercontent.com"
# Default qualifier of `cdk bootstrap`.
CDK_QUALIFIER = "hnb659fds"
_GEO_PREFIX = re.compile(r"^(us|eu|apac|jp|au|ca|global|us-gov)\.")


def github_oidc_principal(
    c: Config, subject_suffix: str, *, main_only: bool = False
) -> iam.IPrincipal:
    """Trust one GitHub event class and this repository, accounting for org-customized subjects."""
    equals = {
        f"{GITHUB_OIDC_HOST}:aud": "sts.amazonaws.com",
        f"{GITHUB_OIDC_HOST}:repository": f"{c.github_org}/{c.github_repo}",
    }
    if main_only:
        # Environment-based subjects omit the branch. AWS supports `ref` as a
        # separate GitHub OIDC condition, so enforce main in the trust policy too.
        equals[f"{GITHUB_OIDC_HOST}:ref"] = "refs/heads/main"
    return iam.FederatedPrincipal(
        federated=f"arn:aws:iam::{c.aws_account}:oidc-provider/{GITHUB_OIDC_HOST}",
        conditions={
            "StringEquals": equals,
            "StringLike": {
                f"{GITHUB_OIDC_HOST}:sub": f"repo:{c.github_org}*/{c.github_repo}*:{subject_suffix}"
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

    Attached by the app stack, the first to know the resolved ARN: the starter
    harness's id is assigned when it deploys, after this stack. Endpoints are
    addressed under the harness ARN.

    Two actions: InvokeHarness runs the harness's runtime on the caller's behalf, and AgentCore authorizes that
    second call as InvokeAgentRuntime on the same harness ARN. With only the first, every turn fails with
    AccessDenied (seen on the first real chat), which the API reports as "no assistant is configured".
    """
    return iam.PolicyStatement(
        sid="InvokeHarness",
        actions=["bedrock-agentcore:InvokeHarness", "bedrock-agentcore:InvokeAgentRuntime"],
        resources=[harness_arn, f"{harness_arn}/*"],
    )


def get_harness(harness_arn: str) -> iam.PolicyStatement:
    """The task role reads the resolved harness to find its memory. Attached by the app stack, like invoke_harness."""
    return iam.PolicyStatement(
        sid="GetHarness",
        actions=["bedrock-agentcore:GetHarness"],
        resources=[harness_arn],
    )


def harness_memory(memory_arn: str) -> iam.PolicyStatement:
    """History and session deletion read and delete events in the harness's memory.

    Scoped to that one memory: the app stack receives its ARN, resolved from the
    harness by scripts/deploy_app.py, and attaches this, like invoke_harness.
    """
    return iam.PolicyStatement(
        sid="HarnessMemoryEvents",
        actions=["bedrock-agentcore:ListEvents", "bedrock-agentcore:DeleteEvent"],
        resources=[memory_arn],
    )


def deploy_role(c: Config) -> RoleSpec:
    account, region = c.aws_account, c.aws_region
    return RoleSpec(
        id="GithubDeployRole",
        role_name=c.deploy_role,
        description="Assumed by GitHub Actions (OIDC) to deploy this project.",
        assumed_by=iam.CompositePrincipal(
            *(
                github_oidc_principal(c, f"environment:{environment}", main_only=True)
                for environment in c.environments
            )
        ),
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
                sid="ReadNetworkForDeploy",
                actions=[
                    "ec2:DescribeManagedPrefixLists",
                    "ec2:DescribeVpcs",
                    "ec2:DescribeSubnets",
                    "ec2:DescribeInternetGateways",
                    "ec2:DescribeRouteTables",
                ],
                resources=["*"],
            ),
            iam.PolicyStatement(
                sid="ReadAppServiceForDeploy",
                actions=["ecs:DescribeServices"],
                resources=[f"arn:aws:ecs:{region}:{account}:service/{c.cluster}/{c.service}"],
            ),
            iam.PolicyStatement(
                sid="ReadTaskDefinitionForDeploy",
                actions=["ecs:DescribeTaskDefinition"],
                resources=["*"],
            ),
            iam.PolicyStatement(
                sid="ReadApiRepositoryForDeploy",
                actions=["ecr:DescribeRepositories"],
                resources=[f"arn:aws:ecr:{region}:{account}:repository/{c.ecr_repository}"],
            ),
            iam.PolicyStatement(
                sid="ReadHarnessForDeploy",
                actions=["bedrock-agentcore:GetHarness"],
                resources=[f"arn:aws:bedrock-agentcore:{region}:{account}:harness/*"],
            ),
            iam.PolicyStatement(
                sid="ReadUserPoolClientForDeploy",
                actions=["cognito-idp:DescribeUserPoolClient"],
                # Cognito assigns the pool ID only when the auth stack is created,
                # after this roles stack; bound the read to this account and region.
                resources=[f"arn:aws:cognito-idp:{region}:{account}:userpool/*"],
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


def diff_role(c: Config) -> RoleSpec:
    """PRs can read deployment inputs and assume only the CDK lookup role."""
    account, region = c.aws_account, c.aws_region
    lookup_role = f"arn:aws:iam::{c.aws_account}:role/cdk-{CDK_QUALIFIER}-lookup-role-{c.aws_account}-{c.aws_region}"
    return RoleSpec(
        id="GithubDiffRole",
        role_name=c.diff_role,
        description="Assumed by GitHub pull requests to run read-only CDK template diffs.",
        assumed_by=github_oidc_principal(c, "pull_request"),
        statements=[
            iam.PolicyStatement(
                sid="AssumeCdkLookupRole",
                actions=["sts:AssumeRole"],
                resources=[lookup_role],
            ),
            iam.PolicyStatement(
                sid="ReadProjectStacks",
                actions=["cloudformation:DescribeStacks"],
                resources=[
                    f"arn:aws:cloudformation:{region}:{account}:stack/{c.name}-*/*",
                    f"arn:aws:cloudformation:{region}:{account}:stack/{c.harness_stack}/*",
                ],
            ),
            iam.PolicyStatement(
                sid="ReadNetworkForDiff",
                actions=[
                    "ec2:DescribeManagedPrefixLists",
                    "ec2:DescribeVpcs",
                    "ec2:DescribeSubnets",
                    "ec2:DescribeInternetGateways",
                    "ec2:DescribeRouteTables",
                ],
                resources=["*"],
            ),
            iam.PolicyStatement(
                sid="ReadHarnessForDiff",
                actions=["bedrock-agentcore:GetHarness"],
                resources=[f"arn:aws:bedrock-agentcore:{region}:{account}:harness/*"],
            ),
            iam.PolicyStatement(
                sid="ReadServiceForDiff",
                actions=["ecs:DescribeServices"],
                resources=[f"arn:aws:ecs:{region}:{account}:service/{c.cluster}/{c.service}"],
            ),
            iam.PolicyStatement(
                sid="ReadTaskDefinitionForDiff",
                actions=["ecs:DescribeTaskDefinition"],
                resources=["*"],
            ),
            iam.PolicyStatement(
                sid="ReadCdkBootstrapVersion",
                actions=["ssm:GetParameter"],
                resources=[f"arn:aws:ssm:{region}:{account}:parameter/cdk-bootstrap/{CDK_QUALIFIER}/version"],
            ),
        ],
    )


def harness_execution_role(c: Config) -> RoleSpec:
    """Assumed by AgentCore to run the starter harness: a model and managed memory.

    The platform's harness role minus what tools need (gateway invoke, S3
    skills), which it does not need until the harness has tools.
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
                    # A cross-region profile (us.anthropic.X) routes to the model in any region of its geography.
                    f"arn:aws:bedrock:*::foundation-model/{_GEO_PREFIX.sub('', c.harness_model_id)}",
                    f"arn:aws:bedrock:{region}:{account}:inference-profile/{c.harness_model_id}",
                ],
            ),
            # Third-party models (Anthropic included) are enabled through a
            # Marketplace subscription the first time they are invoked; these actions take no resource scoping.
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


def table_access(c: Config) -> iam.PolicyStatement:
    """The running API's access to the template's two tables, and to nothing else in DynamoDB.

    Scoped by name: the names come from project.toml, so the roles stack needs no reference to the
    data stack and stays deployable before it.
    """
    prefix = f"arn:aws:dynamodb:{c.aws_region}:{c.aws_account}:table"
    return iam.PolicyStatement(
        sid="DataTables",
        actions=[
            "dynamodb:GetItem",
            "dynamodb:PutItem",
            "dynamodb:UpdateItem",
            "dynamodb:DeleteItem",
            "dynamodb:Query",
            "dynamodb:DescribeTable",  # the readiness probe
        ],
        resources=[f"{prefix}/{c.sessions_table}", f"{prefix}/{c.items_table}"],
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
            table_access(c),
        ],
    )


def role_specs(c: Config) -> list[RoleSpec]:
    specs = [deploy_role(c), diff_role(c), execution_role(c), task_role(c)]
    if c.deploys_starter_harness:
        specs.append(harness_execution_role(c))
    return specs
