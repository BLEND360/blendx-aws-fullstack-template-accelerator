import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Template

from definitions.roles import role_specs
from definitions.tables import OWNER_KEY, table_specs
from specs.table import TableSpec
from stacks.data import DataStack
from stacks.roles import RolesStack
from tests.conftest import fixed_config

C = fixed_config()
ENV = cdk.Environment(account=C.aws_account, region=C.aws_region)


def synth(specs=None) -> Template:
    stack = DataStack(cdk.App(), C.data_stack, specs=specs or table_specs(C), env=ENV)
    return Template.from_stack(stack)


@pytest.fixture(scope="module")
def template() -> Template:
    return synth()


def tables(template: Template) -> dict[str, dict]:
    return {r["Properties"]["TableName"]: r for r in template.find_resources("AWS::DynamoDB::Table").values()}


def test_the_two_tables_exist_under_the_names_project_toml_derives(template):
    assert set(tables(template)) == {C.sessions_table, C.items_table}


def test_every_table_is_keyed_owner_first_then_its_own_id(template):
    sort_keys = {C.sessions_table: "session_id", C.items_table: "item_id"}
    for name, resource in tables(template).items():
        schema = {k["KeyType"]: k["AttributeName"] for k in resource["Properties"]["KeySchema"]}
        assert schema == {"HASH": OWNER_KEY, "RANGE": sort_keys[name]}, name


def test_billing_is_on_demand(template):
    for name, resource in tables(template).items():
        assert resource["Properties"]["BillingMode"] == "PAY_PER_REQUEST", name


def test_deleting_the_stack_or_replacing_a_table_never_deletes_data(template):
    for name, resource in tables(template).items():
        assert resource["DeletionPolicy"] == "Retain", name
        assert resource["UpdateReplacePolicy"] == "Retain", name


def test_point_in_time_recovery_is_on(template):
    for name, resource in tables(template).items():
        assert resource["Properties"]["PointInTimeRecoverySpecification"] == {"PointInTimeRecoveryEnabled": True}, name


def test_tables_declare_only_their_keys_so_no_conversation_content_can_be_indexed(template):
    for name, resource in tables(template).items():
        props = resource["Properties"]
        declared = {a["AttributeName"] for a in props["AttributeDefinitions"]}
        assert declared == {k["AttributeName"] for k in props["KeySchema"]}, name
        assert "GlobalSecondaryIndexes" not in props and "LocalSecondaryIndexes" not in props, name


def test_adding_a_table_is_one_entry():
    extra = TableSpec("NotesTable", f"{C.name}-notes", OWNER_KEY, "note_id", "Another owned thing.")
    assert len(tables(synth([*table_specs(C), extra]))) == 3


def test_data_stack_is_separate_from_roles_and_exports_nothing(template):
    assert C.data_stack != C.roles_stack
    assert not template.to_json().get("Outputs"), "a cross-stack export makes deploy order rigid"


def test_task_role_reaches_these_two_tables_and_no_others():
    roles = Template.from_stack(RolesStack(cdk.App(), C.roles_stack, specs=role_specs(C), env=ENV))
    resources = set()
    for policy in roles.find_resources("AWS::IAM::Policy").values():
        props = policy["Properties"]
        if not props["Roles"][0]["Ref"].startswith("EcsTaskRole"):
            continue
        for st in props["PolicyDocument"]["Statement"]:
            actions = [st["Action"]] if isinstance(st["Action"], str) else st["Action"]
            if any(a.startswith("dynamodb:") for a in actions):
                resources.update([st["Resource"]] if isinstance(st["Resource"], str) else st["Resource"])
    prefix = f"arn:aws:dynamodb:{C.aws_region}:{C.aws_account}:table"
    assert resources == {f"{prefix}/{C.sessions_table}", f"{prefix}/{C.items_table}"}
