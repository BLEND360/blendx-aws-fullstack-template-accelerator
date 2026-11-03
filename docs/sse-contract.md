# SSE Contract

How the stream of a chat turn is pinned between backend and frontend by one neutral JSON file that neither app owns and neither imports from the other.

## The fixture

`contract/sse-turns.json` holds the `vocabulary` (the six event names: `delta`, `tool_started`, `tool_input`, `tool_finished`, `done`, `error`) and the `turns`: a normal one and one that fails midway. Each turn has:

- `events`: what the parser must deliver
- `wire`: the exact bytes on the wire
- `state`: what the reducer must produce

```mermaid
graph LR
    F[contract/sse-turns.json]
    F --> BT[backend: test_sse_contract.py]
    F --> FT[frontend: sseContract.test.ts]
    BT --> W[endpoint bytes equal wire; TURN_EVENT_NAMES equal vocabulary]
    FT --> P[createSseParser(wire, split anywhere) gives events; chatReducer(events) gives state]
```

The only thing the two apps share is this file. CI has no path filters, so the `api` and `web` jobs run on every PR, including any change to it.

## Add an event

Four places change; if one is missed, at least one test fails.

1. Backend model: the dataclass, the `TurnEvent` union and `TURN_EVENT_NAMES` in `backend/api/app/core/models.py`. The emitter `routers/turns.py` serializes any event in that list with camelCase fields. The producer is `services/turn.py`.
2. Frontend type and reader: the `TurnEvent` variant and its case in `toTurnEvent`, in `frontend/web/src/api/events.ts`.
3. Frontend reducer: the case in `applyEvent` in `frontend/web/src/features/chat/chatState.ts`.
4. Fixture: the name in `vocabulary` and a turn that emits it, in `events`, `wire` and `state`.

## Regenerate `wire`

`wire` is what the browser sees, with Python's separators (`{"text": "Hel"}`), so generate it from the real endpoint, not by hand. In a `uv run python` session inside `backend/api`, using `install` from `tests/api_stack.py` and `send` from `tests/test_turns_api.py`:

- `install(ReplayInvoker.from_fixture(<harnessFixture>))` and replace `turn_service` with a `TurnService` whose registry has `current_time` set to a clock fixed at 1700000000.
- `POST /api/v1/sessions/{id}/messages` with `TestClient`; send `X-Request-Id` only if the turn has a `requestId`.
- Paste `response.text` into `wire`; derive `events` and `state` by hand and confirm with both tests.

## Guarantees

Every stream ends with exactly one `done` or one `error`. An `error` carries `{ code, retryable, requestId }` and never any text from a dependency. A long silent turn stays open because the server writes a `: ping` comment every 15 seconds, which the parser ignores. See [backend-api](./backend-api.md).
