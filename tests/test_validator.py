import pytest

from schema_linter.validator import SchemaError, format_path, json_equal, validate


def messages(instance, schema):
    return [(e.location, e.message) for e in validate(instance, schema)]


# -- types ------------------------------------------------------------------

@pytest.mark.parametrize(
    "value, type_name",
    [
        (None, "null"), (True, "boolean"), ({}, "object"), ([], "array"),
        (1.5, "number"), (3, "number"), (3, "integer"), (4.0, "integer"),
        ("x", "string"),
    ],
)
def test_matching_types(value, type_name):
    assert validate(value, {"type": type_name}) == []


@pytest.mark.parametrize(
    "value, type_name",
    [
        (True, "integer"), (False, "number"), (1, "boolean"), (1.5, "integer"),
        ("1", "number"), ([], "object"), ({}, "array"), (None, "string"),
    ],
)
def test_mismatched_types(value, type_name):
    errors = validate(value, {"type": type_name})
    assert len(errors) == 1
    assert errors[0].message.startswith(f"expected {type_name}")


def test_type_list():
    schema = {"type": ["string", "null"]}
    assert validate(None, schema) == []
    assert messages(5, schema) == [("$", "expected string or null, got integer")]


def test_boolean_schemas():
    assert validate(42, True) == []
    assert messages(42, False) == [("$", "no value is allowed here")]


# -- objects ----------------------------------------------------------------

def test_required_fields():
    schema = {"type": "object", "required": ["id", "name"]}
    assert validate({"id": 1, "name": "x"}, schema) == []
    assert messages({"id": 1}, schema) == [("$", "missing required property 'name'")]


def test_nested_property_paths():
    schema = {
        "type": "object",
        "properties": {
            "user": {"type": "object", "properties": {"age": {"type": "integer"}}}
        },
    }
    assert messages({"user": {"age": "old"}}, schema) == [
        ("$.user.age", "expected integer, got string")
    ]


def test_additional_properties_false():
    schema = {"properties": {"a": {}}, "additionalProperties": False}
    assert messages({"a": 1, "b": 2}, schema) == [("$.b", "unexpected property 'b'")]


def test_additional_properties_schema():
    schema = {"additionalProperties": {"type": "number"}}
    assert messages({"x": 1, "y": "no"}, schema) == [
        ("$.y", "expected number, got string")
    ]


def test_pattern_properties():
    schema = {
        "patternProperties": {"^n_": {"type": "number"}},
        "additionalProperties": False,
    }
    assert validate({"n_a": 1}, schema) == []
    assert len(validate({"n_a": "x", "other": 1}, schema)) == 2


def test_property_counts_and_names():
    schema = {"minProperties": 2, "maxProperties": 3, "propertyNames": {"maxLength": 3}}
    assert "needs at least 2" in validate({"a": 1}, schema)[0].message
    errors = validate({"a": 1, "toolong": 2}, schema)
    assert [e.message for e in errors] == ["invalid property name 'toolong'"]


# -- arrays -----------------------------------------------------------------

def test_array_items():
    schema = {"type": "array", "items": {"type": "string"}}
    assert validate(["a", "b"], schema) == []
    assert messages(["a", 2, "c", None], schema) == [
        ("$[1]", "expected string, got integer"),
        ("$[3]", "expected string, got null"),
    ]


def test_array_length():
    schema = {"minItems": 1, "maxItems": 2}
    assert messages([], schema) == [("$", "has 0 items, needs at least 1")]
    assert messages([1, 2, 3], schema) == [("$", "has 3 items, allows at most 2")]


def test_unique_items_respects_json_types():
    schema = {"uniqueItems": True}
    assert validate([1, True, "1", [1], {"a": 1}], schema) == []
    assert messages([1, 2, 1], schema) == [("$[2]", "duplicate of item at index 0")]
    assert len(validate([{"a": [1]}, {"a": [1]}], schema)) == 1


