from tentpole.schema import SCHEMAS, render_schemas


def test_registry_has_all_sheets_with_ownership():
    assert set(SCHEMAS) == {"issues", "epics", "fixversions", "dependencies",
                            "capacity", "accuracy", "future_work", "exceptions", "team"}
    assert SCHEMAS["issues"].owned == "machine"
    assert SCHEMAS["future_work"].owned == "human"
    assert SCHEMAS["exceptions"].owned == "human"
    assert SCHEMAS["team"].owned == "human"


def test_every_schema_has_exactly_one_primary():
    for schema in SCHEMAS.values():
        primaries = [c for c in schema.columns if c.primary]
        assert len(primaries) == 1, schema.name
        assert schema.primary_column() is primaries[0]


def test_human_sheets_have_no_synced_columns():
    assert SCHEMAS["future_work"].synced_names() == []
    assert SCHEMAS["exceptions"].synced_names() == []
    assert SCHEMAS["team"].synced_names() == []
    assert "Key" in SCHEMAS["issues"].synced_names()


def test_render_schemas_lists_every_sheet_and_column():
    text = render_schemas()
    for schema in SCHEMAS.values():
        assert schema.name in text
        for col in schema.columns:
            assert col.name in text
    assert "human" in text and "machine" in text
