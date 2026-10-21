from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.routers.dependencies import User, auth_service, current_user
from app.services.auth import AuthService

router = APIRouter(tags=["auth"])


class UserProfile(BaseModel):
    id: str
    name: str
    email: str
    roles: list[str]


class LoginRequest(BaseModel):
    id_token: str


class LoginResponse(BaseModel):
    access_token: str
    user: UserProfile


def _profile(user: User) -> UserProfile:
    return UserProfile(id=user.id, name=user.name, email=user.email, roles=list(user.roles))


@router.post("/auth/login", response_model=LoginResponse)
def login(body: LoginRequest, service: AuthService = Depends(auth_service)) -> LoginResponse:
    """Trade the identity provider's token for the app's session credential (1 hour, no refresh)."""
    access_token, claims = service.login(body.id_token)
    return LoginResponse(
        access_token=access_token, user=_profile(User(claims.subject, claims.email, claims.name, claims.roles))
    )


@router.get("/auth/me", response_model=UserProfile)
def me(user: User = Depends(current_user)) -> UserProfile:
    return _profile(user)
