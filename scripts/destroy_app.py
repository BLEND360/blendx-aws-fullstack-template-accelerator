"""Delete what the project deployed, so it stops costing money.

    uv run --project infra python scripts/destroy_app.py                              # the plan: nothing is deleted
    uv run --project infra python scripts/destroy_app.py --confirm <project-name>     # the app and its network
    uv run --project infra python scripts/destroy_app.py --confirm <project-name> --everything

By default it removes the app (CloudFormation stack, then the container repository, the session secret and
the SPA bucket that the stack keeps) and the network: the template's own network stack, and the network
that `prepare_network.py` added to the existing VPC of project.toml's [network] (found by its Project tag and
name, inside that VPC). With --everything it also
removes the harness, the DynamoDB tables, the user pool and the roles: the data and the accounts, which
are not recoverable. It always prints the plan first, and deletes only after `--confirm` carries the
project's name.

It only touches resources whose name derives from project.toml or, inside the [network] VPC, that
`prepare_network.py` tagged and named for the project, and never a VPC. The account-level pieces (CDK bootstrap, the GitHub OIDC provider) are shared and are left.
Every step tolerates a resource that is already gone, and a step whose prerequisite failed is skipped, so
running it again finishes the job. The last thing it prints is whatever still exists.
"""

import argparse
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "infra"))

import boto3  # noqa: E402
from botocore.exceptions import ClientError, WaiterError  # noqa: E402

import config  # noqa: E402
import harness_resolve  # noqa: E402
from awsutil import APP_PER_DAY, NAT_PER_DAY, DeployError, check_account, cli, load_config, owned_filters  # noqa: E402

WAIT = {"Delay": 15, "MaxAttempts": 120}  # up to 30 minutes: a CloudFront distribution is slow to go


class DestroyError(DeployError):
    pass


@dataclass
class Step:
    key: str
    label: str
    items: Callable[[], list[str]]  # what exists now; empty means there is nothing to delete
    delete: Callable[[], None]
    after: tuple[str, ...] = ()  # steps that must be done (or have nothing to do) first
    keeps: str = ""  # for the default run: why this is kept and what removes it

    def check(self) -> tuple[list[str], str | None]:
        """(what exists, why it could not be checked). Never raises: a denied read must not end the run."""
        try:
            return self.items(), None
        except ClientError as e:
            return [], describe(e)


def describe(error: Exception) -> str:
    if isinstance(error, ClientError):
        return f"{error.response['Error']['Code']} ({error.response['Error']['Message']})"
    return str(error)


def _missing(error: ClientError) -> bool:
    code = error.response["Error"]["Code"]
    return code in ("ResourceNotFoundException", "RepositoryNotFoundException", "404", "NoSuchBucket", "NotFound") or (
        code == "ValidationError" and "does not exist" in error.response["Error"]["Message"]
    )


def _exists(call: Callable[[], object]) -> bool:
    try:
        call()
    except ClientError as e:
        if _missing(e):
            return False
        raise
    return True


