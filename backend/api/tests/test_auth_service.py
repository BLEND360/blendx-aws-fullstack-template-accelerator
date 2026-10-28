"""AuthService with stand-in ports: no network, no keys."""

import pytest

from app.core.errors import InvalidTokenError, UnavailableError
from app.services.auth import AuthService
from app.core.models import Identity, SessionClaims


class FakeVerifier:
    def __init__(self, groups=("admin",)):
        self.groups = groups

    def verify(self, id_token):
        if id_token != "good":
            raise InvalidTokenError(detail="bad")
        return Identity("u-1", "u@example.test", "U One", self.groups)


class FakeTokens:
    def issue(self, claims):
        return f"session:{claims.subject}:{','.join(claims.roles)}"

    def decode(self, token):
        if not token.startswith("session:"):
            raise InvalidTokenError(detail="bad")
        _, subject, roles = token.split(":")
        return SessionClaims(subject, "u@example.test", "U One", tuple(r for r in roles.split(",") if r))


def test_login_turns_groups_into_roles_and_issues_a_credential():
    token, claims = AuthService(FakeVerifier(("admin", "user")), FakeTokens()).login("good")
    assert claims.roles == ("admin", "user")
    assert token == "session:u-1:admin,user"


def test_no_groups_means_no_roles():
    _, claims = AuthService(FakeVerifier(()), FakeTokens()).login("good")
    assert claims.roles == ()


def test_a_rejected_provider_token_issues_nothing():
    with pytest.raises(InvalidTokenError):
        AuthService(FakeVerifier(), FakeTokens()).login("bad")


def test_login_without_cognito_is_unavailable_not_invalid():
    with pytest.raises(UnavailableError) as exc:
        AuthService(None, None).login("good")
    assert exc.value.code == "auth_unavailable"


def test_authenticate_reads_the_credential_without_asking_the_provider():
    claims = AuthService(None, FakeTokens()).authenticate("session:u-2:user")
    assert (claims.subject, claims.roles) == ("u-2", ("user",))


def test_authenticate_without_token_validation_is_invalid():
    with pytest.raises(InvalidTokenError):
        AuthService(None, None).authenticate("session:u-2:user")
