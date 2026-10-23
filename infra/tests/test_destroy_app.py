"""scripts/destroy_app.py against an in-memory account that records every deletion in the order it happens."""

import importlib.util
import sys
from pathlib import Path

import pytest
from botocore.exceptions import ClientError, WaiterError

import config
from tests.test_config import VALID, write

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
_spec = importlib.util.spec_from_file_location("destroy_app", SCRIPTS / "destroy_app.py")
destroy_app = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(destroy_app)

ACCOUNT = "111122223333"  # what VALID configures; the project is "acme-portal"
HARNESS_ID = "acmeportal_assistant-AbC123"
POOL = "eu-west-1_AbCdEf"
VPC = "vpc-0123abcd"
OTHER_VPC = "vpc-0fffffff"
EXISTING = f'\n[network]\nvpc_id = "{VPC}"\nprivate_subnets = {{ eu-west-1a = "subnet-0a1b2c3d", eu-west-1b = "subnet-4e5f6a7b" }}\n'


def err(code: str, message: str = "boom") -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": message}}, "Op")


def tagged(project: str, name: str) -> list[dict]:
    return [{"Key": "Project", "Value": project}, {"Key": "Name", "Value": name}]


class World:
    """The account. It has no method to delete a VPC, so any attempt to is an AttributeError; `log` is the order of deletions."""

    def __init__(self, c: config.Config, *, harness=True):
        self.c, self.log, self.account = c, [], ACCOUNT
        self.fail: dict[str, ClientError] = {}  # "<call>:<id>" -> error to raise
        self.waiter_fail: set[str] = set()  # waiters that end in a WaiterError (a stack that ends DELETE_FAILED, a timeout)
        self.deny: set[str] = set()  # read calls that answer AccessDenied
        self.versions: dict[str, list[dict]] = {}
        self.s3_errors = False
        self.delete_batches: list[int] = []
        self.stacks = {c.app_stack, c.network_stack, c.roles_stack, c.auth_stack, c.data_stack}
        if harness:
            self.stacks.add(c.harness_stack)
        self.repos, self.secrets = {c.ecr_repository}, {c.auth_jwt_secret_name}
        self.buckets = {c.web_bucket: {"index.html", "assets/a.js"}}
        self.dynamo_tables = {c.sessions_table, c.items_table}
        self.pools = {POOL: "acme-portal-111122223333"}
        self.endpoints = ["DEFAULT", "PROD"]
        # a network prepared by prepare_network.py, plus things that must survive
        self.nats = [{"NatGatewayId": "nat-ours", "VpcId": VPC, "State": "available", "Tags": tagged(c.name, f"{c.name}-nat")},
                     {"NatGatewayId": "nat-other-project", "VpcId": VPC, "State": "available", "Tags": tagged("another", "another-nat")},
                     {"NatGatewayId": "nat-untagged", "VpcId": VPC, "State": "available", "Tags": []}]
        self.subnets = [{"SubnetId": "subnet-ours-a", "VpcId": VPC, "Tags": tagged(c.name, f"{c.name}-private-a")},
                        {"SubnetId": "subnet-ours-b", "VpcId": VPC, "Tags": tagged(c.name, f"{c.name}-private-b")},
                        {"SubnetId": "subnet-public", "VpcId": VPC, "Tags": []}]
        self.route_tables = [{"RouteTableId": "rtb-ours", "VpcId": VPC, "Tags": tagged(c.name, f"{c.name}-private"),
                              "Associations": [{"RouteTableAssociationId": "assoc-a", "SubnetId": "subnet-ours-a", "Main": False},
                                               {"RouteTableAssociationId": "assoc-b", "SubnetId": "subnet-ours-b", "Main": False}]},
                             {"RouteTableId": "rtb-main", "VpcId": VPC, "Tags": [], "Associations": [{"RouteTableAssociationId": "assoc-m", "Main": True}]}]
        self.addresses = [{"AllocationId": "eipalloc-ours", "NatGatewayId": "nat-ours", "Tags": tagged(c.name, f"{c.name}-nat")},
                          {"AllocationId": "eipalloc-other", "Tags": []}]

    def maybe_fail(self, key):
        if key in self.fail:
            raise self.fail[key]

    def waiter(self, name):
        world = self

        class Waiter:
            def wait(self, **kwargs):
                if name in world.waiter_fail:
                    raise WaiterError(name=name, reason="Waiter encountered a terminal failure state", last_response={})
                if name == "nat_gateway_deleted":  # only now is the NAT gone and its address free
                    for nat in world.nats:
                        if nat["NatGatewayId"] in kwargs.get("NatGatewayIds", []):
                            nat["State"] = "deleted"

        return Waiter()

    # -------- boto3 surface
    def client(self, name):
        return getattr(self, "_" + name.replace("-", "_"))()

    def _sts(self):
        world = self
        return type("Sts", (), {"get_caller_identity": lambda self: {"Account": world.account}})()

    def _cloudformation(self):
        world, c = self, self.c

        class Cfn:
            def describe_stacks(self, StackName):
                if StackName not in world.stacks:
                    raise err("ValidationError", f"Stack with id {StackName} does not exist")
                outputs = {
                    c.auth_stack: {"UserPoolId": POOL},
                    c.harness_stack: {"ApplicationHarnessAssistantArnOutputAB12": f"arn:aws:bedrock-agentcore:eu-west-1:{ACCOUNT}:harness/{HARNESS_ID}"},
                }.get(StackName, {})
                return {"Stacks": [{"Outputs": [{"OutputKey": k, "OutputValue": v} for k, v in outputs.items()]}]}

            def delete_stack(self, StackName):
                world.maybe_fail(f"delete_stack:{StackName}")
                world.log.append(f"stack:{StackName}")
                world.stacks.discard(StackName)

            def get_waiter(self, name):
                return world.waiter(name)

        return Cfn()

    def _ecr(self):
        world = self

        class Ecr:
            def describe_repositories(self, repositoryNames):
                if repositoryNames[0] not in world.repos:
                    raise err("RepositoryNotFoundException")
                return {"repositories": [{}]}

            def delete_repository(self, repositoryName, force):
                assert force is True
                world.maybe_fail(f"delete_repository:{repositoryName}")
                world.log.append(f"ecr:{repositoryName}")
                world.repos.discard(repositoryName)

        return Ecr()

    def _secretsmanager(self):
        world = self

        class Secrets:
            def describe_secret(self, SecretId):
                if SecretId not in world.secrets:
                    raise err("ResourceNotFoundException")
                return {}

            def delete_secret(self, SecretId, ForceDeleteWithoutRecovery):
                assert ForceDeleteWithoutRecovery is True
                world.log.append(f"secret:{SecretId}")
                world.secrets.discard(SecretId)

        return Secrets()

    def _s3(self):
        world = self

        class Paginator:
            def __init__(self, kind):
                self.kind = kind

            def paginate(self, Bucket):
                keys = sorted(world.buckets.get(Bucket, []))
                if self.kind == "list_objects_v2":
                    return [{"Contents": [{"Key": k} for k in keys[i : i + 1500]]} for i in range(0, len(keys), 1500)] or [{}]
                versions = world.versions.get(Bucket, [])
                return [{"Versions": [v for v in versions if not v.get("marker")], "DeleteMarkers": [v for v in versions if v.get("marker")]}]

        class S3:
            def head_bucket(self, Bucket):
                if "head_bucket" in world.deny:
                    raise err("AccessDenied", "forbidden")
                if Bucket not in world.buckets:
                    raise err("404")

            def get_paginator(self, name):
                return Paginator(name)

            def delete_objects(self, Bucket, Delete):
                assert Delete.get("Quiet") is True and len(Delete["Objects"]) <= 1000  # Quiet lives inside Delete in the real API
                world.delete_batches.append(len(Delete["Objects"]))
                if world.s3_errors:
                    return {"Errors": [{"Key": Delete["Objects"][0]["Key"], "Code": "AccessDenied"}]}
                for obj in Delete["Objects"]:
                    if "VersionId" in obj:
                        world.versions[Bucket] = [v for v in world.versions[Bucket] if (v["Key"], v["VersionId"]) != (obj["Key"], obj["VersionId"])]
                    else:
                        world.buckets[Bucket].discard(obj["Key"])
                if world.log[-1:] != [f"s3-empty:{Bucket}"]:
                    world.log.append(f"s3-empty:{Bucket}")
                return {}

            def delete_bucket(self, Bucket):
                if world.buckets[Bucket] or world.versions.get(Bucket):
                    raise err("BucketNotEmpty")
                world.log.append(f"s3:{Bucket}")
                del world.buckets[Bucket]

        return S3()

    @staticmethod
    def _is_ours(resource, filters):
        for f in filters or []:
            if f["Name"] == "vpc-id" and resource.get("VpcId") not in f["Values"]:
                return False
            if f["Name"] == "tag:Project":
                if {t["Key"]: t["Value"] for t in resource.get("Tags", [])}.get("Project") not in f["Values"]:
                    return False
            if f["Name"] == "state" and resource.get("State") not in f["Values"]:
                return False
        return True

    def _ec2(self):
        world = self

        class Ec2:
            def describe_nat_gateways(self, Filter):
                return {"NatGateways": [n for n in world.nats if world._is_ours(n, Filter) and n["State"] != "deleted"]}

            def delete_nat_gateway(self, NatGatewayId):
                assert next(n for n in world.nats if n["NatGatewayId"] == NatGatewayId)["State"] != "deleting", "already being deleted"
                world.log.append(f"nat:{NatGatewayId}")
                next(n for n in world.nats if n["NatGatewayId"] == NatGatewayId)["State"] = "deleting"  # until its waiter returns

            def describe_route_tables(self, Filters):
                return {"RouteTables": [t for t in world.route_tables if world._is_ours(t, Filters)]}

            def disassociate_route_table(self, AssociationId):
                world.log.append(f"disassociate:{AssociationId}")
                for t in world.route_tables:
                    t["Associations"] = [a for a in t["Associations"] if a["RouteTableAssociationId"] != AssociationId]

            def delete_route_table(self, RouteTableId):
                world.log.append(f"route-table:{RouteTableId}")
                world.route_tables = [t for t in world.route_tables if t["RouteTableId"] != RouteTableId]

            def describe_subnets(self, Filters):
                return {"Subnets": [s for s in world.subnets if world._is_ours(s, Filters)]}

            def delete_subnet(self, SubnetId):
                world.maybe_fail(f"delete_subnet:{SubnetId}")
                world.log.append(f"subnet:{SubnetId}")
                world.subnets = [s for s in world.subnets if s["SubnetId"] != SubnetId]

            def describe_addresses(self, Filters):
                return {"Addresses": [a for a in world.addresses if world._is_ours(a, Filters)]}

            def release_address(self, AllocationId):
                holder = next((a.get("NatGatewayId") for a in world.addresses if a["AllocationId"] == AllocationId), None)
                if holder and next(n for n in world.nats if n["NatGatewayId"] == holder)["State"] != "deleted":
                    raise err("InvalidIPAddress.InUse", "the address is still held by a NAT gateway")
                world.log.append(f"eip:{AllocationId}")
                world.addresses = [a for a in world.addresses if a["AllocationId"] != AllocationId]

            def get_waiter(self, name):
                assert name == "nat_gateway_deleted"
                return world.waiter(name)

        return Ec2()

    def _dynamodb(self):
        world = self

        class Dynamo:
            def describe_table(self, TableName):
                if TableName not in world.dynamo_tables:
                    raise err("ResourceNotFoundException")
                return {}

            def delete_table(self, TableName):
                world.log.append(f"table:{TableName}")
                world.dynamo_tables.discard(TableName)

            def get_waiter(self, name):
                return type("W", (), {"wait": lambda self, **_: None})()

        return Dynamo()

    def _cognito_idp(self):
        world = self

        class Cognito:
            def list_user_pools(self, MaxResults, NextToken=None):
                return {"UserPools": [{"Id": pool, "Name": world.c.user_pool} for pool in world.pools]}

            def describe_user_pool(self, UserPoolId):
                if UserPoolId not in world.pools:
                    raise err("ResourceNotFoundException")
                return {"UserPool": {"Domain": world.pools[UserPoolId]}}

            def delete_user_pool_domain(self, Domain, UserPoolId):
                world.log.append(f"pool-domain:{Domain}")
                world.pools[UserPoolId] = ""

            def delete_user_pool(self, UserPoolId):
                world.log.append(f"pool:{UserPoolId}")
                del world.pools[UserPoolId]

        return Cognito()

    def _bedrock_agentcore_control(self):
        world = self

        class Control:
            def list_harness_endpoints(self, harnessId, **_):
                return {"endpoints": [{"endpointName": n} for n in world.endpoints]}

            def delete_harness_endpoint(self, harnessId, endpointName):
                assert endpointName != "DEFAULT", "the default endpoint belongs to the harness and goes with it"
                world.log.append(f"endpoint:{endpointName}")
                world.endpoints.remove(endpointName)

        return Control()