def build_steps(c: config.Config, session, sleep: Callable[[float], None], everything: bool) -> list[Step]:
    cfn = session.client("cloudformation")

    def stack(name: str, key: str, label: str, after: tuple[str, ...] = (), keeps: str = "", delete: Callable[[], None] | None = None) -> Step:
        def delete_stack() -> None:
            cfn.delete_stack(StackName=name)
            cfn.get_waiter("stack_delete_complete").wait(StackName=name, WaiterConfig=WAIT)

        return Step(key, label, lambda: [name] if _exists(lambda: cfn.describe_stacks(StackName=name)) else [], delete or delete_stack, after, keeps)

    def registry_items() -> list[str]:
        found = _exists(lambda: session.client("ecr").describe_repositories(repositoryNames=[c.ecr_repository]))
        return [c.ecr_repository] if found else []

    def secret_items() -> list[str]:
        found = _exists(lambda: session.client("secretsmanager").describe_secret(SecretId=c.auth_jwt_secret_name))
        return [c.auth_jwt_secret_name] if found else []

    def bucket_items() -> list[str]:
        return [c.web_bucket] if _exists(lambda: session.client("s3").head_bucket(Bucket=c.web_bucket)) else []

    def delete_bucket() -> None:
        s3 = session.client("s3")
        for kind, collect in (
            ("list_objects_v2", lambda page: [{"Key": o["Key"]} for o in page.get("Contents", [])]),
            (
                "list_object_versions",
                lambda page: [{"Key": o["Key"], "VersionId": o["VersionId"]} for o in [*page.get("Versions", []), *page.get("DeleteMarkers", [])]],
            ),
        ):
            for page in s3.get_paginator(kind).paginate(Bucket=c.web_bucket):
                objects = collect(page)
                for i in range(0, len(objects), 1000):
                    batch = {"Objects": objects[i : i + 1000], "Quiet": True}
                    failed = s3.delete_objects(Bucket=c.web_bucket, Delete=batch).get("Errors", [])
                    if failed:  # delete_objects answers 200 even when single objects were refused
                        raise DestroyError(f"{len(failed)} object(s) in the bucket could not be deleted, e.g. {failed[0]['Key']} ({failed[0]['Code']})")
        s3.delete_bucket(Bucket=c.web_bucket)

    steps = [
        stack(c.app_stack, "app", f"the app stack {c.app_stack} (load balancer, service, CloudFront)"),
        Step(
            "registry", "container repository (and its images)", registry_items,
            lambda: session.client("ecr").delete_repository(repositoryName=c.ecr_repository, force=True), ("app",),
        ),
        Step(
            "secret", "session secret", secret_items,
            lambda: session.client("secretsmanager").delete_secret(SecretId=c.auth_jwt_secret_name, ForceDeleteWithoutRecovery=True), ("app",),
        ),
        Step("bucket", "SPA bucket (emptied first)", bucket_items, delete_bucket, ("app",)),
        stack(c.network_stack, "network-stack", f"the network stack {c.network_stack}", ("app",)),
    ]
    if c.existing_network:  # a network the template created is the stack above; only a prepared VPC has pieces of its own
        steps += _prepared_network_steps(c, session.client("ec2"), sleep)
    if everything:
        steps += _everything_steps(c, session, sleep, stack)
    return steps


def _prepared_network_steps(c: config.Config, ec2, sleep: Callable[[float], None]) -> list[Step]:
    """What `prepare_network.py` added to the existing VPC, found by its tags and names. Never the VPC itself."""
    vpc = c.existing_network.vpc_id

    def nats() -> list[dict]:
        return ec2.describe_nat_gateways(
            Filter=[*owned_filters(c, "nat", vpc), {"Name": "state", "Values": ["pending", "available", "deleting"]}]
        )["NatGateways"]

    def delete_nats() -> None:
        found = nats()
        ids = [n["NatGatewayId"] for n in found]
        for nat in found:
            if nat["State"] != "deleting":  # an earlier run already asked: only wait for it
                ec2.delete_nat_gateway(NatGatewayId=nat["NatGatewayId"])
        if ids:
            ec2.get_waiter("nat_gateway_deleted").wait(NatGatewayIds=ids, WaiterConfig=WAIT)

    def route_tables() -> list[dict]:
        tables = ec2.describe_route_tables(Filters=owned_filters(c, "private", vpc))["RouteTables"]
        # The main table of a VPC cannot be deleted and is never ours to touch, whatever it is tagged with.
        return [t for t in tables if not any(a.get("Main") for a in t.get("Associations", []))]

    def delete_route_tables() -> None:
        for table in route_tables():
            for association in table.get("Associations", []):
                ec2.disassociate_route_table(AssociationId=association["RouteTableAssociationId"])
            ec2.delete_route_table(RouteTableId=table["RouteTableId"])

    def subnets() -> list[dict]:
        return ec2.describe_subnets(Filters=owned_filters(c, "private-*", vpc))["Subnets"]

    def delete_subnets() -> None:
        for subnet in subnets():
            for attempt in range(12):  # the app's network interfaces linger for a minute and block the subnet
                try:
                    ec2.delete_subnet(SubnetId=subnet["SubnetId"])
                    break
                except ClientError as e:
                    if e.response["Error"]["Code"] != "DependencyViolation" or attempt == 11:
                        raise
                    sleep(10)

    def addresses() -> list[dict]:
        return ec2.describe_addresses(Filters=owned_filters(c, "nat"))["Addresses"]  # an address belongs to no VPC

    def delete_addresses() -> None:
        for address in addresses():
            ec2.release_address(AllocationId=address["AllocationId"])

    return [
        Step("nat", "NAT gateway", lambda: [n["NatGatewayId"] for n in nats()], delete_nats, ("app", "network-stack")),
        Step("route-table", "route table", lambda: [t["RouteTableId"] for t in route_tables()], delete_route_tables, ("app", "network-stack")),
        Step("subnets", "private subnet", lambda: [s["SubnetId"] for s in subnets()], delete_subnets, ("app", "nat", "route-table")),
        Step("address", "Elastic IP", lambda: [a["AllocationId"] for a in addresses()], delete_addresses, ("nat",)),
    ]


