"""Local JSON Schema Linter: validate JSON files against local schemas offline."""

from .locator import JSONSyntaxError, parse_with_lines
from .validator import SchemaError, ValidationError, check_schema, validate

__all__ = [
    "JSONSyntaxError",
    "SchemaError",
    "ValidationError",
    "check_schema",
    "parse_with_lines",
    "validate",
]

__version__ = "1.0.0"
