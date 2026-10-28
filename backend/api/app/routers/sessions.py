"""Sessions: a user's conversations with the agent, and their history.

Parses, authorizes and delegates. The owner is always the authenticated user; the
body can only name a model and tool ids. Anything else a client sends (a harness ARN,
a memory id, an actor, an owner) is not a field here and is dropped on parse.
"""

from fastapi import APIRouter, Depends, Response
from pydantic import ConfigDict

from app.core.camel import CamelModel
from app.core.models import SessionRecord
from app.routers.dependencies import (
    User,
    current_user,
    history_service,
    session_service,
    tool_registry,
)
from app.services.history import HistoryService
from app.services.ports import ToolPort
from app.services.runtime_config import UNSET, Overrides
from app.services.sessions import SessionService

router = APIRouter(prefix="/api/v1/sessions", tags=["sessions"])


class SessionOverrides(CamelModel):
    """What a client may choose. Unknown fields are ignored, not rejected: they never get used."""

    model_config = ConfigDict(extra="ignore")

    model_id: str | None = None
    tool_ids: list[str] | None = None

    def to_overrides(self) -> Overrides:
        # Left out is not the same as null: out keeps the value, null restores the frozen default.
        sent = self.model_fields_set
        return Overrides(
            model_id=self.model_id if "model_id" in sent else UNSET,
            tool_ids=self.tool_ids if "tool_ids" in sent else UNSET,
        )


class ToolView(CamelModel):
    id: str
    label: str


class ConfigView(CamelModel):
    model_id: str
    tool_ids: list[str]
    tools: list[ToolView]


class SessionView(CamelModel):
    """A session as a client sees it: no owner, no memory coordinates, no revision."""

    id: str
    created_at: str
    updated_at: str
    config: ConfigView


class SessionList(CamelModel):
    sessions: list[SessionView]


class MessageView(CamelModel):
    role: str
    text: str
    created_at: str


class HistoryView(CamelModel):
    messages: list[MessageView]


def _view(record: SessionRecord, tools: ToolPort) -> SessionView:
    values = record.config.values
    return SessionView(
        id=record.session_id,
        created_at=record.created_at,
        updated_at=record.updated_at,
        config=ConfigView(
            model_id=values.model_id,
            tool_ids=list(values.tool_ids),
            tools=[ToolView(id=i, label=tools.label(i) or i) for i in values.tool_ids],
        ),
    )


@router.post("", status_code=201, response_model=SessionView)
def create_session(
    body: SessionOverrides,
    user: User = Depends(current_user),
    service: SessionService = Depends(session_service),
    tools: ToolPort = Depends(tool_registry),
) -> SessionView:
    return _view(service.create(user.id, body.to_overrides()), tools)


@router.get("", response_model=SessionList)
def list_sessions(
    user: User = Depends(current_user),
    service: SessionService = Depends(session_service),
    tools: ToolPort = Depends(tool_registry),
) -> SessionList:
    return SessionList(sessions=[_view(r, tools) for r in service.list(user.id)])


@router.get("/{session_id}", response_model=SessionView)
def get_session(
    session_id: str,
    user: User = Depends(current_user),
    service: SessionService = Depends(session_service),
    tools: ToolPort = Depends(tool_registry),
) -> SessionView:
    return _view(service.get(user.id, session_id), tools)


@router.patch("/{session_id}", response_model=SessionView)
def update_session(
    session_id: str,
    body: SessionOverrides,
    user: User = Depends(current_user),
    service: SessionService = Depends(session_service),
    tools: ToolPort = Depends(tool_registry),
) -> SessionView:
    return _view(service.update(user.id, session_id, body.to_overrides()), tools)


@router.delete("/{session_id}", status_code=204, response_class=Response)
def delete_session(
    session_id: str, user: User = Depends(current_user), service: SessionService = Depends(session_service)
) -> Response:
    service.delete(user.id, session_id)
    return Response(status_code=204)


@router.get("/{session_id}/messages", response_model=HistoryView)
def get_history(
    session_id: str, user: User = Depends(current_user), service: HistoryService = Depends(history_service)
) -> HistoryView:
    return HistoryView(
        messages=[MessageView(role=m.role, text=m.text, created_at=m.created_at) for m in service.get(user.id, session_id)]
    )
