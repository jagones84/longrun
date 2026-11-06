#!/usr/bin/env python3
"""Duration conversion: HH/MM/SS parsing and formatting."""
import re
import sys

PART = re.compile(r"(\d+)([hms])")
ORDER = {"h": 0, "m": 1, "s": 2}


def parse_duration(text):
    """'1h30m15s' -> 5415. Raises ValueError outside the documented grammar."""
    s = str(text)
    if not s:
        raise ValueError("empty duration")
    if s.strip() != s:
        raise ValueError("surrounding whitespace")
    pos, seen, total = 0, -1, 0
    while pos < len(s):
        m = PART.match(s, pos)
        if not m:
            raise ValueError("bad part at %r" % s[pos:])
        unit = m.group(2)
        if ORDER[unit] <= seen:
            raise ValueError("unit out of order: %r" % s)
        seen = ORDER[unit]
        total += int(m.group(1)) * {"h": 3600, "m": 60, "s": 1}[unit]
        pos = m.end()
    return total


def format_duration(seconds):
    """5400 -> '1h30m'. Raises ValueError on a negative or non-integer input."""
    if not isinstance(seconds, int) or isinstance(seconds, bool) or seconds < 0:
        raise ValueError("seconds must be a non-negative integer")
    out = []
    for unit, size in (("h", 3600), ("m", 60), ("s", 1)):
        if seconds >= size:
            out.append("%d%s" % (seconds // size, unit))
            seconds %= size
    return "".join(out) or "0s"


def main(argv):
    if len(argv) != 2:
        print("usage: convert.py <duration>", file=sys.stderr)
        return 2
    try:
        print(parse_duration(argv[1]))
    except ValueError as exc:
        print("usage: convert.py <duration> (%s)" % exc, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
