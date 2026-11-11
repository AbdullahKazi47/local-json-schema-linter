"""Validation of JSON values against a practical subset of JSON Schema.

Supported keywords:

* general:  type, enum, const, $ref (local "#/..." pointers only)
* combinators: allOf, anyOf, oneOf, not
* objects:  properties, required, additionalProperties, patternProperties,
            minProperties, maxProperties, propertyNames
* arrays:   items (single schema or tuple list), additionalItems,
            minItems, maxItems, uniqueItems, contains
* strings:  minLength, maxLength, pattern
* numbers:  minimum, maximum, exclusiveMinimum, exclusiveMaximum, multipleOf

Unknown keywords (such as "title" or "description") are ignored, matching the
behaviour of standard JSON Schema validators.
"""

import math
import re
from dataclasses import dataclass

TYPE_NAMES = ("null", "boolean", "object", "array", "number", "integer", "string")


@dataclass(frozen=True)
class ValidationError:
    """A single problem found in a document or schema.

    ``path`` is a tuple of keys/indexes leading to the offending value.
    """

    path: tuple
    message: str

    @property
    def location(self):
        return format_path(self.path)


class SchemaError(ValueError):
    """Raised when a schema cannot be used (for example, a broken $ref)."""


def format_path(path):
    """Render a path tuple as ``$.key[0].other``."""
    parts = ["$"]
    for part in path:
        if isinstance(part, int):
            parts.append(f"[{part}]")
        elif re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", part):
            parts.append(f".{part}")
        else:
            parts.append(f"[{part!r}]")
    return "".join(parts)


def type_of(value):
    """Return the JSON type name of a Python value produced by a JSON parser."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    raise TypeError(f"not a JSON value: {value!r}")


def is_type(value, name):
    actual = type_of(value)
    if name == "number":
        return actual in ("number", "integer")
    if name == "integer":
        return actual == "integer" or (
            actual == "number" and math.isfinite(value) and value.is_integer()
        )
    return actual == name


def json_equal(a, b):
    """Compare JSON values without Python's ``True == 1`` conflation."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(json_equal(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(json_equal(a[k], b[k]) for k in a)
    return type(a) is type(b) and a == b