@pytest.fixture
def c(tmp_path) -> config.Config:
    return config.load(write(tmp_path, VALID))


def run(c, world, *args):
    return destroy_app.main([*args], cfg=c, session=type("S", (), {"client": lambda self, name: world.client(name)})(), sleep=lambda _: None)


def confirm(c) -> list[str]:
    return ["--confirm", c.name]


# ------------------------------------------------------------------ the plan and the confirmation


def test_without_confirmation_it_shows_the_plan_and_deletes_nothing(c, capsys):
    world = World(c)
    assert run(c, world) == 0
    out = capsys.readouterr().out
    assert world.log == []
    assert c.app_stack in out and c.ecr_repository in out and "nat-ours" in out and "--confirm" in out and "USD" in out


def test_a_confirmation_that_is_not_the_project_name_is_refused_and_deletes_nothing(c, capsys):
    world = World(c)
    assert run(c, world, "--confirm", "something-else") == 1
    assert world.log == [] and c.name in capsys.readouterr().err


def test_credentials_for_another_account_stop_it_before_anything_is_deleted(c, capsys):
    world = World(c)
    world.account = "999999999999"
    assert run(c, world, *confirm(c)) == 1
    assert world.log == [] and "999999999999" in capsys.readouterr().err


# ------------------------------------------------------------------ the default run: the app and its network


