# Configuration

Reference for `project.toml`, the single parameter source, and for the backend environment variables it produces.

## project.toml

| Section | Field | Meaning |
|---|---|---|
| `[project]` | `name` | Lowercase letters, digits, hyphens; 3 to 24 characters. Prefix of every resource |
| `[project]` | `aws_account`, `aws_region` | Target account and region. Deploy scripts refuse to run if the credentials belong to another account |
| `[project]` | `github_org`, `github_repo` | Repository the deploy role trusts through GitHub OIDC |
| `[network]` | `vpc_id`, `private_subnets` | Optional. Names an existing VPC and one private subnet per zone; nothing in it is created or modified. Omit it and the template creates `<name>-network` |
| `[auth]` | `callback_urls` | Extra sign-in and sign-out return addresses besides `http://localhost:5173/`. The deploy adds the public URL, with a trailing slash |
| `[ecr]` | `image_retention_count` | Images kept for rollback, default 30; the running image is always retained |
| `[harness]` | `arn`, `endpoint` | Empty `arn` deploys the starter harness. Set it to consume an existing one; `endpoint` is the alias (`PROD`, `STAGING`) |
| `[harness]` | `model_id`, `model_ids` | Model of the starter harness; allowlist the backend accepts |
| `[environments.<env>]` | `desired_count`, `cpu`, `memory`, `nat_gateways` | Per environment: tasks, Fargate size, NAT gateways (1 or 2, one per zone) |

An invalid file stops every script with `project.toml is invalid` and the name of the field.

### Existing VPC requirements

When `[network]` is set, the VPC needs an internet gateway attached (CloudFront requires it for a private origin) and each private subnet needs a default route through a NAT, not an internet gateway. The deployment checks all of it before creating anything and names the missing subnet or condition. Organizations that forbid creating internet gateways force this path; `deploy.py` detects it with a dry run and stops before deploying.

## Backend environment variables

`backend/api/app/core/config.py` validates them at import time and names the offending variable, so a missing value stops startup instead of causing a 500 on the first request. `setup.py` writes the first block from `project.toml`.

| Variable | Default | What it does |
|---|---|---|
| `PROJECT_NAME`, `AWS_REGION` | required | Names and region |
| `SESSIONS_TABLE_NAME`, `ITEMS_TABLE_NAME` | required | DynamoDB tables of the data stack |
| `COGNITO_USER_POOL_ID`, `COGNITO_APP_CLIENT_ID` | empty | Set both or neither |
| `AUTH_JWT_SECRET` | empty | Signs the session credential; 32+ characters, required once Cognito is configured |
| `AUTH_TOKEN_TTL_SECONDS` | `3600` | Life of the session credential; there is no refresh |
| `HARNESS_ARN` | empty | Harness to invoke; empty makes `/ready` report `harness_misconfigured` |
| `HARNESS_ENDPOINT` | required | Harness alias |
| `ALLOWED_MODEL_IDS` | required | JSON list of accepted models |
| `DATA_STORE` | `auto` | `auto` is DynamoDB on ECS and memory locally; `memory` or `dynamodb` force one |
| `LOCAL_AUTH_BYPASS` | `false` | Serve authenticated routes as a stand-in user; ignored on ECS |
| `HARNESS_REPLAY` | `false` | Answer turns from recordings; ignored on ECS |
| `HARNESS_REPLAY_DELAY_SECONDS` | `0.04` | Pause between replayed events |
| `HARNESS_IDLE_TIMEOUT_SECONDS`, `HARNESS_TURN_TIMEOUT_SECONDS` | `300`, `900` | Longest harness silence; longest whole turn |
| `MAX_TOOL_ROUNDS` | `8` | Local-tool round trips per turn |

## Frontend variables

`frontend/web/.env` carries the `VITE_COGNITO_*` values. While they are empty the app runs in local mode: no sign-in, a banner says so, and the backend must have `LOCAL_AUTH_BYPASS=true`. Everything else the deployment decides, such as the models, comes from `GET /api/v1/configuration`; the SPA keeps no copy.
