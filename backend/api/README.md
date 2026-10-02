# api

FastAPI service. Needs `backend/api/.env`, written by `python scripts/setup.py`.

```bash
uv sync
uv run uvicorn app.main:app --reload     # http://localhost:8000/health
```

```bash
uv run pytest        # no AWS credentials needed
uv run lint-imports  # layering: routers -> services -> repositories | clients | harness -> core
```

Where things go: `routers/` parse, authorize, delegate; `services/` decide, and
reach the outside only through the `Protocol` ports in `services/ports.py`;
`clients/`, `repositories/` and `harness/` are the adapters that talk to AWS and
translate its errors with `core.errors.classify_aws_error`. See
the root [README](../../README.md#architecture).