def _short(value, limit=40):
    text = repr(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _plural(count, word):
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


# ---------------------------------------------------------------------------
# Instance validation
# ---------------------------------------------------------------------------


class _Validator:
    def __init__(self, root_schema):
        self.root = root_schema

    def resolve(self, ref):
        if ref == "#":
            return self.root
        if not ref.startswith("#/"):
            raise SchemaError(f"only local '#/...' references are supported: {ref!r}")
        node = self.root
        for token in ref[2:].split("/"):
            token = token.replace("~1", "/").replace("~0", "~")
            if isinstance(node, dict) and token in node:
                node = node[token]
            elif isinstance(node, list) and token.isdigit() and int(token) < len(node):
                node = node[int(token)]
            else:
                raise SchemaError(f"cannot resolve reference {ref!r}")
        return node

    def errors(self, value, schema, path, depth=0):
        if depth > 100:
            raise SchemaError("schema recursion is too deep (circular $ref?)")
        if schema is True or schema == {}:
            return []
        if schema is False:
            return [ValidationError(path, "no value is allowed here")]

        if "$ref" in schema:
            return self.errors(value, self.resolve(schema["$ref"]), path, depth + 1)

        found = []
        found += self._check_type(value, schema, path)
        if found:
            # A wrong type makes the type-specific checks meaningless noise.
            return found
        found += self._check_values(value, schema, path)
        found += self._check_combinators(value, schema, path, depth)
        if isinstance(value, dict):
            found += self._check_object(value, schema, path, depth)
        elif isinstance(value, list):
            found += self._check_array(value, schema, path, depth)
        elif isinstance(value, str):
            found += self._check_string(value, schema, path)
        elif is_type(value, "number"):
            found += self._check_number(value, schema, path)
        return found

    def _check_type(self, value, schema, path):
        if "type" not in schema:
            return []
        expected = schema["type"]
        names = [expected] if isinstance(expected, str) else list(expected)
        if any(is_type(value, name) for name in names):
            return []
        wanted = " or ".join(names)
        return [ValidationError(path, f"expected {wanted}, got {type_of(value)}")]

    def _check_values(self, value, schema, path):
        found = []
        if "const" in schema and not json_equal(value, schema["const"]):
            found.append(
                ValidationError(path, f"must equal {_short(schema['const'])}")
            )
        if "enum" in schema and not any(json_equal(value, o) for o in schema["enum"]):
            options = ", ".join(_short(o, 20) for o in schema["enum"])
            found.append(
                ValidationError(path, f"{_short(value)} is not one of: {options}")
            )
        return found

    def _check_combinators(self, value, schema, path, depth):
        found = []
        for sub in schema.get("allOf", []):
            found += self.errors(value, sub, path, depth + 1)
        if "anyOf" in schema:
            if not any(
                not self.errors(value, sub, path, depth + 1) for sub in schema["anyOf"]
            ):
                found.append(
                    ValidationError(path, "does not match any of the allowed schemas")
                )
        if "oneOf" in schema:
            matches = sum(
                1 for sub in schema["oneOf"] if not self.errors(value, sub, path, depth + 1)
            )
            if matches != 1:
                found.append(
                    ValidationError(
                        path,
                        f"must match exactly one schema in oneOf, matched {matches}",
                    )
                )
        if "not" in schema and not self.errors(value, schema["not"], path, depth + 1):
            found.append(ValidationError(path, "must not match the 'not' schema"))
        return found

    def _check_object(self, value, schema, path, depth):
        found = []
        for name in schema.get("required", []):
            if name not in value:
                found.append(
                    ValidationError(path, f"missing required property {name!r}")
                )

        count = len(value)
        if "minProperties" in schema and count < schema["minProperties"]:
            found.append(ValidationError(
                path, f"has {_plural(count, 'property')}, needs at least "
                      f"{schema['minProperties']}"))
        if "maxProperties" in schema and count > schema["maxProperties"]:
            found.append(ValidationError(
                path, f"has {_plural(count, 'property')}, allows at most "
                      f"{schema['maxProperties']}"))

        properties = schema.get("properties", {})
        patterns = schema.get("patternProperties", {})
        additional = schema.get("additionalProperties", True)
        for key, item in value.items():
            child = path + (key,)
            if "propertyNames" in schema and self.errors(
                key, schema["propertyNames"], child, depth + 1
            ):
                found.append(ValidationError(child, f"invalid property name {key!r}"))
            matched = False
            if key in properties:
                matched = True
                found += self.errors(item, properties[key], child, depth + 1)
            for pattern, sub in patterns.items():
                if re.search(pattern, key):
                    matched = True
                    found += self.errors(item, sub, child, depth + 1)
            if not matched:
                if additional is False:
                    found.append(
                        ValidationError(child, f"unexpected property {key!r}")
                    )
                else:
                    found += self.errors(item, additional, child, depth + 1)
        return found

    def _check_array(self, value, schema, path, depth):
        found = []
        count = len(value)
        if "minItems" in schema and count < schema["minItems"]:
            found.append(ValidationError(
                path, f"has {_plural(count, 'item')}, needs at least {schema['minItems']}"))
        if "maxItems" in schema and count > schema["maxItems"]:
            found.append(ValidationError(
                path, f"has {_plural(count, 'item')}, allows at most {schema['maxItems']}"))

        if schema.get("uniqueItems") is True:
            for i in range(count):
                for j in range(i):
                    if json_equal(value[i], value[j]):
                        found.append(ValidationError(
                            path + (i,), f"duplicate of item at index {j}"))
                        break

        items = schema.get("items", True)
        if isinstance(items, list):
            for index, sub in enumerate(items[:count]):
                found += self.errors(value[index], sub, path + (index,), depth + 1)
            extra = schema.get("additionalItems", True)
            for index in range(len(items), count):
                if extra is False:
                    found.append(ValidationError(
                        path + (index,),
                        f"unexpected item; only {_plural(len(items), 'item')} allowed"))
                else:
                    found += self.errors(value[index], extra, path + (index,), depth + 1)
        else:
            for index, item in enumerate(value):
                found += self.errors(item, items, path + (index,), depth + 1)

        if "contains" in schema and not any(
            not self.errors(item, schema["contains"], path, depth + 1) for item in value
        ):
            found.append(
                ValidationError(path, "no item matches the 'contains' schema")
            )
        return found

    def _check_string(self, value, schema, path):
        found = []
        length = len(value)
        if "minLength" in schema and length < schema["minLength"]:
            found.append(ValidationError(
                path, f"string is {_plural(length, 'character')} long, needs at least "
                      f"{schema['minLength']}"))
        if "maxLength" in schema and length > schema["maxLength"]:
            found.append(ValidationError(
                path, f"string is {_plural(length, 'character')} long, allows at most "
                      f"{schema['maxLength']}"))
        if "pattern" in schema and not re.search(schema["pattern"], value):
            found.append(ValidationError(
                path, f"{_short(value)} does not match pattern {schema['pattern']!r}"))
        return found

    def _check_number(self, value, schema, path):
        found = []
        if "minimum" in schema and value < schema["minimum"]:
            found.append(ValidationError(path, f"{value} is less than minimum {schema['minimum']}"))
        if "maximum" in schema and value > schema["maximum"]:
            found.append(ValidationError(path, f"{value} is greater than maximum {schema['maximum']}"))
        low = schema.get("exclusiveMinimum")
        if is_number(low) and value <= low:
            found.append(ValidationError(path, f"{value} must be greater than {low}"))
        high = schema.get("exclusiveMaximum")
        if is_number(high) and value >= high:
            found.append(ValidationError(path, f"{value} must be less than {high}"))
        step = schema.get("multipleOf")
        if step is not None:
            quotient = value / step
            if not math.isclose(quotient, round(quotient), rel_tol=0, abs_tol=1e-9):
                found.append(ValidationError(path, f"{value} is not a multiple of {step}"))
        return found


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate(instance, schema):
    """Return a list of :class:`ValidationError` for ``instance``.

    The schema is assumed to be well formed; call :func:`check_schema` first
    to detect malformed schemas. Raises :class:`SchemaError` when a ``$ref``
    cannot be resolved.
    """
    return _Validator(schema).errors(instance, schema, ())


# ---------------------------------------------------------------------------
# Schema checking
# ---------------------------------------------------------------------------

_SCHEMA_KEYWORDS = ("additionalProperties", "additionalItems", "contains", "not",
                    "propertyNames")
_SCHEMA_MAPS = ("properties", "patternProperties", "definitions", "$defs")
_SCHEMA_LISTS = ("allOf", "anyOf", "oneOf")
_NUMBER_KEYWORDS = ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum")
_COUNT_KEYWORDS = ("minLength", "maxLength", "minItems", "maxItems",
                   "minProperties", "maxProperties")


def check_schema(schema):
    """Return a list of :class:`ValidationError` describing schema defects.

    Paths in the returned errors point into the schema document itself.
    """
    found = []
    _check_schema_node(schema, (), found)
    if not found:
        _check_refs(schema, schema, (), found)
    return found


def _check_schema_node(node, path, found):
    if isinstance(node, bool):
        return
    if not isinstance(node, dict):
        found.append(ValidationError(
            path, f"a schema must be an object or boolean, got {type_of(node)}"))
        return

    def bad(key, message):
        found.append(ValidationError(path + (key,), message))

    if "type" in node:
        kind = node["type"]
        names = [kind] if isinstance(kind, str) else kind
        if not isinstance(names, list) or not names:
            bad("type", "'type' must be a type name or a non-empty list of names")
        else:
            for name in names:
                if name not in TYPE_NAMES:
                    bad("type", f"unknown type {name!r}; use one of {', '.join(TYPE_NAMES)}")

    if "required" in node:
        req = node["required"]
        if not isinstance(req, list) or not all(isinstance(r, str) for r in req):
            bad("required", "'required' must be a list of property names")
        elif len(set(req)) != len(req):
            bad("required", "'required' contains duplicate names")

    if "enum" in node and not isinstance(node["enum"], list):
        bad("enum", "'enum' must be a list")

    for key in _NUMBER_KEYWORDS:
        if key in node and not is_number(node[key]):
            bad(key, f"{key!r} must be a number")
    if "multipleOf" in node and not (is_number(node["multipleOf"]) and node["multipleOf"] > 0):
        bad("multipleOf", "'multipleOf' must be a number greater than 0")
    for key in _COUNT_KEYWORDS:
        if key in node and not (type_of(node[key]) == "integer" and node[key] >= 0):
            bad(key, f"{key!r} must be a non-negative integer")
    if "uniqueItems" in node and not isinstance(node["uniqueItems"], bool):
        bad("uniqueItems", "'uniqueItems' must be true or false")

    if "pattern" in node:
        _check_regex(node["pattern"], path + ("pattern",), found)

    if "$ref" in node and not isinstance(node["$ref"], str):
        bad("$ref", "'$ref' must be a string")

    for key in _SCHEMA_KEYWORDS:
        if key in node:
            _check_schema_node(node[key], path + (key,), found)

    for key in _SCHEMA_MAPS:
        if key not in node:
            continue
        mapping = node[key]
        if not isinstance(mapping, dict):
            bad(key, f"{key!r} must be an object mapping names to schemas")
            continue
        for name, sub in mapping.items():
            if key == "patternProperties":
                _check_regex(name, path + (key, name), found)
            _check_schema_node(sub, path + (key, name), found)

    for key in _SCHEMA_LISTS:
        if key not in node:
            continue
        subs = node[key]
        if not isinstance(subs, list) or not subs:
            bad(key, f"{key!r} must be a non-empty list of schemas")
            continue
        for index, sub in enumerate(subs):
            _check_schema_node(sub, path + (key, index), found)

    if "items" in node:
        items = node["items"]
        if isinstance(items, list):
            for index, sub in enumerate(items):
                _check_schema_node(sub, path + ("items", index), found)
        else:
            _check_schema_node(items, path + ("items",), found)


def _check_regex(pattern, path, found):
    if not isinstance(pattern, str):
        found.append(ValidationError(path, "a pattern must be a string"))
        return
    try:
        re.compile(pattern)
    except re.error as exc:
        found.append(ValidationError(path, f"invalid regular expression: {exc}"))


def _check_refs(root, node, path, found):
    """Report every ``$ref`` in the schema that does not resolve."""
    if isinstance(node, dict):
        if isinstance(node.get("$ref"), str):
            try:
                _Validator(root).resolve(node["$ref"])
            except SchemaError as exc:
                found.append(ValidationError(path + ("$ref",), str(exc)))
        for key, value in node.items():
            if key not in ("enum", "const"):
                _check_refs(root, value, path + (key,), found)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _check_refs(root, value, path + (index,), found)
