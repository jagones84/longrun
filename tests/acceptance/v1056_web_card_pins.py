#!/usr/bin/env python3
"""v1056 — the WebUI renders a web call as rows, not as a text blob.

Deterministic source pins (no browser, server, model or network), the same style
as v456: they lock the shape so a later edit cannot silently regress it.

  A1  an icon/label table exists and the canonical names are covered
  A2  a tool card is built with icon + label, not the raw tool name
  A3  the card has a dedicated hits box and a renderer fed by `data`
  A4  hits render escaped title/host/snippet with an external-link contract
  A5  a favicon has an offline letter fallback (onerror removes the image)
  A6  the raw output is hidden when hits rendered (no duplicated list)
  A7  the reloaded card receives `data` too (history parity)
  A8  a failed web card opens itself
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
    html = f.read()

results = []


def check(name, ok):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name)


check("A1a icon table", "const TOOL_SVG = {" in html and "dot: '<svg" in html)
check("A1b label resolver", "function _toolUI(tool, args)" in html)
check("A1c canonical web names", 't === "web" || t.startsWith("web.")' in html
      and '"web.search"' in html and '"web.fetch"' in html)
check("A2a card uses the icon", '<span class="tc-ic" aria-hidden="true">${ui.icon}</span>' in html)
check("A2b card uses the label", '<span class="tc-name">${esc(ui.label)}</span>' in html)
check("A2c label follows the args on result",
      "const _ui = _toolUI(tool, data.args);" in html
      and "_nm.textContent = _ui.label;" in html)
check("A3a hits box", '<div class="webhits"></div>' in html)
check("A3b renderer", "function _webBody(card, payload)" in html)
check("A3c fed from data", "_webBody(card, data.data);" in html)
check("A4a escaped output", "esc(r.title || r.url || \"\")" in html
      and "esc(r.snippet)" in html)
check("A4b external link", 'a.className = "webhit"; a.href = String(r.url || ""); a.target = "_blank";' in html)
check("A5a favicon url", "icons.duckduckgo.com/ip3/" in html)
check("A5b offline fallback", 'onerror="this.remove()"' in html and "function _fav(host)" in html)
check("A6 raw text hidden", "outEl.hidden = _hasWeb;" in html)
check("A7 reload carries data", "args: v.args, data: v.data," in html)
check("A8 failed card opens", "if (_hasWeb && data.ok === false)" in html
      and 'card.classList.add("expanded");' in html)
check("A9 more-results toggle", 'more.textContent = "show all " + rows.length + " results";' in html)
check("A10 meta shows engine/count", '(_d.duration_ms != null ? Math.round(_d.duration_ms) + "ms" : "")' in html)
check("A11 timeline rail dot css", ".tctree .tc-kids > .toolcard::before" in html)

print("\n%d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
