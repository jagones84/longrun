#!/usr/bin/env python3
"""v572 (STAGED — audit F5): malformed/unreadable configs warn loudly instead
of failing silently. Missing files stay silent (normal first-run).
"""

import logging
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
TMP = tempfile.mkdtemp(prefix="sf-v572-")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.util import dataio  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


LOG = logging.getLogger("longrun.util.dataio")


class _H(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, r):
        self.records.append(r)


h = _H()
LOG.addHandler(h)
try:
    bad = os.path.join(TMP, "bad.yaml")
    with open(bad, "w", encoding="utf-8") as f:
        f.write("tools: [unclosed\n  bad indent: : :\n")
    h.records.clear()
    out = dataio.read_yaml(bad, {"fallback": True})
    check("1a malformed YAML still returns the default (never fatal)",
          out == {"fallback": True}, out)
    check("1b malformed YAML warns with the path",
          any(r.levelno >= logging.WARNING and "bad.yaml" in r.getMessage()
              for r in h.records),
          [r.getMessage() for r in h.records])

    missing = os.path.join(TMP, "nope.yaml")
    h.records.clear()
    out = dataio.read_yaml(missing, {"fallback": True})
    check("2a missing file still returns the default",
          out == {"fallback": True}, out)
    check("2b missing file stays silent (normal first-run)",
          not h.records, [r.getMessage() for r in h.records])

    h.records.clear()
    out = dataio.load_yaml("{oops", {"fallback": True})
    check("3a malformed inline text returns the default",
          out == {"fallback": True}, out)
    check("3b malformed inline text warns",
          any(r.levelno >= logging.WARNING for r in h.records),
          [r.getMessage() for r in h.records])
finally:
    LOG.removeHandler(h)

print("TOTAL %d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