def test_tuple_items():
    schema = {"items": [{"type": "string"}, {"type": "integer"}], "additionalItems": False}
    assert validate(["a", 1], schema) == []
    assert validate(["a"], schema) == []
    assert messages(["a", 1, 2], schema) == [
        ("$[2]", "unexpected item; only 2 items allowed")
    ]


def test_contains():
    schema = {"contains": {"const": "x"}}
    assert validate(["a", "x"], schema) == []
    assert messages(["a"], schema) == [("$", "no item matches the 'contains' schema")]


def test_array_of_objects():
    schema = {
        "type": "array",
        "items": {"type": "object", "required": ["id"]},
    }
    assert messages([{"id": 1}, {}], schema) == [("$[1]", "missing required property 'id'")]


# -- strings and numbers ----------------------------------------------------

def test_string_constraints():
    schema = {"minLength": 2, "maxLength": 4, "pattern": "^[a-z]+$"}
    assert validate("abc", schema) == []
    assert len(validate("A", schema)) == 2
    assert "allows at most 4" in validate("abcde", schema)[0].message


def test_number_constraints():
    schema = {"minimum": 0, "maximum": 10, "exclusiveMaximum": 10, "multipleOf": 0.5}
    assert validate(2.5, schema) == []
    assert "less than minimum" in validate(-1, schema)[0].message
    assert "must be less than 10" in validate(10, schema)[0].message
    assert "not a multiple" in validate(1.2, schema)[0].message


def test_float_multiple_of_tolerates_rounding():
    assert validate(0.3, {"multipleOf": 0.1}) == []


# -- enum, const, combinators, refs -----------------------------------------

def test_enum_and_const():
    assert validate("red", {"enum": ["red", "green"]}) == []
    assert "is not one of" in validate("blue", {"enum": ["red", "green"]})[0].message
    assert validate(True, {"enum": [1]}) != []
    assert validate(1, {"const": 1.0}) == []
    assert validate(0, {"const": False}) != []


def test_combinators():
    any_of = {"anyOf": [{"type": "string"}, {"type": "integer"}]}
    assert validate(1, any_of) == []
    assert validate(1.5, any_of) != []

    one_of = {"oneOf": [{"type": "number"}, {"type": "integer"}]}
    assert validate(1.5, one_of) == []
    assert "matched 2" in validate(1, one_of)[0].message

    all_of = {"allOf": [{"minimum": 1}, {"maximum": 3}]}
    assert validate(2, all_of) == []
    assert len(validate(5, all_of)) == 1

    assert validate("x", {"not": {"type": "integer"}}) == []
    assert validate(1, {"not": {"type": "integer"}}) != []


def test_local_refs_and_recursion():
    schema = {
        "$defs": {
            "node": {
                "type": "object",
                "required": ["value"],
                "properties": {
                    "value": {"type": "integer"},
                    "children": {"type": "array", "items": {"$ref": "#/$defs/node"}},
                },
            }
        },
        "$ref": "#/$defs/node",
    }
    tree = {"value": 1, "children": [{"value": 2, "children": [{"value": "x"}]}]}
    assert messages(tree, schema) == [
        ("$.children[0].children[0].value", "expected integer, got string")
    ]


def test_unresolvable_ref_raises():
    with pytest.raises(SchemaError):
        validate(1, {"$ref": "#/definitions/missing"})
    with pytest.raises(SchemaError):
        validate(1, {"$ref": "other.json"})


def test_circular_ref_raises():
    with pytest.raises(SchemaError):
        validate(1, {"$defs": {"a": {"$ref": "#/$defs/a"}}, "$ref": "#/$defs/a"})


# -- helpers ----------------------------------------------------------------

def test_format_path():
    assert format_path(()) == "$"
    assert format_path(("a", 0, "b c")) == "$.a[0]['b c']"


def test_json_equal():
    assert json_equal(1, 1.0)
    assert not json_equal(1, True)
    assert json_equal({"a": [1, None]}, {"a": [1.0, None]})
    assert not json_equal({"a": 1}, {"b": 1})
