# Getting Started

Clone, configure and run the template locally with no AWS account. Replay mode serves recorded turns, so the whole chat works without credentials or a deployed harness.

## Prerequisites

[uv](https://docs.astral.sh/uv/), Node.js 22+, and Docker (optional). The AWS steps additionally need the AWS CLI with credentials for the target account, the `agentcore` CLI (`npm i -g @aws/agentcore`), `jq` and `bash`.

## Configure

Clone the template (or your team's repository created from it) and edit `project.toml` before anything else:

- A unique lowercase project name: 3 to 24 letters, digits and single hyphens.
- The target AWS account and region, and the GitHub organization and repository the deploy role trusts.
- The harness settings. To use an existing AgentCore harness, set `harness.arn` and `harness.endpoint`.

Do not use the sample account number and do not deploy into an account you have not verified. See [configuration](./configuration.md) for every field.

## Set up once

```bash
python scripts/setup.py
```

`setup.py` validates `project.toml`, writes `backend/api/.env` and `frontend/web/.env` (generating `AUTH_JWT_SECRET`), and then deletes itself. Treat it as one-time onboarding; start from a fresh clone to repeat it, or `git restore scripts/setup.py`. Use plain `python` for this script only: the others need boto3, which `uv run --project infra` provides.

## Run with Docker Compose in replay mode

```bash
# Bash / Git Bash
HARNESS_REPLAY=true docker compose up --build

# PowerShell
$env:HARNESS_REPLAY = "true"
docker compose up --build
```

Open http://localhost:5173. A message containing the word `tool` plays the recorded turn that calls a tool (and the tool really runs); anything else plays the recorded text turn. The web app shows a "Demo mode" notice. History survives a reload and is forgotten when the API restarts.

Compose forwards `HARNESS_REPLAY` to the API container (default `false`). If host ports 8000 or 5173 are taken, set `API_PORT` or `WEB_PORT` before starting. The API container mounts `~/.aws` read-only and forwards `AWS_PROFILE` when set; create the folder if it does not exist.

Replay is not a connectivity or deployment test: only the model's words are canned, while events, order and tool execution are the real code path.

## Run without Docker

```bash
# API at http://localhost:8000/health
cd backend/api && uv sync && uv run uvicorn app.main:app --reload

# Web at http://localhost:5173, API on :8000
cd frontend/web && npm install && npm run dev
```

Locally the API keeps sessions and items in memory and skips sign-in (`LOCAL_AUTH_BYPASS=true`). `/ready` reports `degraded` until credentials and a harness exist; that is expected.

## Point the local app at AWS (optional)

Set `DATA_STORE=dynamodb` and `HARNESS_ARN` in `backend/api/.env`, keep valid credentials in `~/.aws`, and restart. `/ready` should report `ok`, with a `table:<name>` check per table. Your identity needs `GetItem`, `PutItem`, `UpdateItem`, `DeleteItem`, `Query` and `DescribeTable` on the two tables, and invoke access on the harness. Copy `harness_arn` and `harness_endpoint` printed by `deploy_harness.py` into `HARNESS_ARN` and `HARNESS_ENDPOINT` only for this local case: the deployed app finds the harness itself.

## Run the tests

```bash
cd backend/api && uv run pytest && uv run lint-imports   # no AWS credentials needed
cd infra && uv run pytest                                 # synthesizes stacks, no credentials
cd frontend/web && npm test && npm run typecheck && npm run test:neutral && npm run check:boundaries
```

CI runs exactly these. Next: [deployment](./deployment.md).
