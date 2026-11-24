import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Template

from definitions.app import app_specs
from definitions.network import network_specs
from deployment import DeployInputs
from stacks.app import AppStack
from stacks.network import NetworkStack
from tests.test_app_definitions import EXPECTED_VARIABLES, INPUTS
from tests.conftest import fixed_config

C = fixed_config()
ENV = cdk.Environment(account=C.aws_account, region=C.aws_region)


def synth(specs=None) -> Template:
    app = cdk.App()
    network = NetworkStack(app, C.network_stack, specs=network_specs(), nat_gateways=1, env=ENV)
    stack = AppStack(app, C.app_stack, specs=specs or app_specs(C, INPUTS), vpc=network.vpcs["Network"], env=ENV)
    return Template.from_stack(stack)


@pytest.fixture(scope="module")
def template() -> Template:
    return synth()


def only(template: Template, kind: str) -> dict:
    (resource,) = template.find_resources(kind).values()
    return resource


def container(template: Template) -> dict:
    (definition,) = only(template, "AWS::ECS::TaskDefinition")["Properties"]["ContainerDefinitions"]
    return definition


# --- compute: service, roles, logs, secret (3.2) ---


def test_names_come_from_the_configuration(template):
    assert only(template, "AWS::ECR::Repository")["Properties"]["RepositoryName"] == C.ecr_repository
    assert only(template, "AWS::ECS::Cluster")["Properties"]["ClusterName"] == C.cluster
    assert only(template, "AWS::ECS::Service")["Properties"]["ServiceName"] == C.service


def test_the_image_repository_is_kept_when_the_stack_goes(template):
    assert only(template, "AWS::ECR::Repository")["DeletionPolicy"] == "Retain"


def test_the_service_has_no_public_ip(template):
    network = only(template, "AWS::ECS::Service")["Properties"]["NetworkConfiguration"]["AwsvpcConfiguration"]
    assert network["AssignPublicIp"] == "DISABLED"


def test_the_service_runs_the_configured_tasks_on_fargate(template):
    service = only(template, "AWS::ECS::Service")["Properties"]
    assert service["LaunchType"] == "FARGATE" and service["DesiredCount"] == C.sizing("dev").desired_count


def test_without_an_image_the_service_has_no_tasks_and_still_deploys():
    template = synth(app_specs(C, DeployInputs(**{**vars(INPUTS), "image_tag": ""})))
    assert only(template, "AWS::ECS::Service")["Properties"]["DesiredCount"] == 0


def test_rolling_updates_never_drop_below_the_running_tasks_and_roll_back_on_failure(template):
    config_ = only(template, "AWS::ECS::Service")["Properties"]["DeploymentConfiguration"]
    assert (config_["MinimumHealthyPercent"], config_["MaximumPercent"]) == (100, 200)
    assert config_["DeploymentCircuitBreaker"] == {"Enable": True, "Rollback": True}


def test_the_task_is_sized_by_the_environment_and_runs_on_x86(template):
    properties = only(template, "AWS::ECS::TaskDefinition")["Properties"]
    dev = C.sizing("dev")
    assert (properties["Cpu"], properties["Memory"]) == (str(dev.cpu), str(dev.memory))
    assert properties["RuntimePlatform"]["CpuArchitecture"] == "X86_64"


def test_the_existing_roles_are_used_and_none_is_created(template):
    template.resource_count_is("AWS::IAM::Role", 0)
    properties = only(template, "AWS::ECS::TaskDefinition")["Properties"]
    assert properties["TaskRoleArn"] == C.role_arn(C.task_role)
    assert properties["ExecutionRoleArn"] == C.role_arn(C.execution_role)


def test_the_task_environment_is_exactly_the_contract_and_has_no_session_secret(template):
    environment = {e["Name"]: e["Value"] for e in container(template)["Environment"]}
    assert environment == EXPECTED_VARIABLES
    assert "AUTH_JWT_SECRET" not in environment


