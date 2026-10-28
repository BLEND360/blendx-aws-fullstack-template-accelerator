import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Match, Template

from definitions.auth import auth_specs
from stacks.auth import AuthStack
from tests.conftest import fixed_config

C = fixed_config()
ENV = cdk.Environment(account=C.aws_account, region=C.aws_region)


@pytest.fixture(scope="module")
def template() -> Template:
    return Template.from_stack(AuthStack(cdk.App(), C.auth_stack, specs=auth_specs(C), env=ENV))


def test_one_pool_named_from_project_toml_without_self_sign_up_and_retained(template):
    template.resource_count_is("AWS::Cognito::UserPool", 1)
    template.has_resource(
        "AWS::Cognito::UserPool",
        {
            "Properties": {
                "UserPoolName": C.user_pool,
                "AdminCreateUserConfig": {"AllowAdminCreateUserOnly": True},
                "UsernameAttributes": ["email"],
            },
            "DeletionPolicy": "Retain",
        },
    )


def test_public_client_with_code_grant_and_the_localhost_return_address(template):
    template.has_resource_properties(
        "AWS::Cognito::UserPoolClient",
        {
            "ClientName": C.app_client,
            "GenerateSecret": False,
            "AllowedOAuthFlows": ["code"],
            "AllowedOAuthScopes": Match.array_with(["openid", "email", "profile"]),
            "CallbackURLs": Match.array_with(["http://localhost:5173/"]),
            "LogoutURLs": Match.array_with(["http://localhost:5173/"]),
        },
    )


def test_hosted_ui_domain_and_both_groups(template):
    template.has_resource_properties("AWS::Cognito::UserPoolDomain", {"Domain": C.cognito_domain_prefix})
    groups = {r["Properties"]["GroupName"] for r in template.find_resources("AWS::Cognito::UserPoolGroup").values()}
    assert groups == {"admin", "user"}


def test_outputs_are_what_the_spa_and_api_need(template):
    assert set(template.find_outputs("*")) == {"UserPoolId", "AppClientId", "Domain"}


def test_extra_callback_urls_reach_the_client():
    from dataclasses import replace

    c = replace(C, auth_callback_urls=("https://app.acme.test/",))
    t = Template.from_stack(AuthStack(cdk.App(), c.auth_stack, specs=auth_specs(c), env=ENV))
    t.has_resource_properties(
        "AWS::Cognito::UserPoolClient",
        {"CallbackURLs": ["http://localhost:5173/", "https://app.acme.test/"]},
    )
