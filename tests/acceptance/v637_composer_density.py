#!/usr/bin/env python3
"""v637 — the chat footer says less (composer).

Operator: the footer carried a placeholder that repeated the shortcut, a native
select with glyph prefixes, a model button showing a doubled provider
(`deepseek/deepseek-…`) and 12/22px of padding.

Contract:
  A) The placeholder is one word; the shortcut stays in the send button tooltip.
  B) `#qmode` options are `queue` / `steer` (values and the localStorage wiring
     unchanged — only the glyph prefix left).
  C) `_modelShort` shows the LAST segment of a `provider:id` or `provider/model`
     ref; the full ref is reachable in the button tooltip.
  D) One tighter padding/gap for the whole footer.

Run: python tests/acceptance/v637_composer_density.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="v637_")
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

# ---- A. placeholder -----------------------------------------------------------
check("A1 the placeholder is one word",
      'placeholder="Message…"' in UI
      and "Message the agent…   (Ctrl+⏎ send)" not in UI)
check("A2 the shortcut is still documented on the send button",
      # v680: Enter sends; Shift+Enter (or Ctrl/Cmd+Enter) inserts a newline.
      'title="send (Enter — Shift+Enter for a newline)"' in UI)

# ---- B. queue mode picker -----------------------------------------------------
check("B1 the options carry no glyph prefix",
      '<option value="queue">queue</option>' in UI
      and '<option value="steer">steer</option>' in UI
      and "＋ queue</option>" not in UI)
check("B2 the value wiring is untouched",
      'localStorage.getItem("sf_qmode") || "queue"' in UI
      and '_qm.onchange = () => localStorage.setItem("sf_qmode", _qm.value);' in UI)

# ---- C. model label ----------------------------------------------------------
check("C1 the model label shows the last segment of either ref shape",
      'const i = Math.max(s.lastIndexOf(":"), s.lastIndexOf("/"));' in UI)
check("C2 the full ref stays in the tooltip",
      'b.title = ref ? ("choose the LLM for this chat \\u2014 now: " + ref)' in UI)

# ---- D. footer rhythm --------------------------------------------------------
check("D1 one tighter padding/gap for the footer",
      "#composer { display: flex; flex-direction: column; gap: 8px; padding: 8px 18px 10px;" in UI)

print("\nv637: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
