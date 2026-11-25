"""Original entity KeyValues syntax reader shared by inspection and recovery.

Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
Preserves duplicate outputs and literal path separators; no script execution.
"""
from inspect_bsp import FormatError


def parse_entities(text):
    """Preserve duplicate keyvalues. Reject incomplete/nested entity blocks."""
    prefix, terminator, tail = text.partition('\0')
    if terminator and tail.strip('\0 \t\r\n'):
        raise FormatError('Entity data follows NUL terminator')
    text = prefix
    tokens, i = [], 0
    while i < len(text):
        c = text[i]
        if c.isspace() or c == '\0':
            i += 1; continue
        if text.startswith('//', i):
            end = text.find('\n', i); i = len(text) if end < 0 else end+1; continue
        if c in '{}':
            tokens.append(c); i += 1; continue
        if c != '"':
            raise FormatError('Expected a quoted entity key/value')
        i += 1; value = ''
        while i < len(text) and text[i] != '"':
            if text[i] == '\\' and i+1 < len(text) and text[i+1] in '\\"':
                i += 1
            value += text[i]; i += 1
        if i == len(text):
            raise FormatError('Unterminated entity string')
        i += 1; tokens.append(('value', value))
    result, i = [], 0
    while i < len(tokens):
        if tokens[i] != '{':
            raise FormatError('Expected entity opening brace')
        pairs = []; i += 1
        while i < len(tokens) and tokens[i] != '}':
            if i+1 >= len(tokens) or not isinstance(tokens[i], tuple) or not isinstance(tokens[i+1], tuple):
                raise FormatError('Entity key/value pair is incomplete')
            pairs.append([tokens[i][1], tokens[i+1][1]]); i += 2
        if i == len(tokens):
            raise FormatError('Unterminated entity block')
        result.append(pairs); i += 1
    return result



def parse_partition(data):
    """Read the native ENTITIES01 text format; other headers fail explicitly."""
    header, newline, body = data.partition(b'\n')
    if not newline or header.rstrip(b'\r') != b'ENTITIES01':
        raise FormatError('Expected terminated ENTITIES01 partition header')
    return parse_entities(body.decode('utf-8', errors='surrogateescape'))
