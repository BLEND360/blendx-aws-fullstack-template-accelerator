"""Id token verification, with RSA keys generated here: no Cognito, no network."""

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.clients.cognito import CognitoVerifier
from app.core.errors import InvalidTokenError, UnavailableError

REGION, POOL, CLIENT = "us-east-1", "us-east-1_abc", "client-1"
ISSUER = f"https://cognito-idp.{REGION}.amazonaws.com/{POOL}"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class Jwks:
    def __init__(self, error=None):
        self.error = error

    def get_signing_key_from_jwt(self, token):
        if self.error:
            raise self.error
        return type("K", (), {"key": KEY.public_key()})()


def token(key=KEY, **overrides):
    claims = {
        "iss": ISSUER, "aud": CLIENT, "sub": "u-1", "token_use": "id", "email": "u@example.test",
        "name": "U One", "cognito:groups": ["admin"], "exp": int(time.time()) + 600,
    }
    claims.update(overrides)
    return jwt.encode({k: v for k, v in claims.items() if v is not None}, key, algorithm="RS256", headers={"kid": "k1"})


def verifier(jwks=None):
    return CognitoVerifier(REGION, POOL, CLIENT, jwks or Jwks())


def test_valid_token_yields_the_identity():
    identity = verifier().verify(token())
    assert (identity.subject, identity.email, identity.name, identity.groups) == ("u-1", "u@example.test", "U One", ("admin",))


def test_no_groups_claim_means_no_groups():
    assert verifier().verify(token(**{"cognito:groups": None})).groups == ()


@pytest.mark.parametrize(
    "bad",
    [
        token(exp=int(time.time()) - 10),
        token(aud="someone-else"),
        token(iss="https://cognito-idp.us-east-1.amazonaws.com/other"),
        token(key=OTHER_KEY),
        token(token_use="access"),
        "not-a-token",
    ],
)
def test_invalid_tokens_are_rejected_without_echoing_them(bad):
    with pytest.raises(InvalidTokenError) as exc:
        verifier().verify(bad)
    assert bad not in str(exc.value.detail)


def test_unreachable_keys_are_unavailable_not_invalid():
    with pytest.raises(UnavailableError):
        verifier(Jwks(jwt.PyJWKClientConnectionError("down"))).verify(token())


def test_unknown_key_id_is_invalid():
    with pytest.raises(InvalidTokenError):
        verifier(Jwks(jwt.PyJWKClientError("no kid"))).verify(token())
