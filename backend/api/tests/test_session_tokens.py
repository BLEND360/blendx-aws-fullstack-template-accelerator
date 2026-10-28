"""The app's session credential: round trip, expiry, foreign secret, and Cognito's tokens are not accepted."""

import time

import jwt
import pytest

from app.clients.session_tokens import SessionTokenCodec
from app.core.errors import InvalidTokenError
from app.core.models import SessionClaims

SECRET = "x" * 32
CLAIMS = SessionClaims("u-1", "u@example.test", "U One", ("admin",))


def codec(secret=SECRET, ttl=3600, issuer="proj"):
    return SessionTokenCodec(secret, issuer, ttl)


def test_round_trip():
    assert codec().decode(codec().issue(CLAIMS)) == CLAIMS


def test_ttl_sets_the_expiry():
    payload = jwt.decode(codec(ttl=60).issue(CLAIMS), options={"verify_signature": False})
    assert payload["exp"] - payload["iat"] == 60


def test_expired_token_is_rejected():
    with pytest.raises(InvalidTokenError):
        codec(ttl=-1).decode(codec(ttl=-1).issue(CLAIMS))


def test_other_secret_is_rejected():
    with pytest.raises(InvalidTokenError):
        codec().decode(codec(secret="y" * 32).issue(CLAIMS))


def test_tampered_payload_is_rejected():
    head, _, sig = codec().issue(CLAIMS).split(".")
    forged = jwt.encode({"sub": "u-1", "roles": ["admin"], "iss": "proj", "iat": 1, "exp": int(time.time()) + 99}, "k" * 32)
    with pytest.raises(InvalidTokenError):
        codec().decode(f"{head}.{forged.split('.')[1]}.{sig}")


def test_a_token_from_another_issuer_or_algorithm_is_rejected():
    with pytest.raises(InvalidTokenError):
        codec().decode(codec(issuer="other").issue(CLAIMS))
    unsigned = jwt.encode({"sub": "u-1", "iss": "proj", "iat": 1, "exp": int(time.time()) + 99}, None, algorithm="none")
    with pytest.raises(InvalidTokenError):
        codec().decode(unsigned)


def test_garbage_is_rejected_without_leaking_it():
    with pytest.raises(InvalidTokenError) as exc:
        codec().decode("not-a-token")
    assert "not-a-token" not in str(exc.value.detail)
