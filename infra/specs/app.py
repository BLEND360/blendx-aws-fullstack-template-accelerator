from dataclasses import dataclass

from aws_cdk import aws_iam as iam
from aws_cdk import aws_logs as logs


@dataclass(frozen=True)
class ApiSpec:
    """The API as a container service: image, size, configuration, roles and where it listens."""

    repository: str
    cluster: str
    service: str
    load_balancer: str
    task_role_arn: str
    execution_role_arn: str
    cpu: int
    memory: int
    desired_count: int  # 0 while there is no image to run
    image_tag: str  # empty: no image has been pushed yet
    container_port: int
    health_path: str
    alb_idle_timeout_seconds: int
    log_group: str
    log_retention: logs.RetentionDays
    environment: dict[str, str]  # plain values only; secrets never go here
    jwt_secret_name: str  # delivered to the task as a secret named AUTH_JWT_SECRET
    task_statements: list[iam.PolicyStatement]  # added to the task role, scoped to the resolved harness
    cloudfront_prefix_list: str  # the only source the load balancer admits


@dataclass(frozen=True)
class WebSpec:
    """The public entry: a private SPA bucket and the prefixes CloudFront sends to the API."""

    bucket: str
    api_paths: tuple[str, ...]
    origin_read_timeout_seconds: int  # how long CloudFront waits for the API to say something
    spa_fallback: bool  # client-side routes answer with the SPA's entry page


@dataclass(frozen=True)
class AppSpec:
    id: str
    api: ApiSpec
    web: WebSpec
    description: str