def test_the_session_secret_reaches_the_task_as_a_secret_not_as_text(template):
    (secret,) = container(template)["Secrets"]
    assert secret["Name"] == "AUTH_JWT_SECRET"
    assert "Ref" in secret["ValueFrom"]  # the secret's own ARN, never its value


def test_the_session_secret_is_generated_long_and_survives_the_stack(template):
    resource = only(template, "AWS::SecretsManager::Secret")
    assert resource["Properties"]["Name"] == C.auth_jwt_secret_name
    assert resource["Properties"]["GenerateSecretString"]["PasswordLength"] >= 32
    assert resource["DeletionPolicy"] == "Retain"


def test_logs_go_to_their_own_group_with_a_retention(template):
    properties = only(template, "AWS::Logs::LogGroup")["Properties"]
    assert properties["LogGroupName"] == C.log_group and properties["RetentionInDays"] == 30
    (logical_id,) = template.find_resources("AWS::Logs::LogGroup")
    assert container(template)["LogConfiguration"]["Options"]["awslogs-group"] == {"Ref": logical_id}


def test_the_harness_grants_are_attached_to_the_task_role_scoped_to_the_resolved_arns(template):
    policies = template.find_resources("AWS::IAM::Policy", {"Properties": {"Roles": [C.task_role]}})
    statements = [s for p in policies.values() for s in p["Properties"]["PolicyDocument"]["Statement"]]
    by_sid = {s["Sid"]: s for s in statements if "Sid" in s}
    assert set(by_sid) == {"InvokeHarness", "GetHarness", "HarnessMemoryEvents"}
    assert by_sid["HarnessMemoryEvents"]["Resource"] == INPUTS.memory_arn
    assert "memory/*" not in str(statements)


# --- load balancer and security groups (3.3) ---


def attributes(resource: dict) -> dict[str, str]:
    return {a["Key"]: a["Value"] for a in resource["Properties"].get("LoadBalancerAttributes", resource["Properties"].get("TargetGroupAttributes", []))}


def ingress_rules(template: Template) -> list[dict]:
    """Every ingress rule, whether inline on a security group or a standalone resource."""
    rules = [r["Properties"] for r in template.find_resources("AWS::EC2::SecurityGroupIngress").values()]
    for group in template.find_resources("AWS::EC2::SecurityGroup").values():
        rules += group["Properties"].get("SecurityGroupIngress", [])
    return rules


def logical_id(template: Template, kind: str, description: str) -> str:
    (found,) = [k for k, r in template.find_resources(kind).items() if description in r["Properties"].get("GroupDescription", "")]
    return found


def test_the_load_balancer_is_internal_and_named_from_the_configuration(template):
    properties = only(template, "AWS::ElasticLoadBalancingV2::LoadBalancer")["Properties"]
    assert properties["Scheme"] == "internal" and properties["Name"] == C.load_balancer


def test_the_load_balancer_waits_longer_than_cloudfront_before_closing_an_idle_connection(template):
    alb = only(template, "AWS::ElasticLoadBalancingV2::LoadBalancer")
    assert attributes(alb)["idle_timeout.timeout_seconds"] == "120"


def test_the_listener_is_plain_http_inside_the_network_and_nothing_is_open_to_the_world(template):
    listener = only(template, "AWS::ElasticLoadBalancingV2::Listener")["Properties"]
    assert (listener["Port"], listener["Protocol"]) == (80, "HTTP")
    assert not [r for r in ingress_rules(template) if r.get("CidrIp") == "0.0.0.0/0"]


def test_the_load_balancer_admits_only_the_cloudfront_prefix_list(template):
    alb_sg = logical_id(template, "AWS::EC2::SecurityGroup", "load balancer")
    from_prefix = [r for r in ingress_rules(template) if r.get("SourcePrefixListId")]
    assert [(r["SourcePrefixListId"], r["FromPort"], r["ToPort"]) for r in from_prefix] == [(INPUTS.cloudfront_prefix_list, 80, 80)]
    assert [r["GroupId"] for r in from_prefix] == [{"Fn::GetAtt": [alb_sg, "GroupId"]}]


