from fnmatch import fnmatchcase

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Match, Template

from definitions.roles import CDK_QUALIFIER, harness_execution_role, role_specs
from stacks.roles import RolesStack
from tests.conftest import fixed_config

C = fixed_config()
ACCOUNT = C.aws_account


@pytest.fixture(scope="module")
def template() -> Template:
    app = cdk.App()
    env = cdk.Environment(account=ACCOUNT, region=C.aws_region)
    return Template.from_stack(RolesStack(app, C.roles_stack, specs=role_specs(C), env=env))


def role(template: Template, name: str) -> dict:
    roles = template.find_resources("AWS::IAM::Role", {"Properties": {"RoleName": name}})
    assert len(roles) == 1, f"expected one role named {name}"
    return next(iter(roles.values()))["Properties"]


def granted_actions(template: Template, role_logical_id_prefix: str) -> set[str]:
    actions = set()
    for resource in template.find_resources("AWS::IAM::Policy").values():
        props = resource["Properties"]
        if not props["Roles"][0]["Ref"].startswith(role_logical_id_prefix):
            continue
        for statement in props["PolicyDocument"]["Statement"]:
            assert statement["Effect"] == "Allow"
            a = statement["Action"]
            actions.update([a] if isinstance(a, str) else a)
    return actions


def allows(template: Template, role_prefix: str, action: str, resource: str) -> bool:
    for policy in template.find_resources("AWS::IAM::Policy").values():
        props = policy["Properties"]
        if not props["Roles"][0]["Ref"].startswith(role_prefix):
            continue
        for statement in props["PolicyDocument"]["Statement"]:
            actions = statement["Action"]
            if isinstance(actions, str):
                actions = [actions]
            resources = statement["Resource"]
            if isinstance(resources, str):
                resources = [resources]
            if action in actions and any(fnmatchcase(resource, pattern) for pattern in resources):
                return True
    return False


def test_one_role_per_spec(template):
    template.resource_count_is("AWS::IAM::Role", len(role_specs(C)))


def test_deploy_role_trusts_only_main_on_the_deployment_environments(template):
    statements = role(template, C.deploy_role)["AssumeRolePolicyDocument"]["Statement"]
    host = "token.actions.githubusercontent.com"
    assert len(statements) == len(C.environments)
    for statement, environment in zip(statements, C.environments, strict=True):
        assert statement["Action"] == "sts:AssumeRoleWithWebIdentity"
        assert statement["Principal"]["Federated"] == f"arn:aws:iam::{ACCOUNT}:oidc-provider/{host}"
        assert statement["Condition"] == {
            "StringEquals": {
                f"{host}:aud": "sts.amazonaws.com",
                f"{host}:repository": f"{C.github_org}/{C.github_repo}",
                f"{host}:ref": "refs/heads/main",
            },
            "StringLike": {f"{host}:sub": f"repo:{C.github_org}*/{C.github_repo}*:environment:{environment}"},
        }


def test_diff_role_is_pull_request_only_and_can_assume_only_the_cdk_lookup_role(template):
    props = role(template, C.diff_role)
    (statement,) = props["AssumeRolePolicyDocument"]["Statement"]
    host = "token.actions.githubusercontent.com"
    assert statement["Condition"]["StringEquals"] == {
        f"{host}:aud": "sts.amazonaws.com",
        f"{host}:repository": f"{C.github_org}/{C.github_repo}",
    }
    assert statement["Condition"]["StringLike"][f"{host}:sub"] == (
        f"repo:{C.github_org}*/{C.github_repo}*:pull_request"
    )
    assert granted_actions(template, "GithubDiffRole") == {
        "sts:AssumeRole",
        "cloudformation:DescribeStacks",
        "ec2:DescribeManagedPrefixLists",
        "ec2:DescribeVpcs",
        "ec2:DescribeSubnets",
        "ec2:DescribeInternetGateways",
        "ec2:DescribeRouteTables",
        "bedrock-agentcore:GetHarness",
        "ecs:DescribeServices",
        "ecs:DescribeTaskDefinition",
        "ssm:GetParameter",
    }
    assert not any(
        action.split(":", 1)[1].startswith(("Create", "Update", "Delete", "Put", "Run", "Start", "Stop"))
        for action in granted_actions(template, "GithubDiffRole")
    )
    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with([
                    Match.object_like({
                        "Action": "sts:AssumeRole",
                        "Resource": f"arn:aws:iam::{ACCOUNT}:role/cdk-{CDK_QUALIFIER}-lookup-role-{ACCOUNT}-{C.aws_region}",
                    })
                ])
            }
        },
    )


