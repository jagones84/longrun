"""v407 — Settings ▸ Models reorg + Workspace panel trim (JAG-403i).

Stdlib-only, deterministic, no browser. Covers two UI points:

  A) the Workspace panel no longer prints the redundant "session ▸ … · N chars of
     rules" line nor the "default ▸ …" echo (the path is already in the input box);
  B) Settings ▸ Models is reordered + de-duplicated: Thinking effort first, then
     Compaction model, then ONE merged Embedding section (model select + catalogue +
     add + costs), then the provider add/list. The old separate "Embedding models ·
     personal" / "Embedding costs" heading sections are gone.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HTML = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if (detail and not ok) else ""))


# ------------------------------------------------------------------ A) workspace trim
check("A1 the wsCurrent info line is gone (element + JS)",
      'id="wsCurrent"' not in HTML and '$("wsCurrent")' not in HTML)
check("A2 the wsResult echo line is gone (element + JS)",
      'id="wsResult"' not in HTML and '$("wsResult")' not in HTML)
check("A3 setWorkspace still gives feedback (toast) and reloads",
      "async function setWorkspace()" in HTML and 'toast("folder path required"' in HTML
      and "loadRules(); loadSessions();" in HTML)

# ------------------------------------------------------------------ B) models order
_sec = HTML[HTML.index('data-cat="models"'):HTML.index('data-cat="knowledge"')]
_order = ["Thinking effort", "Compaction model", "Embedding · knowledge index",
          "Add / edit provider", "Providers", "Available models"]
_pos = [_sec.find(h) for h in _order]
check("B1 the Models section is ordered: thinking, compaction, embedding, add-provider, providers, models",
      all(p >= 0 for p in _pos) and _pos == sorted(_pos), str(_pos))
check("B2 Thinking effort is the FIRST block",
      # v654: the heading carries the `live` chip that says the picker writes at
      # once, so the exact `</h2>` form gained a span.
      _sec.find("Thinking effort") < _sec.find("Compaction model"))

# merged embedding section (one card holds model + catalogue + add + costs)
check("B3 the embedding card is merged (model select + catalogue + add + costs together)",
      'id="emModel"' in _sec and 'id="emModelList"' in _sec and 'id="emNewId"' in _sec
      and 'id="emCostTotal"' in _sec)
check("B4 the old separate embedding HEADING sections are gone",
      "<h2>Embedding models · personal</h2>" not in HTML and "<h2>Embedding costs</h2>" not in HTML)
check("B5 add + costs are now collapsible <details> (less clutter)",
      "＋ add a model to the catalogue</summary>" in _sec and ">Embedding costs</summary>" in _sec)
check("B6 the provider block keeps its add-then-list shape",
      _sec.find('id="provId"') < _sec.find('id="provList"') < _sec.find('id="modelsList"'))
check("B7 the embedding picker + cost ids survive (v401 contract)",
      # v654: `emActive` is gone (it repeated the selected option); the probe
      # line `emTestOut` is the surviving status element.
      "emTestOut" in HTML and "emCostByModel" in HTML and "emAddModel" in HTML
      and "emRemoveModel" in HTML)

print("---")
ok = sum(results)
print("%d/%d checks passed" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