def test_the_tasks_admit_only_the_load_balancer_on_the_container_port(template):
    alb_sg = logical_id(template, "AWS::EC2::SecurityGroup", "load balancer")
    service_sg = logical_id(template, "AWS::EC2::SecurityGroup", "API tasks")
    to_tasks = [r for r in ingress_rules(template) if r.get("GroupId") == {"Fn::GetAtt": [service_sg, "GroupId"]}]
    assert [(r["SourceSecurityGroupId"], r["FromPort"]) for r in to_tasks] == [({"Fn::GetAtt": [alb_sg, "GroupId"]}, 8000)]


def test_the_target_group_checks_health_and_drains_before_removing_a_task(template):
    group = only(template, "AWS::ElasticLoadBalancingV2::TargetGroup")
    properties = group["Properties"]
    assert properties["HealthCheckPath"] == "/health" and properties["Port"] == 8000 and properties["TargetType"] == "ip"
    assert attributes(group)["deregistration_delay.timeout_seconds"] == "60"


def test_the_service_is_registered_with_the_target_group(template):
    service = only(template, "AWS::ECS::Service")["Properties"]
    assert [lb["ContainerPort"] for lb in service["LoadBalancers"]] == [8000]
    assert service["HealthCheckGracePeriodSeconds"] == 60


# --- SPA bucket and distribution (3.4) ---


def distribution(template: Template) -> dict:
    return only(template, "AWS::CloudFront::Distribution")["Properties"]["DistributionConfig"]


def test_the_spa_bucket_is_named_from_the_configuration_and_fully_private(template):
    bucket = only(template, "AWS::S3::Bucket")
    assert bucket["Properties"]["BucketName"] == C.web_bucket
    assert bucket["Properties"]["PublicAccessBlockConfiguration"] == {
        "BlockPublicAcls": True, "BlockPublicPolicy": True, "IgnorePublicAcls": True, "RestrictPublicBuckets": True,
    }


def test_the_bucket_requires_tls_and_only_cloudfront_may_read_it(template):
    statements = only(template, "AWS::S3::BucketPolicy")["Properties"]["PolicyDocument"]["Statement"]
    assert any(s["Effect"] == "Deny" and s["Condition"] == {"Bool": {"aws:SecureTransport": "false"}} for s in statements)
    readers = [s for s in statements if s["Effect"] == "Allow"]
    assert readers and all(s["Principal"] == {"Service": "cloudfront.amazonaws.com"} for s in readers)
    assert all("AWS:SourceArn" in str(s["Condition"]) or "aws:SourceArn" in str(s["Condition"]) for s in readers)


def test_the_spa_is_served_through_origin_access_control(template):
    template.resource_count_is("AWS::CloudFront::OriginAccessControl", 1)
    (origin,) = [o for o in distribution(template)["Origins"] if "S3OriginConfig" in o]
    assert origin["OriginAccessControlId"] and origin["S3OriginConfig"] == {"OriginAccessIdentity": ""}


def test_the_default_route_serves_the_spa_over_https_only(template):
    default = distribution(template)["DefaultCacheBehavior"]
    assert default["ViewerProtocolPolicy"] == "redirect-to-https"
    assert distribution(template)["DefaultRootObject"] == "index.html"


def test_client_side_routes_are_rewritten_to_the_entry_page_on_the_default_route_only(template):
    function = only(template, "AWS::CloudFront::Function")["Properties"]
    assert function["FunctionConfig"]["Runtime"] == "cloudfront-js-2.0"
    assert "/index.html" in function["FunctionCode"]
    (association,) = distribution(template)["DefaultCacheBehavior"]["FunctionAssociations"]
    assert association["EventType"] == "viewer-request"


def test_distribution_level_error_pages_are_not_defined_so_api_errors_pass_through_untouched(template):
    assert "CustomErrorResponses" not in distribution(template)


# --- API routes through CloudFront and outputs (3.5) ---

from dataclasses import replace

from aws_cdk import aws_cloudfront as cloudfront

API_PATHS = ("/api/*", "/auth/*")


