import json

import pytest

from schema_linter.locator import JSONSyntaxError, parse_with_lines


DOCUMENT = """{
  "name": "box",
  "size": [
    1,
    2.5,
    -3e2
  ],
  "meta": {"ok": true, "none": null, "off": false}
}"""


def test_parsed_value_matches_stdlib():
    value, _ = parse_with_lines(DOCUMENT)
    assert value == json.loads(DOCUMENT)


def test_records_line_of_every_value():
    _, lines = parse_with_lines(DOCUMENT)
    assert lines[()] == 1
    assert lines[("name",)] == 2
    assert lines[("size",)] == 3
    assert lines[("size", 0)] == 4
    assert lines[("size", 2)] == 6
    assert lines[("meta", "none")] == 8


def test_number_types():
    value, _ = parse_with_lines("[1, -0, 1.5, 2e3, 7E-1]")
    assert value == [1, 0, 1.5, 2000.0, 0.7]
    assert [type(v) for v in value] == [int, int, float, float, float]


def test_string_escapes():
    value, _ = parse_with_lines(r'"a\n\"b\" é"')
    assert value == 'a\n"b" é'


def test_leading_bom_is_ignored():
    value, _ = parse_with_lines('﻿{"a": 1}')
    assert value == {"a": 1}


@pytest.mark.parametrize(
    "text, line, fragment",
    [
        ('{\n  "a": 1,\n}', 3, "property name"),
        ('[1,\n2,\n]', 3, "expected a value"),
        ('{"a" 1}', 1, "expected ':'"),
        ('{"a": 1 "b": 2}', 1, "expected ',' or '}'"),
        ("[1, 2", 1, "expected ',' or ']'"),
        ("", 1, "end of input"),
        ("{'a': 1}", 1, "property name"),
        ('"unterminated', 1, "invalid string"),
        ("01", 1, "unexpected data"),
        ("[tru]", 1, "unexpected character"),
        ('{"a": 1}\n\n{"b": 2}', 3, "unexpected data"),
        ('{"a": 1,\n "a": 2}', 2, "duplicate"),
    ],
)
def test_syntax_errors_report_line(text, line, fragment):
    with pytest.raises(JSONSyntaxError) as info:
        parse_with_lines(text)
    assert info.value.line == line
    assert fragment in info.value.message


def test_syntax_error_reports_column():
    with pytest.raises(JSONSyntaxError) as info:
        parse_with_lines('{\n  "a": ?}')
    assert (info.value.line, info.value.column) == (2, 8)
