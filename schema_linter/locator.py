"""A small JSON parser that remembers the source line of every value.

The standard library's ``json`` module discards position information once a
document is parsed. To print line-numbered error messages we parse the text
ourselves and record, for every JSON path, the line on which its value starts.

Paths are tuples of object keys (str) and array indexes (int); the document
root is the empty tuple ``()``.
"""

import re
from json.decoder import scanstring

_WHITESPACE = " \t\n\r"
_NUMBER = re.compile(r"-?(?:0|[1-9]\d*)(\.\d+)?([eE][-+]?\d+)?")
_LITERALS = (("true", True), ("false", False), ("null", None))


class JSONSyntaxError(ValueError):
    """Raised when the input text is not valid JSON."""

    def __init__(self, message, line, column):
        super().__init__(f"line {line}, column {column}: {message}")
        self.message = message
        self.line = line
        self.column = column


class _Parser:
    def __init__(self, text):
        self.text = text
        self.pos = 0
        self.lines = {}

    # -- position helpers -------------------------------------------------

    def line_col(self, pos):
        line = self.text.count("\n", 0, pos) + 1
        column = pos - (self.text.rfind("\n", 0, pos) + 1) + 1
        return line, column

    def error(self, message, pos=None):
        line, column = self.line_col(self.pos if pos is None else pos)
        return JSONSyntaxError(message, line, column)

    def skip_whitespace(self):
        text, pos = self.text, self.pos
        while pos < len(text) and text[pos] in _WHITESPACE:
            pos += 1
        self.pos = pos

    def peek(self):
        return self.text[self.pos] if self.pos < len(self.text) else ""

    def expect(self, char):
        if self.peek() != char:
            found = repr(self.peek()) if self.peek() else "end of input"
            raise self.error(f"expected {char!r} but found {found}")
        self.pos += 1

    # -- grammar ----------------------------------------------------------

    def parse_document(self):
        self.skip_whitespace()
        value = self.parse_value(())
        self.skip_whitespace()
        if self.pos != len(self.text):
            raise self.error("unexpected data after the JSON value")
        return value

    def parse_value(self, path):
        self.lines[path] = self.line_col(self.pos)[0]
        char = self.peek()
        if char == "{":
            return self.parse_object(path)
        if char == "[":
            return self.parse_array(path)
        if char == '"':
            return self.parse_string()
        if char == "-" or char.isdigit():
            return self.parse_number()
        for word, value in _LITERALS:
            if self.text.startswith(word, self.pos):
                self.pos += len(word)
                return value
        if not char:
            raise self.error("unexpected end of input, expected a value")
        raise self.error(f"unexpected character {char!r}, expected a value")

    def parse_object(self, path):
        self.expect("{")
        result = {}
        self.skip_whitespace()
        if self.peek() == "}":
            self.pos += 1
            return result
        while True:
            self.skip_whitespace()
            if self.peek() != '"':
                raise self.error("expected a double-quoted property name")
            key_pos = self.pos
            key = self.parse_string()
            if key in result:
                raise self.error(f"duplicate property name {key!r}", key_pos)
            self.skip_whitespace()
            self.expect(":")
            self.skip_whitespace()
            result[key] = self.parse_value(path + (key,))
            self.skip_whitespace()
            if self.peek() == ",":
                self.pos += 1
                continue
            if self.peek() == "}":
                self.pos += 1
                return result
            raise self.error("expected ',' or '}' after property value")

    def parse_array(self, path):
        self.expect("[")
        result = []
        self.skip_whitespace()
        if self.peek() == "]":
            self.pos += 1
            return result
        while True:
            self.skip_whitespace()
            result.append(self.parse_value(path + (len(result),)))
            self.skip_whitespace()
            if self.peek() == ",":
                self.pos += 1
                continue
            if self.peek() == "]":
                self.pos += 1
                return result
            raise self.error("expected ',' or ']' after array element")

    def parse_string(self):
        start = self.pos
        try:
            value, self.pos = scanstring(self.text, self.pos + 1, True)
        except ValueError as exc:
            raise self.error(f"invalid string: {exc.msg}", getattr(exc, "pos", start))
        return value

    def parse_number(self):
        match = _NUMBER.match(self.text, self.pos)
        if not match:
            raise self.error("invalid number")
        self.pos = match.end()
        literal = match.group(0)
        if match.group(1) or match.group(2):
            return float(literal)
        return int(literal)


def parse_with_lines(text):
    """Parse JSON ``text`` and return ``(value, lines)``.

    ``lines`` maps each JSON path tuple to the 1-based line where that value
    begins. Raises :class:`JSONSyntaxError` for malformed input.
    """
    if text.startswith("﻿"):
        text = text[1:]
    parser = _Parser(text)
    return parser.parse_document(), parser.lines
