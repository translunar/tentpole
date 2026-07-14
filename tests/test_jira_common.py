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
