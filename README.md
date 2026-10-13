# blendx-fullstack-aws-template

One repository a team clones to get a deployed, authenticated fullstack app on
AWS whose business logic already calls an AgentCore harness. Set four values in
`project.toml`, push, and an agent is responding on a private AWS topology.

Tracking issue: [BLEND360/blendx-core#1144](https://github.com/BLEND360/blendx-core/issues/1144).

## What you get

| | |
|---|---|
| Application | React SPA, FastAPI backend, DynamoDB |
| Agent integration | Invoke a harness, stream the answer as SSE, dispatch tools; no AWS error message ever reaches the browser |
| Starter harness | A model plus managed memory, deployed with the `agentcore` CLI. Point at an existing harness by setting `harness.arn` and `harness.endpoint` |
| Infrastructure | CDK (Python) for network, identity, data, compute, CDN |
| CI/CD | GitHub Actions with OIDC. No long-lived AWS keys |

```
CloudFront (only public entry)
 ├─ /*      → React SPA, private S3
 └─ /api/*  → FastAPI on Fargate (no public IP) → DynamoDB
                                                → AgentCore harness → managed memory
```

## Layout

```
project.toml          # the only place names, account and region are written
Dockerfile            # API image (build context: repo root)
docker-compose.yml    # run that image locally
backend/api/          # FastAPI service — add sibling services here
frontend/web/         # Vite + React SPA — add sibling UIs here
harness/              # starter harness: model + managed memory
infra/                # CDK app (Python)
scripts/              # setup, one-time account bootstrap, harness deploy
.github/workflows/    # ci, deploy
```

## Quick start

```bash
# 1. create the repo from this template, then edit project.toml (name, account, region)
python scripts/setup.py       # validates project.toml, writes the .env files
python scripts/bootstrap.py   # once per AWS account
git push                      # full deploy, agent included
```

Run the API locally:

```bash
docker compose up --build     # http://localhost:8000/health
```

Or without Docker, see [backend/api/README.md](backend/api/README.md).

## Architecture

A modular monolith per environment, ports and adapters inside each service,
delivered as a golden path: the rules below are enforced by CI, not by review.

**Backend layering** (`uv run lint-imports`, configured in `backend/api/pyproject.toml`):

```
routers → services → repositories | clients | harness → core
```

- `routers/` parse, authorize, delegate. No boto3, no table names.
- `services/` decide. No FastAPI, no boto3; outbound calls go through the
  `Protocol` ports in `services/ports.py`.
- `repositories/`, `clients/`, `harness/` are the adapters. They talk to AWS and
  translate its errors with `core.errors.classify_aws_error`.
- Errors leave the process as a fixed sentence plus a stable
  `<dependency>_<category>` code (`harness_unavailable`, `data_throttled`); the
  real cause is logged against the request id.
- The backend test suite passes with no AWS credentials.

**Infrastructure**: one stack per lifetime (roles, auth, data, harness, app), so
an app rollback cannot delete data. Resources are data: `infra/specs/` +
`infra/definitions/` + a generic stack. Every name is derived from
`project.toml` by `infra/config.py`.

**Harness**: follows the platform convention (lives at `harness/app/assistant/`,
CloudFormation outputs `Harness<Pascal>*`, immutable versions, aliases per
environment) so a template-born harness can graduate into the Hub unchanged.

### Extending it

| To do this | Change this | Never touch |
|---|---|---|
| Add an endpoint | `routers/x.py`, `services/x.py`, a test | `harness/` |
| Give the agent a tool | `tools/x.py` + two lines in `tools/registry.py` | `harness/client.py` |
| Add a table | an entry in `infra/definitions/tables.py`, a `repositories/x.py` | `infra/stacks/` |
| Grant a permission | an entry in `infra/definitions/roles.py` | `infra/stacks/` |
| Change the model / use an existing harness | `project.toml` | any code |
| Add a service or UI | a sibling folder under `backend/` or `frontend/` + a CI path filter | the existing ones |

### Out of scope for v1

Gateways, MCP tool runtimes, knowledge bases, evaluations and schedulers;
relational databases; custom domains, WAF, autoscaling.
