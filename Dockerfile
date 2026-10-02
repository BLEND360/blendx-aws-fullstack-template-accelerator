# API image. Build context is the repo root: `docker build .` or `docker compose build`.
# Build stage: uv resolves and installs the locked dependencies into a venv.
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /src
COPY backend/api/pyproject.toml backend/api/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Runtime stage: the venv and the code. No uv, no pip, no build tooling.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/opt/venv/bin:$PATH"
RUN useradd --create-home --uid 10001 app
COPY --from=build /opt/venv /opt/venv
WORKDIR /app
COPY backend/api/app ./app
USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
