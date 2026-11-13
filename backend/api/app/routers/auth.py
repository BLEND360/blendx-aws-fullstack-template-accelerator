from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.routers.dependencies import User, current_user

router = APIRouter(tags=["auth"])


class UserProfile(BaseModel):
    id: str
    name: str
    email: str
    roles: list[str]


# Provisional (frontend-web): ST-08 owns this endpoint and replaces it with real
# token validation and roles. It exists so the SPA can learn who the caller is,
# including under the local bypass.
@router.get("/auth/me", response_model=UserProfile)
def me(user: User = Depends(current_user)) -> UserProfile:
    return UserProfile(id=user.id, name=user.name, email=user.email, roles=[])