def position(world, entry):
    return world.log.index(entry)


def test_the_app_goes_first_and_the_network_pieces_in_dependency_order(c):
    world = World(c)
    assert run(c, world, *confirm(c)) == 0
    p = lambda e: position(world, e)  # noqa: E731
    assert p(f"stack:{c.app_stack}") < p(f"ecr:{c.ecr_repository}") < p(f"s3:{c.web_bucket}")
    assert p(f"stack:{c.app_stack}") < p(f"stack:{c.network_stack}") < p("nat:nat-ours")
    assert p("nat:nat-ours") < p("eip:eipalloc-ours")  # an address is released only after the NAT that held it is gone
    assert p("disassociate:assoc-a") < p("route-table:rtb-ours")
    assert p("nat:nat-ours") < p("subnet:subnet-ours-a") and p("nat:nat-ours") < p("subnet:subnet-ours-b")


def test_the_bucket_is_emptied_before_it_is_deleted(c):
    world = World(c)
    run(c, world, *confirm(c))
    assert position(world, f"s3-empty:{c.web_bucket}") < position(world, f"s3:{c.web_bucket}")


def test_the_session_secret_is_deleted_without_a_recovery_window(c):
    world = World(c)
    run(c, world, *confirm(c))
    assert f"secret:{c.auth_jwt_secret_name}" in world.log and not world.secrets


