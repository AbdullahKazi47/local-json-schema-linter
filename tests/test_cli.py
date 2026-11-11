import io
import json
import runpy
import sys
from pathlib import Path

import pytest

from schema_linter.cli import EXIT_ERROR, EXIT_INVALID, EXIT_OK, lint_text, main

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"

SCHEMA = {
    "type": "object",
    "required": ["id", "items"],
    "properties": {
        "id": {"type": "integer"},
        "items": {"type": "array", "items": {"type": "string"}},
    },
}


def run(*args):
    out = io.StringIO()
    code = main([str(a) for a in args], out=out)
    return code, out.getvalue()


@pytest.fixture
def schema_file(tmp_path):
    path = tmp_path / "schema.json"
    path.write_text(json.dumps(SCHEMA), encoding="utf-8")
    return path


def write(path, text):
    path.write_text(text, encoding="utf-8")
    return path


def test_errors_carry_line_numbers():
    text = '{\n  "id": "seven",\n  "items": [\n    "a",\n    4\n  ]\n}'
    issues = lint_text(text, SCHEMA)
    assert [(i.line, i.location) for i in issues] == [(2, "$.id"), (5, "$.items[1]")]


def test_missing_property_points_at_parent_object():
    text = '{\n  "outer": {\n    "x": 1\n  }\n}'
    schema = {"properties": {"outer": {"required": ["y"]}}}
    (issue,) = lint_text(text, schema)
    assert issue.line == 2
    assert issue.render("f.json") == "f.json:2: $.outer: missing required property 'y'"


def test_valid_file(tmp_path, schema_file):
    target = write(tmp_path / "ok.json", '{"id": 1, "items": ["a"]}')
    code, output = run(schema_file, target)
    assert code == EXIT_OK
    assert "OK" in output
    assert "1 valid, 0 invalid" in output


def test_invalid_file(tmp_path, schema_file):
    target = write(tmp_path / "bad.json", '{\n  "items": [1]\n}')
    code, output = run(schema_file, target)
    assert code == EXIT_INVALID
    assert f"{target}:1: $: missing required property 'id'" in output
    assert f"{target}:2: $.items[0]: expected string, got integer" in output
    assert "2 errors" in output


def test_malformed_json_target(tmp_path, schema_file):
    target = write(tmp_path / "broken.json", '{\n  "id": 1,\n  "items": [,]\n}')
    code, output = run(schema_file, target)
    assert code == EXIT_INVALID
    assert f"{target}:3: invalid JSON" in output


def test_quiet_hides_passing_files(tmp_path, schema_file):
    target = write(tmp_path / "ok.json", '{"id": 1, "items": []}')
    code, output = run("--quiet", schema_file, target)
    assert code == EXIT_OK
    assert "OK" not in output
    assert "Checked 1 file" in output


def test_batch_mode_checks_directory(tmp_path, schema_file):
    data = tmp_path / "data"
    data.mkdir()
    write(data / "a.json", '{"id": 1, "items": []}')
    write(data / "b.json", '{"id": "x", "items": []}')
    write(data / "notes.txt", "not json, ignored")
    nested = data / "nested"
    nested.mkdir()
    write(nested / "c.json", '{"items": []}')

    code, output = run(schema_file, data)
    assert code == EXIT_INVALID
    assert "Checked 2 files: 1 valid, 1 invalid" in output
    assert "c.json" not in output

    code, output = run("--recursive", schema_file, data)
    assert "Checked 3 files: 1 valid, 2 invalid" in output


def test_batch_mode_skips_schema_in_same_directory(tmp_path, schema_file):
    write(tmp_path / "a.json", '{"id": 1, "items": []}')
    code, output = run(schema_file, tmp_path)
    assert code == EXIT_OK
    assert "Checked 1 file:" in output


def test_empty_directory(tmp_path, schema_file):
    empty = tmp_path / "empty"
    empty.mkdir()
    code, output = run(schema_file, empty)
    assert code == EXIT_ERROR
    assert "No JSON files" in output


def test_missing_target(tmp_path, schema_file):
    code, output = run(schema_file, tmp_path / "nope.json")
    assert code == EXIT_ERROR
    assert "cannot read file" in output


def test_malformed_schema_is_reported_with_lines(tmp_path):
    schema = write(tmp_path / "s.json", '{\n  "type": "object",\n  "required": "id"\n}')
    target = write(tmp_path / "t.json", "{}")
    code, output = run(schema, target)
    assert code == EXIT_ERROR
    assert "Schema is not usable" in output
    assert f"{schema}:3: $.required:" in output


def test_schema_with_invalid_json(tmp_path):
    schema = write(tmp_path / "s.json", '{"type": }')
    code, output = run(schema, write(tmp_path / "t.json", "{}"))
    assert code == EXIT_ERROR
    assert "invalid JSON in schema" in output


def test_missing_schema(tmp_path):
    code, output = run(tmp_path / "none.json", tmp_path)
    assert code == EXIT_ERROR
    assert "cannot read schema" in output


def test_bundled_examples():
    schema = EXAMPLES / "person.schema.json"
    data = EXAMPLES / "data"
    code, output = run(schema, data / "valid.json")
    assert code == EXIT_OK

    code, output = run(schema, data)
    assert code == EXIT_INVALID
    assert "Checked 3 files: 1 valid, 2 invalid, 8 errors." in output
    expected = [
        "broken.json:4: invalid JSON: unexpected character ']', expected a value (column 16)",
        "invalid.json:2: $.name: string is 0 characters long, needs at least 1",
        "invalid.json:3: $.age: expected integer, got string",
        "invalid.json:4: $.tags[1]: duplicate of item at index 0",
        "invalid.json:4: $.tags[2]: expected string, got integer",
        "invalid.json:5: $.address: missing required property 'city'",
        "invalid.json:6: $.address.zip: 'ABC' does not match pattern '^[0-9]{5}$'",
        "invalid.json:8: $.nickname: unexpected property 'nickname'",
    ]
    for line in expected:
        assert line in output


def test_runs_as_module(monkeypatch, capsys):
    # Run `python -m schema_linter` in-process: spawning a child interpreter
    # fails on Windows when the test runner has no valid stdin handle.
    monkeypatch.setattr(sys, "argv", [
        "schema_linter",
        str(EXAMPLES / "person.schema.json"),
        str(EXAMPLES / "data" / "valid.json"),
    ])
    sys.modules.pop("schema_linter.__main__", None)
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("schema_linter", run_name="__main__")
    output = capsys.readouterr().out
    assert exc.value.code == 0, output
    assert "1 valid" in output
