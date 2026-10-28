"""Verifies the id token Cognito issues to the SPA after sign-in.

Checks the signature against the user pool's public keys (cached by PyJWKClient),
then issuer, audience (the app client), expiry and that it is an id token, not an
access token. Only /auth/login calls this; every later request carries the app's
own credential and needs no network.
"""

import jwt
from jwt import PyJWKClient

from app.core.errors import AUTH, InvalidTokenError, UnavailableError
from app.core.models import Identity


class CognitoVerifier:
    def __init__(self, region: str, user_pool_id: str, app_client_id: str, jwks: PyJWKClient | None = None) -> None:
        self._issuer = f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}"
        self._client_id = app_client_id
        self._jwks = jwks or PyJWKClient(f"{self._issuer}/.well-known/jwks.json")

    def verify(self, id_token: str) -> Identity:
        try:
            key = self._jwks.get_signing_key_from_jwt(id_token).key
            claims = jwt.decode(
                id_token,
                key,
                algorithms=["RS256"],
                issuer=self._issuer,
                audience=self._client_id,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
        except jwt.PyJWKClientConnectionError as exc:
            raise UnavailableError("Sign-in is unavailable. Try again.", dependency=AUTH, detail="jwks unreachable") from exc
        except jwt.PyJWTError as exc:
            raise InvalidTokenError(detail=f"id token rejected: {type(exc).__name__}") from exc
        if claims.get("token_use") != "id":
            raise InvalidTokenError(detail="not an id token")
        return Identity(
            subject=claims["sub"],
            email=claims.get("email", ""),
            name=claims.get("name", ""),
            groups=tuple(claims.get("cognito:groups", ())),
        )
