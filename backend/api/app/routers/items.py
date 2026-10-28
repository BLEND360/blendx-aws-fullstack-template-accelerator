"""Items: the template's example resource, and the pattern to copy for your own.

Parses, authorizes and delegates. The owner is always the authenticated user; the body can only
name `name` and `description`. The wire shape is the one the SPA's items page already uses.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, StringConstraints

from app.core.camel import CamelModel
from app.core.errors import ValidationFailedError
from app.core.models import ItemRecord
from app.routers.dependencies import User, current_user, item_service
from app.services.items import ItemService

router = APIRouter(prefix="/api/v1/items", tags=["items"])

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]


class ItemView(CamelModel):
    """An item as a client sees it: no owner, no revision."""

    id: str
    name: str
    description: str | None
    created_at: str
    updated_at: str


class ItemList(BaseModel):
    items: list[ItemView]


class NewItem(BaseModel):
    """Unknown fields (an owner, an id) are ignored, never used."""

    model_config = ConfigDict(extra="ignore")

    name: Name
    description: Description | None = None


class ItemChanges(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: Name | None = None
    description: Description | None = None  # null clears it

    def to_changes(self) -> dict[str, str | None]:
        # Left out keeps the value; a null name is not a clearable field.
        sent = {field: getattr(self, field) for field in self.model_fields_set}
        if "name" in sent and sent["name"] is None:
            raise ValidationFailedError(fields=[{"location": "name", "message": "A name is required."}])
        return sent


def _view(r: ItemRecord) -> ItemView:
    return ItemView(id=r.item_id, name=r.name, description=r.description, created_at=r.created_at, updated_at=r.updated_at)


@router.post("", status_code=201, response_model=ItemView)
def create_item(
    body: NewItem, user: User = Depends(current_user), service: ItemService = Depends(item_service)
) -> ItemView:
    return _view(service.create(user.id, body.name, body.description))


@router.get("", response_model=ItemList)
def list_items(user: User = Depends(current_user), service: ItemService = Depends(item_service)) -> ItemList:
    return ItemList(items=[_view(r) for r in service.list(user.id)])


@router.get("/{item_id}", response_model=ItemView)
def get_item(item_id: str, user: User = Depends(current_user), service: ItemService = Depends(item_service)) -> ItemView:
    return _view(service.get(user.id, item_id))


@router.patch("/{item_id}", response_model=ItemView)
def update_item(
    item_id: str, body: ItemChanges, user: User = Depends(current_user), service: ItemService = Depends(item_service)
) -> ItemView:
    return _view(service.update(user.id, item_id, body.to_changes()))


@router.delete("/{item_id}", status_code=204, response_class=Response)
def delete_item(
    item_id: str, user: User = Depends(current_user), service: ItemService = Depends(item_service)
) -> Response:
    service.delete(user.id, item_id)
    return Response(status_code=204)
