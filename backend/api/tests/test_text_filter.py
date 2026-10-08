import pytest

from app.harness.text_filter import PROTOCOL_MARKERS, MarkerFilter

ASCII = "<|DSML|function_calls"


def run(*fragments: str, markers=PROTOCOL_MARKERS) -> list[str]:
    """What is emitted after each fragment, then after the final flush."""
    f = MarkerFilter(markers)
    out = [f.feed(x) for x in fragments]
    out.append(f.flush())
    return out


def test_plain_text_passes_through_immediately():
    assert run("Hello", " world") == ["Hello", " world", ""]


def test_a_whole_marker_is_removed():
    assert "".join(run(f"before {ASCII} after")) == "before  after"


@pytest.mark.parametrize("marker", PROTOCOL_MARKERS)
def test_every_known_marker_is_removed(marker):
    assert "".join(run(f"a{marker}b")) == "ab"


def test_a_marker_split_in_two_is_removed():
    emitted = run("text <|DSML|func", "tion_calls tail")
    assert "".join(emitted) == "text  tail"
    assert "DSML" not in "".join(emitted)


def test_a_marker_split_in_three_is_removed():
    assert "".join(run("x <|DS", "ML|function", "_calls y")) == "x  y"


def test_a_marker_split_one_character_at_a_time_is_removed():
    assert "".join(run(*f"go {ASCII} on")) == "go  on"


def test_only_the_possible_marker_start_is_held_back():
    f = MarkerFilter()
    assert f.feed("some text <") == "some text "  # "<" could start a marker
    assert f.feed("b") == "<b"  # it did not: released with the next fragment


def test_text_that_only_looks_like_a_marker_start_is_released_at_the_end():
    emitted = run("a <|DSML|func")
    assert "".join(emitted) == "a <|DSML|func"
    assert emitted[-1] == "<|DSML|func"  # held until flush, since the stream ended


def test_consecutive_markers_are_all_removed():
    assert "".join(run(ASCII + ASCII, "!")) == "!"


def test_the_marker_list_is_the_only_thing_to_change():
    assert "".join(run("a[[X]]b", markers=("[[X]]",))) == "ab"


def test_an_empty_list_filters_nothing():
    assert run("<|DSML|function_calls", markers=()) == ["<|DSML|function_calls", ""]


def test_flush_is_idempotent():
    f = MarkerFilter()
    f.feed("<|DS")
    assert f.flush() == "<|DS"
    assert f.flush() == ""
