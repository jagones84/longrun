#!/usr/bin/env python3
"""Pipeline schema v3: parse only."""
SCHEMA_VERSION = 3


def parse(line):
    """Parse `key=value;key=value` into a dict; last duplicate wins."""
    out = {}
    text = str(line)
    if not text:
        return out
    for segment in text.split(";"):
        segment = segment.strip()
        if not segment:
            continue
        if "=" not in segment:
            raise ValueError("segment without '=': %r" % segment)
        key, value = segment.split("=", 1)
        key, value = key.strip(), value.strip()
        if not key:
            raise ValueError("empty key in %r" % segment)
        out[key] = value
    return out
