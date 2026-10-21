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

The starter harness is a separate CloudFormation stack owned by the agentcore CLI
(`scripts/deploy_harness.py`). Still to come: network, app
(ECS and CloudFront, ST-07) and the deploy workflow (ST-09).

## Resources are data

Stacks are generic; you add things by adding specs.

| To add | Edit | Never touch |
|---|---|---|
| A table | a `TableSpec` in `definitions/tables.py` | `stacks/data.py` |
| A user pool or its groups | a `UserPoolSpec` in `definitions/auth.py` | `stacks/auth.py` |
| A role or permission | a `RoleSpec` in `definitions/roles.py` | `stacks/roles.py` |

Both tables are keyed by `owner_id` first, so a query is always for one owner.
A new table also needs a grant in `table_access` (`definitions/roles.py`) and a
repository in `backend/api/app/repositories/`.