def test_deploy_role_grants(template):
    assert granted_actions(template, "GithubDeployRole") == {
        "sts:AssumeRole",
        "cloudformation:DescribeStacks",
        "ec2:DescribeManagedPrefixLists",
        "ec2:DescribeVpcs",
        "ec2:DescribeSubnets",
        "ec2:DescribeInternetGateways",
        "ec2:DescribeRouteTables",
        "ecs:DescribeServices",
        "ecs:DescribeTaskDefinition",
        "ecr:DescribeRepositories",
        "bedrock-agentcore:GetHarness",
        "cognito-idp:DescribeUserPoolClient",
        "ecr:GetAuthorizationToken",
        "ecr:BatchCheckLayerAvailability",
        "ecr:CompleteLayerUpload",
        "ecr:DescribeImages",
        "ecr:InitiateLayerUpload",
        "ecr:PutImage",
        "ecr:UploadLayerPart",
        "s3:ListBucket",
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
        "cloudfront:CreateInvalidation",
        # project.toml leaves harness.arn empty, so the deploy role manages the starter's endpoints
        "bedrock-agentcore:CreateHarnessEndpoint",
        "bedrock-agentcore:UpdateHarnessEndpoint",
        "bedrock-agentcore:GetHarnessEndpoint",
        "bedrock-agentcore:CreateAgentRuntimeEndpoint",
        "bedrock-agentcore:UpdateAgentRuntimeEndpoint",
        "bedrock-agentcore:GetAgentRuntimeEndpoint",
    }
    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with([
                    Match.object_like({
                        "Action": "sts:AssumeRole",
                        "Resource": f"arn:aws:iam::{ACCOUNT}:role/cdk-{CDK_QUALIFIER}-*",
                    })
                ])
            }
        },
    )


@pytest.mark.parametrize(
    ("role", "step", "call", "action", "resource"),
    [
        ("GithubDeployRole", "deploy_app", "network_check.check", "ec2:DescribeVpcs", "*"),
        ("GithubDeployRole", "deploy_app", "network_check.check", "ec2:DescribeSubnets", "*"),
        ("GithubDeployRole", "deploy_app", "network_check.check", "ec2:DescribeInternetGateways", "*"),
        ("GithubDeployRole", "deploy_app", "network_check.check", "ec2:DescribeRouteTables", "*"),
        ("GithubDeployRole", "deploy_app", "network_check.cloudfront_prefix_list", "ec2:DescribeManagedPrefixLists", "*"),
        (
            "GithubDeployRole",
            "deploy_app / diff / changed_paths / smoke_test",
            "outputs (diff.py, smoke_test.py) / current_image_tag (deploy_app.py, changed_paths.py)",
            "cloudformation:DescribeStacks",
            f"arn:aws:cloudformation:{C.aws_region}:{ACCOUNT}:stack/{C.app_stack}/*",
        ),
        (
            "GithubDeployRole",
            "deploy_app",
            "current_image_tag",
            "ecs:DescribeServices",
            f"arn:aws:ecs:{C.aws_region}:{ACCOUNT}:service/{C.cluster}/{C.service}",
        ),
        ("GithubDeployRole", "deploy_app", "current_image_tag", "ecs:DescribeTaskDefinition", "*"),
        (
            "GithubDeployRole",
            "deploy_app",
            "repository_exists",
            "ecr:DescribeRepositories",
            f"arn:aws:ecr:{C.aws_region}:{ACCOUNT}:repository/{C.ecr_repository}",
        ),
        (
            "GithubDeployRole",
            "deploy_app",
            "harness_resolve._memory_arn",
            "bedrock-agentcore:GetHarness",
            f"arn:aws:bedrock-agentcore:{C.aws_region}:{ACCOUNT}:harness/*",
        ),
        (
            "GithubDeployRole",
            "deploy_app",
            "sign_in_allows",
            "cognito-idp:DescribeUserPoolClient",
            f"arn:aws:cognito-idp:{C.aws_region}:{ACCOUNT}:userpool/*",
        ),
        (
            "GithubDiffRole",
            "diff.py",
            "cdk diff --method=template",
            "sts:AssumeRole",
            f"arn:aws:iam::{ACCOUNT}:role/cdk-{CDK_QUALIFIER}-lookup-role-{ACCOUNT}-{C.aws_region}",
        ),
        (
            "GithubDiffRole",
            "diff.py / deploy_app.gather",
            "outputs",
            "cloudformation:DescribeStacks",
            f"arn:aws:cloudformation:{C.aws_region}:{ACCOUNT}:stack/{C.app_stack}/*",
        ),
        ("GithubDiffRole", "diff.py / deploy_app.gather", "network_check", "ec2:DescribeVpcs", "*"),
        ("GithubDiffRole", "diff.py / deploy_app.gather", "network_check", "ec2:DescribeSubnets", "*"),
        ("GithubDiffRole", "diff.py / deploy_app.gather", "network_check", "ec2:DescribeInternetGateways", "*"),
        ("GithubDiffRole", "diff.py / deploy_app.gather", "network_check", "ec2:DescribeRouteTables", "*"),
        (
            "GithubDiffRole",
            "diff.py / deploy_app.gather",
            "cloudfront_prefix_list",
            "ec2:DescribeManagedPrefixLists",
            "*",
        ),
        (
            "GithubDiffRole",
            "diff.py / deploy_app.gather",
            "harness_resolve._memory_arn",
            "bedrock-agentcore:GetHarness",
            f"arn:aws:bedrock-agentcore:{C.aws_region}:{ACCOUNT}:harness/*",
        ),
        (
            "GithubDiffRole",
            "diff.py",
            "current_image_tag",
            "ecs:DescribeServices",
            f"arn:aws:ecs:{C.aws_region}:{ACCOUNT}:service/{C.cluster}/{C.service}",
        ),
        (
            "GithubDiffRole",
            "diff.py",
            "current_image_tag",
            "ecs:DescribeTaskDefinition",
            "*",
        ),
        (
            "GithubDiffRole",
            "diff.py / CDK synth",
            "bootstrap version lookup",
            "ssm:GetParameter",
            f"arn:aws:ssm:{C.aws_region}:{ACCOUNT}:parameter/cdk-bootstrap/{CDK_QUALIFIER}/version",
        ),
    ],
)
def test_pipeline_read_inventory_is_granted_and_scoped(template, role, step, call, action, resource):
    assert allows(template, role, action, resource), f"{step}: {call} requires {action} on {resource}"


