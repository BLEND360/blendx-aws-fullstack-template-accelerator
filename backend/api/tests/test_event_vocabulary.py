"""The turn's event vocabulary is a contract with the browser (and with ST-10): changing it must be deliberate."""

from typing import get_args

from app.core import models


def test_vocabulary_is_exactly_these_six_names():
    assert sorted(models.TURN_EVENT_NAMES.values()) == [
        "delta", "done", "error", "tool_finished", "tool_input", "tool_started",
    ]


def test_every_event_type_has_a_name_and_every_name_a_type():
    assert set(get_args(models.TurnEvent)) == set(models.TURN_EVENT_NAMES)


def test_names_are_unique():
    names = list(models.TURN_EVENT_NAMES.values())
    assert len(names) == len(set(names))
