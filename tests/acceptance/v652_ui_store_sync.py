"""v652 — one row per session, one shape per model, one exit per store.

Operator: "riguarda tutta la webui e codebase (che devono essere synced) per
questa tipologia di schifezze" — after v651 fixed the Improvements panel, the
same audit was run over the rest of the UI/backend pair. Three findings were
real:

  A) the session rail drew the SAME session once per group it qualified for
     (Pinned AND its team, Pinned AND "No team", once per team when it belonged
     to several) — one object, two or three rows.
  B) `memory.costlog.clear()` existed with no route and no control: a dead
     object, and the embedding cost ledger could never be reset.
  C) the same model printed as `deepseek/...` in the Control deck and as
     `openrouter:deepseek/...` in Settings ▸ Models — two shapes, one object.

Stdlib only, deterministic, isolated temp dirs.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tmp = tempfile.mkdtemp(prefix="v652-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(tmp, "data")
os.environ["LONGRUN_CODEBASE_DIR"] = os.path.join(tmp, "codebase")
os.environ["LONGRUN_KNOWLEDGE_DIR"] = os.path.join(tmp, "knowledge")
os.environ["LONGRUN_EMBEDDING_DIR"] = os.path.join(tmp, "embedding")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(tmp, "cfg")
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name +
          ((" :: " + str(detail)) if (detail and not ok) else ""))


UI = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
API = open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"),
           encoding="utf-8").read()
ORBIT = open(os.path.join(REPO, "src", "longrun", "orbit", "web", "orbit.html"),
             encoding="utf-8").read()

# ---- A. the session rail draws a session ONCE --------------------------------
check("A1 the rail keeps a drawn set for the render pass",
      "const _drawn = new Set();" in UI)
check("A2 Pinned claims its rows first",
      "pinGroup.forEach(s => _drawn.add(s.id));" in UI
      and "visible.filter(s => isPinned(s.id)).sort(_sysFirst)" in UI)
check("A3 'No team' skips what Pinned already drew",
      "teamsOf(s).length === 0 && !_drawn.has(s.id)" in UI
      and "adhoc.forEach(s => _drawn.add(s.id));" in UI)
check("A4 a team skips every session drawn above it",
      "teamsOf(s).includes(t.id) && !_drawn.has(s.id)" in UI
      and "ss.forEach(s => _drawn.add(s.id));" in UI)
check("A5 the old 'drawn once per group' contract is gone from the CSS note",
      "DRAWN once per group" not in UI)

# ---- B. the embedding cost log has an exit -----------------------------------
from longrun.memory import costlog  # noqa: E402

costlog.clear()
check("B1 clear() on an empty log returns 0", costlog.clear() == 0)
costlog.record("m1", provider="p", tokens=10, est_cost_usd=0.1)
costlog.record("m2", provider="p", tokens=20, est_cost_usd=0.2)
n = costlog.clear()
check("B2 clear() reports what it removed", n == 2, n)
check("B3 the log is actually empty afterwards", costlog.list_all() == [],
      costlog.list_all())
check("B4 the route is wired",
      'if path == "/api/embedding/costs":' in API.split('if method == "DELETE":')[1]
      and "_cl.clear()" in API)
check("B5 the panel has the control, behind a confirm",
      'data-call="emCostsClear"' in UI
      and "async function emCostsClear()" in UI
      and 'api("DELETE", "/api/embedding/costs")' in UI
      and "wipe the whole embedding cost log?" in UI)
check("B6 the module docstring no longer claims 'never pruned'",
      "never pruned" not in open(os.path.join(REPO, "src", "longrun", "memory",
                                              "costlog.py"), encoding="utf-8").read())

# ---- C. one model, one name ---------------------------------------------------
check("C1 the deck labels a model with its canonical ref",
      "return {ref: ref, label: ref};" in ORBIT)
check("C2 no surface relabels it as a bare id",
      "label: m.id" not in ORBIT)
check("C3 the canonical form is provider:id",
      'return "%s:%s"' in open(os.path.join(REPO, "src", "longrun", "model",
                                            "providers.py"), encoding="utf-8").read())

print("\n---\nv652: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
