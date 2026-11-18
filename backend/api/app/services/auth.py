"""Sign-in: the identity provider's token in, the app's own session credential out.

The provider is asked once, at login. Every later request carries the app's
credential, which is checked here without the network. With no provider
configured (local runs) neither port exists and nobody can sign in.
"""

from app.core.errors import AUTH, InvalidTokenError, UnavailableError
from app.core.models import SessionClaims
from app.services.ports import IdentityVerifier, SessionTokens


class AuthService:
    def __init__(self, verifier: IdentityVerifier | None, tokens: SessionTokens | None) -> None:
        self._verifier, self._tokens = verifier, tokens

    def login(self, id_token: str) -> tuple[str, SessionClaims]:
        if self._verifier is None or self._tokens is None:
            raise UnavailableError("Sign-in is unavailable.", dependency=AUTH, detail="cognito not configured")
        identity = self._verifier.verify(id_token)
        claims = SessionClaims(identity.subject, identity.email, identity.name, identity.groups)
        return self._tokens.issue(claims), claims

    def authenticate(self, token: str) -> SessionClaims:
        if self._tokens is None:
            raise InvalidTokenError(detail="no token validation configured")
        return self._tokens.decode(token)
