from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from app.core.config import settings
from app.routers.dependencies import User, current_user

router = APIRouter(tags=["configuration"])


class ClientConfiguration(BaseModel):
    """What the SPA may read about the deployment. Display values only: no ARNs,
    account ids, table names or memory coordinates. Adding a field is a decision
    to expose it, so it is made here, in the model."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    allowed_model_ids: list[str]
    # The first allowed model: the order of ALLOWED_MODEL_IDS is meaningful.
    default_model_id: str
    # The API is answering with recorded responses (a demonstration), not a live harness.
    replay_mode: bool


@router.get("/api/v1/configuration", response_model=ClientConfiguration)
def client_configuration(_user: User = Depends(current_user)) -> ClientConfiguration:
    models = settings.allowed_model_ids
    return ClientConfiguration(allowed_model_ids=models, default_model_id=models[0], replay_mode=settings.replay_enabled)
