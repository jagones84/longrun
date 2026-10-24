#!/usr/bin/env python3
"""v562 (STAGED — M7 compaction guard): previous summary carried, never re-summarized.

Contract (`M7-compaction-guard.md`):
  1. The `compact()` summary block carries a stable prefix.
  2. On the next round only FRESH turns reach the summarizer; the previous
     block is carried forward untouched (no summary-of-summary drift).
  3. No fresh turns -> previous summary returned byte-identical, zero model calls.
  4. Carried + fresh combined is capped (pruned from the front).
  5. `config/compaction.yaml` KEEP names commitments/promises/constraints.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


from longrun.model import context_engine as CE  # noqa: E402

# ---- 1. LLM path stamps the stable prefix; summarizer sees fresh only --------
seen = {}


def fake_llm(old):
    seen["n"] = seen.get("n", 0) + 1
    seen["got"] = list(old)
    return "FRESH-SUMMARY"


prev = {"role": "system", "content": CE.SUMMARY_PREFIX + "old decisions"}
msgs = [prev,
        {"role": "user", "content": "fresh question about billing"},
        {"role": "assistant", "content": "fresh answer with numbers"},
        {"role": "user", "content": "keep me verbatim"}]
out, st = CE.compact(msgs, 50, keep_recent=1, summarizer=fake_llm, force=True)

got_roles = [(m.get("role"), (m.get("content") or "")[:40]) for m in seen.get("got", [])]
check("1a summarizer called once", seen.get("n") == 1, seen.get("n"))
check("1b summarizer NEVER saw the previous summary block",
      all("old decisions" not in (m.get("content") or "") for m in seen.get("got", [])),
      got_roles)
check("1c result carries the previous body",
      bool(out) and "old decisions" in (out[0].get("content") or ""), (out[0].get("content") or "")[:80])
check("1d result contains the fresh summary",
      bool(out) and "FRESH-SUMMARY" in (out[0].get("content") or ""), (out[0].get("content") or "")[:120])
check("1e stable prefix present",
      bool(out) and (out[0].get("content") or "").startswith(CE.SUMMARY_PREFIX),
      (out[0].get("content") or "")[:50])

# ---- 2. No fresh turns -> byte-identical carry, zero model calls -------------
seen.clear()
old_only = [prev, {"role": "user", "content": "keep me verbatim"}]
out2, st2 = CE.compact(old_only, 50, keep_recent=1, summarizer=fake_llm, force=True)
check("2a no model call when nothing fresh", seen.get("n") is None, seen.get("n"))
check("2b summary byte-identical to the previous block",
      bool(out2) and out2[0].get("content") == prev["content"],
      (out2[0].get("content") or "")[:60])
check("2c stats mark the carry", st2.get("summary") == "carried", st2.get("summary"))

# ---- 3. Legacy extractive prefix is recognised as a previous summary ---------
seen.clear()
legacy = {"role": "system", "content": CE.EXTRACTIVE_PREFIX + "legacy decisions"}
msgs3 = [legacy,
         {"role": "user", "content": "something new here"},
         {"role": "user", "content": "keep me"}]
out3, _st3 = CE.compact(msgs3, 50, keep_recent=1, summarizer=fake_llm, force=True)
check("3a legacy block NOT re-summarized",
      all("legacy decisions" not in (m.get("content") or "") for m in seen.get("got", [])),
      [(m.get("role"), (m.get("content") or "")[:30]) for m in seen.get("got", [])])
check("3b legacy body carried into the new block",
      bool(out3) and "legacy decisions" in (out3[0].get("content") or ""), "")

# ---- 4. Combination over the cap prunes from the front, tail intact ----------
seen.clear()
big_prev = {"role": "system", "content": CE.SUMMARY_PREFIX + "HEADMARKER" + "P" * 5900}
msgs4 = [big_prev,
         {"role": "user", "content": "fresh turn with TAILMARKER"},
         {"role": "user", "content": "keep me"}]
out4, _st4 = CE.compact(msgs4, 50, keep_recent=1,
                        summarizer=lambda fresh: "NEWTAIL " + "x" * 500,
                        force=True)
body4 = (out4[0].get("content") or "")
check("4a combined block within cap",
      len(body4) <= len(CE.SUMMARY_PREFIX) + CE.COMBINED_SUMMARY_MAX_CHARS, len(body4))
check("4b tail (fresh summary) intact after prune", "NEWTAIL" in body4, body4[-60:])
check("4c oldest head pruned", "HEADMARKER" not in body4, body4[:80])

# ---- 5. Extractive fallback (no summarizer) with a previous block ------------
msgs5 = [prev,
         {"role": "user", "content": "fresh extractive turn"},
         {"role": "user", "content": "keep me"}]
out5, st5 = CE.compact(msgs5, 50, keep_recent=1, summarizer=None, force=True)
check("5a extractive carry keeps the previous body",
      bool(out5) and "old decisions" in (out5[0].get("content") or ""), "")
check("5b extractive carry folds the fresh turn",
      bool(out5) and "fresh extractive turn" in (out5[0].get("content") or ""), "")
check("5c stats say extractive", st5.get("summary") == "extractive", st5.get("summary"))

# ---- 6. Legacy no-previous behaviour unchanged --------------------------------
msgs6 = [{"role": "user", "content": "plain old turn"},
         {"role": "user", "content": "keep me"}]
out6, st6 = CE.compact(msgs6, 50, keep_recent=1, summarizer=None, force=True)
check("6a legacy extractive prefix kept without previous block",
      bool(out6) and (out6[0].get("content") or "").startswith(CE.EXTRACTIVE_PREFIX),
      (out6[0].get("content") or "")[:50])

# ---- 7. KEEP list names commitments ------------------------------------------
def _repo_file(*parts):
    here = os.path.abspath(os.path.dirname(__file__))
    for _ in range(5):
        cand = os.path.join(here, *parts)
        if os.path.exists(cand):
            return cand
        here = os.path.dirname(here)
    return os.path.join(here, *parts)


cfg = open(_repo_file("config", "compaction.yaml"), encoding="utf-8").read().lower()
check("7a KEEP names commitments/promises/constraints",
      "commitment" in cfg and "promise" in cfg and "constraint" in cfg, "")

print("TOTAL %d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
