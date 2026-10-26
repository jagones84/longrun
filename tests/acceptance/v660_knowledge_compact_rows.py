"""v660 — Knowledge rows are one line, and nothing spills out of its box.

Operator, on the Knowledge panel: "vedi immagine spazi non rispettati
sovrapposizioni, spreco di spazio generalizzato, no compattezza. risolvi."

Measured live on :8790 before the change (Settings ▸ Knowledge):

  * every NOTEBOOK row was **45px** tall and the row was mostly an empty rename
    `<input>` (374px wide) plus a ✓ button — a one-line object drawn as a form;
  * `#indexMeta` reported `scrollWidth 553 / clientWidth 394`: the three meta lines
    inherited `white-space: nowrap` (written for the one-line count chip), so
    "embedding openrouter:google/…" ran ~160px past its box, straight over the
    buttons beside it — the overlap;
  * the "depth" label reported `scrollWidth 155 / clientWidth 120`: the v650 floor
    `min-width: min(160px, 100%)` resolved its percentage against the LABEL's own
    content box, so the select demanded the whole row and the label's own text was
    pushed outside it.

Stdlib only, deterministic, no browser, no server.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HTML = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _fn(name):
    i = HTML.find("function " + name)
    return HTML[i:i + 2200] if i >= 0 else ""


NB = _fn("kbLoadNotebooks")
SESS = _fn("kbLoadSessions")
INLINE = _fn("kbRenameInline")
RENAME = _fn("kbRenameNotebook")

# ---- A. a notebook row is ONE line: chip + name text + count + delete --------
check("A1 the name is TEXT, not an always-on rename field",
      "class=\"kb-main kb-rename\"" in NB and "<input class=\"inp\"" not in NB
      and 'value="' + "' + _attr(n.name)" not in NB)
check("A2 the ✓ rename button is gone (the name IS the affordance)",
      'title="rename">✓</button>' not in NB and "data-save=" not in NB)
check("A3 the row keeps the v653 grammar (chip + count with unit + delete)",
      'data-use=' in NB and '_plural(n.sources || 0, "source")' in NB
      and 'data-del=' in NB)
check("A4 a session notebook shows its name as text too",
      "<input class=\"inp\" data-unn=" not in SESS
      and 'class="kb-main" title="' in SESS)

# ---- B. the rename editor opens in place, one writer ------------------------
check("B1 clicking the name opens the editor in place",
      'box.querySelectorAll("[data-unn]").forEach(el => el.onclick = () => kbRenameInline(el));' in NB
      and "el.replaceWith(inp);" in INLINE and 'inp.className = "inp kb-name";' in INLINE)
check("B2 Enter saves, Escape cancels, blur saves",
      'if (e.key === "Enter"){ e.preventDefault(); finish(true); }' in INLINE
      and 'else if (e.key === "Escape"){ e.preventDefault(); finish(false); }' in INLINE
      and 'inp.addEventListener("blur", () => finish(true));' in INLINE)
check("B3 there is ONE rename writer (no second endpoint call)",
      HTML.count('action: "rename"') == 1
      and "kbRenameNotebook(id, val);" in INLINE
      and 'await api("POST", "/api/knowledge/notebooks", { action: "rename", id: id, name: String(name || "").trim() });' in RENAME)
check("B4 an unchanged or empty name does not fire a request",
      "if (!save || !val || val === before)" in INLINE)

# ---- C. nothing spills out of its own box ------------------------------------
check("C1 the meta LINES may wrap inside the panel",
      "#swMain #indexMeta { min-width: 0; white-space: normal; }" in HTML)
check("C2 a long embedding ref breaks instead of running past the box",
      "#swMain #indexMeta > div { overflow-wrap: anywhere; }" in HTML)
check("C3 a control inside a LABEL gets a real floor, not the parent's width",
      "#swMain label select," in HTML and "min-width: 64px;" in HTML
      and "#swMain label input:not([type=checkbox]):not([type=radio]):not([type=range]) {" in HTML)

# ---- D. the rows are compact and still ONE definition ------------------------
_i = HTML.index("#swMain .kb-row {")
ROW = HTML[_i:_i + 240]
check("D1 the row lost 3px of padding on both sides",
      "padding: 3px 8px;" in ROW and "margin-bottom: 3px;" in ROW
      and "padding: 6px 8px;" not in ROW)
check("D2 the controls inside a row are compact",
      "#swMain .kb-row .ghost { padding: 1px 6px; line-height: 1.35; }" in HTML)
check("D3 v653's one-definition rule still holds",
      HTML.count("#swMain .kb-row {") == 1)

print("\n---\nv660: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
