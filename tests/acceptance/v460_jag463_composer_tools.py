#!/usr/bin/env python3
"""v460 — JAG-463: composer send-while-running, bookmark reveal, bulk tool policy.

  A) a HUMAN STEER must not be dropped by a budget / no-progress stop (live:
     "forced steer doesn't cause the LLM to proceed").
  B) Settings > Tools & approvals has a one-request bulk enable/disable.
  C) a chat bookmark click OPENS every collapsed ancestor section before aligning.
  D) while a turn runs the composer button shows a GREEN dot when the queue is
     non-empty (the button itself stays the red Stop).
  E) model/tool names reach the DOM data-attributes RAW (not HTML-escaped).

Deterministic: no model, no network, no server.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.plan import keepgoing  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _read(rel):
    with open(os.path.join(REPO, rel), encoding="utf-8") as f:
        return f.read()


# ---- A) steer beats the budget / no-progress stop ----------------------------
_c = keepgoing.cfg()
check("A1 keepgoing has a rounds cap to defeat (test precondition)",
      int(_c["keepgoing_max"]) > 0, _c["keepgoing_max"])
_bud = keepgoing.decide(open_nodes=2, rounds=_c["keepgoing_max"], stale=0, started=0,
                        now=1)
check("A2 a spent budget stops the turn (no steer)", _bud["continue"] is False
      and _bud["reason"] == "budget", _bud)
_steer = keepgoing.decide(open_nodes=2, rounds=_c["keepgoing_max"], stale=0, started=0,
                          now=1, steer=True)
check("A3 a pending STEER overrides the budget stop", _steer["continue"] is True,
      _steer)
_stale = keepgoing.decide(open_nodes=2, rounds=0, stale=int(_c["no_progress_rounds"]),
                          started=0, now=1, steer=True)
check("A4 a pending STEER overrides the no-progress stop", _stale["continue"] is True,
      _stale)
_ab = keepgoing.decide(open_nodes=2, rounds=0, stale=0, started=0, now=1, steer=True,
                       aborted=True)
check("A5 an ABORT still wins over a steer", _ab["continue"] is False
      and _ab["reason"] == "user_stop", _ab)

# ---- B) bulk tool policy (one request) ---------------------------------------
_api = _read("src/longrun/core/api_v02.py")
check("B1 POST /api/tools accepts enable_all / disable_all",
      'body.get("enable_all")' in _api and 'body.get("disable_all")' in _api
      and 'bulk=("enable" if want else "disable")' in _api)
_html = _read("webui/index.html")
check("B2 the panel offers enable-all / disable-all buttons",
      'data-bulk="enable"' in _html and 'data-bulk="disable"' in _html)
check("B3 the buttons post the bulk request and re-render",
      "{ enable_all: true }" in _html and "{ disable_all: true }" in _html)

# ---- B4/B5/B6) JAG-498 grouped (per-namespace) tool policy -------------------
check("B4 POST /api/tools accepts a GROUPED `tools` list applied in one request",
      'group = body.get("tools")' in _api
      and "_apply_tool_fields(entry, body)" in _api
      and 'return {"ok": True, "updated": len(group), "tools": registry.catalog()}' in _api)
check("B5 the panel groups tools by namespace, collapsible + state remembered",
      'data-group="${gid}"' in _html and "longrun:toolGroups" in _html
      and 'data-gap="${gid}"' in _html and 'data-gbulk="${gid}"' in _html
      and "{ tools: names, approval: next }" in _html
      and 'enabled: b.dataset.gon !== "1"' in _html)
check("B6 a row shows why a stored `required` does not ask under global FULL",
      'FULL \u21d2 auto' in _html and "global FULL: every tool is auto (never ask)" in _html
      and 'const cur = b.dataset.cur;' in _html)
check("B7 an MCP tool with no dot (`<client>__<tool>`) groups under its client",
      'const sep = dot > 0 ? dot : nm0.indexOf("__");' in _html
      and 'const g = sep > 0 ? nm0.slice(0, sep) : "";' in _html)

# ---- C) a bookmark reveals its collapsed section -----------------------------
check("C1 the bookmark click opens every ancestor <details> before aligning",
      "if (_p.tagName === \"DETAILS\" && !_p.open) { _p.open = true; _opened = true; }" in _html
      and "if (_opened) requestAnimationFrame(() => _alignChatNodeTop(log, m));" in _html)

# ---- D) the queue indicator on the (stop) button ----------------------------
check("D1 the send button carries a hasqueue state",
      'b.classList.toggle("hasqueue", qn > 0);' in _html
      and "#sendBtn.hasqueue::after" in _html)
check("D2 the queue bar refreshes the button state",
      "refreshSendBtn();   // JAG-463: keep the queue dot" in _html)
check("D3 Ctrl+Enter (send) does not also fire the slash picker",
      'e.key === "Enter" && !e.ctrlKey && !e.metaKey' in _html)

# ---- E) raw names in data-attributes ----------------------------------------
check("E1 tool rows put the RAW name in data-tool/data-ap",
      'const nmRaw = _attr(t.name || t.id || "?");' in _html
      and 'data-tool="${nmRaw}"' in _html and 'data-ap="${nmRaw}"' in _html)

print("---")
okc = sum(results)
print("\nv460: %d/%d PASS" % (okc, len(results)))
sys.exit(0 if okc == len(results) else 1)