def _everything_steps(c: config.Config, session, sleep, stack) -> list[Step]:
    cfn = session.client("cloudformation")

    def harness_id() -> str:
        return harness_resolve.starter_harness_arn(c, session).rsplit("/", 1)[-1]

    def endpoints(harness: str) -> list[str]:
        control, names, token = session.client("bedrock-agentcore-control"), [], None
        while True:
            page = control.list_harness_endpoints(harnessId=harness, **({"nextToken": token} if token else {}))
            names += [e["endpointName"] for e in page["endpoints"]]
            token = page.get("nextToken")
            if not token:
                return names

    def delete_harness() -> None:
        harness = harness_id()
        control = session.client("bedrock-agentcore-control")
        # The endpoints the deploy script made (PROD) live outside the stack and block its deletion. DEFAULT belongs
        # to the harness and goes with it.
        ours = [n for n in endpoints(harness) if n != "DEFAULT"]
        for name in ours:
            control.delete_harness_endpoint(harnessId=harness, endpointName=name)
        for _ in range(60):
            if not [n for n in endpoints(harness) if n != "DEFAULT"]:
                break
            sleep(10)
        cfn.delete_stack(StackName=c.harness_stack)
        cfn.get_waiter("stack_delete_complete").wait(StackName=c.harness_stack, WaiterConfig=WAIT)

    harness_step = stack(c.harness_stack, "harness", f"the starter harness {c.harness_stack}", ("app",), "--everything", delete_harness)

    def table_step(name: str, key: str) -> Step:
        dynamo = session.client("dynamodb")

        def delete() -> None:
            dynamo.delete_table(TableName=name)
            dynamo.get_waiter("table_not_exists").wait(TableName=name)

        def items() -> list[str]:
            return [name] if _exists(lambda: dynamo.describe_table(TableName=name)) else []

        return Step(key, f"DynamoDB table {name} (its data is lost)", items, delete, ("app",), "--everything")

    def pools() -> list[dict]:
        cognito, found, token = session.client("cognito-idp"), [], None
        while True:
            page = cognito.list_user_pools(MaxResults=60, **({"NextToken": token} if token else {}))
            found += [p for p in page["UserPools"] if p["Name"] == c.user_pool]
            token = page.get("NextToken")
            if not token:
                return found

    def delete_pool() -> None:
        cognito = session.client("cognito-idp")
        for pool in pools():
            domain = cognito.describe_user_pool(UserPoolId=pool["Id"])["UserPool"].get("Domain")
            if domain:
                cognito.delete_user_pool_domain(Domain=domain, UserPoolId=pool["Id"])
            cognito.delete_user_pool(UserPoolId=pool["Id"])

    steps = [harness_step] if c.deploys_starter_harness else []
    steps += [
        table_step(c.sessions_table, "table-sessions"),
        table_step(c.items_table, "table-items"),
        stack(c.data_stack, "data-stack", f"the data stack {c.data_stack}", ("table-sessions", "table-items")),
        Step("pool", f"user pool {c.user_pool} (its users are lost)", lambda: [p["Id"] for p in pools()], delete_pool, ("app",), "--everything"),
        stack(c.auth_stack, "auth-stack", f"the sign-in stack {c.auth_stack}", ("pool",)),
        stack(
            c.roles_stack, "roles", f"the roles stack {c.roles_stack}",
            ("app", "data-stack", "auth-stack", *(["harness"] if c.deploys_starter_harness else [])),
        ),
    ]
    return steps


