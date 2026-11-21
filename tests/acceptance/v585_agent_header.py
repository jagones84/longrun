#!/usr/bin/env python3
"""v585 — an ANSWER carries no header; a user turn keeps "YOU"; a delegated turn keeps its
sender.

Originally (2026-11-05) every assistant reply was stamped "<agent-id> · LONGRUN". Operator
(2026-11-22, TRAE screenshots): *"perché devi continuamente scrivere A54 · LONGRUN? a cosa
serve? rimuovi quella cosa"*. The assistant header is gone; the per-message copy control
survives on the same line (hover-revealed). A delegated turn still names its sender + subjob,
because a worker must never look like the operator asked it directly.

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

check("A1 the assistant label helper is gone (no dead header builder)",
      "function _aiLabel()" not in HTML and "_aiLabel()" not in HTML)
check("A2 no hardcoded assistant header survives",
      '>LONGRUN</div>' not in HTML and "· LONGRUN</div>" not in HTML)
check("A3 an answer's who line carries ONLY the copy control",
      'const _label = sender ? (sender + (subjob ? " · " + subjob : ""))' in HTML
      and ': (role === "user" ? "YOU" : "");' in HTML
      and 'class="who${_label ? "" : " who-bare"}' in HTML)
check("A4 a user turn keeps YOU and BOTH messages carry the date on the LEFT",
      '(role === "user" ? "YOU" : "")' in HTML and "_dateSpan(ts)" in HTML
      and "_dateSpan(ts) +" in HTML)
check("A5 a delegated turn keeps its sender + subjob attribution",
      "DELEGATED turn keeps its sender + subjob attribution" in HTML
      and 'sender + (subjob ? " · " + subjob : "")' in HTML)
check("A6 the copy control is hover-revealed on an answer, not a permanent row",
      ".msg.ai .who .copy { opacity: 0; transition: opacity .12s; }" in HTML
      and ".msg.ai:hover .who .copy, .msg.ai:focus-within .who .copy { opacity: 1; }" in HTML)
check("A7 the THOUGHT blocks draw no who line at all",
      '<div class="who">${esc(_aiLabel())}</div><details class="think' not in HTML
      and HTML.count('<details class="think') >= 3)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
