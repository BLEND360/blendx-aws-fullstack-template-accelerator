# Troubleshooting

Symptoms seen while running or deploying the template, with cause and fix.

| Symptom | Cause and fix |
|---|---|
| `ModuleNotFoundError: boto3` | A script was run with plain `python`. Use `uv run --project infra python ...` (only `setup.py` uses plain `python`) |
| "Your credentials are for account X, but project.toml says Y" | Wrong profile or `aws_account`. Fix one and retry |
| `Your session has expired ... Please reauthenticate using 'aws login'` (API logs, `/ready` degraded with `data_error`) | Run `aws login` or `aws sso login`, then restart the API |
| `OSError: [Errno 30] Read-only file system` in the container after `aws login` | Compose mounts `~/.aws` read-only; credentials from `aws login` need it writable. Add a git-ignored `docker-compose.override.yml` that mounts `~/.aws` without `:ro` |
| `/ready` is `degraded` with `harness_misconfigured` | `HARNESS_ARN` is empty. Deploy the harness or use `HARNESS_REPLAY=true` |
| `/ready` is `degraded` with `data_error` on a table | Tables not deployed, or `DATA_STORE=dynamodb` without credentials. Run `deploy_data.py` |
| The API refuses to start naming `AUTH_JWT_SECRET` or `COGNITO_APP_CLIENT_ID` | Cognito is configured but the secret is shorter than 32 characters, or only one of pool and client is set |
| `project.toml is invalid` | The message names the field; names are 3 to 24 lowercase letters, digits and single hyphens |
| `deploy.py` stops: "Your organization does not let this user create an internet gateway" | An organization policy forbids it. Use an existing VPC: `find_network.py`, `prepare_network.py`, then the `[network]` block (see [deployment](./deployment.md)) |
| `deploy_app.py` stops naming a subnet or "no internet gateway" | The VPC in `[network]` does not fit: subnets need a route to a NAT and the VPC an internet gateway. `find_network.py` shows which subnets do |
| `error saving credentials ... The stub received the wrong data` pushing the image (Windows) | Docker's credential store caps a credential at 2560 bytes and an ECR token is longer. `deploy_app.py` avoids `docker login`; if you push by hand use a throwaway `DOCKER_CONFIG` |
| A repeat of `deploy_app.py` redeploys although nothing changed | The image tag follows the image's layers; a changed layer (new base image, `uv.lock`) is a new version |
| `aws logs ... /name/api` says the log group name is invalid (Git Bash) | Git Bash rewrites arguments starting with `/`. Run `export MSYS_NO_PATHCONV=1` |
| The site returns the entry page or a 403 right after the first deploy | CloudFront takes a few minutes to propagate; retry in two or three |
| `setup.py` says "already complete" | Both `.env` files exist, so nothing changed. Delete them to regenerate. After a successful run `setup.py` deletes itself; `git restore scripts/setup.py` brings it back |
| The deploy workflow fails at the last step printing a `project.toml` diff | The first deploy added the CloudFront URL to `[auth].callback_urls`. Commit the change and rerun (see [ci-cd](./ci-cd.md)) |