@dataclass
class Outcome:
    deleted: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)
    skipped: dict[str, str] = field(default_factory=dict)


def execute(steps: list[Step]) -> Outcome:
    outcome, done = Outcome(), set()
    for step in steps:
        items, problem = step.check()
        if problem:
            outcome.failed[step.key] = f"{step.label}: could not be checked, so it was left alone: {problem}"
            continue
        if not items:
            done.add(step.key)
            continue
        blocked = [dep for dep in step.after if dep not in done]
        if blocked:
            outcome.skipped[step.key] = f"{step.label}: not attempted, it needs {', '.join(blocked)} to go first"
            continue
        print(f"Deleting {step.label}...", flush=True)
        try:
            step.delete()
        except (ClientError, WaiterError, DeployError) as e:  # a stack that ends DELETE_FAILED is a WaiterError
            outcome.failed[step.key] = f"{step.label}: {describe(e)}"
            continue
        outcome.deleted.append(step.key)
        done.add(step.key)
    return outcome


def print_plan(c: config.Config, steps: list[Step], everything: bool) -> None:
    present = [(s, *s.check()) for s in steps]
    print(f"In account {c.aws_account}, {c.aws_region}, project '{c.name}':")
    for step, items, problem in present:
        if items:
            print(f"  - {step.label}: {', '.join(items)}")
        elif problem:
            print(f"  - {step.label}: could not be checked: {problem}")
    found = {s.key: items for s, items, _ in present if items}
    # The template's own network stack has up to one NAT gateway per zone: at most the largest sizing says.
    nats = len(found["nat"]) if "nat" in found else max(s.nat_gateways for s in c.environments.values()) if "network-stack" in found else 0
    daily = (APP_PER_DAY if "app" in found else 0) + NAT_PER_DAY * nats
    if daily:
        print(f"\nDeleting these stops about {daily:.2f} USD a day (the load balancer and the NAT gateway are most of it).")
    if not any(items or problem for _, items, problem in present):
        print("  (nothing to delete)")
    if not everything:
        print("\nThe data, the user pool, the harness and the roles are kept; add --everything to delete them too.")


@cli
def main(argv: list[str] | None = None, *, cfg: config.Config | None = None, session=None, sleep: Callable[[float], None] = time.sleep) -> int:
    parser = argparse.ArgumentParser(description="Delete what the project deployed.")
    parser.add_argument("--confirm", metavar="PROJECT_NAME", help="delete for real; must be the project's name. Without it only the plan is shown")
    parser.add_argument("--everything", action="store_true", help="also delete the harness, tables, user pool and roles (not recoverable)")
    args = parser.parse_args(argv)

    c = cfg if cfg is not None else load_config()
    session = session or boto3.Session(region_name=c.aws_region)
    check_account(c, session)
    if args.confirm is not None and args.confirm != c.name:
        raise DestroyError(f"--confirm must be the project's name, '{c.name}', not '{args.confirm}'. Nothing was deleted.")
    steps = build_steps(c, session, sleep, args.everything)
    print_plan(c, steps, args.everything)
    if args.confirm is None:
        print(f"\nNothing was deleted. To delete: --confirm {c.name}")
        return 0
    print()
    outcome = execute(steps)

    for message in [*outcome.failed.values(), *outcome.skipped.values()]:
        print(f"! {message}", file=sys.stderr)
    checked = [(s, *s.check()) for s in steps]
    left = [(s, items) for s, items, _ in checked if items]
    unknown = [(s, problem) for s, _, problem in checked if problem]
    print()
    if unknown:
        print("Could not check: " + "; ".join(f"{s.label} ({problem})" for s, problem in unknown))
    if left:
        print("Still exists: " + "; ".join(f"{s.label} ({', '.join(items)})" for s, items in left))
    elif not unknown:
        print(f"Nothing of '{c.name}' remains" + ("." if args.everything else " that this run covers."))
    print("Left on purpose: the CDK bootstrap and the GitHub OIDC provider (shared by the account).")
    return 1 if outcome.failed or outcome.skipped else 0


if __name__ == "__main__":
    sys.exit(main())
