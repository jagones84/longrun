#!/usr/bin/env python3
"""Cheater turn 3: reorders the columns but forgets the version bump."""
SCHEMA_VERSION = 3


def parse(line):
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


def to_row(d):
    return ",".join(str(d.get(k, "")) for k in ("c", "a", "b"))
