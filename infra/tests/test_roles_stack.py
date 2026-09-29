import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Match, Template

import config
from definitions.roles import CDK_QUALIFIER, role_specs
from stacks.roles import RolesStack

C = config.load()
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


def test_one_role_per_spec(template):
    template.resource_count_is("AWS::IAM::Role", len(role_specs(C)))


def test_deploy_role_trusts_only_this_repo_via_oidc(template):
    (statement,) = role(template, C.deploy_role)["AssumeRolePolicyDocument"]["Statement"]
    host = "token.actions.githubusercontent.com"
    assert statement["Action"] == "sts:AssumeRoleWithWebIdentity"
    assert statement["Principal"]["Federated"] == f"arn:aws:iam::{ACCOUNT}:oidc-provider/{host}"
    assert statement["Condition"] == {
        "StringEquals": {
            f"{host}:aud": "sts.amazonaws.com",
            f"{host}:repository": f"{C.github_org}/{C.github_repo}",
        },
        # Wildcards skip the owner/repo ids this org's customized `sub` injects.
        "StringLike": {f"{host}:sub": f"repo:{C.github_org}*/{C.github_repo}*:*"},
    }


def test_deploy_role_grants(template):
    assert granted_actions(template, "GithubDeployRole") == {
        "sts:AssumeRole",
        "cloudformation:DescribeStacks",
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


def test_invoke_harness_statement_scoped_to_resolved_arn():
    from definitions.roles import invoke_harness

    statement = invoke_harness("arn:aws:bedrock-agentcore:r:1:harness/h").to_statement_json()
    assert statement["Action"] == "bedrock-agentcore:InvokeHarness"
    assert statement["Resource"] == [
        "arn:aws:bedrock-agentcore:r:1:harness/h",
        "arn:aws:bedrock-agentcore:r:1:harness/h/*",
    ]


def test_task_role_grants(template):
    assert granted_actions(template, "EcsTaskRole") == {
        "ssmmessages:CreateControlChannel",
        "ssmmessages:CreateDataChannel",
        "ssmmessages:OpenControlChannel",
        "ssmmessages:OpenDataChannel",
    }
