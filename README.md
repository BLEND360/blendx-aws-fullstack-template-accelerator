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
infra/                # CDK app (Python), see infra/README.md
scripts/              # setup, account bootstrap, data and harness deploy
.github/workflows/    # ci, deploy
```

## Quick start

Prerequisites: [uv](https://docs.astral.sh/uv/), Node.js 22+, Docker (optional),
and for the AWS steps the AWS CLI with credentials for the target account.

### 1. Run it locally (no AWS needed)

```bash
# edit project.toml first (name, aws_account, aws_region, github_org, github_repo)
python scripts/setup.py       # validates project.toml, writes the .env files; deletes itself
docker compose up --build     # web http://localhost:5173, API http://localhost:8000/health
```

Locally the API keeps sessions and items in memory and skips sign-in
(`LOCAL_AUTH_BYPASS=true`). `/ready` reports `degraded` until you have AWS
credentials and a harness; that is expected. To chat without any harness, start
the API with recorded answers (`HARNESS_REPLAY=true`, see
[frontend/web/README.md](frontend/web/README.md#showing-it-without-aws)).

Without Docker: [backend/api/README.md](backend/api/README.md) and
[frontend/web/README.md](frontend/web/README.md). `docker compose` mounts
`~/.aws`, so that folder must exist (`mkdir ~/.aws` if you have no credentials).

### 2. Create the AWS resources

Run these from the repo root with your own AWS credentials. Every step is
idempotent.

```bash
# once per AWS account: CDK bootstrap, GitHub OIDC provider, roles stack
uv run --project infra python scripts/bootstrap.py

# DynamoDB tables (sessions, items); needed only to run with DATA_STORE=dynamodb
uv run --project infra python scripts/deploy_data.py

# starter harness (model + managed memory); skipped when harness.arn is set.
# Needs: npm i -g @aws/agentcore, AWS CLI, jq, bash
uv run --project infra python scripts/deploy_harness.py
```

`deploy_harness.py` prints `harness_arn=...` and
`harness_endpoint=...`; put them in `backend/api/.env` as `HARNESS_ARN` and
`HARNESS_ENDPOINT` (or set `harness.arn` in `project.toml` to use an existing
harness and skip the deploy). Use plain `python` for `setup.py` only: the other
scripts need boto3, which `uv run --project infra` provides.

### 3. Point the local app at AWS (optional)

Set `DATA_STORE=dynamodb` and `HARNESS_ARN` in `backend/api/.env`, keep valid
credentials in `~/.aws`, and restart. `/ready` should then report `ok`.

### Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `ModuleNotFoundError: boto3` | You ran `bootstrap.py`, `deploy_data.py` or `deploy_harness.py` with plain `python`. Use `uv run --project infra python ...` |
| "Your credentials are for account X, but project.toml says Y" | Wrong profile or `aws_account` in `project.toml`. Fix one and retry |
| `Your session has expired ... Please reauthenticate using 'aws login'` (API logs, `/ready` degraded with `data_error`) | Run `aws login` (or `aws sso login`), then restart the API |
| `OSError: [Errno 30] Read-only file system` in the container after `aws login` | `docker compose` mounts `~/.aws` read-only; credentials from `aws login` need it writable. Add a git-ignored `docker-compose.override.yml` that mounts `~/.aws` without `:ro` |
| `/ready` is `degraded` with `harness_misconfigured` | `HARNESS_ARN` is empty. Deploy the harness or use `HARNESS_REPLAY=true` |
| `/ready` is `degraded` with `data_error` on a table | Tables not deployed, or `DATA_STORE=dynamodb` with no credentials. Run `deploy_data.py` |
| `project.toml is invalid` | The message names the field; names are 3-24 lowercase letters, digits and single hyphens |
| `setup.py` says "already complete" | Both `.env` files exist; delete them to regenerate (`setup.py` removes itself after the first run) |

### Not built yet

The deployed topology in the diagram above is the target, not the current state.
Today the CDK app has the **roles** and **data** stacks only. Still to come:
network, Cognito (auth stack, ST-08), ECS/CloudFront (app stack, ST-07) and the
deploy workflow (ST-09), so `git push` runs CI but does not deploy yet.
`bootstrap.py` prints two GitHub variables to set (`AWS_DEPLOY_ROLE_ARN`,
`AWS_REGION`); they are used once the deploy workflow exists.

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
