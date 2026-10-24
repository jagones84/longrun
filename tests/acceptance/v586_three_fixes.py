#!/usr/bin/env python3
"""v586 — three small verified bugs, three areas.

W1 composer chips: the #cmdChips div carries inline `display:flex`, which beats
   the `hidden` attribute — the empty bar is ALWAYS visible (dead strip above
   the input). The function must drive visibility via style.display instead.
W2 stale chips: `loadSkills()` fills _skillsCache async but never re-renders
   the chips — a /skill typed before the cache loads stays grey until the next
   keystroke.
B3 dropped thought: the OpenAI-envelope branch of `_normalize_action`
   (`{"name","arguments"}`) returns only action/tool/args — the model's
   `thought` is lost and the CoT attribution breaks for those models.

Deterministic: statics on webui/index.html + one unit on agent.py.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


HTML = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()

_div = HTML[HTML.find('<div id="cmdChips"'):HTML.find('<div id="cmdChips"') + 200]
check("W1 chips visibility is driven by JS, not fought by inline CSS",
      "display:flex" not in _div and "display: flex" not in _div, _div[:150])
_fn = HTML[HTML.find("function _renderCmdChips()"):]
_fn = _fn[:_fn.find("}\n", _fn.find("box.hidden"))]
check("W1b the function toggles display itself",
      "style.display" in _fn, "toggle present")
_ls = HTML[HTML.find("async function loadSkills()"):]
_ls = _ls[:_ls.find("}\n", _ls.find("renderSkills();")) + 2]
check("W2 skill cache fill re-renders the composer chips",
      "_renderCmdChips()" in _ls, "re-render on load")

from longrun.core import server as _srv  # noqa: E402,F401 — first: breaks the agent<->server cycle
from longrun.agent import agent as _ag  # noqa: E402

n = _ag._normalize_action({"name": "fs.read", "arguments": {"path": "a.py"},
                           "thought": "read the file"})
check("B3 OpenAI envelope keeps the thought",
      isinstance(n, dict) and n.get("thought") == "read the file"
      and n.get("tool") == "fs.read", n)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
