#!/usr/bin/env python3
"""v585 — assistant bubbles are stamped with the answering agent + date/time.

Every assistant reply header reads "<agent-id> · LONGRUN" (e.g. A51 · LONGRUN)
when the session is designated, else plain LONGRUN; the date+time stamp
(MM-DD HH:MM:SS) rides on every header as before.

Deterministic static guards on webui/index.html.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


HTML = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()

check("A1 agent-label helper exists and reads the session agent",
      "function _aiLabel()" in HTML and "_agents" in HTML.split("function _aiLabel()")[1][:300]
      and "sessionId" in HTML.split("function _aiLabel()")[1][:300])
check("A2 label falls back to plain LONGRUN without designation",
      '"LONGRUN"' in HTML.split("function _aiLabel()")[1][:400])
check("A3 chat bubbles use the agent label",
      "_aiLabel()" in HTML and 'role === "user" ? "YOU" : _aiLabel()' in HTML)
check("A4 no hardcoded assistant LONGRUN header survives",
      ">LONGRUN</div><details" not in HTML.replace(" ", "").replace("\n", "")
      or HTML.count('>LONGRUN</div><details') == 0,
      "hardcoded assistant headers must all route through _aiLabel()")
check("A5 date+time stamp still rides on every header",
      "MM-DD HH:MM:SS" in HTML and "_tsSpan" in HTML)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
