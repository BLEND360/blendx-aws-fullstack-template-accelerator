# contract

Neutral data that pins the SSE stream contract of a turn. `sse-turns.json` holds the `vocabulary` (the six
event names) and the `turns` (a normal one and one that fails midway), each with `events` (what the parser
must deliver), `wire` (the exact bytes on the wire) and `state` (what the reducer must produce).

Two tests read it, each on its own side: `backend/api/tests/test_sse_contract.py` compares the bytes the
endpoint emits with `wire` and checks `TURN_EVENT_NAMES` against `vocabulary`;
`frontend/web/src/api/sseContract.test.ts` feeds `wire` to `createSseParser` (split at any point) and
`events` to `chatReducer`. Neither app imports from the other: this JSON is the only thing they share. CI has
no path filters, so its `api` and `web` jobs run on every pull request and push, which includes any change
here.

## Add an event

Four places change; if one is missed, at least one test fails.

1. **Backend, model**: the new dataclass, the `TurnEvent` union and `TURN_EVENT_NAMES` in
   `backend/api/app/core/models.py` (the emitter `backend/api/app/routers/turns.py` serializes any event in
   `TURN_EVENT_NAMES` with its fields in camelCase, unchanged). The producer is
   `backend/api/app/services/turn.py`: add the `yield` or the mapping from the harness event there.
2. **Frontend, type and reader**: the `TurnEvent` variant and its case in `toTurnEvent`, in
   `frontend/web/src/api/events.ts`.
3. **Frontend, reducer**: the case in `applyEvent` in `frontend/web/src/features/chat/chatState.ts`.
4. **Fixture**: the name in `vocabulary` and a turn that emits it (in `events`, `wire` and `state`) in
   `contract/sse-turns.json`.

## Regenerate `wire`

`wire` is what the browser sees, with Python's separators (`{"text": "Hel"}`), so generate it from the real
endpoint, not by hand. In a `uv run python` session inside `backend/api`, using `install` from
`tests/api_stack.py` and `send` from `tests/test_turns_api.py`:

- `install(ReplayInvoker.from_fixture(<harnessFixture>))`, and replace `turn_service` with a `TurnService`
  whose registry has `current_time` set to `make_current_time(<a clock fixed at 1700000000>)`.
- `POST /api/v1/sessions/{id}/messages` with `TestClient`; send the `X-Request-Id` header only if the turn has
  a `requestId`.
- Paste `response.text` into `wire`; derive `events` and `state` by hand and check with the two tests.
