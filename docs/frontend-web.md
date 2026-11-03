# Frontend

Reference for the Vite + React single-page app: how it reaches the API, how the chat consumes the stream, how it is structured and how to replace the brand.

## Same-origin only

The SPA talks to the API on its own origin: `/api/*` and `/auth/*`, relative paths, no base URL anywhere. Locally the Vite dev server proxies those two prefixes to the API on :8000; deployed, CloudFront does. `apiFetch` in `src/api/` is the only `fetch` in the app.

## Sign-in

With the `VITE_COGNITO_*` values filled, sign-in is PKCE against Cognito and required; the session state machine in `src/auth/` handles the code exchange, rehydration and the route guard, and the API trades the id token for its own one-hour credential. While the values are empty the app is in local mode: no sign-in, a banner says so, and the backend must run with `LOCAL_AUTH_BYPASS=true`.

## The chat

`/chat` shows the answer streaming in as it is written; when the agent uses a tool a card shows it running and then its result. The conversation is remembered in the browser, so a reload brings the history back; **New conversation** starts another.

A `POST` cannot use `EventSource`, so `src/api/turns.ts` reads the response body itself and `src/api/events.ts` parses it, delivering the same events however the network splits the bytes. `src/features/chat/chatState.ts` holds the reducer that turns events into the timeline. Both are pinned by the shared fixture, see [sse-contract](./sse-contract.md).

## Where things go

| Path | What |
|---|---|
| `src/tokens/` | The whole brand. Everything else imports `from "../tokens"`, never a file inside it |
| `src/api/` | `apiFetch`, `ApiError`, session token, typed endpoint calls, the SSE reader and parser |
| `src/ui/` | Presentational pieces shared by every layer above `api` |
| `src/auth/` | Session state machine and the route guard |
| `src/features/chat/` | Timeline state, conversation and turn hooks, the page, the tool card |
| `src/features/items/` | The example page: list, create, field and service errors. Copy it |
| `src/messages.ts` | Fixed UI strings; the UI shows these or an API error's own message, never a response body |
| `src/test/` | Test doubles for `/api/v1/items`, used only by page tests |

A new page is a folder under `src/features/`, a route in `src/App.tsx` and a row in the nav list in `src/components/AppShell.tsx`.

## Replace the brand

Replace the contents of `src/tokens/` keeping the entry point (`index.ts` exporting `lightTheme`, `darkTheme`, `BrandLogo`, `applyBrandDocument`). `tests/neutral-tokens/index.ts` is a minimal example type-checked against the real one, and `npm run test:neutral` runs the same suite with it. `npm run check:boundaries` fails, naming file and line, when a color literal, a font family or an import of a tokens file appears outside the folder. It is textual: it does not see named colors or values built at runtime.

## The items contract

`/api/v1/items` is served by the backend. `src/test/itemsStandin.ts` is a test double of it; if the real contract changes, update it and `src/features/items/api.ts` together, the only place the SPA knows the contract.

## Commands

```bash
npm test                  # unit and integration, no API, AWS or Cognito needed
npm run typecheck
npm run test:neutral
npm run check:boundaries
npm run build
```
