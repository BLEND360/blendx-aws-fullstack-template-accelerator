# AWS Fullstack Template — Architecture Model

Planning deliverable for [BLEND360/blendx-core#1144](https://github.com/BLEND360/blendx-core/issues/1144).
This document models the application the template produces: its layers,
components, contracts, data, and infrastructure decomposition.

Companion documents:
- [00-proposal-overview.md](00-proposal-overview.md) — the one-page summary
- [01-technical-proposal.md](01-technical-proposal.md) — scope, decisions, and approach
- [03-subtickets.md](03-subtickets.md) — the sub-ticket breakdown
- [05-architecture-standard.md](05-architecture-standard.md) — the pattern this model follows, named, with the rules a consumer inherits

Status: draft for review · Date: September 2026

---

## 1. Layer model

Four application layers and one platform layer. The harness is drawn outside the
application boundary because the application reaches it by ARN and endpoint
name, like any upstream dependency — even though the template provisions a
starter one in its own stack.

```
  ╔═══════════════════════════════════════════════════════════════════╗
  ║  L1  CLIENT                                                       ║
  ║      React SPA · routing · OIDC PKCE · SSE consumer               ║
  ╠═══════════════════════════════════════════════════════════════════╣
  ║  L2  API                                                          ║
  ║      routers (HTTP only) → services (logic) → clients/repos       ║
  ║      middleware: correlation id · CORS · exception handlers       ║
  ╠══════════════════════════════╦════════════════════════════════════╣
  ║  L3  DATA                    ║  L4  HARNESS INTEGRATION           ║
  ║      DynamoDB repositories   ║      client · runtime resolver     ║
  ║      product metadata only   ║      tool registry · SSE emitter   ║
  ╠══════════════════════════════╩════════════════════════════════════╣
  ║  L0  PLATFORM                                                     ║
  ║      CloudFront · S3 · ALB · Fargate · IAM · Cognito · Secrets    ║
  ╚═══════════════════════════════════════════════════════════════════╝
                                    │
                                    │ invoke (streaming)
                                    ▼
                     ┌───────────────────────────────┐
                     │  AgentCore Harness + Memory   │
                     │  own stack · reached by its   │
                     │  (ARN, endpoint) pair         │
                     │  owns conversation content    │
                     └───────────────────────────────┘
```

The split between L3 and L4 is the model's load-bearing decision. The harness
owns conversation content — messages, responses, tool interactions. DynamoDB
owns product metadata and never stores conversation content. Neither one is a
cache of the other, so there is no synchronization problem to solve.

---

## 2. Component inventory

| Layer | Component | Responsibility |
|---|---|---|
| L1 | `src/auth/` | OIDC PKCE against Cognito; session state; route guard |
| L1 | `src/api/` | Typed fetch wrappers; attaches the app JWT; SSE stream consumer |
| L1 | `src/pages/`, `src/components/` | Views and shared UI |
| L1 | `src/tokens/` | Blend Design System theme, isolated so it can be swapped |
| L2 | `app/main.py` | App assembly, middleware order, router registration |
| L2 | `app/core/config.py` | Typed settings from environment, with validation |
| L2 | `app/core/logging.py`, `context.py`, `middleware.py` | Structured logging bound to a request id |
| L2 | `app/core/errors.py`, `exception_handlers.py` | Error taxonomy and the single response shape |
| L2 | `app/core/security.py` | Cognito token validation (JWKS); app JWT mint and verify |
| L2 | `app/routers/` | HTTP concerns only: parse, authorize, delegate, serialize |
| L2 | `app/services/` | Business logic; the only layer that composes repositories and clients |
| L3 | `app/repositories/` | DynamoDB access; one module per table |
| L4 | `app/harness/client.py` | Invoke, stream, page memory events, classify errors |
| L4 | `app/harness/runtime.py` | Resolve, validate, and freeze a session's runtime config |
| L4 | `app/harness/streaming.py` | SSE chunk vocabulary and emitter |
| L4 | `app/tools/` | Inline tool registry and dispatch table |
| L0 | `infra/stacks/` | Four CDK stacks (§8) |

---

## 3. L1 — Client

A single-page application. Static assets only: no server-side rendering, no
Node runtime in production.

| Concern | Model |
|---|---|
| Delivery | Built to `dist/`, synced to a private S3 bucket, served through CloudFront |
| Routing | Client-side. CloudFront rewrites 403 and 404 from the S3 origin to `/index.html` with status 200 so deep links work |
| Auth | Authorization Code + PKCE against Cognito's hosted login; the SPA holds no client secret |
| Session | The app JWT lives in `sessionStorage` and in React context; rehydrated on refresh via the current-user endpoint |
| Server state | React Query for cacheable reads |
| Streaming | `@microsoft/fetch-event-source`, because native `EventSource` cannot POST a body or set an `Authorization` header |
| API base URL | None. Same-origin in production via CloudFront, same-origin in development via the Vite dev proxy |

What the client is not allowed to hold or send: any ARN, harness endpoint name,
S3 URI, memory coordinate, actor id, or executable tool reference. See §12.

---

## 4. L2 — API

### 4.1 Internal layering and its rules

```
  HTTP request
      │
      ▼
  ┌─────────────┐   Parse and validate the request body (Pydantic).
  │  router     │   Resolve the caller. Delegate. Serialize.
  └──────┬──────┘   No business logic. No AWS calls. No table names.
         ▼
  ┌─────────────┐   Own the decision. Compose repositories and clients.
  │  service    │   Enforce ownership. Raise typed app errors.
  └──┬───────┬──┘   No HTTP types. No boto3.
     ▼       ▼
 ┌────────┐ ┌──────────┐   One table or one upstream each.
 │  repo  │ │  client  │   Translate AWS errors into app errors.
 └────────┘ └──────────┘   No business rules.
```

The rule that keeps this honest: a router may not import boto3, and a service
may not import from `fastapi`. Both are checkable in a lint rule or a test.

### 4.2 Middleware order

Starlette applies middleware in reverse registration order, so CORS is
registered last to sit outermost. This is deliberate, not incidental: it means
CORS headers are attached to error responses too. Without it, a 500 reaches the
browser as an opaque CORS failure and the real status is invisible in the
console.

```
  request  →  CORS  →  correlation id  →  routers
  response ←  CORS  ←  correlation id  ←  routers
                │
                └─ X-Request-Id on every response, exposed to JS,
                   bound to every log line the request produces —
                   including lines written from the harness worker thread
```

### 4.3 Error model

One response shape for every failure:

```json
{
  "error": {
    "code": "harness_unavailable",
    "message": "The assistant is temporarily unavailable. Try again shortly.",
    "retryable": true,
    "requestId": "3b2dcb8261fa4f21aca69054492c0034"
  }
}
```

`code` is `<dependency>_<category>`. A client can distinguish "offer a retry"
from "this deployment is broken" without parsing prose.

| Dependency | Categories |
|---|---|
| `harness` | `unavailable`, `throttled`, `misconfigured`, `invalid_request` |
| `memory` | `unavailable`, `throttled`, `misconfigured` |
| `tool` | `failed` |
| `data` | `unavailable`, `throttled`, `conflict` |
| `auth` | `invalid_token`, `forbidden` |
| — | `validation_error`, `internal_error` |

No upstream message text is ever returned. The original is logged against the
request id.

### 4.4 Route surface the template ships

Not a product API — the minimum that demonstrates every pattern a consumer will
extend.

| Method | Path | Demonstrates |
|---|---|---|
| GET | `/health` | Liveness; the ALB health check target |
| GET | `/ready` | Readiness: can this task reach the harness and its tables? |
| GET | `/api/v1/configuration` | Server-supplied client config (model options, feature flags) — removes duplicated constants from the SPA |
| POST | `/auth/login` | Exchange a Cognito id token for an app JWT |
| GET | `/auth/me` | Rehydrate a session |
| POST | `/api/v1/sessions` | Create a session and freeze its runtime config |
| GET | `/api/v1/sessions` | List caller-owned sessions |
| GET | `/api/v1/sessions/{id}` | Read metadata and display-safe resolved config |
| GET | `/api/v1/sessions/{id}/history` | Read conversation events from harness memory |
| POST | `/api/v1/sessions/{id}/messages` | Stream one turn as SSE |
| DELETE | `/api/v1/sessions/{id}` | Delete memory events and metadata |
| GET | `/api/v1/items` + CRUD | A worked example of the repository pattern on a domain table |

---

## 5. L3 — Data

### 5.1 Tables

Two tables, each in the data stack.

`{project}-sessions` — required by the harness integration layer.

| Attribute | Role |
|---|---|
| `owner_id` | Partition key. The caller's Cognito `sub` |
| `session_id` | Sort key. Opaque product id, generated server-side |
| `resolved_config` | Frozen snapshot: validated model, resolved tool refs, system prompt |
| `memory_ref` | Private harness memory coordinates. Never leaves the backend |
| `overrides` | Session-scoped override values |
| `revision` | Optimistic concurrency |
| `created_at`, `updated_at` | Timestamps |
| `deleted` | Soft-delete marker for the retryable deletion flow |

No conversation content. Ever. That lives in harness memory.

`{project}-items` — a worked example domain table, `owner_id` + `item_id`,
shipped so a consumer has a working repository, router, and test to copy rather
than a blank folder.

### 5.2 Access patterns

| Pattern | Operation |
|---|---|
| List a caller's sessions | Query on `owner_id` |
| Load one session | GetItem on the full key |
| Apply an override | UpdateItem with a condition on `revision` |
| Delete a session | UpdateItem to mark deleted, then delete after memory cleanup succeeds |

Ownership is enforced by the key, not by a filter: a foreign `session_id` is a
key miss, and a key miss and a foreign resource both return 404. The client
cannot distinguish "does not exist" from "not yours", which is the intended
behavior.

### 5.3 Why data gets its own stack

Tables live in a separate CloudFormation stack from the application. A rollback
of the ECS service, the ALB, or the CloudFront distribution then cannot touch
user data, because the resources are not in the same stack that is rolling back.
The tables also outlive any given deployment of the API.

---

## 6. L4 — Harness integration

The layer the template exists to provide. See
[01-technical-proposal.md §7](01-technical-proposal.md) for the approach; this
section specifies the contracts.

### 6.1 Turn sequence

```
 Browser            API                      DynamoDB        Harness
   │                 │                          │               │
   │ POST messages   │                          │               │
   │ {"message":"…"} │                          │               │
   ├────────────────►│                          │               │
   │                 │ get session (owner+id)   │               │
   │                 ├─────────────────────────►│               │
   │                 │◄─────────────────────────┤               │
   │                 │   404 if missing OR foreign              │
   │                 │                                          │
   │                 │ invoke(resolved_config, memory_ref, msg)  │
   │                 ├─────────────────────────────────────────►│
   │ SSE: delta      │◄────────── text chunk ───────────────────┤
   │◄────────────────┤                                          │
   │ SSE: tool_started                                          │
   │◄────────────────┤◄────────── tool call request ────────────┤
   │                 │  dispatch to local Python function       │
   │ SSE: tool_input │                                          │
   │◄────────────────┤                                          │
   │                 ├────────── tool result ──────────────────►│
   │ SSE: tool_finished                                         │
   │◄────────────────┤                                          │
   │ SSE: delta      │◄────────── text chunk ───────────────────┤
   │◄────────────────┤                                          │
   │ SSE: done       │◄────────── end of stream ────────────────┤
   │◄────────────────┤                                          │
```

### 6.2 Streaming contract

The chunk vocabulary is the template's backend-to-frontend interface. Both sides
ship against it, and both sides have tests that pin it.

| Chunk | Payload | Client effect |
|---|---|---|
| `delta` | text fragment | Append to the streaming text block |
| `tool_started` | tool id, display label | Add a tool-call block, status running |
| `tool_input` | resolved structured input | Attach to the active tool-call block |
| `tool_finished` | status, redacted result | Update that block's status and result |
| `done` | — | End the turn |
| `error` | code, retryable, requestId | Add an error block alongside any text already streamed |

Two rules that come from real failures:

An `error` chunk never erases partial output. A dropped connection after 200
tokens shows those 200 tokens plus an error, not an empty message.

A mid-stream failure can only be an `error` chunk. The HTTP status was already
sent with the first byte, so the taxonomy has to travel in the body.

### 6.3 Async bridge

The AWS SDK's streaming response is a blocking iterator. FastAPI's SSE response
needs an async generator. The client bridges them with a worker thread and a
queue, and the request id is explicitly re-bound inside the worker thread so log
lines written there still correlate.

A read timeout bounds the stream — a tool-using turn can legitimately run for
minutes, so the timeout marks a wedged stream, not a slow one.

### 6.4 Inline tools

A tool is a Python function plus a JSON schema, registered in one place:

```
app/tools/
  registry.py     # TOOLS (schemas) + TOOL_DISPATCH (name → callable)
  example.py      # one worked tool, with its test
```

Adding a tool is one entry in each mapping. The harness client resolves a
requested name against the dispatch table; an unknown name is a
`tool_failed` result reported back to the model, not an exception that ends the
turn. A failing tool likewise becomes a tool result the model can explain or
route around.

### 6.5 Runtime configuration resolution

```
  template defaults  ─┐
                      ├─► merge ─► validate ─► resolve ─► freeze ─► persist
  session overrides  ─┘             │            │
                                    │            └─ registry ids → executable refs
                                    └─ model ∈ allowlist, else 422
```

Frozen at session creation. An omitted override field preserves its current
value; an explicit `null` clears it and restores the frozen default. Later edits
to the source configuration cannot alter an existing session.

---

## 7. Identity and authorization

### 7.1 Token flow

```
  Browser ──► Cognito hosted login ──► [optional] corporate IdP via SAML
                     │
                     │  pre-token-generation Lambda:
                     │  reject if the user is not in the allowed group
                     ▼
  Browser ◄── authorization code ──► exchange (PKCE) ──► Cognito id_token
     │
     │ POST /auth/login { id_token }
     ▼
  API: verify signature via JWKS, verify issuer and audience,
       extract sub / name / email, mint an app JWT (HS256, short expiry)
     │
     ▼
  Browser: store app JWT in sessionStorage; send it on every later call
```

Two tokens by design. Cognito proves identity once; the application then runs
its own session with its own expiry, so neither the IdP's nor Cognito's token
lifetime leaks into the rest of the app.

### 7.2 Authorization model

| Rule | Mechanism |
|---|---|
| A caller owns their own resources | `owner_id` is the Cognito `sub`, taken from the token, never from the request |
| Foreign resources are invisible | `owner_id` is the partition key; a foreign id is a key miss → 404 |
| Access is granted outside the app | Membership in a Cognito group; managed in AWS, no IdP admin needed |

Known weakness inherited from the MVP, recorded so the template does not repeat
it silently: the pre-token Lambda is the only place group membership is checked.
Once the API holds a validated token it does not re-check. Revoking access takes
effect on the next sign-in, not immediately. The template should either
re-check the group claim in `security.py` or shorten the app JWT expiry; this is
noted as a decision in ST-08.

### 7.3 Local development

A flag serves authenticated endpoints without a bearer token, attributing calls
to a configured identity, so interactive docs and curl work. It is ignored
outright when the process detects it is a deployed task, so setting it in a task
definition cannot weaken a real environment. Every bypassed call logs a warning.

---

## 8. L0 — Infrastructure decomposition

### 8.1 Stacks and dependency order

```
   ┌───────────────┐
   │  RolesStack   │  GitHub OIDC deploy role, task role, execution role,
   └───────┬───────┘  harness execution role
           │          Created by bootstrap; referenced by name elsewhere
   ┌───────┼──────────────┬──────────────────┐
   ▼       ▼              ▼                  │
┌──────────┐ ┌───────────┐ ┌──────────────┐  │
│AuthStack │ │ DataStack │ │   Harness    │  │  independent of each other
│          │ │           │ │ agentcore CLI│  │
│user pool │ │ sessions  │ │ harness.json │  │
│PKCE clnt │ │ items     │ │ model +      │  │
│group+λ   │ │           │ │ managed mem  │  │
│[SAML]    │ │           │ │ + endpoints  │  │
│          │ │           │ │ [skipped if  │  │
│          │ │           │ │  ARN given]  │  │
└────┬─────┘ └─────┬─────┘ └──────┬───────┘  │
     │             │              │          │
     └──────┬──────┴──────────────┴──────────┘
            ▼
      ┌───────────┐
      │ AppStack  │  VPC (or imported) · ECS cluster · Fargate service
      │           │  internal ALB · S3 · CloudFront · app JWT secret
      └───────────┘
```

Why this decomposition:

| Stack | Separated because |
|---|---|
| Roles | It is the bootstrap dependency — the deploy role must exist before CI can assume it to deploy anything, including itself |
| Auth | A user pool deletion loses every user record; it must not share a fate with an application rollback |
| Data | Same reason, for user data; tables outlive any deployment of the API |
| Harness | Managed memory holds conversation history, so it must survive an application rollback. It is also the stack a consumer replaces or drops when pointing at an existing harness, which only works if it stands alone |
| App | The only stack a routine deploy touches |

The harness stack is conditional: when `project.toml` supplies a harness ARN, it
is not synthesized at all, and the app stack receives that ARN — with the
configured endpoint name — instead of the starter harness's output. Same
mechanism the MVP uses to skip a stack whose deploy-time inputs are absent, and
it is what keeps "bring your own harness" a configuration change rather than a
code change.

The harness is the one "stack" this repository does not author. It is deployed
by the `agentcore` CLI over the CDK app that `@aws/agentcore-cdk` generates,
following the platform's layout and naming conventions — see
[01-technical-proposal.md §2.4](01-technical-proposal.md). The pipeline reads
the resulting version back from CloudFormation outputs named
`Harness<PascalName>{Id,Arn,Status,Version,AgentRuntimeArn}` rather than from a
stack output this repository defines.

Cross-stack values are passed as plain strings derived from `project.toml`, not
as CDK cross-stack references. A CDK reference creates a CloudFormation export,
and an export in use cannot be deleted — which makes the stacks' deploy orders
rigid and produces rollbacks with messages like "cannot delete export as it is
in use". The MVP hit this and works around it in code; the template avoids it by
construction.

### 8.2 Declarative resource specs

The pattern worth carrying from the MVP verbatim: a dataclass for the shape, a
data module for the instances, and a generic stack that iterates.

```
infra/
  specs/roles.py        @dataclass RoleSpec:  id, name, assumed_by, statements
  definitions/roles.py  ROLE_SPECS = [RoleSpec(...), RoleSpec(...)]
  stacks/roles_stack.py for spec in ROLE_SPECS: iam.Role(...)
```

Adding a role, a table, or a queue is one entry in a list. No stack code changes.

### 8.3 Network

The template creates a minimal VPC by default — two public subnets across two
availability zones — with an override in `project.toml` to import an existing
VPC by id instead. The MVP only supports the import path, which blocks a team
that has no VPC yet.

Security groups follow a chain, each allowing exactly one source:

| Group | Ingress |
|---|---|
| ALB | TCP 80 from the CloudFront origin prefix list only |
| Task | TCP 8000 from the ALB security group only |

Egress is left to the account default rather than declared. Declaring it
explicitly is worse than it sounds: on any stack rollback, for any reason,
CloudFormation deletes the explicit rule without restoring the implicit default,
which silently removes the task's outbound access. This happened twice during
the MVP's deployment work.

---

## 9. Configuration and secrets

```
  project.toml ──► infra/config.py ──► CDK ──► ECS task definition
       │                                            │  environment: plain config
       │                                            │  secrets:     from Secrets Manager
       │                                            ▼
       │                                     app/core/config.py
       │                                     typed settings, validated at import
       │
       ├──► scripts/setup.py ──► backend/api/.env, frontend/web/.env   (local dev)
       │
       └──► CI ──► VITE_* build-time variables for the SPA
```

| Value | Where it lives | Why |
|---|---|---|
| Project name, region, table names | `project.toml` → derived | One source, no drift |
| Harness ARN and endpoint | `agentcore` stack outputs, or `project.toml` when it names an existing harness | One pair, two possible sources; the task sees only the resolved *(ARN, endpoint)*. The endpoint is what pins which immutable version is served |
| Model allowlist | `project.toml` → task environment | Validated server-side; the SPA reads it from the configuration endpoint |
| Cognito pool and client ids | `AuthStack` outputs → task environment and SPA build | Created by IaC, never hand-copied |
| App JWT signing key | Secrets Manager, generated by CDK, injected by ECS | Never in an environment variable in the repo, never printed |
| CORS origins | Derived from the CloudFront domain | Validated at startup: empty or wildcard fails fast, because a wildcard with credentials is rejected by browsers and would look configured while failing every call |

The SPA's configuration arrives two ways on purpose. Build-time variables
(`VITE_*`) carry what the bundle needs to boot: the Cognito authority. Runtime
configuration arrives from `GET /api/v1/configuration`, so values like the model
list change without a rebuild and cannot drift from the backend's allowlist.

---

## 10. Environments

One CDK app, an `ENV` input, and a suffix on every stack and resource name.

| Environment | Characteristics |
|---|---|
| `dev` | One task, smallest size, tables with on-demand billing, destroy-on-delete |
| `staging` | Production shape at minimum scale |
| `prod` | Sized from `project.toml`, retain-on-delete for data and auth stacks |

The MVP is single-environment, which is correct for an MVP and wrong for a
template. Environment support is scoped as an extension (ST-12) so v1 can ship
with one environment and the naming discipline already in place.

---

## 11. Observability

| Signal | Mechanism |
|---|---|
| Logs | Structured JSON to CloudWatch Logs, one log group per service, every line carrying the request id |
| Correlation | `X-Request-Id` accepted inbound or generated, returned on every response, exposed to the browser so it can appear in a bug report |
| Metrics | ECS Container Insights; ALB target health; CloudFront error rates |
| Traces | Not in v1. The correlation id covers the single-service case |
| Readiness | `GET /ready` reports whether the harness and the tables are reachable from inside the task — the check that distinguishes "the container is up" from "the container can do its job" |

---

## 12. Security boundaries

The boundary that matters most is what the browser is permitted to send.

| The client may send | The client may never send |
|---|---|
| Message text | A harness or gateway ARN, or a harness endpoint name |
| A session id (opaque, server-generated) | A memory id or actor id |
| A configuration id from a catalogue | An S3 skill URI |
| Override values (model id, tool ids) | An executable tool reference |
| Its app JWT | An `owner_id` |

Everything on the right is resolved server-side from something on the left. A
consumer extending the template inherits this by following the pattern; the
architecture is what makes the wrong thing awkward to build.

Other boundaries:

| Boundary | Enforcement |
|---|---|
| Public internet reaches only CloudFront | ALB is internal; the S3 bucket blocks public access and is reachable only through its origin access control |
| The task reaches only what it needs | Task role scoped to named tables, the named secret, and the named harness |
| CI reaches AWS without keys | GitHub OIDC with a trust policy scoped to one repository |
| Images are traceable | ECR immutable tags, `<sha>-<run_attempt>`; a re-run cannot overwrite a published image |

---

## 13. Architecture principles

The rules a consumer should not break without deciding to.

Single public entry point. CloudFront is the only thing on the internet.
Everything else is private, and same-origin delivery means CORS is a
development concern, not a production one.

The backend owns the capability surface. The client selects ids; only the
backend resolves them to anything executable.

Reproducible runtime snapshots. A session's configuration is validated and
frozen before first use. Later edits never reach into a running session.

Content and metadata are separate. The harness owns conversation content;
DynamoDB owns product metadata. Neither mirrors the other.

Data and identity outlive deployments. Their stacks are separate, so an
application rollback cannot reach them.

Failures are typed and quiet. Every error has a stable code and a retryable
flag. No upstream text reaches a client; the original is in the logs against the
request id.

Configuration has one source. `project.toml` for build and deploy time, the
configuration endpoint for runtime. Nothing is duplicated across layers.
