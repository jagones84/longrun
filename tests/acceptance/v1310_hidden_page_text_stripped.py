#!/usr/bin/env python3
"""v1310 — hidden page text never reaches the model: `_strip_html` is a sanitizer.

Source (read 2026-11-26): the harvest of `third-parties/` (proposal
`.agent/docs/proposals/2026-11/2026-11-26_third-party-harvest.md`, row R172-T1).
Scrapling's RAG guidance lists the prompt-injection vectors a page can carry
without an operator seeing them; Longrun's `tools._strip_html` is the ONE
extractor every `web.fetch` and every search provider feeds through.

Old behaviour: script/style/nav chrome was removed, but HTML comments,
`<template>` content, elements marked hidden (`hidden`, `aria-hidden="true"`,
`style="display:none"`) and zero-width / bidi control characters survived —
so a page could plant an instruction the model reads and the operator cannot.

This pins:

  A  the vectors are removed (comment, template, hidden, aria-hidden, display:none,
     zero-width, bidi, BOM);
  B  visible text survives, and `aria-hidden="false"` is NOT over-stripped;
  C  the pre-existing contract still holds (script/style chrome gone, entities decoded);
  D  the single owner — the fetch path and the search paths all call `_strip_html`
     (a source-level check, so one edit covers every surface).

Deterministic: a pure string transform. No model, no network, no server.
Run:  python3 tests/acceptance/v1310_hidden_page_text_stripped.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(REPO, "src")

# Isolate the data home BEFORE any app import.
TMP = tempfile.mkdtemp(prefix="sf-v1310-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from longrun.tools import tools as T  # noqa: E402

FAILED = []
CHECKS = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ((" — %s" % (detail,)) if detail else ""))
    CHECKS.append(name)
    if not ok:
        FAILED.append(name)


strip = T._strip_html

# ── A · the injection vectors are removed ───────────────────────────────────
check("A1 an HTML comment never reaches the model",
      "SECRET-INSTRUCTION" not in strip("<p>ok</p><!-- SECRET-INSTRUCTION -->"))

check("A2 <template> content (inert to a reader, visible to the parser) is gone",
      "TEMPLATED" not in strip('<template><p>TEMPLATED</p></template><p>ok</p>'))

check("A3 a bare `hidden` element is removed",
      "HIDDEN-BARE" not in strip('<div hidden>HIDDEN-BARE</div><p>ok</p>'))

check("A4 aria-hidden=\"true\" content is removed",
      "HIDDEN-ARIA" not in strip(
          '<div aria-hidden="true">HIDDEN-ARIA</div><p>ok</p>'))

check("A5 a display:none element is removed",
      "HIDDEN-STYLE" not in strip(
          "<span style=\"color:red;display:none\">HIDDEN-STYLE</span><p>ok</p>"))

check("A6 a zero-width space cannot glue a hidden token",
      "\u200b" not in strip("<p>ig\u200bnore</p>"))

check("A7 a bidi override is removed (RTL spoofing vector)",
      "\u202e" not in strip("<p>abc\u202edef</p>"))

check("A8 a BOM is removed",
      "\ufeff" not in strip("<p>\ufeffhello</p>"))

# ── B · visible text survives; aria-hidden="false" is not over-stripped ─────
_body = strip('<div aria-hidden="false"><p>VISIBLE-WORD</p></div>')
check("B1 aria-hidden=\"false\" content is KEPT",
      "VISIBLE-WORD" in _body, _body)

check("B2 ordinary prose is unchanged",
      strip("<h1>Title</h1><p>Hello world</p>") == "Title Hello world",
      strip("<h1>Title</h1><p>Hello world</p>"))

check("B3 a hidden span inside visible prose loses only the hidden part",
      strip('<p>keep<span hidden>DROP</span>this</p>') == "keep this",
      strip('<p>keep<span hidden>DROP</span>this</p>'))

# ── C · the pre-existing contract still holds ───────────────────────────────
check("C1 script/style/nav chrome is still dropped",
      "evil" not in strip("<script>evil()</script><style>x{}</style><nav>menu</nav><p>real</p>"),
      strip("<script>evil()</script><style>x{}</style><nav>menu</nav><p>real</p>"))

check("C2 entities are still decoded",
      strip("<p>a &amp; b &lt;c&gt;</p>") == "a & b <c>",
      strip("<p>a &amp; b &lt;c&gt;</p>"))

# ── D · one owner feeds every web surface ───────────────────────────────────
_src = open(os.path.join(SRC, "longrun", "tools", "tools.py"), encoding="utf-8").read()
_calls = _src.count("_strip_html(")
check("D1 the browser tool and the search providers share ONE extractor (>=5 call sites)",
      _calls >= 5, "%d call sites" % _calls)
check("D2 both page-text consumers go through it (`browser` and `web.fetch` direct fallback)",
      "text = _strip_html(html)" in _src
      and '_strip_html(raw), "direct"' in _src)

print()
if FAILED:
    print("FAILED %d/%d: %s" % (len(FAILED), len(CHECKS), ", ".join(FAILED)))
    sys.exit(1)
print("OK %d/%d" % (len(CHECKS), len(CHECKS)))
