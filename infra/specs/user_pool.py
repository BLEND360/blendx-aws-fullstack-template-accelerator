from dataclasses import dataclass


@dataclass(frozen=True)
class UserPoolSpec:
    """One Cognito user pool with its single public web client, hosted-UI domain and groups."""

    id: str
    pool_name: str
    client_name: str
    domain_prefix: str
    groups: tuple[str, ...]  # a user's groups become the API's roles
    callback_urls: tuple[str, ...]
    logout_urls: tuple[str, ...]
    description: str
