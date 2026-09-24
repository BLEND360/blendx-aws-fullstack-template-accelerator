# AWS Fullstack Template — Diagrams

Lucidchart-ready diagram sources for
[BLEND360/blendx-core#1144](https://github.com/BLEND360/blendx-core/issues/1144),
acceptance criterion 1: "Architecture doc/diagram covering frontend, backend,
database, and harness-integration layers".

Companion documents:
- [00-proposal-overview.md](00-proposal-overview.md) — the one-page summary
- [01-technical-proposal.md](01-technical-proposal.md) — scope, decisions, approach
- [02-architecture-model.md](02-architecture-model.md) — the model these diagrams draw
- [03-subtickets.md](03-subtickets.md) — the sub-ticket breakdown
- [05-architecture-standard.md](05-architecture-standard.md) — the pattern these diagrams draw

---

## The diagrams

One overview for socializing the proposal, then four technical views — because
the layers relate to each other in several different ways and one picture cannot
carry them all without becoming unreadable.

| File | View | Answers |
|---|---|---|
| [diagrams/00-overview.mmd](diagrams/00-overview.mmd) | High level, no component detail | What a team gets when they clone, on one screen |
| [diagrams/01-system-layers.mmd](diagrams/01-system-layers.mmd) | Runtime, all five layers with their internal components | Who calls whom, and what each layer is made of |
| [diagrams/02-iac-ownership.mmd](diagrams/02-iac-ownership.mmd) | Deploy time, CDK stack ownership | Who creates what, in what order, and where each name comes from |
| [diagrams/03-turn-sequence.mmd](diagrams/03-turn-sequence.mmd) | One streamed agent turn | How a single request crosses every layer |
| [diagrams/04-aws-components.xml](diagrams/04-aws-components.xml) | Deployed AWS services with official icons, account and VPC boundaries | Which AWS services exist, where they sit, what talks to what |

Use 00 with anyone who is not going to build it; it is embedded in
[00-proposal-overview.md](00-proposal-overview.md) and deliberately hides every
component. Start with 01 for the architecture review. Use 03 when explaining the
harness integration layer specifically — it is the path that touches everything,
so it is the most convincing single picture of how the layers cooperate. Use 04
with anyone who thinks in AWS services rather than application layers — a cloud
architect, a security review, a cost conversation.

---

## Why 04 is not Mermaid

Mermaid has no AWS icons — it imports as boxes. Diagram 04 is the icon diagram,
so it is authored as draw.io XML using the official AWS shape set
(`mxgraph.aws4.*`), which is the same icon library Lucidchart ships as
**AWS 2025**. It keeps the AWS service colors rather than the Blend palette,
because AWS icons are iconography, not brand fill; the group boundaries and the
non-AWS shapes stay Blend.

**This file is imported, not pasted.** It is draw.io XML, not Mermaid — pasting
it into Lucidchart's *Diagram as code* panel returns "No diagram type detected",
because that panel only parses Mermaid. It is also why the file is named `.xml`
rather than `.drawio`: Lucidchart's file picker filters on the extension.

Import path: Lucidchart documents page → **Import** → **draw.io** → pick
`04-aws-components.xml`. The same option exists inside a document under
`File → Import Diagram`.

Fallback if the draw.io importer is not on the plan: open the file at
[app.diagrams.net](https://app.diagrams.net) (`File → Open from → Device`),
export as SVG, and import the SVG into Lucidchart. Icons survive as editable
vector shapes.

To edit the diagram, open it in draw.io (or the draw.io VS Code extension) and
save over the same file. Do not redraw it in Lucidchart only: a Lucidchart edit
that is not in the `.xml` is lost on the next import.

One thing to expect after importing into Lucidchart: the three agent-platform
shapes arrive as flat teal squares with no glyph. `mxgraph.aws4.bedrock` is a
valid draw.io stencil — it renders correctly there — but Lucidchart's AWS stencil
set predates Bedrock, and its importer draws an unknown stencil as a blank
colored square. Fix it in Lucidchart by dragging **Amazon Bedrock** from the
AWS 2025 shape panel onto the three placeholders; everything else imports with
its icon.

A blank colored square is also what a wrong stencil name looks like. If one
appears where it should not, check the name against the live list in
[drawio's Sidebar-AWS4.js](https://github.com/jgraph/drawio/blob/dev/src/main/webapp/js/diagramly/sidebar/Sidebar-AWS4.js)
— the short names are not guessable (`mxgraph.aws4.ecs`, not
`elastic_container_service`).

---

## Importing into Lucidchart

Primary path: `File → Import Diagram`, choose Mermaid, paste the contents of a
`.mmd` file. Lucidchart also exposes Mermaid through its diagram-as-text panel
depending on the plan and version.

Fallback if Mermaid import is unavailable: paste the file into
[mermaid.live](https://mermaid.live), export as SVG, then import the SVG into
Lucidchart. The result is editable shapes rather than a flat image.

Two things to expect after import:

Layout needs manual work. Mermaid's auto-layout produces a correct graph, not a
presentable one. The subgraph boundaries and the node contents are what the
import is for; arranging them is a Lucidchart job.

Colors survive, the palette comment does not. The `classDef` lines carry the
Blend palette into the import. The comment block explaining them is stripped, so
the legend below is the reference.

---

## Legend

| Treatment | Meaning |
|---|---|
| White fill, Washed Blue border | Application code or infrastructure the template owns |
| Off White fill, Washed Blue border, cylinder shape | A durable store — S3, a DynamoDB table, managed memory |
| Off White fill, Gray border | A managed AWS service, or CI machinery |
| White fill, turquoise border, 2px | The harness integration layer, and `project.toml` — the two things that make this template different from a generic scaffold |
| Off White fill, Gray text | An annotation, not a component |
| Solid arrow | A call, or a creation relationship |
| Dotted arrow | A reference, a grant, or a value flowing as configuration |
| Thick arrow | A bootstrap-order dependency |

Palette: Washed Blue `#053057`, Dark Gray `#1a1a1a`, Off White `#f5f5f5`,
White `#ffffff`, Gray `#64748b`, Neon Turquoise `#00EDED`. Turquoise appears as
a border accent only — never as a fill and never as text.

---

## Layer inventory

For rebuilding by hand in Lucidchart, or for reviewing coverage without opening
the sources.

### L1 · Client

| Component | Responsibility |
|---|---|
| Pages and components | Views |
| AuthProvider | OIDC Authorization Code + PKCE, session state |
| ProtectedRoute | Route guard |
| apiFetch | Attaches the app JWT, parses the error shape |
| SSE consumer | `fetch-event-source`, because native `EventSource` cannot POST a body or set a header |
| React Query | Cacheable server state |
| Design tokens | Blend Design System, isolated in `src/tokens` so it can be swapped |

### L0 · Edge

| Component | Responsibility |
|---|---|
| CloudFront distribution | The only public surface |
| Behavior: default | Cached, origin is the private S3 bucket |
| Behavior: `/api/*`, `/auth/*`, `/health` | Uncached, all methods, forwards the viewer request except Host |
| Error responses | 403 and 404 from S3 rewrite to `/index.html` as 200, for client-side routing |
| S3 bucket | Private, all public access blocked, reachable only through its origin access control |
| Internal ALB | Not internet-facing; ingress from the CloudFront prefix list only |
| Security groups | A chain — ALB from CloudFront, task from ALB. Egress deliberately not declared |

### L2 · API

| Group | Components |
|---|---|
| Middleware | CORS (outermost, so its headers reach error responses), correlation id, exception handlers |
| Routers | health, auth, configuration, sessions, items |
| Services | auth_service, sessions_service, chat_service, items_service |
| Core | config, security, errors, logging |

### L3 · Data

| Component | Responsibility |
|---|---|
| session_repository | Sessions table access, optimistic concurrency on `revision` |
| item_repository | The worked example of the pattern |
| Table: sessions | `owner_id` + `session_id`; resolved config snapshot and private memory reference. No conversation content |
| Table: items | `owner_id` + `item_id`; the example domain table |

No connection string and no pool. DynamoDB is an HTTPS API and credentials come
from the ECS task role.

### L4 · Harness integration

| Component | Responsibility |
|---|---|
| runtime.py | Merge defaults with overrides, validate the model against the allowlist, resolve ids to executable references, freeze the snapshot |
| client.py | Invoke by *(ARN, endpoint)* and stream, bridge the blocking SDK iterator to an async generator, page memory events, classify AWS errors |
| streaming.py | The chunk vocabulary: `delta`, `tool_started`, `tool_input`, `tool_finished`, `done`, `error` |
| tools/registry.py | Tool schemas and the dispatch map |
| tools/example.py | One worked tool with its test |

Invariant this layer must keep: it resolves a harness ARN and endpoint name from
configuration and nothing else, so the harness stays replaceable by
configuration. The endpoint is what pins which immutable harness version is
served — see `01-technical-proposal.md` §2.4.

### Managed services and agent platform

| Component | Responsibility |
|---|---|
| Cognito | User pool, public PKCE client, hosted login, access group, pre-token Lambda gate; optional SAML provider |
| Secrets Manager | The app JWT signing key, generated by CDK and injected by ECS |
| CloudWatch Logs | Structured logs, every line carrying the request id |
| ECR | Immutable image tags, `<sha>-<run_attempt>` |
| IAM task role | Scoped to the named tables, the named secret, and the named harness |
| AgentCore Harness | Starter: a model plus managed memory, with STAGING/PROD endpoints. Replaceable via `project.toml` |
| Managed memory | Owns conversation content — messages, responses, tool interactions |
| Deferred (ST-13) | Gateways, MCP runtimes, knowledge bases, skills, schedulers |

---

## Keeping these current

The diagrams are generated from the model in
[02-architecture-model.md](02-architecture-model.md), not the other way round. A
change to the architecture goes into that document first, then into the `.mmd`
source, then into Lucidchart. A Lucidchart edit that is not reflected in the
`.mmd` file will be lost on the next import.
