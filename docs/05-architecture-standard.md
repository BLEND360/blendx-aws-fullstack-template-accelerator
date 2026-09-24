# AWS Fullstack Template — Architecture Standard

The pattern the template follows, why it is that one, and how a consuming team
extends it without leaving the path.

Companion documents:
- [00-proposal-overview.md](00-proposal-overview.md) — the one-page summary
- [01-technical-proposal.md](01-technical-proposal.md) — scope, decisions, and approach
- [02-architecture-model.md](02-architecture-model.md) — the architecture model this document names

Status: draft for review · Date: September 2026

---

## 1. Why this document exists

[02-architecture-model.md](02-architecture-model.md) describes what the template
builds. It does not name the pattern, and an unnamed pattern cannot be taught,
reviewed, or defended. A team that cannot name the rule they are following will
drift off it in the first sprint after cloning.

This document names it, so that a code review can say "this breaks the port
rule" instead of "this feels wrong".

---

## 2. The pattern, in one sentence

A modular monolith per environment, ports and adapters inside each service,
delivered as a golden path.

Three choices, each answering a different question:

| Question | Answer | Consequence |
|---|---|---|
| How is it deployed? | Modular monolith — one container, folders that could become containers | A two-person team ships without operating a distributed system, and extraction stays available |
| How is it structured inside? | Ports and adapters (hexagonal) | Business logic never imports AWS; the agent runtime is swappable and testable without credentials |
| How is it adopted? | Golden path — template plus guardrails plus CI gates | The standard is executable, not documentation nobody reads |

The first two are well-known patterns; the third is the one that decides whether
the other two survive contact with a real project.

---

## 3. Why not the alternatives

Each of these is a reasonable pattern that is wrong for this template. Recorded
with the condition that would make it right, so a consumer knows when to
graduate.

| Pattern | Why not for v1 | Adopt when |
|---|---|---|
| Microservices | A team of two would run five deploy pipelines to serve one product. The MVP's single service has never been the bottleneck | A module needs its own scaling profile, runtime, or release cadence |
| Clean Architecture, full four rings | Use-case classes and a DTO at every boundary triple the file count for a CRUD route. Consumers delete the ceremony and keep the mess | Never, at this size. The dependency rule is the valuable part and hexagonal already gives it |
| DDD tactical patterns — aggregates, value objects, domain events | The template has no domain. A scaffold that ships `SessionAggregate` teaches a shape the consumer's actual domain will not fit | The consumer's product has real invariants across entities. That is their decision, not the template's |
| CQRS and event sourcing | Two models and a projection pipeline to serve a session list. The read and write loads are identical | Reads and writes diverge by an order of magnitude, or an audit log is a hard requirement |
| Message bus between layers | Indirection with no subscriber. A queue whose only consumer is the next function is a function call with extra failure modes | A turn must survive the request that started it — background jobs, scheduled agents (ST-13) |
| Vertical slices only, no layers | Works, and better than layers past a certain size. But it moves the AWS boundary into every slice, and the boundary is the thing this template is protecting | A layer folder passes roughly ten modules. See §7 |

The pattern here is not "the most sophisticated one available". It is the
cheapest one that still makes the wrong thing awkward to build.

---

## 4. The patterns already in the model, named

Most of the work is done. [02-architecture-model.md](02-architecture-model.md)
already specifies these; naming them makes them teachable.

| In the model | The pattern | What it buys |
|---|---|---|
| `routers` → `services` → `repositories`/`clients`, with routers barred from boto3 and services from FastAPI (§4.1) | Dependency rule, hexagonal | Business logic is testable with no HTTP and no AWS |
| `app/harness/` translating AgentCore errors and protocol sentinels into app types (§6, §4.3) | Anti-corruption layer | AgentCore's shape changing is a one-file change |
| The harness reached by *(ARN, endpoint)* from configuration (§8.1) | Dependency inversion at the infrastructure boundary | "Bring your own harness" is a config change, not a refactor |
| `app/tools/registry.py` — schemas plus a dispatch table (§6.4) | Plugin registry | One extension point for agent capability. Two lines per tool |
| `resolved_config` frozen at session creation (§6.5) | Immutable snapshot | A config edit cannot reach into a running session |
| The SSE chunk vocabulary, pinned by tests on both sides (§6.2) | Published contract | Backend and frontend cannot drift silently |
| `specs/` + `definitions/` + a generic stack (§8.2) | Configuration as data | A role or table is a list entry, not stack code |
| One stack per lifetime — roles, auth, data, harness, app (§8.1) | Separation by rate of change | An app rollback cannot delete user data |

Eight named patterns, zero new folders. That is the point of this section.

---

## 5. What the standard is missing

Two gaps, both cheap, both load-bearing for a template that will be cloned by
people who never read this document.

### 5.1 The ports are implied, not declared

