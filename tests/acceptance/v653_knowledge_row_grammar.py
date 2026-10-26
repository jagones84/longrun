"""v653 — ONE row grammar, ONE scrollbar, no prose in cards (Settings ▸ Knowledge).

Operator, on a Knowledge screenshot: "guarda questa pagina ti prego. vedi che
schifo di disordine? applica fix qui e ovunque, non solo qui".

What was actually wrong (and is fixed here, in every list of that panel and in
the two other Settings cards that had the same shape):

  A) a row was built ad hoc per list: a lowercase chip, an inline-styled link, a
     BARE NUMBER with no unit, and a ✕ floating in its own baseline.
  B) the sources list scrolled inside the settings panel's own scroll — two
     scrollbars for one page.
  C) explanatory paragraphs lived INSIDE cards (knowledge meta, research mode,
     appearance bold-text, config backup) — the section tooltip is where they
     belong.
  D) controls named their implementation, not their object ("+ add + index",
     "↻ sources" that switched view instead of refreshing it).

Stdlib only, deterministic, no browser.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HTML = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name +
          ((" :: " + str(detail)) if (detail and not ok) else ""))


def _fn(name):
    i = HTML.find("function " + name)
    return HTML[i:i + 2600] if i >= 0 else ""


SRC = _fn("_kbSourceRow")
FILES = _fn("kbFiles")
LOAD = _fn("kbLoadSources")
NB = _fn("kbLoadNotebooks")
SESS = _fn("kbLoadSessions")

# ---- A. one row grammar, and every number carries its unit --------------------
check("A1 a source row is chip + object + count-with-unit + remove",
      # v657 (operator: "no code duplication, single source of truth"): the
      # count-with-unit fragment is built ONCE by `_chunkSpan`; both lists call it,
      # so the literal lives in that builder and not in the row function.
      'class="kb-kind"' in SRC and 'class="kb-main' in SRC
      and "_chunkSpan(s.chunks)" in SRC
      and 'class="kb-x"' in SRC)
check("A2 the files list speaks the same grammar",
      'class="kb-kind">file' in FILES
      and 'class="kb-main kbopen"' in FILES
      and "_chunkSpan(f.chunks)" in FILES)
check("A3 the list caption states both numbers with units",
      '_plural(rows.length, "source")' in LOAD and '_plural(chunks, "chunk")' in LOAD
      and '_plural(rows.length, "file")' in FILES)
check("A4 a notebook row labels its count too",
      '_plural(n.sources || 0, "source")' in NB
      and '_plural(n.sources || 0, "source")' in SESS)
check("A4b one plural helper, so '1 chunks' cannot happen",
      "function _plural(n, word)" in HTML and 'v === 1 ? "" : "s"' in HTML
      and ".toLocaleString()" in HTML)
check("A5 no bare-number cell is left in the Knowledge lists",
      'class="cn"' not in SRC and 'class="cn"' not in FILES
      and 'class="cn"' not in NB and 'class="cn"' not in SESS)

# ---- B. one scrollbar ---------------------------------------------------------
check("B1 the list is not a second scroll window",
      "#swMain .kb-list { max-height" not in HTML
      and 'id="kbNotebooks" style="max-height' not in HTML)

# ---- C. prose lives in the section tooltip, not in the card -------------------
check("C1 the knowledge meta block is numbers, not a sentence",
      'class="kb-meta" id="indexMeta"' in HTML
      and "Global knowledge base — notebooks of sources" not in HTML
      and 'title="Global knowledge base: notebooks of sources' in HTML)
check("C2 the auto mode explains itself on hover",
      # v656 (operator: the Research panel wasted a line): the mode switch rides
      # the topic row and its label shrank to the object it names — the full
      # explanation stays in the title, which is what this check is really about.
      "<span>auto</span>" in HTML
      and "search + fetch + summarise + import (uses the research LLM)" not in HTML
      and "search + fetch + summarise + import, using the research LLM" in HTML)
check("C3 the bold-text label is a label, the explanation a tooltip",
      "<span>Bolder text</span>" in HTML
      and "heavier weights on messages, labels and headings" not in HTML)
check("C4 the config backup prose is a tooltip, not a card",
      "Why routing.yaml is listed" not in HTML
      and "routing.yaml is listed because" in HTML)

# ---- D. controls name their object -------------------------------------------
check("D1 add does not carry two verbs", "+ add + index" not in HTML
      and 'data-call="kbAddSource" title="fetch every ref in the box and index it">+ add</button>' in HTML)
check("D2 refresh reloads what is on screen",
      'data-call="kbRefresh"' in HTML and "function kbRefresh()" in HTML
      and 'if (kbState.view === "files") kbFiles(); else kbLoadSources();' in HTML
      and 'kbState.view = "files";' in FILES and 'kbState.view = "sources";' in LOAD)

# ---- E. one definition per rule ----------------------------------------------
check("E1 one .kb-row definition, no duplicated styling",
      HTML.count("#swMain .kb-row {") == 1)
check("E2 a plain label cannot wrap letter by letter",
      # v651 gave .remaining `overflow-wrap: anywhere`; that collapses the element's
      # min-content width to ONE character, so inside a flex row "depth" and
      # "max sources" stacked vertically on the live page. break-word keeps the
      # wrap and the word.
      ".remaining { color: var(--dim); font-size: 11px; overflow-wrap: break-word; }" in HTML)
check("E3 a label carrying a control never shrinks its own text",
      # live: "max sources" wrapped onto two lines while its input stayed on the
      # first one, because the label was a shrinkable flex child.
      "#swMain label:has(input, select) { flex: 0 0 auto; }" in HTML)

print("\n---\nv653: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
