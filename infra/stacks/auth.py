from aws_cdk import CfnOutput, RemovalPolicy, Stack
from aws_cdk import aws_cognito as cognito
from constructs import Construct

from specs.user_pool import UserPoolSpec


class AuthStack(Stack):
    """Provisions every UserPoolSpec it is given. Pools are added in definitions/auth.py, not here.

    Its own stack, and RETAIN, so neither an app rollback nor deleting this stack deletes the users.
    """

    def __init__(self, scope: Construct, construct_id: str, specs: list[UserPoolSpec], **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        for spec in specs:
            pool = cognito.UserPool(
                self,
                spec.id,
                user_pool_name=spec.pool_name,
                self_sign_up_enabled=False,
                sign_in_aliases=cognito.SignInAliases(email=True),
                standard_attributes=cognito.StandardAttributes(email=cognito.StandardAttribute(required=True, mutable=True)),
                account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
                removal_policy=RemovalPolicy.RETAIN,
            )
            # Public client (no secret): the SPA runs in a browser and PKCE protects the code exchange.
            client = pool.add_client(
                f"{spec.id}Client",
                user_pool_client_name=spec.client_name,
                generate_secret=False,
                prevent_user_existence_errors=True,
                o_auth=cognito.OAuthSettings(
                    flows=cognito.OAuthFlows(authorization_code_grant=True),
                    scopes=[cognito.OAuthScope.OPENID, cognito.OAuthScope.EMAIL, cognito.OAuthScope.PROFILE],
                    callback_urls=list(spec.callback_urls),
                    logout_urls=list(spec.logout_urls),
                ),
            )
            pool.add_domain(f"{spec.id}Domain", cognito_domain=cognito.CognitoDomainOptions(domain_prefix=spec.domain_prefix))
            for group in spec.groups:
                cognito.CfnUserPoolGroup(self, f"{spec.id}Group-{group}", user_pool_id=pool.user_pool_id, group_name=group)

            CfnOutput(self, "UserPoolId", value=pool.user_pool_id)
            CfnOutput(self, "AppClientId", value=client.user_pool_client_id)
            CfnOutput(self, "Domain", value=f"{spec.domain_prefix}.auth.{self.region}.amazoncognito.com")
