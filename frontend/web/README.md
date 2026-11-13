# web

Vite + React single-page app. It talks to the API on its own origin only:
`/api/*` and `/auth/*`, relative paths, no base URL anywhere. Locally the Vite dev
server proxies those two prefixes to the API; deployed, CloudFront does (ST-07).

## Run it

```bash
# Everything, from the repo root (API :8000, web :5173)
docker compose up --build

# Or the web alone, with the API running on :8000
cd frontend/web && npm install && npm run dev      # http://localhost:5173
```

`scripts/setup.py` writes `frontend/web/.env` with the `VITE_COGNITO_*` values.
While they are empty the app runs in **local mode**: no sign-in, a banner says so,
and the backend must have `LOCAL_AUTH_BYPASS=true` (the generated
`backend/api/.env` does). With them filled, sign-in (PKCE against Cognito) is
required and local mode is not offered. Everything else the deployment decides
(models, ...) comes from `GET /api/v1/configuration`; the SPA keeps no copy.

## The chat

`/chat` is a conversation with the agent: the answer streams in as it is written, and when the agent
uses a tool a card shows it running and then what came out. The conversation is remembered in this
browser, so a reload brings the history back; **New conversation** starts another.

It talks to `POST /api/v1/sessions/{id}/messages`, which answers with server-sent events. A `POST`
cannot use `EventSource`, so `src/api/turns.ts` reads the response body itself and `src/api/events.ts`
parses it (the same events however the network splits them).

### Showing it without AWS

Start the API with recorded answers and the whole chat works with no credentials and no harness:

```powershell
cd backend/api
$env:HARNESS_REPLAY = "true"          # bash: HARNESS_REPLAY=true uv run uvicorn ...
uv run uvicorn app.main:app --reload
```

A message containing the word **tool** plays the recorded turn that calls a tool (and the tool really
runs); anything else plays the recorded text turn. The answer does not depend on the question, so the
page shows a "Demo mode" notice. Reloading keeps the history; restarting the API forgets it. It is ignored
in a deployed task. `HARNESS_REPLAY_DELAY_SECONDS` (default `0.04`) sets the pause between events.

## Test it

```bash
npm test                  # unit and integration, no API, AWS or Cognito needed
npm run typecheck
npm run test:neutral      # the same suite with the brand swapped for a neutral theme
npm run check:boundaries  # brand values and API base URLs, repo-wide
npm run build
```

CI (`web` job) runs exactly these. Manual check with the app running: toggle the
theme; in **Items** create one named `error` (retryable 503, with request id) and
one with an empty name (field error); stop the API and reload (service unavailable).

## Where things go

| Path | What |
|------|------|
| `src/tokens/` | The whole brand. Everything else imports `from "../tokens"`, never a file inside it |
| `src/api/` | `apiFetch` (the only `fetch`), `ApiError`, session token, typed endpoint calls |
| `src/ui/` | Presentational pieces shared by every layer above `api`: `ApiErrorAlert`, `LoadingIndicator` |
| `src/auth/` | Session state machine (PKCE, rehydration, local mode) and the route guard |
| `src/features/chat/` | The chat: timeline state (`chatState`), the conversation and turn hooks, the page, the tool card |
| `src/features/items/` | The example page: list, create, field errors, service errors. Copy it |
| `src/messages.ts` | Fixed UI strings; the UI shows these or an API error's own message, never a response body |
| `dev/items-standin.ts` | Dev-only stand-in for `/api/v1/items` until ST-05 |

A new page is a folder under `src/features/`, a route in `src/App.tsx` and a row in
the nav list in `src/components/AppShell.tsx`.

## Replace the brand

Replace the contents of `src/tokens/` keeping the same entry point
(`index.ts` exporting `lightTheme`, `darkTheme`, `BrandLogo`, `applyBrandDocument`);
`tests/neutral-tokens/index.ts` is a minimal example and is type-checked against
the real one. `npm run check:boundaries` fails, naming file and line, if a color
literal, a font family or an import of a tokens file appears outside the folder.
It is textual: it does not see named colors (`red`) or values built at runtime.

## Retire the items stand-in

When ST-05 ships `/api/v1/items`: delete `dev/items-standin.ts` and the
`itemsStandIn()` line in `vite.config.ts`. If the real contract differs from the
one in `src/features/items/api.ts`, that file is the only place to change.