def test_only_what_the_project_owns_goes_not_other_projects_or_untagged_resources(c):
    world = World(c)
    run(c, world, *confirm(c))
    assert [n["NatGatewayId"] for n in world.nats if n["State"] != "deleted"] == ["nat-other-project", "nat-untagged"]
    assert [s["SubnetId"] for s in world.subnets] == ["subnet-public"]
    assert [t["RouteTableId"] for t in world.route_tables] == ["rtb-main"]
    assert [a["AllocationId"] for a in world.addresses] == ["eipalloc-other"]
    assert world.route_tables[0]["Associations"] == [{"RouteTableAssociationId": "assoc-m", "Main": True}]  # the main table is untouched


def test_a_main_route_table_is_never_touched_even_if_someone_tagged_it_with_the_project(c):
    world = World(c)
    main = next(t for t in world.route_tables if t["RouteTableId"] == "rtb-main")
    main["Tags"] = tagged(c.name, "mistaken")
    run(c, world, *confirm(c))
    assert "route-table:rtb-main" not in world.log and "disassociate:assoc-m" not in world.log
    assert any(t["RouteTableId"] == "rtb-main" for t in world.route_tables)


def test_the_data_sign_in_harness_and_roles_stay_by_default(c, capsys):
    world = World(c)
    run(c, world, *confirm(c))
    assert {c.data_stack, c.auth_stack, c.roles_stack, c.harness_stack} <= world.stacks
    assert world.dynamo_tables == {c.sessions_table, c.items_table}
    assert POOL in world.pools
    assert "--everything" in capsys.readouterr().out


def test_it_never_deletes_a_vpc_nor_anything_in_a_vpc_it_does_not_own(c):
    world = World(c)
    run(c, world, "--everything", *confirm(c))  # World has no delete-VPC method: an attempt would raise AttributeError
    assert not any(entry.startswith("vpc:") for entry in world.log)


