#!/usr/bin/env python3
"""v1263 — the marketplace card scans, the DETAIL reads: full description + origin page.

Operator (2026-11-21): *"nel catalogo marketplace non c'è modo di leggere descrizioni
complete degli oggetti? sono tutte tagliate; cliccando un tasto devo poter vedere la
descrizione completa immagino, se no portarmi proprio all'URL della pagina d'origine
così le guardo bene no? vedi come fanno altre harness."*

A  the card stays a two-line scan row and gains a NAMED detail opener (ⓘ = keyboard path)
B  the detail is one dialog: the SAME description whole, the entry's fields, and a link
C  the origin PAGE is catalogue data (ClawHub `<owner>/skills/<slug>`, MCP website/repo),
   derived for catalogues synced before the field existed; only http(s) ever links
D  the stored copy is a real description now (1200, cut on a word boundary), not a teaser

Deterministic and offline. Run: python3 tests/acceptance/v1263_market_detail_and_origin.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))


def src(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


UI = src("webui", "index.html")
JS = src("webui", "assets", "market.js")
SYNC = src("src", "longrun", "core", "market_sync.py")
MKT = src("src", "longrun", "core", "market.py")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:240]) if detail and not ok else ""))


def between(text, start, end):
    i = text.find(start)
    return text[i:text.find(end, i)] if i >= 0 else ""


def fn(text, name):
    return between(text, "function %s(" % name, "\nfunction ")


# ---- A: the card scans, the opener is named ------------------------------
CARD = fn(JS, "card")
check("A1 the catalogue card carries its id and a clickable surface",
      'data-item="${esc(item.id)}"' in CARD
      and "const info = infoBtn(item);" in CARD and "<div class=\"mkt-act\">${info}${act}</div>" in CARD)
check("A2 the opener has a name and a tooltip (graphics rule 2)",
      'class="ghost mkt-open" data-item-open=' in JS
      and 'aria-label="full description and source of ' in JS
      and 'title="full description \\u00b7 source page"' in JS)
check("A3 the card still clamps to two lines and reads as clickable",
      "-webkit-line-clamp: 2" in UI and ".mkt-card[data-item] { cursor: pointer; }" in UI)
A5 = fn(JS, "wire")
check("A4 a click opens the detail, but never from the card's own buttons",
      'const op = ev.target.closest("[data-item-open]");' in A5
      and 'const cardEl = ev.target.closest(".mkt-card[data-item]");' in A5
      and 'if (cardEl && !ev.target.closest("button,a"))' in A5)

# ---- B: one dialog, the same copy, the entry's fields --------------------
DETAIL = between(JS, "function openDetail(", "\n/* \u2500\u2500 wiring")
check("B1 the detail is a real modal with a title and its own scroll",
      'win.id = "mktDetailWin"' in DETAIL and 'win.setAttribute("role", "dialog")' in DETAIL
      and 'win.setAttribute("aria-modal", "true")' in DETAIL
      and 'win.setAttribute("aria-labelledby", "mktDlgTitle")' in DETAIL
      and 'win.setAttribute("id", "mktDlgTitle")' not in DETAIL and 'id="mktDlgTitle"' in DETAIL)
check("B2 it renders the SAME description whole, never a second summary",
      'const desc = String(item.description || "");' in DETAIL
      and 'class="mkt-dlg-desc"' in DETAIL and 'white-space: pre-wrap' in UI
      and "item.description" in fn(JS, "card"))
check("B3 the entry's fields are all reachable",
      all(s in DETAIL for s in ('_row("publisher"', '_row("version"', '_row("kind"',
                                '_row("license"', '_row("downloads"', '_row("digest"',
                                "_row(\"server\"", "members")))
check("B4 ✕, the backdrop and Escape close it, and focus goes back",
      'document.addEventListener("keydown", ev => {' in JS
      and 'ev.key === "Escape" && el("mktDetailWin")' in JS
      and 'ev.target.closest("[data-mktclose]")' in JS
      and "if (back2 && back2.focus)" in JS)

# ---- C: the origin page is data, and only http(s) links ------------------
SRC = fn(JS, "_srcBlock")
check("C1 the dialog links the origin page and refuses any other scheme",
      'if (_httpUrl(home))' in SRC and 'origin page \\u2197' in SRC
      and 'target="_blank" rel="noopener noreferrer"' in SRC
      and 'function _httpUrl(u) { return /^https?:\\/\\//i.test(String(u || "")); }' in JS)
check("C2 the download artifact is labelled as an artifact, not a page",
      'if (_httpUrl(dl) && dl !== home)' in SRC and "not a page" in SRC)
check("C3 the sync stores the ClawHub page and the MCP website/repository",
      'def _claw_page(owner, slug):' in SYNC
      and '"homepage": _claw_page(row.get("ownerHandle"), slug),' in SYNC
      and '"homepage": _page(srv.get("websiteUrl")) or _page(repo.get("url")),' in SYNC)
check("C4 the normaliser keeps a valid homepage and derives the old ClawHub rows",
      'if not re.match(r"^https?://", home, re.I):' in MKT
      and 'str(origin).endswith("clawhub")' in MKT
      and '"homepage": home,' in MKT)

# ---- D: the stored copy is a real description ----------------------------
check("D1 the cap holds a description, not a teaser",
      "DESC_MAX = 1200" in SYNC and "desc[:DESC_MAX]" not in SYNC)
check("D2 the cut is on a word boundary and says it was cut",
      "def _clip(text, limit=DESC_MAX):" in SYNC and 'cut.rstrip(" ,;:.-") + "\\u2026"' in SYNC)

from longrun.core import market, market_sync  # noqa: E402

long = "word " * 400
short = market_sync._clip("a  b\n c")
cut = market_sync._clip(long)
check("D3 _clip collapses whitespace and never splits a word",
      short == "a b c" and len(cut) <= market_sync.DESC_MAX + 1
      and cut.endswith("\u2026") and "wor\u2026" not in cut and cut.rstrip("\u2026").endswith("word"),
      (len(cut), cut[-12:]))
check("D4 a ClawHub page is <owner>/skills/<slug>",
      market_sync._claw_page("18072937735", "smyx-human-emotion")
      == "https://clawhub.ai/18072937735/skills/smyx-human-emotion"
      and market_sync._claw_page("", "x") == "")
mcp = market_sync._map_server({"server": {
    "name": "ac.sample/mcp", "title": "Sample", "description": "D " * 900,
    "websiteUrl": "https://sample.example/p",
    "remotes": [{"type": "streamable-http", "url": "https://api.sample/mcp"}]}})
check("D5 an MCP entry carries its page and a clipped description",
      mcp and mcp["homepage"] == "https://sample.example/p"
      and len(mcp["description"]) <= market_sync.DESC_MAX + 1
      and mcp["server"]["url"] == "https://api.sample/mcp", mcp)
old = market._normalize({"id": "skill/foo", "kind": "skill", "name": "foo",
                         "publisher": "abc", "description": "hello"}, "imported:clawhub")
bad = market._normalize({"id": "skill/bar", "kind": "skill", "name": "bar",
                         "publisher": "abc", "homepage": "javascript:alert(1)"},
                        "imported:clawhub")
plain = market._normalize({"id": "skill/baz", "kind": "skill", "name": "baz"},
                          "bundled")
check("D6 old rows gain the page, foreign schemes never become a link",
      old.get("homepage") == "https://clawhub.ai/abc/skills/foo"
      and bad.get("homepage") == "https://clawhub.ai/abc/skills/bar"
      and plain.get("homepage") == "", (old.get("homepage"), bad.get("homepage"), plain.get("homepage")))

print("\n---\nv1263: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
