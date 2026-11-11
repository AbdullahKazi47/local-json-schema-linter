import pytest

from schema_linter.validator import check_schema


def problems(schema):
    return [(e.location, e.message) for e in check_schema(schema)]


@pytest.mark.parametrize(
    "schema",
    [
        True,
        False,
        {},
        {"type": "object", "required": ["a"], "properties": {"a": {"type": "string"}}},
        {"type": ["string", "null"], "enum": ["a", None]},
        {"items": [{"type": "string"}], "additionalItems": False},
        {"anyOf": [{"type": "string"}, True]},
        {"definitions": {"x": {"type": "integer"}}, "$ref": "#/definitions/x"},
        {"pattern": "^[a-z]+$", "minLength": 0, "multipleOf": 2},
        {"title": "ignored", "description": "unknown keywords are fine"},
    ],
)
def test_well_formed_schemas(schema):
    assert check_schema(schema) == []


@pytest.mark.parametrize(
    "schema, location, fragment",
    [
        ([], "$", "must be an object or boolean"),
        ("string", "$", "must be an object or boolean"),
        ({"type": "text"}, "$.type", "unknown type 'text'"),
        ({"type": []}, "$.type", "non-empty list"),
        ({"type": 5}, "$.type", "type name"),
        ({"required": "name"}, "$.required", "list of property names"),
        ({"required": ["a", "a"]}, "$.required", "duplicate"),
        ({"properties": []}, "$.properties", "must be an object"),
        ({"properties": {"a": 5}}, "$.properties.a", "object or boolean"),
        ({"items": "string"}, "$.items", "object or boolean"),
        ({"items": [{"type": "nope"}]}, "$.items[0].type", "unknown type"),
        ({"anyOf": []}, "$.anyOf", "non-empty list"),
        ({"oneOf": [{"type": "bad"}]}, "$.oneOf[0].type", "unknown type"),
        ({"enum": "a"}, "$.enum", "must be a list"),
        ({"minimum": "0"}, "$.minimum", "must be a number"),
        ({"minLength": -1}, "$.minLength", "non-negative integer"),
        ({"maxItems": 1.5}, "$.maxItems", "non-negative integer"),
        ({"multipleOf": 0}, "$.multipleOf", "greater than 0"),
        ({"uniqueItems": "yes"}, "$.uniqueItems", "true or false"),
        ({"pattern": "[unclosed"}, "$.pattern", "invalid regular expression"),
        ({"patternProperties": {"(": {}}}, "$.patternProperties['(']", "invalid regular"),
        ({"$ref": 3}, "$['$ref']", "must be a string"),
        ({"$ref": "#/definitions/nope"}, "$['$ref']", "cannot resolve"),
        ({"not": "x"}, "$.not", "object or boolean"),
    ],
)
def test_malformed_schemas(schema, location, fragment):
    found = problems(schema)
    assert found, f"expected a problem for {schema!r}"
    assert any(loc == location and fragment in msg for loc, msg in found), found


def test_reports_all_problems():
    schema = {
        "type": "object",
        "required": "x",
        "properties": {"a": {"type": "strng"}, "b": {"minimum": "1"}},
    }
    assert len(check_schema(schema)) == 3


def test_enum_values_are_not_treated_as_refs():
    assert check_schema({"enum": [{"$ref": "#/nowhere"}]}) == []
