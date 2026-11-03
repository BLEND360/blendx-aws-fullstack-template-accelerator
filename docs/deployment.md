# Deployment

Deploy the template to AWS from a workstation, understand what each step creates, and clean it up. Automated deployment from GitHub is in [ci-cd](./ci-cd.md).

## Deploy everything

Authenticate (`aws login` or `aws sso login`) and verify that `aws sts get-caller-identity` shows the account in `project.toml`. Then, from the repository root:

```bash
uv run --project infra python scripts/deploy.py --env dev
```

It runs the steps below in order and prints the public URL. Every step is idempotent: on a deployed project it changes nothing, and after a failure you run the same command again. The first run takes 15 to 25 minutes (CloudFront and the load balancer are slow to create); a repeat takes under a minute. Then create a user and open the URL:

```bash
uv run --project infra python scripts/create_user.py you@example.com
```

## Steps

| Order | Script | Creates |
|---|---|---|
| 1 | `bootstrap.py` | CDK bootstrap, GitHub OIDC provider and the roles stack. Once per account; prints the `gh variable set` commands |
| 2 | `deploy_data.py` | DynamoDB tables `<name>-sessions` and `<name>-items` |
| 3 | `deploy_auth.py` | Cognito user pool, app client, groups; writes both `.env` files |
| 4 | `deploy_harness.py` | Starter harness and managed memory. Skipped when `harness.arn` is set |
| 5 | `deploy_app.py --env dev` | Network, ECR, API service, SPA and CloudFront |

`deploy_app.py` also supports `--step image|stack|spa`, `--image-tag` and `--keep-image`, which is how the pipeline reuses it in separate steps. The `network` and `app` stacks exist only when the CDK app receives `-c env=<environment>` together with what is known only at deploy time (harness and memory ARNs, Cognito ids, the CloudFront prefix list, the image tag). `deploy_app.py` resolves and passes all of it; to deploy by hand read `infra/deployment.py`.

### The application image

`deploy_app.py` builds the API image with the repository root as build context, pushes it to an immutable ECR repository and deploys the stack with that tag. The tag follows the image's layers, so unchanged sources give the same tag and a repeat does not redeploy the service. In CI the tag is `<sha>-<run_attempt>` because runners share no layer cache. It does not use `docker login`: Docker's credential store caps a credential at 2560 bytes and an ECR token is longer.

ECR keeps the last `ecr.image_retention_count` images (30 by default) plus the image the service runs; an `active` marker follows the ECS image once the service is stable.

## Network

By default the template creates `<name>-network`: two zones, private subnets for the API and its load balancer, and one NAT gateway in `dev` (two in `prod`). If the organization forbids internet gateways, point `[network]` at an existing VPC. Two helpers inspect and prepare one:

```bash
uv run --project infra python scripts/find_network.py                 # read-only: which VPC can host the app
uv run --project infra python scripts/prepare_network.py              # plan: what it would add (default VPC if unspecified)
uv run --project infra python scripts/prepare_network.py --create     # two private subnets, a NAT, an own route table
```

`prepare_network.py` tags everything with `Project=<name>`, never changes what exists, is safe to rerun and leaves `project.toml` to you.

## Sign-in

`deploy_auth.py` writes `COGNITO_*` and `VITE_COGNITO_*` into the `.env` files, ensures `AUTH_JWT_SECRET` exists and sets `LOCAL_AUTH_BYPASS=false`. Groups become the API's roles (`admin`, `user`); nobody can self sign-up, so users come from `create_user.py` (`--group user` for a non-admin). The API trades Cognito's id token for its own one-hour session credential (`POST /auth/login`); there is no silent refresh. `deploy_app.py` adds the deployed URL to `[auth].callback_urls` and redeploys sign-in.

## Costs

About 2 USD per day while deployed (US East, small sizes): NAT gateway 1.10, load balancer 0.55, one small Fargate task 0.30. DynamoDB on demand, CloudFront, logs and the secret are close to nothing. Delete test deployments.

## Destroy

```bash
uv run --project infra python scripts/destroy_app.py                                       # plan: what exists and costs; deletes nothing
uv run --project infra python scripts/destroy_app.py --confirm <project-name>              # the app and its network
uv run --project infra python scripts/destroy_app.py --confirm <project-name> --everything # also harness, tables, users and roles
```

It removes only what this project created (names from `project.toml`, or the `Project` tag), never a VPC, in the right order. A failed step is reported and the safe rest continues; rerunning finishes the job and it ends by listing what still exists. `--everything` deletes data and accounts permanently. The CDK bootstrap and the GitHub OIDC provider are shared by the account and are always kept.
