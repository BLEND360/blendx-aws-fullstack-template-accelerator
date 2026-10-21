"""The app's own session credential: a short-lived signed token, issued at sign-in.

Signed with AUTH_JWT_SECRET (HS256). The algorithm is pinned when decoding, so a
token signed any other way, Cognito's included, is rejected.
"""

import time

import jwt

from app.core.errors import InvalidTokenError
from app.core.models import SessionClaims


class SessionTokenCodec:
    def __init__(self, secret: str, issuer: str, ttl_seconds: int) -> None:
        self._secret, self._issuer, self._ttl = secret, issuer, ttl_seconds

    def issue(self, claims: SessionClaims) -> str:
        now = int(time.time())
        payload = {
            "iss": self._issuer,
            "sub": claims.subject,
            "email": claims.email,
            "name": claims.name,
            "roles": list(claims.roles),
            "iat": now,
            "exp": now + self._ttl,
        }
        return jwt.encode(payload, self._secret, algorithm="HS256")

    def decode(self, token: str) -> SessionClaims:
        try:
            p = jwt.decode(
                token,
                self._secret,
                algorithms=["HS256"],
                issuer=self._issuer,
                options={"require": ["exp", "iat", "sub", "iss"]},
            )
        except jwt.PyJWTError as exc:
            raise InvalidTokenError(detail=f"session token rejected: {type(exc).__name__}") from exc
        return SessionClaims(p["sub"], p.get("email", ""), p.get("name", ""), tuple(p.get("roles", ())))