def behaviors(template: Template) -> dict[str, dict]:
    return {b["PathPattern"]: b for b in distribution(template)["CacheBehaviors"]}


def test_exactly_the_two_reserved_prefixes_go_to_the_api(template):
    assert set(behaviors(template)) == set(API_PATHS)


@pytest.mark.parametrize("path", API_PATHS)
def test_api_routes_are_never_cached_and_forward_authorization_and_the_query(template, path):
    behavior = behaviors(template)[path]
    assert behavior["CachePolicyId"] == cloudfront.CachePolicy.CACHING_DISABLED.cache_policy_id
    assert behavior["OriginRequestPolicyId"] == cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER.origin_request_policy_id


@pytest.mark.parametrize("path", API_PATHS)
def test_api_routes_are_https_only_pass_every_method_and_are_not_compressed(template, path):
    behavior = behaviors(template)[path]
    assert behavior["ViewerProtocolPolicy"] == "https-only"
    assert set(behavior["AllowedMethods"]) == {"GET", "HEAD", "OPTIONS", "PUT", "PATCH", "POST", "DELETE"}
    assert behavior["Compress"] is False  # a compressing edge could hold SSE events back
    assert "FunctionAssociations" not in behavior  # the SPA rewrite never touches the API


def test_api_routes_reach_the_load_balancer_through_a_vpc_origin_waiting_sixty_seconds(template):
    origin_ids = {b["TargetOriginId"] for b in behaviors(template).values()}
    (api_origin,) = [o for o in distribution(template)["Origins"] if o["Id"] in origin_ids]
    assert api_origin["VpcOriginConfig"]["OriginReadTimeout"] == 60
    endpoint = only(template, "AWS::CloudFront::VpcOrigin")["Properties"]["VpcOriginEndpointConfig"]
    assert endpoint["OriginProtocolPolicy"] == "http-only" and endpoint.get("HTTPPort", 80) == 80


def test_the_six_outputs_the_deploy_script_reads_exist(template):
    outputs = template.to_json()["Outputs"]
    assert {"AppPublicUrl", "AppDistributionId", "AppSpaBucket", "AppRepositoryUri", "AppClusterName", "AppServiceName"} <= set(outputs)
    assert str(outputs["AppPublicUrl"]["Value"]).startswith("{'Fn::Join': ['', ['https://'")


def test_a_second_app_spec_gets_its_own_resources_without_editing_the_stack():
    (first,) = app_specs(C, INPUTS)
    second = replace(
        first,
        id="Second",
        api=replace(first.api, repository="other-repo", cluster="other-cluster", service="other-service",
                    load_balancer="other-alb", log_group="/other/api", jwt_secret_name="other/secret"),
        web=replace(first.web, bucket="other-bucket"),
    )
    template = synth([first, second])
    for kind in ("AWS::ECS::Service", "AWS::CloudFront::Distribution", "AWS::S3::Bucket", "AWS::ECR::Repository"):
        template.resource_count_is(kind, 2)
    assert {"AppPublicUrl", "SecondPublicUrl"} <= set(template.to_json()["Outputs"])


def test_the_load_balancer_can_only_talk_back_to_the_tasks(template):
    alb_sg = logical_id(template, "AWS::EC2::SecurityGroup", "load balancer")
    service_sg = logical_id(template, "AWS::EC2::SecurityGroup", "API tasks")
    group = template.find_resources("AWS::EC2::SecurityGroup")[alb_sg]["Properties"]
    # CDK writes the "no outbound" default as a rule that matches nothing (255.255.255.255/32).
    assert all(r.get("CidrIp") == "255.255.255.255/32" for r in group.get("SecurityGroupEgress", []))
    egress = [r["Properties"] for r in template.find_resources("AWS::EC2::SecurityGroupEgress").values() if r["Properties"]["GroupId"] == {"Fn::GetAtt": [alb_sg, "GroupId"]}]
    assert [(r["DestinationSecurityGroupId"], r["FromPort"]) for r in egress] == [({"Fn::GetAtt": [service_sg, "GroupId"]}, 8000)]
