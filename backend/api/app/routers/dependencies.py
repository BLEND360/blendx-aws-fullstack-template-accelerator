"""Request dependencies shared by routers."""

from dataclasses import dataclass

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings
from app.core.errors import InvalidTokenError
from app.core.logging import get_logger

logger = get_logger(__name__)
_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class User:
    id: str
    email: str
    name: str


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> User:
    """The caller. Every authenticated route depends on this.

    Token validation (Cognito id token in, app JWT out) arrives with ST-08;
    until then only the local bypass admits anyone. The bypass is ignored in a
    deployed task, whatever LOCAL_AUTH_BYPASS says.
    """
    if settings.auth_bypass_enabled:
        logger.warning("local_auth_bypass_used", user_id=settings.local_auth_user_id)
        return User(settings.local_auth_user_id, settings.local_auth_user_email, settings.local_auth_user_name)
    raise InvalidTokenError(detail="no token validation configured" if credentials else "missing bearer token")
