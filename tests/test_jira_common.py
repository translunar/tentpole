import pytest

from tentpole.adapters.jira_common import _sprint_id

LEGACY = ("com.atlassian.greenhopper.service.sprint.Sprint@1a2b3c["
          "rapidViewId=7,state=ACTIVE,name=S5,startDate=2026-07-13,"
          "id=123,goal=]")


def test_sprint_id_from_dict_entries():
    # The last entry is the issue's current placement.
    assert _sprint_id([{"id": 4, "name": "S4"},
                       {"id": 5, "name": "S5"}]) == 5


def test_sprint_id_parses_legacy_sprint_string():
    """Older Server/DC serializes the sprint field as a toString() dump.
    The id must be recovered from it -- not silently dropped."""
    assert _sprint_id([LEGACY]) == 123


def test_sprint_id_empty_or_absent_is_none():
    assert _sprint_id(None) is None
    assert _sprint_id([]) is None


def test_sprint_id_unrecognized_shape_raises_actionable_error():
    """Returning None here would silently strip the sprint from every
    issue on the instance and make a broken sync look healthy."""
    with pytest.raises(ValueError,
                       match="unrecognized sprint custom-field value"):
        _sprint_id([12345])


def test_sprint_id_dict_without_id_raises_actionable_error():
    """A dict entry lacking an 'id' key must not silently become None --
    that would strip the sprint from every issue while the extract stayed
    green. It must fall through to the same actionable error as any other
    unrecognized shape."""
    with pytest.raises(ValueError,
                       match="unrecognized sprint custom-field value"):
        _sprint_id([{"name": "S5", "state": "ACTIVE"}])
    with pytest.raises(ValueError,
                       match="unrecognized sprint custom-field value"):
        _sprint_id([{}])


def test_sprint_id_dict_with_none_id_raises_actionable_error():
    """A present-but-None 'id' must not silently become None -- that is
    indistinguishable from "no sprint" downstream and would drop the
    sprint from the issue while the extract stayed green."""
    with pytest.raises(ValueError,
                       match="unrecognized sprint custom-field value"):
        _sprint_id([{"id": None}])


def test_sprint_id_dict_with_string_id_raises_actionable_error():
    """A string 'id' (e.g. "4") never matches an int Sprint.id downstream,
    so the issue would silently leave its sprint bucket -- reject it
    rather than pass it through."""
    with pytest.raises(ValueError,
                       match="unrecognized sprint custom-field value"):
        _sprint_id([{"id": "4"}])


def test_sprint_id_dict_with_falsy_zero_id_still_returns_zero():
    """0 is a falsy but structurally legitimate sprint id -- it must
    still be returned, not treated as missing."""
    assert _sprint_id([{"id": 0}]) == 0


def test_sprint_id_dict_with_int_id_returns_it():
    assert _sprint_id([{"id": 4}]) == 4


def test_sprint_id_dict_with_bool_id_raises_actionable_error():
    """bool is a subclass of int in Python, but True/False is not a
    meaningful sprint id -- reject it deliberately."""
    with pytest.raises(ValueError,
                       match="unrecognized sprint custom-field value"):
        _sprint_id([{"id": True}])
