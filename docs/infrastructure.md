# Infrastructure

Reference for the CDK app in `infra/`: the stacks, how resources are modelled as data, the scripts that operate them and the starter harness.

## Stacks

Names, account and region come from `project.toml` through `infra/config.py`; nothing writes a resource name literally.

| Stack | What | Deployed by |
|---|---|---|
| `<name>-roles` | GitHub deploy and PR-diff roles (OIDC), ECS task and execution roles, harness execution role | `bootstrap.py` |
| `<name>-auth` | Cognito user pool (no self sign-up, RETAIN), public app client, hosted-UI domain, groups `admin` and `user` | `deploy_auth.py` |
| `<name>-data` | DynamoDB `<name>-sessions` and `<name>-items` (RETAIN, pay-per-request) | `deploy_data.py` |
| `<name>-network` | VPC with private subnets, NAT gateways and S3 and DynamoDB endpoints. Not created when `[network]` names an existing VPC | `deploy_app.py` |
| `<name>-app` | ECR repository, ECS cluster and Fargate service, internal load balancer, session secret, log group, private SPA bucket, CloudFront distribution | `deploy_app.py` |

The starter harness is a separate CloudFormation stack owned by the `agentcore` CLI (`deploy_harness.py`). One stack per lifetime means an app rollback cannot delete data. The pipeline deploys them in the order roles, auth, data, harness, then the app.

`network` and `app` need `-c env=<environment>` plus deploy-time values (harness and memory ARNs, Cognito ids, the CloudFront prefix list, the image tag), which `scripts/deploy_app.py` resolves, so deploying the other stacks never needs any of it.

## Resources are data

Stacks are generic and provision whatever they receive. `infra/specs/` defines one frozen dataclass per resource type, `infra/definitions/` lists the instances derived from `Config`, and `infra/stacks/` stays untouched when you add things.

| To add | Edit | Never touch |
|---|---|---|
| A table | a `TableSpec` in `definitions/tables.py` | `stacks/data.py` |
| A user pool or its groups | a `UserPoolSpec` in `definitions/auth.py` | `stacks/auth.py` |
| A role or permission | a `RoleSpec` in `definitions/roles.py` | `stacks/roles.py` |
| A network | a `NetworkSpec` in `definitions/network.py` | `stacks/network.py` |
| The app (API service, SPA, CDN) | an `AppSpec` in `definitions/app.py` | `stacks/app.py` |

Both tables are keyed by `owner_id` first, so a query is always for one owner. A new table also needs a grant in `table_access` (`definitions/roles.py`) and a repository in `backend/api/app/repositories/`.

## Scripts

All run as `uv run --project infra python scripts/<name>.py`.

| Script | What it does |
|---|---|
| `deploy.py --env dev` | The whole project, in order, idempotent; ends with the public URL |
| `destroy_app.py [--confirm <name>] [--everything]` | The plan by default; with the project name deletes the app and its network |
| `find_network.py` | Read-only: which VPC can host the app, and the `[network]` block for it |
| `prepare_network.py [--create]` | Adds private subnets and a NAT to an existing VPC; plan by default |
| `deploy_app.py --env dev` | Network, image, service, SPA and CloudFront; `--step`, `--image-tag`, `--keep-image` |
| `changed_paths.py --env dev` | Chooses image and SPA steps by comparing HEAD with the commit running in ECS |
| `diff.py --env dev` | `cdk diff --method=template`, without change sets |
| `smoke_test.py --env dev` | Checks `/api/health` through the public CloudFront URL; `--url` works without AWS |
| `bootstrap.py`, `deploy_data.py`, `deploy_auth.py`, `deploy_harness.py`, `create_user.py` | The individual steps |

## Starter harness

The harness follows the platform convention so a template-born harness can graduate into the Hub unchanged: it lives at `harness/app/assistant/`, CloudFormation outputs are `Harness<Pascal>*`, versions are immutable and environments are aliases pinned to a version. `agentcore.json`, `aws-targets.json` and `harness.json` are rendered from `project.toml` by `infra/harness_files.py` and are git-ignored; the backend never imports from `harness/`. `scripts/harness/` is vendored from the platform: it is not edited, it is re-copied. To use an existing harness instead, set `harness.arn` and `harness.endpoint` and the starter is not deployed.

## Tests

`uv run pytest` in `infra/` synthesizes stacks and asserts templates with no credentials. `test_no_hardcoded_names.py` guarantees the project name lives only in `project.toml`.
