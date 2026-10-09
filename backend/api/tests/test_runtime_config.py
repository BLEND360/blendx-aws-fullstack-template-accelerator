import pytest

from app.core.errors import ValidationFailedError
from app.core.models import RuntimeValues, SessionConfig
from app.services.runtime_config import UNSET, Overrides, resolve, template_defaults

ALLOWED = ["model-a", "model-b"]
TOOLS = frozenset({"t1", "t2", "t3"})
DEFAULTS = template_defaults(ALLOWED, ["t1", "t2"])


def create(**overrides) -> SessionConfig:
    return resolve(DEFAULTS, ALLOWED, TOOLS, Overrides(**overrides))


def test_template_defaults_are_the_first_model_and_every_registered_tool():
    assert DEFAULTS == RuntimeValues("model-a", ("t1", "t2"))


def test_creation_without_overrides_uses_the_defaults_and_freezes_them():
    config = create()
    assert config.values == DEFAULTS
    assert config.frozen_defaults == DEFAULTS


def test_creation_applies_overrides_over_the_defaults():
    config = create(model_id="model-b", tool_ids=["t3"])
    assert config.values == RuntimeValues("model-b", ("t3",))
    assert config.frozen_defaults == DEFAULTS


def test_a_model_outside_the_allowlist_is_rejected_with_its_field():
    with pytest.raises(ValidationFailedError) as raised:
        create(model_id="gpt-nope")
    assert raised.value.fields == [{"location": "body.modelId", "message": "Model is not allowed."}]
    assert "gpt-nope" not in str(raised.value.to_payload())  # the caller's text is not echoed


def test_an_unknown_tool_is_rejected_and_the_position_is_named():
    with pytest.raises(ValidationFailedError) as raised:
        create(tool_ids=["t1", "ghost"])
    assert [f["location"] for f in raised.value.fields] == ["body.toolIds.1"]


def test_every_problem_is_reported_together():
    with pytest.raises(ValidationFailedError) as raised:
        create(model_id="nope", tool_ids=["ghost"])
    assert len(raised.value.fields) == 2


def test_duplicate_tool_ids_collapse_keeping_order():
    assert create(tool_ids=["t2", "t1", "t2"]).values.tool_ids == ("t2", "t1")


def test_an_empty_tool_list_is_valid():
    assert create(tool_ids=[]).values.tool_ids == ()


# --- update ----------------------------------------------------------------------
def test_omitted_fields_keep_their_current_value():
    current = create(model_id="model-b", tool_ids=["t3"])
    updated = resolve(DEFAULTS, ALLOWED, TOOLS, Overrides(), current)
    assert updated == current


def test_a_field_set_changes_only_that_field():
    current = create(model_id="model-b", tool_ids=["t3"])
    updated = resolve(DEFAULTS, ALLOWED, TOOLS, Overrides(model_id="model-a"), current)
    assert updated.values == RuntimeValues("model-a", ("t3",))


def test_null_restores_the_default_frozen_at_creation():
    current = create(model_id="model-b", tool_ids=["t3"])
    updated = resolve(DEFAULTS, ALLOWED, TOOLS, Overrides(model_id=None, tool_ids=None), current)
    assert updated.values == DEFAULTS


def test_null_restores_the_creation_default_even_after_the_template_changed():
    current = create(model_id="model-b")  # frozen: model-a
    new_defaults = template_defaults(["model-b", "model-a"], ["t1"])  # the template moved on
    updated = resolve(new_defaults, ["model-b", "model-a"], TOOLS, Overrides(model_id=None), current)
    assert updated.values.model_id == "model-a"
    assert updated.frozen_defaults == DEFAULTS


def test_a_session_keeps_working_after_the_allowlist_shrinks_until_it_is_changed():
    current = create(model_id="model-b")
    shrunk = resolve(DEFAULTS, ["model-a"], TOOLS, Overrides(tool_ids=["t1"]), current)  # model left alone
    assert shrunk.values.model_id == "model-b"
    with pytest.raises(ValidationFailedError):
        resolve(DEFAULTS, ["model-a"], TOOLS, Overrides(model_id="model-b"), current)


def test_update_validates_what_it_sets():
    current = create()
    with pytest.raises(ValidationFailedError):
        resolve(DEFAULTS, ALLOWED, TOOLS, Overrides(tool_ids=["ghost"]), current)


def test_unset_is_not_none():
    assert Overrides().model_id is UNSET
    assert Overrides(model_id=None).model_id is None