@pytest.mark.parametrize("name", [C.task_role, C.execution_role])
def test_ecs_roles_trust_ecs_tasks_in_this_account(template, name):
    (statement,) = role(template, name)["AssumeRolePolicyDocument"]["Statement"]
    assert statement["Principal"] == {"Service": "ecs-tasks.amazonaws.com"}
    assert statement["Condition"] == {"StringEquals": {"aws:SourceAccount": ACCOUNT}}


def test_execution_role_uses_managed_policy_only(template):
    (arn,) = role(template, C.execution_role)["ManagedPolicyArns"]
    assert "AmazonECSTaskExecutionRolePolicy" in str(arn)
    assert granted_actions(template, "EcsExecutionRole") == set()


def test_harness_role_trusts_agentcore_in_this_account(template):
    (statement,) = role(template, C.harness_execution_role)["AssumeRolePolicyDocument"]["Statement"]
    assert statement["Principal"] == {"Service": "bedrock-agentcore.amazonaws.com"}
    assert statement["Condition"] == {
        "StringEquals": {"aws:SourceAccount": ACCOUNT},
        "ArnLike": {"aws:SourceArn": f"arn:aws:bedrock-agentcore:{C.aws_region}:{ACCOUNT}:*"},
    }


def test_harness_role_grants_model_and_memory_only(template):
    actions = granted_actions(template, "HarnessExecutionRole")
    assert {"bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"} <= actions
    assert "bedrock-agentcore:ListEvents" in actions
    assert "bedrock-agentcore:InvokeGateway" not in actions
    assert not any(a.startswith("s3:") for a in actions)


def test_harness_role_invokes_only_its_model_through_the_cross_region_profile():
    (statement,) = [s.to_statement_json() for s in harness_execution_role(C).statements if s.sid == "InvokeModels"]
    model = C.harness_model_id
    assert model.startswith("us.anthropic.")
    assert statement["Resource"] == [
        f"arn:aws:bedrock:*::foundation-model/{model.removeprefix('us.')}",
        f"arn:aws:bedrock:{C.aws_region}:{ACCOUNT}:inference-profile/{model}",
    ]


def test_invoke_harness_statement_scoped_to_resolved_arn():
    from definitions.roles import invoke_harness

    statement = invoke_harness("arn:aws:bedrock-agentcore:r:1:harness/h").to_statement_json()
    # InvokeHarness runs the harness's runtime on the caller's behalf, and AgentCore authorizes that second call
    # as InvokeAgentRuntime on the harness ARN: found on the first real chat, which failed with AccessDenied.
    assert statement["Action"] == ["bedrock-agentcore:InvokeHarness", "bedrock-agentcore:InvokeAgentRuntime"]
    assert statement["Resource"] == [
        "arn:aws:bedrock-agentcore:r:1:harness/h",
        "arn:aws:bedrock-agentcore:r:1:harness/h/*",
    ]


def test_get_harness_statement_is_scoped_to_the_harness():
    from definitions.roles import get_harness

    statement = get_harness("arn:aws:bedrock-agentcore:r:1:harness/h").to_statement_json()
    assert statement["Action"] == "bedrock-agentcore:GetHarness"
    assert statement["Resource"] == "arn:aws:bedrock-agentcore:r:1:harness/h"


def test_history_statement_reads_and_deletes_events_in_the_given_memory_only():
    from definitions.roles import harness_memory

    memory = f"arn:aws:bedrock-agentcore:{C.aws_region}:{ACCOUNT}:memory/assistant_mem-XyZ789"
    statement = harness_memory(memory).to_statement_json()
    assert set(statement["Action"]) == {"bedrock-agentcore:ListEvents", "bedrock-agentcore:DeleteEvent"}
    assert statement["Resource"] == memory
    assert "*" not in statement["Resource"]


def test_task_role_grants(template):
    assert granted_actions(template, "EcsTaskRole") == {
        "ssmmessages:CreateControlChannel",
        "ssmmessages:CreateDataChannel",
        "ssmmessages:OpenControlChannel",
        "ssmmessages:OpenDataChannel",
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:UpdateItem",
        "dynamodb:DeleteItem",
        "dynamodb:Query",
        "dynamodb:DescribeTable",
    }
