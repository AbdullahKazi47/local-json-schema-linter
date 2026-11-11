"""Command-line interface for the JSON Schema linter.

Usage:
    python -m schema_linter SCHEMA TARGET [TARGET ...] [--recursive] [--quiet]

Each TARGET may be a JSON file or a directory. Directories are checked in
batch mode: every ``*.json`` file inside is validated against SCHEMA.

Exit codes: 0 = everything valid, 1 = validation or JSON syntax errors found,
2 = the schema itself is unusable or a target cannot be read.
"""

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .locator import JSONSyntaxError, parse_with_lines
from .validator import SchemaError, check_schema, validate

EXIT_OK = 0
EXIT_INVALID = 1
EXIT_ERROR = 2


@dataclass
class Issue:
    line: int
    location: str
    message: str

    def render(self, filename):
        if self.location:
            return f"{filename}:{self.line}: {self.location}: {self.message}"
        return f"{filename}:{self.line}: {self.message}"


@dataclass
class FileReport:
    path: Path
    issues: list = field(default_factory=list)
    fatal: bool = False

    @property
    def ok(self):
        return not self.issues


def _line_for(path, lines):
    """Find the line of ``path``, falling back to its nearest known parent."""
    while path not in lines and path:
        path = path[:-1]
    return lines.get(path, 1)


def load_json(path):
    """Read and parse a JSON file, returning ``(value, lines)``."""
    text = Path(path).read_text(encoding="utf-8")
    return parse_with_lines(text)


def lint_text(text, schema):
    """Validate JSON ``text`` against an already-checked ``schema``.

    Returns a list of :class:`Issue` sorted by line number.
    """
    try:
        value, lines = parse_with_lines(text)
    except JSONSyntaxError as exc:
        return [Issue(exc.line, "", f"invalid JSON: {exc.message} (column {exc.column})")]
    issues = [
        Issue(_line_for(err.path, lines), err.location, err.message)
        for err in validate(value, schema)
    ]
    return sorted(issues, key=lambda issue: issue.line)


def lint_file(path, schema):
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return FileReport(path, [Issue(1, "", f"cannot read file: {exc}")], fatal=True)
    return FileReport(path, lint_text(text, schema))


def load_schema(path):
    """Load and sanity-check a schema file.

    Returns ``(schema, problems)`` where ``problems`` is a list of rendered
    error lines; ``schema`` is ``None`` when the schema is unusable.
    """
    try:
        schema, lines = load_json(path)
    except (OSError, UnicodeDecodeError) as exc:
        return None, [f"{path}: cannot read schema: {exc}"]
    except JSONSyntaxError as exc:
        return None, [f"{path}:{exc.line}: invalid JSON in schema: {exc.message} "
                      f"(column {exc.column})"]
    errors = check_schema(schema)
    if errors:
        rendered = [
            Issue(_line_for(err.path, lines), err.location, err.message).render(path)
            for err in errors
        ]
        return None, rendered
    return schema, []


def collect_targets(targets, schema_path, recursive=False):
    """Expand directories into the JSON files they contain."""
    schema_resolved = Path(schema_path).resolve()
    files = []
    for target in targets:
        target = Path(target)
        if target.is_dir():
            pattern = "**/*.json" if recursive else "*.json"
            found = sorted(p for p in target.glob(pattern) if p.is_file())
            files.extend(p for p in found if p.resolve() != schema_resolved)
        else:
            files.append(target)
    return files


def build_parser():
    parser = argparse.ArgumentParser(
        prog="schema_linter",
        description="Validate JSON files against a local JSON Schema, fully offline.",
    )
    parser.add_argument("schema", help="path to the JSON Schema file")
    parser.add_argument(
        "targets", nargs="+", metavar="TARGET",
        help="JSON file(s) to check, or directories to check in batch mode",
    )
    parser.add_argument(
        "-r", "--recursive", action="store_true",
        help="in batch mode, also search sub-directories",
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true",
        help="only print errors and the final summary",
    )
    return parser


def main(argv=None, out=None):
    out = out or sys.stdout
    args = build_parser().parse_args(argv)

    schema, problems = load_schema(args.schema)
    if schema is None:
        print("Schema is not usable:", file=out)
        for line in problems:
            print(f"  {line}", file=out)
        return EXIT_ERROR

    files = collect_targets(args.targets, args.schema, args.recursive)
    if not files:
        print("No JSON files found to check.", file=out)
        return EXIT_ERROR

    reports = []
    for path in files:
        try:
            report = lint_file(path, schema)
        except SchemaError as exc:
            print(f"Schema is not usable: {exc}", file=out)
            return EXIT_ERROR
        reports.append(report)
        if report.ok:
            if not args.quiet:
                print(f"OK    {path}", file=out)
            continue
        print(f"FAIL  {path} ({len(report.issues)} error"
              f"{'' if len(report.issues) == 1 else 's'})", file=out)
        for issue in report.issues:
            print(f"  {issue.render(path)}", file=out)

    failed = sum(1 for r in reports if not r.ok)
    total_errors = sum(len(r.issues) for r in reports)
    print(f"\nChecked {len(reports)} file{'s' if len(reports) != 1 else ''}: "
          f"{len(reports) - failed} valid, {failed} invalid, "
          f"{total_errors} error{'s' if total_errors != 1 else ''}.", file=out)

    if any(r.fatal for r in reports):
        return EXIT_ERROR
    return EXIT_INVALID if failed else EXIT_OK
