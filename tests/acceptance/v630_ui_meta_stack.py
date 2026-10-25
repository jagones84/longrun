"""v630 — the status badge anchors the todo row; the IDs live UNDER it.

Operator report (mobile chat, then the RH Plan panel): "why not move the agent
id, the todo id and the job id UNDER the done marker, so the text gets the
horizontal space back?". The rows used to be `[done] A8.n28 | label` inline, so
the label lost ~110px in an already narrow column.

Contract:
  A) chat thread  — <summary> is a 2-column grid: [badge + ids] | label, and
     the agent/todo id sits in a COLUMN under the status badge.
  B) RH Plan panel — the same pattern on `.task`: the badge is the first child
     of `.tmeta` and every id (todo + job + subjob) wraps in one line below it.
  C) nothing is lost — the ids are still painted live (`_paintNode`) and the
     job/subjob chips are still clickable bridges.

Run: python tests/acceptance/v630_ui_meta_stack.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="v630_")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_GRAPHS_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_THREADS_DIR"] = os.path.join(TMP, "threads")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
for d in ("cfg", "sessions", "graphs", "threads", "data"):
    os.makedirs(os.path.join(TMP, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def src(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


UI = src("webui", "index.html")


def block(selector, text=None):
    """The CSS body of `selector { ... }` (first occurrence)."""
    doc = text if text is not None else UI
    head = selector + " {"
    if head not in doc:
        return ""
    return doc.split(head)[1].split("}")[0]


# ---- A. chat thread ------------------------------------------------------------
sum_css = block(".tctree > summary")
check("A1 the chat summary is a two-column grid (badge column | label)",
      "display: grid" in sum_css and "grid-template-columns: auto minmax(0, 1fr)" in sum_css,
      sum_css.strip()[:120])
check("A2 the agent/todo id sits in a COLUMN under the status badge",
      "function _mkSection(" in UI
      and '<summary><span class="tcmeta"><span class="st"></span><span class="tcid"></span></span>'
      in UI)
meta_css = block(".tctree .tcmeta")
check("A3 .tcmeta stacks badge then id (no inline preamble)",
      "flex-direction: column" in meta_css and "align-items: flex-start" in meta_css,
      meta_css.strip()[:120])
check("A4 the label owns the remaining width and may wrap anywhere",
      "min-width: 0" in block(".tctree .tclabel")
      and "overflow-wrap: anywhere" in block(".tctree .tclabel"))

# ---- B. RH Plan panel ----------------------------------------------------------
check("B1 the plan row groups every id in ONE .tids line",
      'const ids = `<span class="tids">' in UI
      and '`;\n    const meta = `<span class="st' in UI)
check("B2 the status badge is the FIRST child of .tmeta (ids come after it)",
      'const meta = `<span class="st ${n.status}">${n.status}</span>${ids}`;' in UI)
tmeta_css = block(".task .tmeta")
check("B3 .task .tmeta is a column (ids under the badge)",
      "flex-direction: column" in tmeta_css and "align-items: flex-start" in tmeta_css,
      tmeta_css.strip()[:120])
check("B4 .task .tids wraps instead of overflowing the meta column",
      "flex-wrap: wrap" in block(".task .tids"))
check("B5 the row aligns to the TOP so a tall meta never centres the label",
      "align-items: flex-start" in block(".step, .task"))
check("B6 the stacked (long-label) variant keeps the same column meta",
      "flex-direction: column" in block(".task.stacked .tmeta"))

# ---- C. nothing lost -----------------------------------------------------------
check("C1 the chat id is still painted live after a status change",
      'const idEl = det.querySelector(".tcid");' in UI
      and "idEl.textContent = _todoid(node);" in UI)
check("C2 the plan chip still prints the todo id",
      'class="tcid" title="node id ${esc(n.id)}">${_todoid(n)}' in UI)
check("C3 the job/subjob chips are still clickable bridges",
      UI.count('class="jt jt-job"') == 2
      and 'el.querySelectorAll(".jt-job")' in UI)

print("\nv630: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
