from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecr as ecr
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_elasticloadbalancingv2 as elbv2
from aws_cdk import aws_iam as iam
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_secretsmanager as secretsmanager
from constructs import Construct

from config import ExistingNetwork
from specs.app import AppSpec
from stacks.network import import_vpc

# What the service runs while no image has been pushed: never pulled, because it has no tasks then.
PLACEHOLDER_TAG = "pending"
JWT_SECRET_VARIABLE = "AUTH_JWT_SECRET"
# A client-side route (/chat, /items/3) has no file behind it: serve the entry page and let the router
# take over. Files have an extension, so they are left alone. Done here, not as distribution-level error
# pages, because those would also replace the API's own 403 and 404 answers.
SPA_REWRITE = """function handler(event) {
  var request = event.request;
  if (request.uri.split('/').pop().indexOf('.') === -1) {
    request.uri = '/index.html';
  }
  return request;
}
"""


class AppStack(Stack):
    """Provisions every AppSpec it is given. Apps are added in definitions/app.py, not here.

    `vpc` is the VPC the network stack created, or the description of an existing one, imported without
    touching it. The roles are not created here: they exist already (roles stack) and are imported by name, which
    is also how the harness grants reach the task role.
    """

    def __init__(
        self, scope: Construct, construct_id: str, specs: list[AppSpec], vpc: ec2.IVpc | ExistingNetwork, **kwargs
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        if isinstance(vpc, ExistingNetwork):
            vpc = import_vpc(self, vpc)
        for spec in specs:
            app = Construct(self, spec.id)
            service = self._compute(app, spec, vpc)
            load_balancer = self._load_balancer(app, spec, vpc, service)
            distribution = self._web(app, spec)
            self._api_routes(distribution, spec, load_balancer)
            self._outputs(spec, distribution, service)

    def _compute(self, scope: Construct, spec: AppSpec, vpc: ec2.IVpc) -> ecs.FargateService:
        api = spec.api
        private = ec2.SubnetSelection(subnets=vpc.private_subnets)

        repository = ecr.Repository(
            scope, "Repository", repository_name=api.repository, removal_policy=RemovalPolicy.RETAIN, image_scan_on_push=True
        )
        cluster = ecs.Cluster(scope, "Cluster", cluster_name=api.cluster, vpc=vpc)

        task_role = iam.Role.from_role_arn(scope, "TaskRole", api.task_role_arn, mutable=True)
        execution_role = iam.Role.from_role_arn(scope, "ExecutionRole", api.execution_role_arn, mutable=True)
        for statement in api.task_statements:
            task_role.add_to_principal_policy(statement)

        # Generated once and kept: re-deploying never rotates it, so sessions in flight stay valid.
        secret = secretsmanager.Secret(
            scope,
            "JwtSecret",
            secret_name=api.jwt_secret_name,
            generate_secret_string=secretsmanager.SecretStringGenerator(password_length=48, exclude_punctuation=True),
            removal_policy=RemovalPolicy.RETAIN,
        )
        log_group = logs.LogGroup(
            scope, "Logs", log_group_name=api.log_group, retention=api.log_retention, removal_policy=RemovalPolicy.DESTROY
        )

        task_definition = ecs.FargateTaskDefinition(
            scope,
            "TaskDefinition",
            cpu=api.cpu,
            memory_limit_mib=api.memory,
            task_role=task_role,
            execution_role=execution_role,
            runtime_platform=ecs.RuntimePlatform(
                cpu_architecture=ecs.CpuArchitecture.X86_64, operating_system_family=ecs.OperatingSystemFamily.LINUX
            ),
        )
        task_definition.add_container(
            "Api",
            image=ecs.ContainerImage.from_ecr_repository(repository, api.image_tag or PLACEHOLDER_TAG),
            environment=api.environment,
            secrets={JWT_SECRET_VARIABLE: ecs.Secret.from_secrets_manager(secret)},
            logging=ecs.LogDrivers.aws_logs(stream_prefix="api", log_group=log_group),
            port_mappings=[ecs.PortMapping(container_port=api.container_port)],
        )

        service_sg = ec2.SecurityGroup(scope, "ServiceSg", vpc=vpc, description="The API tasks.")
        return ecs.FargateService(
            scope,
            "Service",
            service_name=api.service,
            cluster=cluster,
            task_definition=task_definition,
            desired_count=api.desired_count,
            assign_public_ip=False,  # also when the subnet would hand one out
            vpc_subnets=private,
            security_groups=[service_sg],
            min_healthy_percent=100,
            max_healthy_percent=200,
            circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),
            enable_execute_command=True,  # the task role carries the SSM permissions for it
            health_check_grace_period=Duration.seconds(60),  # the container needs a moment before /health answers
        )

    def _load_balancer(self, scope: Construct, spec: AppSpec, vpc: ec2.IVpc, service: ecs.FargateService) -> elbv2.ApplicationLoadBalancer:
        """Internal, in the private subnets. Its only way in is CloudFront's VPC origin."""
        api = spec.api
        # No outbound by default: the rule to the tasks is added when they register as targets.
        security_group = ec2.SecurityGroup(
            scope, "LoadBalancerSg", vpc=vpc, description="The internal load balancer: CloudFront only.", allow_all_outbound=False
        )
        security_group.add_ingress_rule(ec2.Peer.prefix_list(api.cloudfront_prefix_list), ec2.Port.tcp(80), "CloudFront VPC origin")
        load_balancer = elbv2.ApplicationLoadBalancer(
            scope,
            "LoadBalancer",
            load_balancer_name=api.load_balancer,
            vpc=vpc,
            internet_facing=False,
            vpc_subnets=ec2.SubnetSelection(subnets=vpc.private_subnets),
            security_group=security_group,
            idle_timeout=Duration.seconds(api.alb_idle_timeout_seconds),
        )
        # open=False: the listener would otherwise allow the whole world in.
        listener = load_balancer.add_listener("Http", port=80, protocol=elbv2.ApplicationProtocol.HTTP, open=False)
        listener.add_targets(
            "Api",
            port=api.container_port,
            protocol=elbv2.ApplicationProtocol.HTTP,
            targets=[service],
            health_check=elbv2.HealthCheck(path=api.health_path, interval=Duration.seconds(15)),
            deregistration_delay=Duration.seconds(60),
        )
        return load_balancer

    def _web(self, scope: Construct, spec: AppSpec) -> cloudfront.Distribution:
        """The SPA in a private bucket behind CloudFront, over HTTPS only."""
        web = spec.web
        bucket = s3.Bucket(
            scope,
            "WebBucket",
            bucket_name=web.bucket,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            encryption=s3.BucketEncryption.S3_MANAGED,
            removal_policy=RemovalPolicy.RETAIN,
        )
        default_behavior = cloudfront.BehaviorOptions(
            origin=origins.S3BucketOrigin.with_origin_access_control(bucket),
            viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
        )
        if web.spa_fallback:
            rewrite = cloudfront.Function(
                scope, "SpaRewrite", code=cloudfront.FunctionCode.from_inline(SPA_REWRITE), runtime=cloudfront.FunctionRuntime.JS_2_0
            )
            default_behavior = cloudfront.BehaviorOptions(
                origin=default_behavior.origin,
                viewer_protocol_policy=default_behavior.viewer_protocol_policy,
                cache_policy=default_behavior.cache_policy,
                function_associations=[
                    cloudfront.FunctionAssociation(function=rewrite, event_type=cloudfront.FunctionEventType.VIEWER_REQUEST)
                ],
            )
        return cloudfront.Distribution(scope, "Distribution", default_behavior=default_behavior, default_root_object="index.html")

    def _api_routes(self, distribution: cloudfront.Distribution, spec: AppSpec, load_balancer: elbv2.ApplicationLoadBalancer) -> None:
        """Send the API's prefixes to the internal load balancer, untouched: same path, same method."""
        origin = origins.VpcOrigin.with_application_load_balancer(
            load_balancer,
            protocol_policy=cloudfront.OriginProtocolPolicy.HTTP_ONLY,  # inside the network, through the VPC origin
            read_timeout=Duration.seconds(spec.web.origin_read_timeout_seconds),
        )
        for path in spec.web.api_paths:
            distribution.add_behavior(
                path,
                origin,
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.HTTPS_ONLY,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                # Everything but Host: Authorization, cookies and the query string reach the API.
                origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                compress=False,  # compression could hold back the SSE events of a turn
            )

    def _outputs(self, spec: AppSpec, distribution: cloudfront.Distribution, service: ecs.FargateService) -> None:
        # Prefixed with the spec id so a second app in the same stack does not collide.
        for name, value in {
            "PublicUrl": f"https://{distribution.distribution_domain_name}",
            "DistributionId": distribution.distribution_id,
            "SpaBucket": spec.web.bucket,
            "RepositoryUri": f"{self.account}.dkr.ecr.{self.region}.{self.url_suffix}/{spec.api.repository}",
            "ClusterName": spec.api.cluster,
            "ServiceName": service.service_name,
        }.items():
            CfnOutput(self, f"{spec.id}{name}", value=value)
