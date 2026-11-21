#!/usr/bin/env python3
"""v1256 — the context ring really opens, one neutral sparkle, the bar as the message box's
top strip, one-line session rows, the todo id beside its badge, and the Agents funnel.

Operator (2026-11-22, round 172): *"ma perché ti ostini a non fare aprire il menu cliccando
sul context roundcircel in msg box? non si apre ti dico"*; *"perché non hai messo
l'autogenerate dentro la msg box in alto a destra come trae? … E NO GIALLA, cambia in tutta la
webui, falla dello stesso colore dominante di ciò che sta accanto rispetto al theme"*;
*"perché non hai aggiunto la sovrabar alla message box? come trae"*; *"nel LH panel sessions le
cose stanno tutte in una riga, non andare accapo con l'ID agent e il contesto"*; *"anche per i
done dentro la chat accapo c'è A1.n65, mettilo affianco al done, risparmiamo spazio verticale"*;
*"in agents panel non lo hai messo il filtro come in sessions (non duplicato … dovevi duplicare
solo l'oggetto grafico)"*; *"queued message: verificare se già implementato qualcosa"*.

  A  the context ring: an answer cannot own `id="cmpCtx"`; the popover anchors to the click
  B  ONE sparkle, an SVG in currentColor (not the gold U+2728 emoji), on every ✨ control
  C  the Workspace/Plan bar is the TOP STRIP of the message box and keeps the plan line
  D  a session row is ONE line: name · A-id · ctx ring · age
  E  the todo id sits beside its badge, in the chat tree and in the inspector Plan
  F  the Agents panel shows the SAME FilterSort funnel as the Sessions rail
  G  the queued-message lane exists (queue bar, edit/steer/remove, delivery mode)

Deterministic and offline: static pins on webui/index.html and the deck.
Run: python3 tests/acceptance/v1256_context_ring_spark_bar_rows.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HTML = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
DECK = open(os.path.join(REPO, "src", "longrun", "orbit", "web", "orbit.html"),
            encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:240]) if detail and not ok else ""))


# ---- A: the ring -----------------------------------------------------------
check("A1 rendered markdown may not carry an app id (it stole #cmpCtx)",
      'FORBID_ATTR: ["id"]' in HTML and "function mdToHtml(text)" in HTML)
check("A2 the popover anchors to the ring that was CLICKED",
      "function _ctxPopover(anchor)" in HTML
      and '(anchor || $("cmpCtx") || pop).getBoundingClientRect()' in HTML
      and "_ctxPopover(onRing);" in HTML)
check("A3 the ring is a real button with a name and a 24px hit area",
      'class="cmp-ctx" id="cmpCtx" aria-label="context details" aria-haspopup="dialog"' in HTML
      and ".cmp-ctx { flex: 0 0 auto; display: inline-flex;" in HTML)

# ---- B: one sparkle --------------------------------------------------------
check("B1 ONE sparkle, an inline SVG without a hard-coded colour",
      "const SPARK_SVG =" in HTML and 'stroke="currentColor"' in HTML.split("const SPARK_SVG =")[1][:200])
check("B2 the autogenerate button uses it (no colour-emoji textContent)",
      "btn.innerHTML = SPARK_SVG" in HTML and 'btn.textContent = "✨"' not in HTML)
check("B3 it is neutral beside its neighbours and accent only while busy",
      ".gen-bar .gen-spark { color: var(--dim); }" in HTML
      and ".gen-bar .gen-spark:hover { color: var(--txt); }" in HTML
      and ".gen-bar .gen-spark.busy { color: var(--acc);" in HTML)
check("B4 the text buttons that say Automate use the same icon",
      "+ SPARK_SVG + ' Automate</button>'" in HTML
      and "+ SPARK_SVG + ' Automate with Architect…</button>'" in HTML)
_lra = DECK.split('id="lraAutoBtn"')[1].split("</button>")[0]
check("B5 the deck's Architect button is the same SVG, not the emoji",
      'id="lraAutoBtn"' in DECK and "<svg" in _lra and "✨" not in _lra
      and 'stroke="currentColor"' in _lra)

# ---- C: the bar is the message box's top strip ------------------------------
check("C1 the tabs row carries the divider and sits above the textarea",
      ".cs-tabs { display: flex; align-items: center; gap: 4px; min-height: 26px; min-width: 0;" in HTML
      and "padding: 2px 2px 5px; border-bottom: 1px solid var(--line);" in HTML
      and HTML.index('id="cmpSuper"') < HTML.index('id="inpWrap"'))
check("C2 the strip keeps the plan line while no tab is open (TRAE's count)",
      'const sec = _csSec(on || "plan");' in HTML and "_csPaint();" in HTML)
check("C3 the summary still comes from the panel's own line (no second count)",
      'sec.querySelector(".ihd-s")' in HTML and "new MutationObserver(() => _csPaint())" in HTML)

# ---- D: one-line session rows ----------------------------------------------
check("D1 the row does not wrap and the name shrinks instead",
      ".sess { display: flex; flex-wrap: nowrap;" in HTML
      and ".sess .t { flex: 1 1 auto;" in HTML and ".sess .t { flex-basis: 100%" not in HTML)
check("D2 the A-id, the ring and the age all live on that same row",
      '${jid}${_ctxRingHtml(s)}<span class="n">${_sessAgeText(s)}</span>' in HTML)

# ---- E: the id beside the badge -------------------------------------------
check("E1 the chat task row puts the id beside the status badge",
      ".tctree .tcmeta { display: flex; flex-direction: row; align-items: center; gap: 6px; }" in HTML)
check("E2 the inspector Plan row does the same (stacked variant included)",
      ".task .tmeta { display: flex; flex-direction: row; align-items: center;" in HTML
      and ".task.stacked .tmeta { flex-direction: row; align-items: center; gap: 6px; }" in HTML)

# ---- F: the Agents panel funnel -------------------------------------------
check("F1 the hosted deck no longer hides its funnel",
      "html.embed-panel #agFilterBtn{display:none!important}" not in DECK
      and 'id="agFilterBtn"' in DECK)
check("F2 it is the SAME shared control, not a second filter",
      'key: "agents", button: $("agFilterBtn")' in DECK
      and "window.FilterSort ? FilterSort.mount(" in DECK)

# ---- G: the queued-message lane already exists ----------------------------
check("G1 a queued message is visible in the composer (chip + edit/steer/remove)",
      'id="queueBar"' in HTML and "function renderQueue()" in HTML
      and "function editQueued(i)" in HTML and "function steerQueued(i)" in HTML)
check("G2 queue vs steer is ONE stored delivery mode, read by the send path",
      'id="qmodeBtn"' in HTML and 'localStorage.getItem("sf_qmode") || "queue"' in HTML)

print("\n---\nv1256: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
