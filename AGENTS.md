# AGENTS.md

Guide for AI agents working in this repository. For the full project description and deployment steps, read [README.md](./README.md).

## What this repo is

A fullstack app on AWS: React SPA, FastAPI backend, DynamoDB, and an AgentCore harness for the agent. `project.toml` is the only place where names, account and region are written. Do not hardcode them anywhere else.

## Where to edit, by task

| If the user asks for... | Edit | Then run |
|---|---|---|
| UI, pages, styles, components | `frontend/web/` | `npm run typecheck`, `npm test`, `npm run test:neutral`, `npm run check:boundaries`, `npm run build` (from `frontend/web/`) |
| API endpoints, auth, business logic | `backend/api/` | `uv run lint-imports` and `uv run pytest -q` (from `backend/api/`) |
| Agent behavior, model, memory | `harness/` | Deploy with `scripts/deploy_harness.py` (see below) |
| AWS resources (network, data, compute, CDN, identity) | `infra/` | `uv run pytest -q` (from `infra/`) |
| Deployment scripts | `scripts/` | Run the affected script with `--env dev` first |
| Project docs (`docs/`) | `docs/` | `node scripts/validate-docs.mjs` (see [docs/SYNC_DOCS_GUIDELINES.md](./docs/SYNC_DOCS_GUIDELINES.md)) |

Sibling services go in `backend/`, and sibling UIs go in `frontend/`.

## Run locally (no AWS needed)

```bash
python scripts/setup.py       # validates project.toml, writes .env files and the harness config; deletes itself
docker compose up --build     # web http://localhost:5173, API http://localhost:8000/health
```

Run `setup.py` only once per clone. It deletes itself after it runs.

## Deploy

```bash
uv run --project infra python scripts/deploy.py --env dev
```

Tear down with `scripts/destroy_app.py`. Deployment needs AWS credentials for the account in `project.toml`.

## Rules

- Never commit `.env` files or secrets. The harness config is generated and git-ignored.
- Do not put real account IDs, secrets or internal hostnames in tracked files. The repo is public.
- Before finishing a change, run the commands for the folders you touched. CI runs the same ones.
- Follow the user's instructions precisely. Within that scope, act on your own: gather the context you need and finish the requested work in the same run. Ask only when essential information is missing or the request is truly ambiguous.
- Do not claim something works without evidence. Show the command you ran and its result, and say so when a check was skipped or failed.
