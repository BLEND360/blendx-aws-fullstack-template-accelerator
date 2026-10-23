# blendx-fullstack-aws-template

One repository a team clones to get a deployed, authenticated fullstack app on
AWS whose business logic already calls an AgentCore harness. Set four values in
`project.toml`, push, and an agent is responding on a private AWS topology.

Tracking issue: [BLEND360/blendx-core#1144](https://github.com/BLEND360/blendx-core/issues/1144).

## What you get

| | |
|---|---|
| Application | React SPA, FastAPI backend, DynamoDB |
| Agent integration | Invoke a harness, stream the answer as SSE, dispatch tools; no AWS error message ever reaches the browser |
| Starter harness | A model plus managed memory, deployed with the `agentcore` CLI. Point at an existing harness by setting `harness.arn` and `harness.endpoint` |
| Infrastructure | CDK (Python) for network, identity, data, compute, CDN |
| CI/CD | GitHub Actions with OIDC. No long-lived AWS keys |

```
CloudFront (only public entry)
 ├─ /*                → React SPA, private S3
 └─ /api/*, /auth/*   → internal load balancer → FastAPI on Fargate (no public IP) → DynamoDB
                                                                                   → AgentCore harness → managed memory
```

## Layout

```
project.toml          # the only place names, account and region are written
Dockerfile            # API image (build context: repo root)
docker-compose.yml    # run that image locally
backend/api/          # FastAPI service — add sibling services here
frontend/web/         # Vite + React SPA — add sibling UIs here
harness/              # starter harness: model + managed memory
infra/                # CDK app (Python), see infra/README.md
scripts/              # setup, deploy, destroy, and the network helpers (see "Deploying to AWS")
.github/workflows/    # ci, deploy
```

## Quick start

Prerequisites: [uv](https://docs.astral.sh/uv/), Node.js 22+, Docker (optional),
and for the AWS steps the AWS CLI with credentials for the target account.

### 1. Run it locally (no AWS needed)

```bash
# edit project.toml first (name, aws_account, aws_region, github_org, github_repo)
python scripts/setup.py       # validates project.toml, writes the .env files; deletes itself
docker compose up --build     # web http://localhost:5173, API http://localhost:8000/health
```

Locally the API keeps sessions and items in memory and skips sign-in
(`LOCAL_AUTH_BYPASS=true`). `/ready` reports `degraded` until you have AWS
credentials and a harness; that is expected. To chat without any harness, start
the API with recorded answers (`HARNESS_REPLAY=true`, see
[frontend/web/README.md](frontend/web/README.md#showing-it-without-aws)).

Without Docker: [backend/api/README.md](backend/api/README.md) and
[frontend/web/README.md](frontend/web/README.md). `docker compose` mounts
`~/.aws`, so that folder must exist (`mkdir ~/.aws` if you have no credentials).

### 2. Deploy to AWS

Needs credentials for the account in `project.toml` (`aws login` or `aws sso login`; check with
`aws sts get-caller-identity`), plus Docker, Node.js and, for the harness step, the AWS CLI, the `agentcore` CLI
(`npm i -g @aws/agentcore`), `jq` and `bash` (`deploy_harness.py` runs the platform's own scripts, which call them).
From the repo root:

```bash
uv run --project infra python scripts/deploy.py --env dev
```

That runs, in order, everything below (each step is idempotent, so on an already deployed project it changes
nothing, and after a failure you run the same command again) and ends by printing the app's public URL:
account setup, data, sign-in, harness (skipped when `harness.arn` is set) and the app. Then create a user and
open the URL:

```bash
uv run --project infra python scripts/create_user.py you@example.com
```

The first run takes 15 to 25 minutes (CloudFront and the load balancer are slow to create); a repeat takes under a
minute. **While it is deployed it costs money**: see [Costs and cleaning up](#costs-and-cleaning-up).

Each step on its own, if you prefer them one at a time:

```bash
# once per AWS account: CDK bootstrap, GitHub OIDC provider, roles stack
uv run --project infra python scripts/bootstrap.py

# DynamoDB tables (sessions, items); needed only to run with DATA_STORE=dynamodb
uv run --project infra python scripts/deploy_data.py

# sign-in: Cognito user pool, wired into the .env files (see "Sign-in" below)
uv run --project infra python scripts/deploy_auth.py

# starter harness (model + managed memory); skipped when harness.arn is set.
# Needs: npm i -g @aws/agentcore, AWS CLI, jq, bash
uv run --project infra python scripts/deploy_harness.py

# the app: network (unless [network] points at an existing VPC), API service, SPA, CloudFront.
# Needs Docker and npm. Also adds the public URL to [auth] callback_urls in project.toml.
uv run --project infra python scripts/deploy_app.py --env dev
```

`deploy_harness.py` prints `harness_arn=...` and
`harness_endpoint=...`; put them in `backend/api/.env` as `HARNESS_ARN` and
`HARNESS_ENDPOINT` (or set `harness.arn` in `project.toml` to use an existing
harness and skip the deploy). Use plain `python` for `setup.py` only: the other
scripts need boto3, which `uv run --project infra` provides.

### Network

By default the template creates its own VPC (`<name>-network`: two zones, private subnets for the API and its load
balancer, one NAT gateway in `dev` and two in `prod`, set by `nat_gateways` in `[environments]`). The API has no
public IP and CloudFront reaches it through the internal load balancer.

Some organizations do not allow creating an internet gateway, and then the template cannot create that VPC:
`deploy.py` asks the account first (a dry-run, nothing is created) and, if it is not allowed, stops before deploying
anything and tells you to use a VPC that already exists. For that, the `[network]` section of `project.toml` names
the VPC and a private subnet per zone (nothing in the VPC is created or modified by the deployment):

```toml
[network]
vpc_id          = "vpc-0123456789abcdef0"
private_subnets = { us-east-1a = "subnet-...", us-east-1b = "subnet-..." }
```

To find or make a VPC that fits (it needs an internet gateway attached, which CloudFront requires for a private
origin, and private subnets whose default route goes through a NAT):

```bash
uv run --project infra python scripts/find_network.py                    # lists the account's VPCs, says which can host the app, prints the [network] block
uv run --project infra python scripts/prepare_network.py                 # none can? shows what it would add to a VPC (default VPC if you do not say)
uv run --project infra python scripts/prepare_network.py --create        # ...and creates it: two private subnets, a NAT, a route table of its own
```

`prepare_network.py` tags everything it creates with `Project=<name>`, never changes what already exists, can be run
again safely, prints the `[network]` block and leaves `project.toml` to you. The deployment checks the VPC before
creating anything and names the subnet or the condition that is missing.

### Costs and cleaning up

Roughly, per day while it is deployed (US East, small sizes): NAT gateway 1.10 USD, load balancer 0.55 USD, one small
Fargate task 0.30 USD; DynamoDB (on demand), CloudFront, logs and the secret are close to nothing. About 2 USD a day, so
**delete a test deployment when you are done**:

```bash
uv run --project infra python scripts/destroy_app.py                                   # the plan: what exists, what it costs; deletes nothing
uv run --project infra python scripts/destroy_app.py --confirm <project-name>          # the app and its network
uv run --project infra python scripts/destroy_app.py --confirm <project-name> --everything   # also the harness, tables, users and roles
```

It removes only what this project created (names from `project.toml`, or the `Project` tag), never a VPC, and in the
right order; a step that fails is reported and the rest that is safe goes on, and running it again finishes the job. It
ends by listing anything that still exists. `--everything` deletes data and accounts for good. The CDK bootstrap and the
GitHub OIDC provider are shared by the account and are always left.

### Sign-in

Locally there is no sign-in (`LOCAL_AUTH_BYPASS=true`, you are a stand-in admin). To sign in for real:

```bash
uv run --project infra python scripts/deploy_auth.py                      # Cognito + writes both .env files
uv run --project infra python scripts/create_user.py you@example.com      # prints the password; --group user for a non-admin
```

`deploy_auth.py` writes `COGNITO_*` and `VITE_COGNITO_*` into the `.env` files, makes sure `AUTH_JWT_SECRET`
exists and sets `LOCAL_AUTH_BYPASS=false` (set it back to `true` to skip sign-in locally). Restart the API and
the web app, open http://localhost:5173 and sign in. Nothing is copied by hand.

Groups become the API's roles (`admin`, `user`); nobody can self sign-up, so users come from `create_user.py`.
The API trades Cognito's id token for its own 1-hour session credential (`POST /auth/login`); there is no silent
refresh. `deploy_app.py` adds the deployed URL (https, trailing slash) to `[auth] callback_urls` in
`project.toml` and redeploys sign-in for you; to allow another address, add it there and run `deploy_auth.py`.

### 3. Point the local app at AWS (optional)

Set `DATA_STORE=dynamodb` and `HARNESS_ARN` in `backend/api/.env`, keep valid
credentials in `~/.aws`, and restart. `/ready` should then report `ok`.

### Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `ModuleNotFoundError: boto3` | You ran `bootstrap.py`, `deploy_data.py`, `deploy_auth.py`, `create_user.py` or `deploy_harness.py` with plain `python`. Use `uv run --project infra python ...` |
| "Your credentials are for account X, but project.toml says Y" | Wrong profile or `aws_account` in `project.toml`. Fix one and retry |
| `Your session has expired ... Please reauthenticate using 'aws login'` (API logs, `/ready` degraded with `data_error`) | Run `aws login` (or `aws sso login`), then restart the API |
| `OSError: [Errno 30] Read-only file system` in the container after `aws login` | `docker compose` mounts `~/.aws` read-only; credentials from `aws login` need it writable. Add a git-ignored `docker-compose.override.yml` that mounts `~/.aws` without `:ro` |
| `/ready` is `degraded` with `harness_misconfigured` | `HARNESS_ARN` is empty. Deploy the harness or use `HARNESS_REPLAY=true` |
| `/ready` is `degraded` with `data_error` on a table | Tables not deployed, or `DATA_STORE=dynamodb` with no credentials. Run `deploy_data.py` |
| API refuses to start naming `AUTH_JWT_SECRET` or `COGNITO_APP_CLIENT_ID` | Cognito is configured but the secret is shorter than 32 characters, or only one of pool and client is set |
| `project.toml is invalid` | The message names the field; names are 3-24 lowercase letters, digits and single hyphens |
| `deploy.py` stops: "Your organization does not let this user create an internet gateway" | A policy of your AWS organization forbids it, so the template cannot create its VPC. Use an existing one: `find_network.py`, `prepare_network.py`, then the `[network]` block (see "Network") |
| `deploy_app.py` stops naming a subnet or "no internet gateway" | The VPC in `[network]` does not fit: the subnet needs a route to a NAT (not an internet gateway) and the VPC an internet gateway. `find_network.py` shows which subnets do |
| `error saving credentials ... The stub received the wrong data` pushing the image (Windows) | Docker's credential store caps a credential at 2560 bytes and an ECR token is longer. `deploy_app.py` does not use `docker login` for this reason; if you push by hand, use a throwaway `DOCKER_CONFIG` |
| A repeat of `deploy_app.py` redeploys the service although nothing changed | The image tag follows the image's layers; a build that changed a layer (new base image, `uv.lock`) is a new version. Same sources and cache give the same tag |
| `aws logs ... /name/api` says the log group name is invalid (Git Bash) | Git Bash rewrites arguments that start with `/`. Run `export MSYS_NO_PATHCONV=1` first |
| The site returns the entry page, or a 403, right after the first deploy | CloudFront takes a few minutes to propagate; try again in two or three |
| `setup.py` says "already complete" | Both `.env` files exist; delete them to regenerate (`setup.py` removes itself after the first run) |

### Not built yet

The deploy workflow (ST-09): `git push` runs CI but does not deploy yet, so deploying is `scripts/deploy.py` from a
machine with credentials. `bootstrap.py` prints two GitHub variables to set (`AWS_DEPLOY_ROLE_ARN`, `AWS_REGION`);
they are used once the workflow exists.

## Architecture

A modular monolith per environment, ports and adapters inside each service,
delivered as a golden path: the rules below are enforced by CI, not by review.

**Backend layering** (`uv run lint-imports`, configured in `backend/api/pyproject.toml`):

```
routers → services → repositories | clients | harness → core
```

- `routers/` parse, authorize, delegate. No boto3, no table names.
- `services/` decide. No FastAPI, no boto3; outbound calls go through the
  `Protocol` ports in `services/ports.py`.
- `repositories/`, `clients/`, `harness/` are the adapters. They talk to AWS and
  translate its errors with `core.errors.classify_aws_error`.
- Errors leave the process as a fixed sentence plus a stable
  `<dependency>_<category>` code (`harness_unavailable`, `data_throttled`); the
  real cause is logged against the request id.
- The backend test suite passes with no AWS credentials.

**Infrastructure**: one stack per lifetime (roles, auth, data, harness, network, app), so
an app rollback cannot delete data. Resources are data: `infra/specs/` +
`infra/definitions/` + a generic stack. Every name is derived from
`project.toml` by `infra/config.py`.

**Harness**: follows the platform convention (lives at `harness/app/assistant/`,
CloudFormation outputs `Harness<Pascal>*`, immutable versions, aliases per
environment) so a template-born harness can graduate into the Hub unchanged.

### Extending it

| To do this | Change this | Never touch |
|---|---|---|
| Add an endpoint | `routers/x.py`, `services/x.py`, a test | `harness/` |
| Give the agent a tool | `tools/x.py` + two lines in `tools/registry.py` | `harness/client.py` |
| Add a table | an entry in `infra/definitions/tables.py`, a `repositories/x.py` | `infra/stacks/` |
| Grant a permission | an entry in `infra/definitions/roles.py` | `infra/stacks/` |
| Change the model / use an existing harness | `project.toml` | any code |
| Add a service or UI | a sibling folder under `backend/` or `frontend/` + a CI path filter | the existing ones |

### Out of scope for v1

Gateways, MCP tool runtimes, knowledge bases, evaluations and schedulers;
relational databases; custom domains, WAF, autoscaling.
