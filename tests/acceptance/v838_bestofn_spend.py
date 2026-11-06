#!/usr/bin/env python3
"""v838 — test-time compute is spent where the ranker can discriminate (v838).

Measured 2026-11-06 on the harness's own cost ledgers: over three days 124M of
359M tokens (34.5%; 78% in the worst session) were DUPLICATE best-of-N samples,
one extra full-context model call per action step. The ranker that picked between
them is `prm.rank_text`, which scores TEXT quality: two parseable actions both
get 0.9 and the tiebreak is `min(len/4000, 0.2)` — the longer string wins. So the
extra sample bought verbosity, not correctness.

This pins the new spend policy, the switch that restores the old one, and the
ledger tag that keeps the cost of test-time compute auditable.

Deterministic, offline, no model. Run: python3 tests/acceptance/v838_bestofn_spend.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))
# The ledger dir is read at import time: point it at a temp dir FIRST so this
# test never appends a row to the operator's real cost ledger.
os.environ["LONGRUN_COSTS_DIR"] = tempfile.mkdtemp(prefix="v838-costs-")

from longrun.plan import bestofn, prm, difficulty                      # noqa: E402
from longrun.model import costs                                       # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# --- A: the shipped policy -----------------------------------------------------
cfg = bestofn.cfg()
check("A1 an action step gets NO extra sample by default",
      bestofn.spend_extra(3, is_action=True, c=cfg) is False, cfg)
check("A2 a prose step still gets one (the ranker can judge text)",
      bestofn.spend_extra(2, is_action=False, c=cfg) is True, cfg)
check("A3 n=1 spends nothing whatever the step is",
      bestofn.spend_extra(1, is_action=False, c=cfg) is False
      and bestofn.spend_extra(1, is_action=True, c=cfg) is False)

# --- B: the switch restores the previous gate ---------------------------------
old = dict(cfg, on_actions=True)
check("B1 bestofn.on_actions:true samples ACTIONS again",
      bestofn.spend_extra(2, is_action=True, c=old) is True)
check("B2 ... and no longer samples prose", bestofn.spend_extra(2, is_action=False,
                                                              c=old) is False)

# --- C: why — the ranker cannot tell two actions apart ------------------------
short = json.dumps({"action": "tool", "tool": "fs.read", "args": {"path": "a"}})
long_ = json.dumps({"action": "tool", "tool": "fs.read",
                    "args": {"path": "a", "note": "I will read the file now, "
                                                 "carefully, and report back " * 4}})
s_short, s_long = prm.rank_text(short), prm.rank_text(long_)
check("C1 both parseable actions score the same base", s_short >= 0.9 and s_long >= 0.9,
      (s_short, s_long))
check("C2 the LONGER action wins on the length bonus alone", s_long > s_short,
      (s_short, s_long))

# --- D: the difficulty estimate still scales N (the mechanism is intact) ------
_hard = {"open_nodes": 3, "msg_words": 200}
check("D1 a hard task asks for more than one candidate",
      difficulty.n_for(_hard) >= 2, difficulty.n_for(_hard))

# --- E: the cost ledger records WHY a call was made ---------------------------
usage = {"prompt_tokens": 1000, "completion_tokens": 50}
tagged = costs.record("v838", "openrouter:z-ai/glm-5.3-flash", usage,
                      latency_ms=1200, tag="bestofn")
plain = costs.record("v838", "openrouter:z-ai/glm-5.3-flash", usage, latency_ms=900)
check("E1 an extra sample persists its tag", tagged.get("tag") == "bestofn", tagged)
check("E2 an ordinary call carries no tag", "tag" not in plain, sorted(plain))
check("E3 the extra sample keeps its own latency", tagged.get("latency_ms") == 1200,
      tagged.get("latency_ms"))

print("---")
ok = sum(RESULTS)
print("%d/%d PASS" % (ok, len(RESULTS)))
sys.exit(0 if ok == len(RESULTS) else 1)