# ------------------------------------------------------------------ --everything


def test_everything_adds_the_harness_then_the_data_then_sign_in_then_the_roles_in_that_order(c):
    world = World(c)
    assert run(c, world, "--everything", *confirm(c)) == 0
    p = lambda e: position(world, e)  # noqa: E731
    assert p("endpoint:PROD") < p(f"stack:{c.harness_stack}")
    assert p(f"stack:{c.app_stack}") < p(f"stack:{c.harness_stack}") < p(f"table:{c.sessions_table}")
    assert p(f"table:{c.sessions_table}") < p(f"stack:{c.data_stack}")
    assert p(f"pool-domain:acme-portal-111122223333") < p(f"pool:{POOL}") < p(f"stack:{c.auth_stack}")
    assert p(f"stack:{c.auth_stack}") < p(f"stack:{c.roles_stack}")
    assert world.stacks == set() and world.pools == {} and world.dynamo_tables == set()


def test_the_default_endpoint_is_left_to_the_harness_and_only_ours_is_deleted(c):
    world = World(c)
    run(c, world, "--everything", *confirm(c))
    assert "endpoint:DEFAULT" not in world.log and "endpoint:PROD" in world.log


def test_a_harness_the_project_does_not_own_is_never_touched(tmp_path):
    arn = f"arn:aws:bedrock-agentcore:eu-west-1:{ACCOUNT}:harness/someone-elses-XyZ789"
    c = config.load(write(tmp_path, VALID.replace('arn = ""', f'arn = "{arn}"')))
    world = World(c, harness=False)
    assert run(c, world, "--everything", *confirm(c)) == 0
    assert not any("harness" in e or e.startswith("endpoint") for e in world.log)


# ------------------------------------------------------------------ robustness


def test_running_it_again_after_everything_is_gone_deletes_nothing_and_succeeds(c, capsys):
    world = World(c)
    run(c, world, "--everything", *confirm(c))
    world.log.clear()
    assert run(c, world, "--everything", *confirm(c)) == 0
    assert world.log == [] and "nothing" in capsys.readouterr().out.lower()


def test_a_failed_deletion_is_reported_and_what_depended_on_it_is_not_attempted(c, capsys):
    world = World(c)
    world.fail[f"delete_stack:{c.app_stack}"] = err("AccessDenied")
    assert run(c, world, *confirm(c)) == 1
    out = capsys.readouterr()
    assert c.app_stack in out.err + out.out and "AccessDenied" in out.err + out.out
    # the registry, the bucket and every network piece depend on the app: none was touched
    assert f"ecr:{c.ecr_repository}" not in world.log and not any(e.startswith(("nat:", "subnet:", "eip:")) for e in world.log)


def test_a_failure_in_one_independent_step_does_not_stop_the_others(c):
    world = World(c)
    world.fail[f"delete_repository:{c.ecr_repository}"] = err("AccessDenied")
    assert run(c, world, *confirm(c)) == 1
    assert f"s3:{c.web_bucket}" in world.log and "nat:nat-ours" in world.log


def test_the_end_lists_what_still_exists(c, capsys):
    world = World(c)
    world.fail[f"delete_subnet:subnet-ours-a"] = err("DependencyViolation")
    sleeper = lambda _: None  # noqa: E731
    destroy_app.main([*confirm(c)], cfg=c, session=type("S", (), {"client": lambda self, name: world.client(name)})(), sleep=sleeper)
    assert "subnet-ours-a" in capsys.readouterr().out.split("Still exists")[-1]


def test_a_subnet_that_is_still_in_use_is_retried_before_giving_up(c):
    """Right after the app goes, its network interfaces linger for a minute and block the subnets."""
    world = World(c)
    attempts = []
    real = world.client("ec2")

    class Flaky:
        def __getattr__(self, name):
            return getattr(real, name)

        def delete_subnet(self, SubnetId):
            attempts.append(SubnetId)
            if len(attempts) < 3:
                raise err("DependencyViolation")
            return real.delete_subnet(SubnetId=SubnetId)

    session = type("S", (), {"client": lambda self, name: Flaky() if name == "ec2" else world.client(name)})()
    assert destroy_app.main([*confirm(c)], cfg=c, session=session, sleep=lambda _: None) == 0
    assert len(attempts) >= 3 and "subnet-ours-a" not in [s["SubnetId"] for s in world.subnets]


