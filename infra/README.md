# infra

CDK app (Python). Names, account and region come from `../project.toml` through
`config.py`; nothing here writes a resource name literally (a test enforces it).

```bash
uv sync
uv run pytest                                  # no AWS credentials needed
npx --yes aws-cdk@2 synth                      # from this folder, needs credentials only for lookups
```

## Stacks today

| Stack | What | Deployed by |
|---|---|---|
| `<name>-roles` | GitHub deploy role (OIDC), ECS task and execution roles, harness execution role | `scripts/bootstrap.py` |
| `<name>-auth` | Cognito user pool (no self sign-up, RETAIN), public app client, hosted-UI domain, groups `admin` and `user` | `scripts/deploy_auth.py` |
| `<name>-data` | DynamoDB tables `<name>-sessions` and `<name>-items` (RETAIN, pay-per-request) | `scripts/deploy_data.py` |
| `<name>-network` | VPC with private subnets, NAT gateways (`nat_gateways` per environment) and S3 and DynamoDB endpoints. Not created when `[network]` in `project.toml` names an existing VPC | `scripts/deploy_app.py` |
| `<name>-app` | ECR repository, ECS cluster and Fargate service (task and execution roles imported by name, harness grants attached to the task role), internal load balancer, session secret, log group, private SPA bucket and the CloudFront distribution | `scripts/deploy_app.py` |

The starter harness is a separate CloudFormation stack owned by the agentcore CLI
(`scripts/deploy_harness.py`). Still to come: the deploy workflow (ST-09).

`network` and `app` exist only when the CDK app gets `-c env=<environment>`, together with what is known only at
deploy time (harness and memory ARNs, Cognito ids, the CloudFront prefix list, the image tag); `scripts/deploy_app.py`
resolves and passes all of it, so deploying the other stacks never needs any of it. To deploy by hand, read
`infra/deployment.py`.

## Scripts

All run as `uv run --project infra python scripts/<name>.py`.

| Script | What it does |
|---|---|
| `deploy.py --env dev` | The whole project, in order, idempotent; ends with the public URL |
| `destroy_app.py [--confirm <name>] [--everything]` | The plan by default; with the project's name, deletes the app and its network (with `--everything`, also data, users, harness and roles) |
| `find_network.py` | Read-only: which VPC in the account can host the app, and the `[network]` block for it |
| `prepare_network.py [--create]` | Adds private subnets and a NAT to an existing VPC (plan by default); everything is tagged `Project=<name>` |
| `deploy_app.py --env dev` | Network, API image, service, SPA and CloudFront; adds the public URL to `[auth] callback_urls` |
| `bootstrap.py`, `deploy_data.py`, `deploy_auth.py`, `deploy_harness.py`, `create_user.py` | The individual steps |

## Resources are data

Stacks are generic; you add things by adding specs.

| To add | Edit | Never touch |
|---|---|---|
| A table | a `TableSpec` in `definitions/tables.py` | `stacks/data.py` |
| A user pool or its groups | a `UserPoolSpec` in `definitions/auth.py` | `stacks/auth.py` |
| A role or permission | a `RoleSpec` in `definitions/roles.py` | `stacks/roles.py` |
| A network | a `NetworkSpec` in `definitions/network.py` | `stacks/network.py` |
| The app (API service, SPA, CDN) | an `AppSpec` in `definitions/app.py` | `stacks/app.py` |

Both tables are keyed by `owner_id` first, so a query is always for one owner.
A new table also needs a grant in `table_access` (`definitions/roles.py`) and a
repository in `backend/api/app/repositories/`.
