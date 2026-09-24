# AWS Fullstack Template — Technical Proposal

Planning deliverable for [BLEND360/blendx-core#1144](https://github.com/BLEND360/blendx-core/issues/1144)
— "Plan AWS fullstack template accelerator (app + DB + harness integration)".

Companion documents:
- [00-proposal-overview.md](00-proposal-overview.md) — the one-page summary of this document
- [02-architecture-model.md](02-architecture-model.md) — the full architecture model
- [03-subtickets.md](03-subtickets.md) — the scoped sub-ticket breakdown
- [05-architecture-standard.md](05-architecture-standard.md) — the architecture pattern and the rules a consumer inherits

Status: draft for review · Date: September 2026

---

## 1. Purpose

BlendX 2.0's AWS vertical has no reusable fullstack scaffold. Every new AWS app
re-solves the same problems before writing a line of product code: private
ingress, IAM, container build and publish, keyless CI/CD, SSO, and — for any app
with an agent in it — the non-trivial mechanics of streaming a harness response
to a browser.

This proposal defines `blendx-fullstack-aws-template`: a single repository a
team clones to get a deployed, authenticated fullstack application whose
business logic calls an AgentCore harness. It plays the role that
`blendx-fullstack-app-template` plays for Snowflake/SPCS, adapted to AWS.

### In scope

- Frontend, backend, and database layers as a working, deployable application
- A documented harness integration layer: how custom business logic invokes a
  harness and streams the result to the client
- A minimal, working starter harness — a model plus managed memory, no tools —
  so a clone has an agent responding on day one (see §2.1)
- Infrastructure as code for everything the application needs
- Keyless CI/CD from first push
- A one-command parametrization step so the clone becomes the team's project

### Out of scope

- The rest of the AgentCore surface: gateways, MCP tool runtimes, knowledge
  bases, evaluations, and scheduled execution (see §2.1)
- Relational database support (see §2.2)
- Multi-tenant or shared-workspace models
- Custom domains, WAF, and autoscaling policies (§10)

---

## 2. Decisions taken

Three scope questions were resolved before this document was written. They set
the size of the whole project, so they are recorded here with their consequences.

### 2.1 The application consumes a harness, and the template ships a minimal one to consume

Two statements, and both hold at once.

The application layer treats the harness as an external dependency it calls.
The integration layer is written against an ARN, never against infrastructure it
owns, so the harness can be swapped without touching application code.

The template also provisions one minimal harness, so a clone works on day one
without borrowing someone else's.

| | Content |
|---|---|
| Application layer ships | Harness client, runtime-configuration resolver, inline-tool registry, SSE streaming contract, error taxonomy |
| Infrastructure ships | A starter harness: a model, a managed-memory declaration, and its execution role. Nothing else |
| Configuration | `harness.arn` and `harness.endpoint` in `project.toml`. Left empty, the template's own starter harness is used; set to an existing ARN, that one is used instead and the starter harness is not deployed. `endpoint` names which alias of that harness the application invokes — see §2.4 |
| Not shipped | Gateways, MCP tool runtimes, knowledge bases, skills, evaluations, schedulers |

Why a starter harness is cheap enough to include: a harness is a declarative
file. The MVP's has tools and skills attached and runs about 40 lines; stripped
to a model and managed memory it is eight.

```json
{
  "name": "my_app",
  "model": { "provider": "bedrock", "modelId": "…" },
  "executionRoleArn": "arn:…",
  "memory": { "mode": "managed" }
}
```

What is expensive in AgentCore is everything around it — in the MVP the
gateways, MCP runtimes, knowledge base, and schedulers are six CDK stacks and
five workflows, each with deploy-time context that cannot be authored before
its component exists. That is what stays out of v1 and moves to ST-13.

What this buys: the adoption flow has no "first, obtain a harness" prerequisite,
which was the main cost of excluding it. A team with a platform harness still
points at it by changing one value.

Why the distinction still matters: the integration layer must not grow a
dependency on the starter harness's shape. It resolves an ARN and an endpoint
name from configuration and nothing else, so replacing the starter harness with
a gateway-equipped one is a configuration change, not a refactor.

### 2.2 DynamoDB is the default database

The data layer is DynamoDB, provisioned by CDK in its own stack. No relational
option in the first version.

Why: it is what the MVP has proven in production, it needs no VPC data
subnets or connection pooling, and it costs nothing when idle — which matters
for a scaffold that will be cloned for prototypes.

Consequence to accept: a team needing SQL builds that layer themselves. An
Aurora Serverless v2 module is a candidate follow-up, not a v1 commitment.

### 2.3 The template is an extraction, not a migration

There is no existing 2.0 AWS repository. The template is a new repository, built
by extracting the essential, proven parts of `blendx-aws-mvp-be` and
`blendx-aws-mvp-fe` into a clean monorepo.

Extraction, not migration, has a specific meaning here: nothing is lifted with
its history or its workarounds. In particular, the MVP's `MvpAppStack` carries
pinned logical IDs and property-deletion overrides because it was migrated onto
a live CloudFormation stack. A greenfield template has no live stack to
preserve, so those constructs must not be copied. See §8.

### 2.4 The starter harness follows the platform's versions-and-aliases model

The BlendX AWS platform has since documented how it operates Harnesses, in
[Hub → Harnesses](https://share.blend360.com/blendx-living-docs/aws/blendx-20/hub/harnesses/)
(source: `blendx-aws-foundry-infra`, `hub/harnesses/`). Two properties of that
model are load-bearing for this template, and one non-goal is worth stating.

**Immutable versions, aliases as environments.** A Harness is one AWS resource.
Every deploy that changes its configuration creates a new immutable version;
STAGING and PROD are *endpoints* (aliases) on that one resource, each pinned to
a version. Promotion repoints an alias — it never redeploys. This is the Lambda
versions/aliases model applied to AgentCore.

The consequence for this template is the configuration contract. A bare ARN
identifies the resource but not the version being served, which is exactly the
ambiguity the alias primitive exists to remove. So `project.toml` carries both:

```toml
[harness]
arn      = ""       # empty → deploy and use the starter harness
endpoint = "PROD"   # which alias to invoke when arn names a platform harness
```

The starter harness path is unaffected in practice — the template creates its
own STAGING/PROD endpoints on the harness it deploys — but the integration layer
resolves *(arn, endpoint)* rather than an ARN, so pointing at a platform harness
stays a configuration change (§2.1) instead of becoming a code change the first
time a consumer needs staging.

**The `agentcore` CLI is the deployment path, not our own CDK app.** The
platform deploys Harnesses with `agentcore validate` / `agentcore deploy` over
the CDK app that `@aws/agentcore-cdk` generates, in a fixed layout:

```
harness/
├── agentcore/
│   ├── agentcore.json     # project config; `harnesses` array points at app/
│   ├── aws-targets.json   # account + region
│   └── cdk/               # @aws/agentcore-cdk app, Jest test included
└── app/<name>/
    └── harness.json       # model + managed memory
```

The MVP already has exactly this shape at
`blendx-aws-mvp-be/agentcore/project_assistant_harness/`. ST-15 previously left
"CLI or our own CDK stack" open; the platform convention settles it. Expressing
the harness directly in the template's CDK app would save one toolchain and cost
the ability to ever promote a template-born harness into the Hub without
rebuilding it. The naming rules come along for free and should be adopted
verbatim: stack `AgentCore-<agentcore.json name>-<target>`, outputs
`Harness<PascalName>{Id,Arn,Status,Version,AgentRuntimeArn}`, catalog id
`harness_<name>`.

**Non-goal: the Hub catalog.** The platform tracks Harnesses in two Postgres
tables written today by direct SQL through an SSM tunnel with master
credentials. A cloned template cannot and should not do that, so harnesses born
from this template are not registered in the Hub. The platform's own
documentation records a write API in `blendx-aws-foundry-be` as the intended
replacement; that is the future integration point. See §11 item 6.

---

## 3. Repository shape: one monorepo

The MVP is two repositories, and they are coupled in a way that is invisible
from either side. The backend's app stack creates the frontend's S3 bucket and
CloudFront distribution; the frontend's deploy workflow reads
`FrontendBucketName` and `CloudFrontDistributionId` from the backend's
CloudFormation outputs. The frontend repository contains no infrastructure and
cannot deploy unless the backend stack already exists.

The template is one repository. The coupling is real, so it should be visible.

```
blendx-fullstack-aws-template/
├── project.toml                  # single parameter source (§4)
├── backend/                      # one folder per service
│   └── api/                      # FastAPI service
│       ├── app/
│       │   ├── core/             # config, logging, errors, middleware
│       │   ├── routers/          # HTTP layer only
│       │   ├── services/         # business logic
│       │   ├── clients/          # AWS and harness clients
│       │   ├── repositories/     # DynamoDB access
│       │   ├── harness/          # the integration layer (§7)
│       │   └── tools/            # inline tool registry
│       ├── tests/
│       └── Dockerfile
├── frontend/                     # one folder per app
│   └── web/                      # Vite + React SPA
│       ├── src/{api,auth,pages,components,tokens}/
│       └── vite.config.ts        # dev proxy — see §6.2
├── harness/                      # the starter harness (§2.1, §2.4)
│   ├── agentcore/                # agentcore.json, aws-targets.json, cdk/
│   └── app/assistant/
│       └── harness.json          # model + managed memory. ~8 lines
├── infra/                        # CDK (Python), one app
│   ├── app.py
│   ├── config.py                 # reads project.toml, derives every name
│   ├── specs/                    # dataclasses: RoleSpec, TableSpec, ...
│   ├── definitions/              # the data: roles.py, tables.py, ...
│   ├── stacks/                   # roles, auth, data, harness, app
│   └── tests/
├── scripts/
│   ├── setup.py                  # parametrize the clone, then self-delete
│   └── bootstrap.py              # one-time account setup (§9)
├── .github/workflows/            # ci.yml, deploy.yml
└── docs/
```

`backend/` and `frontend/` sit at the same level, and each holds one folder per
deployable unit rather than a single service. The template ships one of each —
`backend/api` and `frontend/web` — so v1 has exactly the same surface either
way. What the shape buys is that the second service does not force a
reorganization: a worker, a second API, or an admin UI is a new sibling folder,
with its own Dockerfile or build, and nothing above it moves.

Independent deploys are preserved through path filters in the workflows, not
through repository boundaries. A change under `frontend/web/` publishes the SPA
and invalidates the CDN; it does not rebuild the container image.

### Why not two repos, or a container-per-app monorepo

Two repos reproduce the MVP's hidden dependency. A third option — give the
frontend its own stack so the repos decouple — costs a second CloudFront
distribution and a second origin configuration, and gains nothing: the two
layers are deployed by the same team, for the same product, at the same time.

---

## 4. Single parameter source

The MVP has the same literal values written in several places. `ALLOWED_MODEL_IDS`
appears in [infra/app.py](../../infra/app.py),
[app/core/config.py](../../app/core/config.py), and the frontend's
`runConfig.ts`, each with a comment warning that the three must agree. Project
name, account id, table names, and the Cognito pool id are similarly scattered.

The template has one file:

```toml
[project]
name        = "analytics-portal"
aws_account = "123456789012"
aws_region  = "us-east-1"
github_org  = "BLEND360"

[harness]
# Leave empty to deploy and use the template's starter harness.
# Set to an existing harness ARN to consume that one instead; the starter
# harness is then not deployed.
arn         = ""
endpoint    = "PROD"    # which alias of that harness to invoke — see §2.4
model_id    = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"   # starter harness
model_ids   = ["us.anthropic.claude-sonnet-4-5-20250929-v1:0"]  # backend allowlist

[environments.dev]
desired_count = 1
cpu           = 256
memory        = 512

[environments.prod]
desired_count = 2
cpu           = 512
memory        = 1024
```

`infra/config.py` reads it and derives every resource name: stacks, ECR
repository, cluster, service, tables, roles, bucket. `scripts/setup.py` reads it
to write the two `.env` files. CI reads it to export the SPA's build-time
variables.

The model list is not duplicated into the frontend. The SPA requests it from a
configuration endpoint, which the MVP already has
([app/routers/configuration.py](../../app/routers/configuration.py)).

---

## 5. Stack selection

| Layer | Choice | Rationale |
|---|---|---|
| Backend | Python 3.12, FastAPI, `uv` | Proven in the MVP; native async is a prerequisite for streaming a harness response; `uv` gives a locked, fast, reproducible build |
| Frontend | Vite, React 18, TypeScript, Ant Design via Blend Design System | Proven in the MVP; the design system is already built against Ant Design |
| Streaming client | `@microsoft/fetch-event-source` | Native `EventSource` cannot send a POST body or an `Authorization` header |
| Database | DynamoDB | §2.2 |
| Compute | ECS Fargate | No servers to patch; the container is the unit of deploy; ECS Exec gives shell access to a private task without a VPN |
| Ingress | CloudFront | One public entry point for both SPA and API, so production is same-origin and needs no CORS |
| IaC | AWS CDK (Python) | Same language as the backend, so one toolchain; the MVP's declarative spec pattern depends on real code, not templates |
| Harness toolchain | `agentcore` CLI over `@aws/agentcore-cdk` | The exception to the one-toolchain rule, and a deliberate one: it is the platform's convention, and matching it is what keeps a template-born harness promotable to the Hub (§2.4) |
| Identity | Cognito, optional SAML federation | Federation to a corporate IdP is the common Blend case; Cognito groups keep access control inside AWS |
| CI/CD | GitHub Actions with OIDC | No long-lived AWS keys anywhere |

---

## 6. Deployment model

### 6.1 Topology

CloudFront is the only public entry point. It serves the SPA from a private S3
bucket through an origin access control, and forwards API paths to an internal
ALB through a VPC origin. Neither the bucket nor the load balancer is reachable
from the internet.

```
                        ┌──────────────┐
                        │   Browser    │
                        └──────┬───────┘
                               │ HTTPS
                        ┌──────▼───────────────────────────┐
                        │        CloudFront                │
                        │  behavior routing, no CORS       │
                        └──┬────────────────────────────┬──┘
                    /*     │                            │  /api/*  /auth/*  /health
              (cached)     │                            │  (uncached, all methods)
                 ┌─────────▼────────┐        ┌──────────▼─────────┐
                 │  S3 (private)    │        │  ALB (internal)    │
                 │  OAC, no public  │        │  SG: CloudFront    │
                 │  access          │        │  prefix list only  │
                 └──────────────────┘        └──────────┬─────────┘
                                                        │ :8000
                                             ┌──────────▼─────────┐
                                             │  Fargate task      │
                                             │  FastAPI           │
                                             └──────────┬─────────┘
                        ┌───────────────────────────────┼──────────────────┐
                        │                               │                  │
                 ┌──────▼───────┐            ┌──────────▼───────┐  ┌───────▼────────┐
                 │  DynamoDB    │            │  Secrets Manager │  │  AgentCore     │
                 │  (own stack) │            │  (app JWT key)   │  │  Harness       │
                 └──────────────┘            └──────────────────┘  │  + managed mem │
                                                                   │  (own stack)   │
                                                                   └────────────────┘
```

The harness has its own stack and its own lifecycle. At runtime the application
reaches it by ARN and endpoint name, like any other upstream dependency, which
is what makes it replaceable — see §2.1 and §2.4.

### 6.2 No reverse-proxy container

The Snowflake template runs an Nginx container on port 8000 to route `/api/*` to
the backend and `/*` to the frontend. On AWS that job belongs to CloudFront
behaviors, which cost nothing in container CPU and add a CDN for free. The
template ships no proxy container.

Local development reproduces the same routing with Vite's dev proxy:

```ts
server: { proxy: { "/api": "http://localhost:8000", "/auth": "http://localhost:8000" } }
```

This matters beyond convenience. With the proxy, dev and production route
identically and the SPA never needs an API base URL, so CORS configuration
disappears from the template entirely. The MVP instead points the SPA at
`http://localhost:8000` in development, which forces a CORS allowlist to exist
and be kept correct.

### 6.3 One deploy path

A push to the default branch runs one ordered pipeline. The MVP learned this the
hard way: independent path-triggered workflows fired in parallel on the same
merge, and the container image could go live before its task role had the
DynamoDB grants it needed.

```
push → test (api, web, infra)
     → deploy roles      (IAM must exist before anything references it)
     → deploy auth       (Cognito ids feed the API task and the SPA build)
     → deploy data       (tables must exist before the API points at them)
     → deploy harness    (skipped when project.toml names an existing ARN)
     → build + push image to ECR (immutable tag: <sha>-<run_attempt>)
     → deploy app stack  (ECS service, ALB, S3, CloudFront)
     → publish SPA to S3 + invalidate CloudFront
     → smoke test through the public URL
```

The harness step runs `agentcore deploy` (§2.4), which creates a new immutable
version, then points the template's endpoint at it. With one environment this
is indistinguishable from a redeploy and the simpler reading is fine. It stops
being fine the moment the template grows a second environment: the platform's
rule is that promotion repoints an alias at a version already validated
elsewhere, never redeploys. ST-12 inherits that rule rather than inventing one.

---

## 7. Harness integration approach

This is the core deliverable of #1144 and the part of the MVP most worth
extracting. It is not a thin wrapper: in the MVP it is roughly 1,200 lines
across four files.

| MVP source | Lines | Responsibility |
|---|---|---|
| [app/clients/harness_client.py](../../app/clients/harness_client.py) | 712 | Invoke and stream, bridge the blocking SDK iterator into async, dispatch inline tool calls, strip provider protocol sentinels from text deltas, page conversation events, classify AWS errors |
| [app/services/chat_service.py](../../app/services/chat_service.py) | 222 | Orchestrate one turn, emit the SSE chunk sequence |
| [app/services/session_runtime_service.py](../../app/services/session_runtime_service.py) | 204 | Resolve and freeze a session's runtime configuration |
| [app/tools/harness.py](../../app/tools/harness.py) | 95 | Inline tool registry and dispatch |

### 7.1 How custom business logic invokes the harness

```
  POST /api/v1/sessions/{id}/messages
  body: { "message": "..." }            ← the only thing the browser sends
        │
        ▼
  ┌───────────────────────────────────────────────────────────┐
  │ 1. authorize        session belongs to the caller?         │
  │                     404 for both missing and foreign       │
  ├───────────────────────────────────────────────────────────┤
  │ 2. load snapshot    frozen runtime config from DynamoDB:   │
  │                     model, tool refs, system prompt,       │
  │                     private memory reference               │
  ├───────────────────────────────────────────────────────────┤
  │ 3. invoke           harness client, streaming              │
  │                     ┌──────────────────────────────────┐  │
  │                     │ blocking SDK iterator            │  │
  │                     │   → worker thread → queue        │  │
  │                     │   → async generator              │  │
  │                     └──────────────────────────────────┘  │
  ├───────────────────────────────────────────────────────────┤
  │ 4. tool callbacks   harness asks for an inline tool →      │
  │                     dispatch to a local Python function →  │
  │                     return the result → stream resumes     │
  ├───────────────────────────────────────────────────────────┤
  │ 5. emit             SSE chunks to the client:              │
  │                     delta · tool_started · tool_input ·    │
  │                     tool_finished · done · error           │
  └───────────────────────────────────────────────────────────┘
```

The streaming chunk vocabulary is the template's contract between backend and
frontend. It is specified in
[02-architecture-model.md §6.2](02-architecture-model.md).

### 7.2 The three rules the integration layer enforces

Backend-controlled capability surface. The browser may send a message, a
template id, a tool registry id, and override values. It may never send an ARN,
an S3 skill URI, a memory coordinate, or an executable tool reference. Only the
backend resolves an id to something executable.

Frozen runtime snapshots. A session captures its resolved configuration —
validated model, resolved tool references, system prompt — before the first
invocation. Editing the source template afterwards cannot change a running
session or the value restored when an override is cleared.

No upstream text reaches the client. A botocore error message names the task
role, the account, and the resource. The error layer maps it to a fixed sentence
with a stable code shaped `<dependency>_<category>` plus a `retryable` flag, and
logs the original against the request id. A failure mid-stream arrives as a
terminal SSE `error` chunk carrying the same code, because by then there is no
status code left to set.

### 7.3 What the template ships as the integration layer

- `app/harness/client.py` — invoke a resolved *(ARN, endpoint)* pair, stream,
  event paging, error classification
- `app/harness/runtime.py` — resolve, validate, and freeze a session's config
- `app/harness/streaming.py` — the SSE chunk emitter and its typed vocabulary
- `app/tools/` — the inline tool registry plus one worked example tool
- `frontend/web/src/api/chat.ts` — the matching client-side stream consumer
- A written guide: how to add a tool, how to add a chunk type, what never
  crosses the boundary

---

## 8. Extraction plan: what comes from the MVP

| Asset | Action | Note |
|---|---|---|
| Backend layering (`core`, `routers`, `services`, `clients`, `repositories`) | Extract | Thin routers, logic in services — keep the rule, drop the domain |
| Structured logging, correlation id middleware, error taxonomy | Extract as-is | Generic and complete |
| Harness client, runtime resolver, tool registry, SSE contract | Extract and generalize | §7 — the core |
| Session repository and table design | Extract | Product metadata only; the harness owns conversation content |
| Declarative infra pattern (`spec` + `definitions` + generic stack) | Extract | Adding a role or a table stays a data change |
| CloudFront + internal ALB + Fargate topology | Rebuild from the pattern | Do not copy the stack file — see below |
| GitHub OIDC trust policy construction | Extract | Includes the subject-claim customization this org requires |
| Immutable ECR tagging, ordered deploy chain | Extract | |
| Deployment validator (static and live checks) | Extract, generalized | Extension — ST-11 |
| Prompt-template domain (templates table, Baseline partition) | Drop | Product-specific to the MVP |
| Harness definition (`harness.json`, execution role, deploy workflow) | Extract, stripped to minimum | §2.1 — model plus managed memory, no tools or skills. The MVP's `agentcore/project_assistant_harness/` layout is also the platform's, so it is extracted as-is rather than reshaped — §2.4 |
| AgentCore gateways, MCP runtimes, knowledge bases, schedulers | Drop from v1 | §2.1 — optional module, ST-13 |
| Pinned logical IDs, `SecurityGroupEgress` deletion overrides, `OriginSSLProtocols` removal | Drop | See below |
| Hand-configured Cognito | Rebuild in CDK | The MVP's pool was created in the console; ids are documented, not coded |

### Why the migration workarounds must not be copied

`MvpAppStack` overrides the logical id of every resource and deletes two
properties from the rendered template. Each of those exists for a specific
reason documented in the MVP, and every reason is "there is a live
CloudFormation stack whose resources must be matched byte-for-byte." A
greenfield template creates its stack fresh. Copying the overrides would carry
forward constraints with no cause, and the next engineer would have no way to
tell which are load-bearing.

The template's `AppStack` uses CDK defaults. The MVP's rationale stays in the
MVP, where it is true.

---

## 9. Developer adoption flow

```
1  gh repo create my-app --template BLEND360/blendx-fullstack-aws-template
2  edit project.toml            # name, account, region
3  python scripts/setup.py      # renames resources, writes .env files, self-deletes
4  python scripts/bootstrap.py  # ONE TIME per AWS account
5  git push origin main         # full deploy, starter harness included
```

There is no step that says "obtain a harness". Step 5 deploys one.

Step 4 exists to resolve a bootstrap ordering problem the MVP documents in prose:
the GitHub OIDC deploy role is created by the same CDK app that needs that role
in order to run. The MVP's answer is "an engineer runs `cdk deploy` locally once."
In the template that is a script: it runs `cdk bootstrap`, creates the OIDC
provider and the roles stack with the operator's own credentials, then prints the
repository variables to set. It is idempotent and safe to re-run.

---

## 10. Deferred

Not in v1, and each one is a candidate follow-up rather than an oversight:

| Item | Why deferred |
|---|---|
| Custom domain and ACM certificate | Needs a DNS decision per project; `*.cloudfront.net` works out of the box |
| WAF on CloudFront | Cost per project; add when a template consumer is public-facing |
| ECS service autoscaling | Needs real load characteristics to set targets |
| Relational database module | §2.2 |
| Harness tools: gateways, MCP runtimes, knowledge bases, skills | §2.1 — the starter harness has no tools; ST-13 adds the surface that gives it some |
| Scheduled agent execution | §2.1 — needs the same AgentCore surface as above |
| Backend re-check of Cognito group membership | The MVP's pre-token Lambda is the only access gate and is documented as a single point of failure; worth fixing, but it is an auth-design change, not scaffolding |
| Harness rollback | §2.4 — repointing an endpoint at an earlier version is the platform's rollback, and `blendx-aws-foundry-infra` already ships the scripts (`point-harness-alias.sh`, `wait-harness-ready.sh`). Adopting the alias contract now is what makes this a later wiring job rather than a later redesign; with one environment there is nothing yet to roll back to |

---

## 11. Open decisions and risks

| # | Item | Impact | Proposed resolution |
|---|---|---|---|
| ~~1~~ | ~~Which harness does a new project point at?~~ | — | RESOLVED: the template deploys its own starter harness, with `harness.arn` and `harness.endpoint` in `project.toml` as the override for pointing at an existing one. See §2.1 and §2.4 |
| 2 | Does the template assume an existing VPC, or create one? | The MVP references an existing VPC and subnets by id. A team with no VPC cannot deploy | Create a minimal VPC in the template by default, with an override to use an existing one |
| 3 | Is SAML federation on by default? | A project without a corporate IdP does not need it; one with it should not wire it by hand | Cognito native users by default; SAML behind a flag in `project.toml`, driven by a metadata file |
| 4 | Where does the template live, and how is it versioned? | Consumers will want fixes after cloning, and a GitHub template repo gives no upgrade path | Accept that v1 has no upgrade path; track the question for v2 |
| 5 | Does the SPA's Blend Design System dependency belong in a template? | It couples the template to an internal package | Keep it — every consumer is a Blend team — but isolate it to `src/tokens/` so it can be swapped |
| 6 | Do template-born harnesses belong in the Hub catalog? | The platform's catalog is the org-wide view of what harnesses exist; harnesses created by clones are invisible in it | v1 does not register. Writes are direct SQL through a bastion today (§2.4), which a clone must not do. Revisit when `blendx-aws-foundry-be` exposes the write API the platform has already scoped |
| 7 | Does `setup.py` derive resource names using the platform's convention? | Registering a template-born harness in the Hub later is one matrix entry if the names already match, and a rename of live resources if they do not | Adopt the convention verbatim (§2.4). The cost is a naming rule in `setup.py`; the cost of not doing it is paid by whoever graduates the first harness |

Item 2 blocks writing the adoption guide. The rest can be settled during
implementation.
