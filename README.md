# Local JSON Schema Linter

A zero-dependency command-line tool that validates JSON files against local
JSON Schema files and prints human-readable, line-numbered error reports.
It uses only the Python 3 standard library and runs entirely offline.

## Features

- Checks one or more JSON files against a schema file
- **Batch mode**: pass a directory to check every `*.json` file inside it
  (add `--recursive` to include sub-directories)
- Every error has a file name, line number and JSON path, for example
  `data.json:5: $.items[1]: expected string, got integer`
- Reports JSON syntax errors with line and column
- Checks the schema itself first, so typos like `"type": "strng"` or a broken
  `$ref` are reported with their line in the schema file
- No network access, no `pip install`

### Supported schema keywords

| Area        | Keywords |
|-------------|----------|
| General     | `type`, `enum`, `const`, `$ref` (local `#/...` only), `definitions`, `$defs` |
| Combinators | `allOf`, `anyOf`, `oneOf`, `not` |
| Objects     | `properties`, `required`, `additionalProperties`, `patternProperties`, `minProperties`, `maxProperties`, `propertyNames` |
| Arrays      | `items` (single schema or tuple list), `additionalItems`, `minItems`, `maxItems`, `uniqueItems`, `contains` |
| Strings     | `minLength`, `maxLength`, `pattern` |
| Numbers     | `minimum`, `maximum`, `exclusiveMinimum`, `exclusiveMaximum`, `multipleOf` |

Other keywords (such as `title`, `description` or `format`) are ignored, the
same way standard validators handle them. Patterns are compiled with Python's
`re` module.

## How to run

You need Python 3.8 or newer. From this folder:

```sh
# Check a single file
python -m schema_linter examples/person.schema.json examples/data/valid.json

# Check several files
python -m schema_linter schema.json a.json b.json

# Batch mode: check every .json file in a directory
python -m schema_linter examples/person.schema.json examples/data

# Include sub-directories, and only print failures
python -m schema_linter schema.json configs/ --recursive --quiet
```

If the schema file sits inside the directory being checked, it is skipped.

Example output from the bundled examples (paths shortened):

```
FAIL  examples/data/broken.json (1 error)
  examples/data/broken.json:4: invalid JSON: unexpected character ']', expected a value (column 16)
FAIL  examples/data/invalid.json (7 errors)
  examples/data/invalid.json:2: $.name: string is 0 characters long, needs at least 1
  examples/data/invalid.json:3: $.age: expected integer, got string
  examples/data/invalid.json:4: $.tags[1]: duplicate of item at index 0
  examples/data/invalid.json:4: $.tags[2]: expected string, got integer
  examples/data/invalid.json:5: $.address: missing required property 'city'
  examples/data/invalid.json:6: $.address.zip: 'ABC' does not match pattern '^[0-9]{5}$'
  examples/data/invalid.json:8: $.nickname: unexpected property 'nickname'
OK    examples/data/valid.json

Checked 3 files: 1 valid, 2 invalid, 8 errors.
```

### Exit codes

| Code | Meaning |
|------|---------|
| 0    | All files are valid |
| 1    | At least one file has validation or JSON syntax errors |
| 2    | The schema is unusable, a file could not be read, or no files were found |

### Using it as a library

```python
from schema_linter import check_schema, parse_with_lines, validate

value, lines = parse_with_lines(open("data.json", encoding="utf-8").read())
for error in validate(value, schema):
    print(lines.get(error.path), error.location, error.message)
```

## Project layout

```
schema_linter/
  locator.py    JSON parser that records the line of every value
  validator.py  schema validation and schema sanity checks
  cli.py        command-line interface and batch mode
examples/       a sample schema plus valid, invalid and malformed data
tests/          pytest suite
```

## Running the tests

```sh
python -m pytest -q
```

The tests cover the line-tracking parser (including malformed JSON),
every supported keyword, malformed schemas, and the CLI including batch mode.

Built with Claude Code, picked by VERONICA.