The dependency rule exists as prose and a test. It should exist as a type. One
`Protocol` per outbound dependency, in the layer that owns the need:

```python
# backend/api/app/harness/port.py
class HarnessPort(Protocol):
    def stream(self, cfg: ResolvedConfig, memory: MemoryRef,
               message: str) -> AsyncIterator[Chunk]: ...
```

Two implementations ship: the AgentCore adapter, and a fake that replays a
recorded stream fixture.

The fake is the one that matters. Without it, every test of a service, every
frontend integration test, and every contributor's first hour needs AWS
credentials and a deployed harness. With it, the whole turn sequence — deltas,
a tool call, an error chunk — runs offline in milliseconds.

Repositories do not need a hand-written fake. `moto` covers DynamoDB and is
already a standard Python AWS test dependency. There is no `moto` for AgentCore
streaming, which is exactly why the harness port gets one and the tables do not.

### 5.2 The rules are not enforced by anything that fails a build

A standard that only lives in a document is a preference. The enforcement is a
configuration file, not code:

```ini
# .importlinter
[importlinter:contract:layers]
name    = Backend layering
type    = layers
layers  = app.routers
          app.services
          app.repositories | app.clients | app.harness
          app.core
```

`lint-imports` in CI. Roughly fifteen lines, and it catches the exact drift that
turns a clean scaffold into the codebase everyone complains about at month six:
a router that reaches for a table because the service layer felt like ceremony.

This is the fitness-function idea from evolutionary architecture, at the only
scale worth paying for: one contract, one CI step.

---

## 6. How a consumer extends it

The architecture is defined by its extension points. Every routine change should
be an entry in a list, not a new pattern. If a consumer has to invent a shape,
the template failed.

| To do this | Change this | Never touch |
|---|---|---|
| Add an endpoint | `routers/x.py`, `services/x.py`, a test | `harness/` |
| Give the agent a capability | `tools/x.py` plus two lines in `tools/registry.py` | `harness/client.py` |
| Add a table | one entry in `infra/definitions/tables.py`, one `repositories/x.py` | `infra/stacks/` |
| Grant a permission | one entry in `infra/definitions/roles.py` | `infra/stacks/` |
| Change the model | `project.toml` | any code |
| Use an existing harness | `harness.arn` and `harness.endpoint` in `project.toml` | any code |
| Add a second service | a sibling folder under `backend/`, plus a path filter | the existing service |
| Add a second UI | a sibling folder under `frontend/`, plus a path filter | the existing app |

Eight routine changes. Six are a list entry or a config value. That ratio is the
measurable form of "it has foundations".

---

## 7. When to leave the path

A standard that never allows growth gets abandoned rather than extended. Each
exit below is legitimate, with the signal that justifies it.

| Signal | Move to | Note |
|---|---|---|
| A layer folder passes roughly ten modules | Feature modules inside the same layering: `app/features/<name>/{router,service,repository}.py` | The dependency rule and the import contract carry over unchanged |
| A module needs its own scaling profile, runtime, or team | Its own folder under `backend/`, its own task definition | The folder shape exists so this is a move, not a rewrite |
| A tool must be shared across apps, or is not Python | An AgentCore gateway or MCP runtime | Already scoped as ST-13. The inline registry stays for app-local tools |
| A turn must outlive its request | A queue and a worker | The first legitimate use of a message bus here |
| Access patterns need joins | Add a relational store next to DynamoDB | The repository port is the seam; services do not change |

The rule for all five: leave the path deliberately, in a pull request that says
which signal fired. Drifting off it silently is the failure this document is
written to prevent.

---

## 8. The standard, as a checklist

What a reviewer checks. Seven lines, and the first four are machine-checkable.

- [ ] A router imports no boto3 and knows no table name
- [ ] A service imports nothing from `fastapi` and nothing from `boto3`
- [ ] Every outbound dependency is reached through a declared port
- [ ] The backend test suite passes with no AWS credentials present
- [ ] A new agent capability is a registry entry, not a change to the harness client
- [ ] A new AWS resource is a definitions entry, not a change to a stack
- [ ] No value that lives in `project.toml` is written literally anywhere else

---

Sources consulted for the pattern survey:
[Hexagonal architecture](https://en.wikipedia.org/wiki/Hexagonal_architecture_(software)) ·
[Ports and adapters, Garrido Paz](https://jmgarridopaz.github.io/content/hexagonalarchitecture.html) ·
[Hexagonal architecture in AI agent development](https://medium.com/@martia_es/applying-hexagonal-architecture-in-ai-agent-development-44199f6136d3) ·
[Golden paths for engineering consistency, Google Cloud](https://cloud.google.com/blog/products/application-development/golden-paths-for-engineering-execution-consistency) ·
[What is a golden path, Red Hat](https://www.redhat.com/en/topics/platform-engineering/golden-paths)
