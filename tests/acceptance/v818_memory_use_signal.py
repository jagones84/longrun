#!/usr/bin/env python3
"""v818 — which memories were injected, and were they USED (B-6).

Longrun counted how many memories it injected and never whether the answer used
them, so the memory ranking could never be tuned by evidence. Recall is not use:
the strongest memory system beat full context on recall (0.621 vs 0.570) and
trailed badly on use (0.247 vs 0.431), with 21-27% of recalled memories unused
(2026-11-05). `retrieve()` now carries the memory id, `build()` reports the ids it
injected, `usage_signal()` labels used/unused, and the turn publishes `memory.use`.

  A) a retrieved hit carries its memory id;
  B) `build()` reports the injected ids and their contents;
  C) `usage_signal` separates a reused memory from an ignored one;
  D) the panel data and the turn event exist (wiring pins).

Deterministic, no live model, no network, no server.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v818-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server                       # noqa: E402,F401 — import cycle
from longrun.model import context_engine as ce        # noqa: E402
from longrun.memory import memory                     # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


CONTENT = "the deploy target is the dgx spark box on the local network"
REC = {"mid": "M1", "kind": "memory.store", "ts": 1.0, "content": CONTENT}
memory.search = lambda *a, **k: [(0.9, dict(REC))]

# --------------------------------------------------------- A. the id rides ---
hits = ce.retrieve("deploy target", semantic=False)
check("A1 a retrieved hit carries its memory id", hits and hits[0].get("mid") == "M1", hits)

# ------------------------------------------------------- B. build reports it ---
msgs, stats = ce.build("SYS", [], message="where do we deploy?")
check("B1 build reports the injected ids", stats.get("memory_ids") == ["M1"],
      stats.get("memory_ids"))
check("B2 build keeps the injected contents for the usage check",
      (stats.get("memories") or [{}])[0].get("mid") == "M1", stats.get("memories"))

# --------------------------------------------------------- C. the use signal ---
used = ce.usage_signal("We deploy to the DGX Spark box on the local network.", [dict(REC)])
check("C1 a reply that reuses the memory counts as used", used["used"] == 1, used)
ignored = ce.usage_signal("The weather in Rome is warm and sunny today.", [dict(REC)])
check("C2 a reply about something else is unused", ignored["used"] == 0, ignored)
check("C3 the counts add up", (ignored["injected"] == 1 and ignored["unused"] == 1), ignored)
check("C4 a record with no id is not counted",
      ce.usage_signal("x", [{"content": "no id here"}])["injected"] == 0)
check("C5 nothing injected is not an error",
      ce.usage_signal("x", []) == {"injected": 0, "used": 0, "unused": 0, "used_ids": []})

# ------------- C6. generic filler is not evidence of use (found in review) -------
FILLER = {"mid": "F1", "content": "this will that from your have when then they them"}
_filler = ce.usage_signal("this will that from your have when then they them", [dict(FILLER)])
check("C6 a memory made only of generic words is not reported as used",
      _filler["injected"] == 1 and _filler["used"] == 0, _filler)

# ---------------------------------------------------------------- D. wiring ---
http = open(os.path.join(REPO, "src", "longrun", "core", "httpapi.py"), encoding="utf-8").read()
check("D1 the panel data carries memory_use", '"memory_use": mem_use' in http)
ag = open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"), encoding="utf-8").read()
check("D2 the turn publishes memory.use", 'publish("memory.use"' in ag)
ui = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
check("D3 the Context panel shows the used/injected chip", "_ctxMemUse" in ui)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
