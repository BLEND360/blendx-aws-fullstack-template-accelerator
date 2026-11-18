"""Every deployed app the template provisions. Add one by adding an AppSpec to the list app_specs
returns; AppStack needs no change.

The task's variables are the ones scripts/setup.py writes for local runs, minus the two that only make
sense there (the auth bypass and the generated session secret: deployed, the secret comes from Secrets
Manager). Values that exist only at deploy time (harness, Cognito ids, image) arrive as DeployInputs.
"""

import json

from aws_cdk import aws_logs as logs

from config import Config
from definitions.roles import get_harness, harness_memory, invoke_harness
from deployment import DeployInputs
from specs.app import ApiSpec, AppSpec, WebSpec

APP_ID = "App"
CONTAINER_PORT = 8000  # the port the Dockerfile exposes
HEALTH_PATH = "/health"
API_PATHS = ("/api/*", "/auth/*")  # the prefixes the SPA and the backend reserve
# CloudFront's default origin response timeout is 30 s; the API pings every 15 s while a turn is quiet.
ORIGIN_READ_TIMEOUT_SECONDS = 60
# Longer than CloudFront's, so CloudFront is the one to give up on a silent connection.
ALB_IDLE_TIMEOUT_SECONDS = 120


def task_environment(c: Config, inputs: DeployInputs) -> dict[str, str]:
    return {
        "PROJECT_NAME": c.name,
        "AWS_REGION": c.aws_region,
        "SESSIONS_TABLE_NAME": c.sessions_table,
        "ITEMS_TABLE_NAME": c.items_table,
        "HARNESS_ARN": inputs.harness_arn,
        "HARNESS_ENDPOINT": c.harness_endpoint,
        "ALLOWED_MODEL_IDS": json.dumps(list(c.model_ids)),
        "COGNITO_USER_POOL_ID": inputs.user_pool_id,
        "COGNITO_APP_CLIENT_ID": inputs.app_client_id,
    }


def app_specs(c: Config, inputs: DeployInputs) -> list[AppSpec]:
    size = c.sizing(inputs.env)
    return [
        AppSpec(
            id=APP_ID,
            api=ApiSpec(
                repository=c.ecr_repository,
                cluster=c.cluster,
                service=c.service,
                load_balancer=c.load_balancer,
                task_role_arn=c.role_arn(c.task_role),
                execution_role_arn=c.role_arn(c.execution_role),
                cpu=size.cpu,
                memory=size.memory,
                desired_count=size.desired_count if inputs.image_tag else 0,
                image_tag=inputs.image_tag,
                container_port=CONTAINER_PORT,
                health_path=HEALTH_PATH,
                alb_idle_timeout_seconds=ALB_IDLE_TIMEOUT_SECONDS,
                log_group=c.log_group,
                log_retention=logs.RetentionDays.ONE_MONTH,
                environment=task_environment(c, inputs),
                jwt_secret_name=c.auth_jwt_secret_name,
                task_statements=[
                    invoke_harness(inputs.harness_arn),
                    get_harness(inputs.harness_arn),
                    harness_memory(inputs.memory_arn),
                ],
                cloudfront_prefix_list=inputs.cloudfront_prefix_list,
            ),
            web=WebSpec(
                bucket=c.web_bucket,
                api_paths=API_PATHS,
                origin_read_timeout_seconds=ORIGIN_READ_TIMEOUT_SECONDS,
                spa_fallback=True,
            ),
            description="The deployed app: the API on a private container service behind CloudFront, and the SPA.",
        )
    ]
