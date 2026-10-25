"""v406 — knowledge/research UI + Browser removal + org-chart click (JAG-403h).

Stdlib-only, deterministic, no browser. Covers the user's 6 points:

  0) the duplicate BROWSER tab is removed (its search half duplicated Discover)
  1) org-chart single click previews the constellation AND highlights + scrolls to
     the agent in the AGENTS table (JAG-451 — was preview-only in JAG-403h)
  3) a `text` source (pasted text / research summary) is NOT a false file link
  4) the notebooks list is bounded (scrolls when there are many)
  5) depth + max-sources are ALWAYS visible and drive both modes
  6) Knowledge status/clear sit to the RIGHT of the counts (wrap when narrow)
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HTML = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
ORBIT = open(os.path.join(REPO, "src", "longrun", "orbit", "web", "orbit.html"), encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if (detail and not ok) else ""))


# ------------------------------------------------------------------ 0) Browser gone
check("0 the Browser tab + its code are removed",
      'data-insp="browser"' not in HTML and "function browserGo" not in HTML
      and "function _renderBrowserUrls" not in HTML and '["browser", "Browser"]' not in HTML)

# ------------------------------------------------------------------ 1) org chart click
check("1a org-chart single click also highlights the agent in the AGENTS table (v615: select, no camera — scroll only when asked)",
      "this.agents.focusAgent(a.session)" in ORBIT and "focusAgent(sid, scroll)" in ORBIT
      and "_applyFocus()" in ORBIT and 'classList.add("rowsel")' in ORBIT
      and "scrollIntoView" in ORBIT and "_scrollNext" in ORBIT)
check("1b it still opens the constellation (onPick)",
      "if (this.onPick) this.onPick(this.bySid[n.dataset.sid]);" in ORBIT)

# ------------------------------------------------------------------ 3) text source
_i = HTML.find("function _kbSourceRow")
_seg = HTML[_i:_i + 2000]
check("3 a `text` source is shown as plain text (no false file link)",
      'else if (s.kind === "text")' in _seg
      and _seg.index('s.kind === "text"') < _seg.index("else if (ref) {"))

# ------------------------------------------------------------------ 4) notebooks bounded
check("4 the notebooks list is a bounded scroll window",
      'id="kbNotebooks" style="max-height:200px;overflow:auto' in HTML)

# ------------------------------------------------------------------ 5) research options
check("5a depth + max-sources are ALWAYS visible (before the auto-only block)",
      0 <= HTML.index('id="researchDepth"') < HTML.index('id="kbAutoOpts" hidden'))
check("5b max sources still has its input",
      'id="researchN"' in HTML)
check("5c manual discover uses the chosen max-sources value",
      'parseInt(($("researchN") && $("researchN").value)' in HTML
      and '/api/knowledge/discover", { q: q, n: n }' in HTML)
check("5d the deep/shallow depth select is present",
      '<option value="deep">deep</option>' in HTML and '<option value="shallow">shallow</option>' in HTML)

# ------------------------------------------------------------------ 6) status/clear right
check("6a the Knowledge counts + buttons share one wrapping flex row",
      # JAG-425: the repeated inline style became utility classes (u-df u-g6 u-f0a).
      'id="indexMeta" style="flex:1;min-width:180px"' in HTML
      and ('style="display:flex;gap:6px;flex:0 0 auto"' in HTML
           or 'class="u-df u-g6 u-f0a"' in HTML))
check("6b status/clear no longer sit in their own row below",
      'title="refresh the counts">status</button>' in HTML
      and 'onclick="kbStatus()"' not in HTML)

print("---")
ok = sum(results)
print("%d/%d checks passed" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
