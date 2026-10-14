# api

FastAPI service. Needs `backend/api/.env`, written by `python scripts/setup.py`.

```bash
uv sync
uv run uvicorn app.main:app --reload     # http://localhost:8000/health
```

## Configuration

`app/core/config.py` validates these at startup and names the offending variable. `setup.py`
writes the first block from `project.toml`; the rest are optional.

| Variable | Default | What it does |
|---|---|---|
| `PROJECT_NAME`, `AWS_REGION` | required | Names and region |
| `SESSIONS_TABLE_NAME`, `ITEMS_TABLE_NAME` | required | DynamoDB tables of the data stack |
| `HARNESS_ARN` | empty | Harness to invoke; empty makes `/ready` report `harness_misconfigured` |
| `HARNESS_ENDPOINT` | required | Harness alias (`PROD`, `STAGING`) |
| `ALLOWED_MODEL_IDS` | required | JSON list, e.g. `["model-a"]` |
| `DATA_STORE` | `auto` | `auto`: DynamoDB on ECS, memory locally. `memory` / `dynamodb` force one |
| `LOCAL_AUTH_BYPASS` | `false` | Serve authenticated routes as a stand-in user. Ignored on ECS |
| `HARNESS_REPLAY` | `false` | Answer turns from recorded streams, no AWS. Ignored on ECS |
| `HARNESS_REPLAY_DELAY_SECONDS` | `0.04` | Pause between replayed events |
| `HARNESS_IDLE_TIMEOUT_SECONDS`, `HARNESS_TURN_TIMEOUT_SECONDS` | `300`, `900` | Longest harness silence; longest whole turn |
| `MAX_TOOL_ROUNDS` | `8` | Local-tool round trips per turn |

### Against DynamoDB from your laptop

By default sessions and items live in process memory and vanish on restart. To use the real
tables: deploy the data stack (root README, step 2), then in `backend/api/.env` set
`DATA_STORE=dynamodb` and keep valid credentials in `~/.aws`. Your identity needs
`GetItem`, `PutItem`, `UpdateItem`, `DeleteItem`, `Query` and `DescribeTable` on the two tables
(the deployed task role has exactly those). `/ready` shows a `table:<name>` check per table.

```bash
uv run pytest        # no AWS credentials needed
uv run lint-imports  # layering: routers -> services -> repositories | clients | harness -> core
```

Where things go: `routers/` parse, authorize, delegate; `services/` decide, and
reach the outside only through the `Protocol` ports in `services/ports.py`;
`clients/`, `repositories/` and `harness/` are the adapters that talk to AWS and
translate its errors with `core.errors.classify_aws_error`. See
the root [README](../../README.md#architecture).

How the API talks to the agent (sessions, streamed turns, tools, extending it): [INTEGRATION.md](INTEGRATION.md).
