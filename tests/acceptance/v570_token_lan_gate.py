#!/usr/bin/env python3
"""v570 (STAGED — audit F1): a non-loopback bind without a token must refuse
to serve unless explicitly opted out (`--insecure-lan`).
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server  # noqa: E402,F401 — server first (circular import)
from longrun.core import httpapi  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


gate = getattr(httpapi, "lan_bind_allowed", None)
if gate is None:
    for n in ("1a", "1b", "2a", "2b", "3a", "3b"):
        check(n + " tokenless-LAN gate", False, "lan_bind_allowed missing")
    print("TOTAL %d/%d" % (sum(results), len(results)))
    sys.exit(1)

check("1a loopback without a token stays allowed",
      gate("127.0.0.1", None, False) is True)
check("1b IPv6 loopback without a token stays allowed",
      gate("::1", None, False) is True)
check("2a 0.0.0.0 without a token is refused",
      gate("0.0.0.0", None, False) is False)
check("2b a LAN IP without a token is refused",
      gate("192.168.1.37", None, False) is False)
check("3a 0.0.0.0 with a token is allowed",
      gate("0.0.0.0", "secret", False) is True)
check("3b explicit insecure-lan opt-out is allowed (operator's risk)",
      gate("0.0.0.0", None, True) is True)

print("TOTAL %d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
