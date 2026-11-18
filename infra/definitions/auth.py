"""Every Cognito user pool the template provisions. Add one by adding a UserPoolSpec to the list
auth_specs returns; AuthStack needs no change.

Groups are the API's roles: `admin` and `user`. Callback URLs are localhost plus whatever
project.toml's [auth] lists (the deployed app's URL is added there once it exists).
"""

from config import LOCAL_CALLBACK_URL, Config
from specs.user_pool import UserPoolSpec


def auth_specs(c: Config) -> list[UserPoolSpec]:
    urls = (LOCAL_CALLBACK_URL, *c.auth_callback_urls)
    return [
        UserPoolSpec(
            id="UserPool",
            pool_name=c.user_pool,
            client_name=c.app_client,
            domain_prefix=c.cognito_domain_prefix,
            groups=("admin", "user"),
            callback_urls=urls,
            logout_urls=urls,
            description="Users of the web app. Accounts are created by an administrator; there is no self sign-up.",
        )
    ]