# ------------------------------------------------------------------ what a review of the first version found


def test_a_waiter_that_ends_in_failure_is_reported_and_the_run_goes_on_instead_of_ending_in_a_traceback(c, capsys):
    """A stack that ends DELETE_FAILED (a role in use, a network interface) or a timeout is a WaiterError, not a ClientError."""
    world = World(c)
    world.waiter_fail.add("stack_delete_complete")
    assert run(c, world, *confirm(c)) == 1
    out = capsys.readouterr()
    assert c.app_stack in out.err and "Still exists" in out.out  # the summary was still printed
    assert f"ecr:{c.ecr_repository}" not in world.log  # what depended on the app was not attempted


def test_a_nat_that_fails_to_delete_is_reported_and_its_address_and_subnets_are_left_alone(c, capsys):
    world = World(c)
    world.waiter_fail.add("nat_gateway_deleted")
    assert run(c, world, *confirm(c)) == 1
    assert "eip:eipalloc-ours" not in world.log and not any(e.startswith("subnet:") for e in world.log)
    assert "Still exists" in capsys.readouterr().out


def test_a_read_that_is_denied_is_reported_and_the_steps_that_do_not_depend_on_it_still_run(c, capsys):
    world = World(c)
    world.deny.add("head_bucket")
    assert run(c, world, *confirm(c)) == 1
    out = capsys.readouterr()
    assert "bucket" in out.err.lower() and "AccessDenied" in out.err
    assert "nat:nat-ours" in world.log and f"ecr:{c.ecr_repository}" in world.log
    assert "Could not check" in out.out and "SPA bucket" in out.out  # what it could not see is listed, not assumed gone


def test_the_plan_does_not_end_in_a_traceback_when_a_read_is_denied(c, capsys):
    world = World(c)
    world.deny.add("head_bucket")
    assert run(c, world) == 0
    assert "AccessDenied" in capsys.readouterr().out


def test_a_nat_that_is_already_being_deleted_is_waited_for_not_deleted_again_and_its_address_waits_for_it(c):
    world = World(c)
    world.nats[0]["State"] = "deleting"
    assert run(c, world, *confirm(c)) == 0  # FakeEc2 refuses a second delete of a NAT that is "deleting"
    assert "nat:nat-ours" not in world.log
    assert "eip:eipalloc-ours" in world.log


def test_every_version_and_delete_marker_and_batches_of_at_most_a_thousand_go_before_the_bucket(c):
    world = World(c)
    world.buckets[c.web_bucket] = {f"assets/f{i}.js" for i in range(2500)}
    world.versions[c.web_bucket] = [{"Key": "index.html", "VersionId": "v1"}, {"Key": "index.html", "VersionId": "v2", "marker": True}]
    assert run(c, world, *confirm(c)) == 0
    assert c.web_bucket not in world.buckets
    assert max(world.delete_batches) <= 1000 and sum(world.delete_batches) == 2500 + 2


def test_an_object_that_could_not_be_deleted_is_a_reported_failure_and_the_bucket_is_not_deleted(c, capsys):
    world = World(c)
    world.s3_errors = True
    assert run(c, world, *confirm(c)) == 1
    assert f"s3:{c.web_bucket}" not in world.log and "AccessDenied" in capsys.readouterr().err


def test_with_an_existing_vpc_only_its_tagged_resources_go_not_a_tagged_one_in_another_vpc(tmp_path):
    c = config.load(write(tmp_path, VALID + EXISTING))
    world = World(c)
    world.subnets.append({"SubnetId": "subnet-elsewhere", "VpcId": OTHER_VPC, "Tags": tagged(c.name, f"{c.name}-private-z")})
    world.nats.append({"NatGatewayId": "nat-elsewhere", "VpcId": OTHER_VPC, "State": "available", "Tags": tagged(c.name, f"{c.name}-nat")})
    assert run(c, world, *confirm(c)) == 0
    assert "subnet:subnet-elsewhere" not in world.log and "nat:nat-elsewhere" not in world.log
    assert "subnet:subnet-ours-a" in world.log and "nat:nat-ours" in world.log


def test_the_route_table_waits_for_the_template_network_stack_as_the_other_network_pieces_do(c):
    world = World(c)
    world.fail[f"delete_stack:{c.network_stack}"] = err("AccessDenied")
    assert run(c, world, *confirm(c)) == 1
    assert "route-table:rtb-ours" not in world.log
