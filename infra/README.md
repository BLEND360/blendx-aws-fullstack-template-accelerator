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
| `<name>-roles` | GitHub deploy and PR-diff roles (OIDC), ECS task and execution roles, harness execution role | `scripts/bootstrap.py` |
| `<name>-auth` | Cognito user pool (no self sign-up, RETAIN), public app client, hosted-UI domain, groups `admin` and `user` | `scripts/deploy_auth.py` |
| `<name>-data` | DynamoDB tables `<name>-sessions` and `<name>-items` (RETAIN, pay-per-request) | `scripts/deploy_data.py` |
| `<name>-network` | VPC with private subnets, NAT gateways (`nat_gateways` per environment) and S3 and DynamoDB endpoints. Not created when `[network]` in `project.toml` names an existing VPC | `scripts/deploy_app.py` |
| `<name>-app` | ECR repository, ECS cluster and Fargate service (task and execution roles imported by name, harness grants attached to the task role), internal load balancer, session secret, log group, private SPA bucket and the CloudFront distribution | `scripts/deploy_app.py` |

The starter harness is a separate CloudFormation stack owned by the agentcore CLI
(`scripts/deploy_harness.py`). GitHub Actions uses `ci.yml` for tests and a read-only CDK template diff, then
`deploy.yml` for ordered deployments from `main`. The deploy role trusts only the Environments declared in
`project.toml` and `refs/heads/main`; the PR role has read-only permissions and can assume only CDK's lookup role.

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
| `deploy_app.py --env dev` | Network, API image, service, SPA and CloudFront; supports `--step image|stack|spa`, `--image-tag` and `--keep-image` |
| `changed_paths.py --env dev` | Chooses image and SPA steps by comparing HEAD with the commit running in ECS |
| `diff.py --env dev` | Runs `cdk diff --method=template` for infrastructure without creating change sets |
| `smoke_test.py --env dev` | Checks `/api/health` through the app's public CloudFront URL; `--url` works without AWS |
| `bootstrap.py`, `deploy_data.py`, `deploy_auth.py`, `deploy_harness.py`, `create_user.py` | The individual steps |

## Enable GitHub Actions deployments

Complete these steps from a configured clone. Confirm `aws_account`, `aws_region`,
`github_org`, and `github_repo` identify the intended account and repository before
running any AWS command.

1. Authenticate locally and verify `aws sts get-caller-identity`; its account ID
   must match `project.toml`.
2. Run `uv run --project infra python scripts/bootstrap.py` once. It bootstraps CDK,
   creates the GitHub OIDC provider when needed, deploys the roles, and prints the
   `gh variable set` commands. Review each ARN and region before using them.
3. In GitHub repository **Settings → Environments**, create `dev` and `prod`.
   Allow deployments from `main` only for both; configure required reviewers for
   `prod` and no reviewer gate for `dev`.
4. In repository **Settings → Secrets and variables → Actions → Variables**, set
   `AWS_DIFF_ROLE_ARN` and `AWS_REGION` using the printed values.
5. In each Environment's variables, set `AWS_DEPLOY_ROLE_ARN` and `AWS_REGION`
   using its matching values. No long-lived AWS keys belong in GitHub secrets.
6. Protect `main` in repository **Settings → Rules → Rulesets** (or branch
   protection rules): require pull requests and the `api`, `infra`, and `web`
   CI checks before merging; do not allow direct pushes that bypass review.
7. Push the configured repository to `main` or dispatch `deploy.yml` selecting
   `dev`; inspect the workflow's CI, OIDC, ordered deploy and `/api/health` smoke
   test. Use `prod` only after `dev` succeeds and the reviewer approves.

Until ST-12 supports separate accounts per environment, both Environments target
the account configured in `project.toml`. The workflow requires the roles to be
deployed and the configured GitHub repository to match the running repository.

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
