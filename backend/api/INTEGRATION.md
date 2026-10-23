# Talking to the agent

How the API converses with an AgentCore harness, and how to extend it without leaving
the pattern. Read it next to the layering in the root [README](../../README.md#architecture).

## What it does

A user has **sessions**. Each one freezes a runtime configuration (a model and the tools
the agent may call) when it is created. Sending a message opens a **turn**: the API invokes
the harness and relays what the agent does to the browser as server-sent events.

| Route | Does |
|-------|------|
| `POST /api/v1/sessions` | Create; body `{ modelId?, toolIds? }` |
| `GET /api/v1/sessions` · `GET /api/v1/sessions/{id}` | List the caller's sessions · read one |
| `PATCH /api/v1/sessions/{id}` | Change model or tools. Omit a field to keep it; send `null` to go back to the default frozen at creation |
| `DELETE /api/v1/sessions/{id}` | Empty the harness memory, then drop the session. If the memory cannot be emptied the session stays hidden and the same call finishes the job |
| `GET /api/v1/sessions/{id}/messages` | The conversation, read from the harness memory |
| `POST /api/v1/sessions/{id}/messages` | Body `{ text }`; the response is a `text/event-stream` |

A turn's events are a **closed vocabulary**; `event:` is the name and `data:` is JSON in camelCase.

| `event` | `data` |
|---------|--------|
| `delta` | `{ text }` |
| `tool_started` | `{ callId, toolId, label }` |
| `tool_input` | `{ callId, input }` |
| `tool_finished` | `{ callId, status: "success" \| "error", result }` |
| `done` | `{}` |
| `error` | `{ code, retryable, requestId }` |

Every stream ends with exactly one `done` or one `error`. Anything refused *before* the
stream opens (unknown session, empty message, no harness configured) is an ordinary JSON
error with its status code, in the same `{ error: { code, message, retryable, requestId } }`
shape as every other error. Codes are `<dependency>_<category>` (`harness_unavailable`,
`memory_throttled`, `data_conflict`, `tool_failed`) plus `validation_error`, `not_found`
and `internal_error`.

## Add a tool

A tool is one entry in `TOOLS` in [`app/tools/builtin.py`](app/tools/builtin.py): an id, a
label shown to the user while it runs, a description for the model, a pydantic model for its
input and a function.

```python
class Lookup(BaseModel):
    order_id: int

def lookup_order(arguments: Lookup) -> dict:
    return {"state": orders.state(arguments.order_id)}

TOOLS.append(Tool(id="lookup_order", label="Looking up the order",
                  description="Finds an order's state.", input_model=Lookup, handler=lookup_order))
```

The model's JSON schema is what the harness sees, and the same model validates what the
agent sends back. A tool never raises to the turn: bad input, an exception or an unknown
tool become a `tool_failed` result the agent can react to, and the browser gets a
redacted result (anything over 16 KB is replaced by `{ "truncated": true }`).

New sessions get every registered tool; sessions that already exist keep the list they were
frozen with. Test it like [`tests/test_tools.py`](tests/test_tools.py) does, and replay a
turn that calls it as in [`tests/test_turn.py`](tests/test_turn.py).

## Add an event type

The vocabulary is a contract with the browser, so changing it is deliberate and breaks tests
on purpose:

1. Add the dataclass to [`app/core/models.py`](app/core/models.py), add it to the `TurnEvent`
   union and to `TURN_EVENT_NAMES`.
2. Emit it from [`app/services/turn.py`](app/services/turn.py). Serialization needs no change:
   the router turns any `TurnEvent` into `event:` + camelCase `data:`.
3. Update the tests that pin it: [`tests/test_event_vocabulary.py`](tests/test_event_vocabulary.py)
   (the list of six names) and the stream assertions in [`tests/test_turns_api.py`](tests/test_turns_api.py).
4. Tell whoever consumes the stream (the chat UI, and the conformance tests of ST-10): it is
   their contract too.

## What never crosses to the client

A client sends text, a session id, tool ids and a model, and nothing else is read. These never
appear in a request that is acted on or in any response or event:

- the harness ARN and endpoint, the memory id, the actor id, the runtime session id
- anything executable (a tool function, a skill URI)
- who owns a session (it comes from the signed-in user) and its revision
- the text of an error from AWS or from a tool, stack traces, account ids

[`tests/test_trust_boundary.py`](tests/test_trust_boundary.py) reads the app's OpenAPI document
and fails if a request or response field names one of them.

## Point the app at an existing harness

Set `harness.arn` and `harness.endpoint` in `project.toml` (and list the models it may use in
`harness.model_ids`), run `python scripts/setup.py`, and the backend reads them as `HARNESS_ARN`
and `HARNESS_ENDPOINT`. No code changes. The task role needs `InvokeHarness` on the harness,
`GetHarness` on it, and `ListEvents`/`DeleteEvent` on its memory; the statements are in
[`infra/definitions/roles.py`](../../infra/definitions/roles.py) (`invoke_harness`, `get_harness`,
`harness_memory`, scoped to the harness and its memory) and `AppStack` attaches them to the task role; `scripts/deploy_app.py` resolves the harness and memory ARNs they are scoped to.

Behind CloudFront. A turn can be silent for a long time while the agent thinks, and CloudFront closes a connection after
60 seconds without a byte (the origin response timeout `AppStack` sets). `EventSourceResponse` writes a `: ping` SSE
comment, which a client does not see as an event, whenever the stream has been idle for 15 seconds, and that is what keeps
a long turn open. The backend adds nothing of its own; `tests/test_sse_keepalive.py` pins the two facts this relies on (the
interval stays well inside CloudFront's window, and the turn endpoint is served by `EventSourceResponse`), so a FastAPI
upgrade that changed either would fail CI.

Still open (the starter harness has no tools of its own, so it could not be tested): when a session
has local tools the call sends a `tools` list, and AgentCore documents that list as overriding the
harness's own tools. With no local tools nothing is sent and the harness keeps its own.

## Slow turn or hung turn

Two limits, both in the environment with these defaults:

- `HARNESS_IDLE_TIMEOUT_SECONDS` (300): the longest the harness may stay **silent**. This is
  botocore's read timeout, so a turn that keeps producing events is never cut, however long it
  runs; one that goes quiet for longer is hung and ends with a retryable `harness_unavailable`.
- `HARNESS_TURN_TIMEOUT_SECONDS` (900): the longest the agent loop may run in total. When it is
  exceeded the harness stops the turn and the stream ends with the same retryable error.

`MAX_TOOL_ROUNDS` (8) bounds how many times a turn may go back and forth running local tools
before it gives up with `tool_failed`. The invocation is **never retried automatically**: it is
not idempotent and a retry would put the user's message in the memory twice. The `retryable`
flag tells the client whether to offer the user a retry.

## Answer with recordings (demonstrations)

`HARNESS_REPLAY=true` makes the API play recorded streams instead of calling a harness, with no AWS
credentials. It is a `HarnessPort` like the real one (`app/harness/replay.py`): the recordings go through
the same translator, so the events, their order and the local tool run are the real thing; only the model's
words are canned. A message containing the word `tool` (any capitalization) plays the recorded tool turn,
anything else the recorded text turn. The conversation is kept in a process-local memory, so history works
until the API restarts.

- `GET /api/v1/configuration` reports `replayMode: true`, and the web app shows a "Demo mode" notice.
- `HARNESS_REPLAY_DELAY_SECONDS` (default `0.04`) is the pause between events, so the streaming is visible.
- It is ignored in a deployed task (detected like the auth bypass), with a startup warning.
- An empty `HARNESS_ARN` is fine in this mode.

## Run it without AWS

`uv run pytest` needs no credentials. The harness is replayed from recorded streams in
[`app/harness/fixtures/`](app/harness/fixtures/) through the real translator (text, a tool call,
a tool the harness ran itself, a split protocol marker, a failure mid-stream), and the memory and
the stores are in-process stand-ins. Locally, sessions and items live in process memory (`DATA_STORE=auto`),
so they do not survive a restart; the app logs `data_store_in_memory` at startup to say so. In a deployed
task they live in DynamoDB; `DATA_STORE=dynamodb` does the same on a laptop, against the tables of the data stack.

`real_text_only.json` and `real_tool_call.json` were recorded from a deployed starter harness (the
reply to a tool result begins with an echo of it, and the harness only accepts a tool result as JSON
*text*). The others (`text_only`, `tool_call`, `managed_tool`, `bad_tool_input`, `marker_split`,
`fails_midstream`) are synthetic, built from the AgentCore service model, because a starter harness
cannot be made to produce them.
