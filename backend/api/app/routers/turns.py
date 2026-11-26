"""Sending a message and streaming the turn back as server-sent events.

Everything that can be refused (unknown session, empty message, no harness
configured) is decided by `prepare`, a dependency that runs before the stream is
opened, so those come back as ordinary JSON errors with their status code. Once the
stream is open the status is 200 and a failure is the last event instead.
"""

from collections.abc import AsyncIterator
from dataclasses import fields
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.core.models import TURN_EVENT_NAMES, TurnEvent
from app.routers.dependencies import User, current_user, turn_service
from app.services.turn import PreparedTurn, TurnService

router = APIRouter(prefix="/api/v1/sessions", tags=["turns"])

MAX_MESSAGE_CHARS = 12000  # bounds what one turn can cost


class MessageIn(BaseModel):
    """The only thing a client sends to start a turn. Anything else is dropped on parse."""

    model_config = ConfigDict(extra="ignore")

    text: str = Field(max_length=MAX_MESSAGE_CHARS)


def prepared_turn(
    session_id: str,
    body: MessageIn,
    user: User = Depends(current_user),
    service: TurnService = Depends(turn_service),
) -> PreparedTurn:
    return service.prepare(user.id, session_id, body.text)


def _data(event: TurnEvent) -> dict[str, Any]:
    # camelCase keys on the wire; nested values (tool input and result) are passed through as they are.
    return {to_camel(f.name): getattr(event, f.name) for f in fields(event)}


@router.post("/{session_id}/messages", response_class=EventSourceResponse)
async def send_message(
    turn: PreparedTurn = Depends(prepared_turn),
    service: TurnService = Depends(turn_service),
) -> AsyncIterator[ServerSentEvent]:
    async for event in service.run(turn):
        yield ServerSentEvent(event=TURN_EVENT_NAMES[type(event)], data=_data(event))
