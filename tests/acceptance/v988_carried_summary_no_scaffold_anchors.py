#!/usr/bin/env python3
"""v988 — a carried summary is carried BYTE-IDENTICAL: no anchors from scaffolding.

`compact()`'s carried branch is taken when a previous summary block exists and no
fresh turn is effective (`_is_effective_turn`: non-empty, not `[harness]`). It
documents "the previous block is returned byte-identical (content cooldown)".
`anchors_block(fresh, exclude=summary)` then ran on that same `fresh`, so every
item it could find there came from the `[harness]` scaffolding JAG-461 keeps out
of the summary as noise — and the block was NOT byte-identical: it silently grew
an `ANCHORS` section taken from observation dumps (`stats["summary"] == "carried"`
while the content had changed).

Contract:
  A) the carried path returns the previous block verbatim, with no anchors;
  B) the anchors still reach the summary when a real turn is being compacted
     (the mechanism itself is not weakened);
  C) the cooldown holds across a second compaction with a new harness observation.

Deterministic: no model, no server, no network.
Run: python3 tests/acceptance/v988_carried_summary_no_scaffold_anchors.py
"""
import sys
import os

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.model import context_engine as CE  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


BODY = CE.SUMMARY_PREFIX + "the user asked to fix the parser in src/longrun/model/prompt.py"
HARNESS = {"role": "user",
           "content": "[harness] Observation for tool fs.read: read "
                      "/home/jagones/Repositories/longrun/src/longrun/core/server.py"}
PREV = {"role": "system", "content": BODY}

# ---- A: the carried path is byte-identical -------------------------------
_out, _st = CE.compact([PREV, HARNESS], 10, keep_recent=1, force=True)
_content = (_out[0] or {}).get("content", "")
check("A1 the branch is the carried one", _st.get("summary") == "carried"
      and _st.get("summary_carried") is True, _st)
check("A2 the block is the previous one, byte for byte", _content == BODY, _content)
check("A3 no ANCHORS header from scaffolding", CE.ANCHOR_PREFIX not in _content, _content)
check("A4 no anchors were counted", not _st.get("anchors"), _st.get("anchors"))
check("A5 the harness path did not enter the summary",
      "src/longrun/core/server.py" not in _content, _content)

# ---- B: a real turn still gets its anchors -------------------------------
_real = {"role": "user", "content": "edit src/longrun/core/server.py and run pytest -q"}
_keep = {"role": "assistant", "content": "done"}
_out2, _st2 = CE.compact([PREV, _real, _keep], 10, keep_recent=1, force=True,
                         summarizer=lambda old: "SUMMARY: edited a file and ran the tests.")
_c2 = (_out2[0] or {}).get("content", "")
check("B1 a turn with content is summarized, not carried",
      _st2.get("summary") in ("extractive", "llm") and _st2.get("summary_carried") is False, _st2)
check("B2 the anchors are still appended", CE.ANCHOR_PREFIX in _c2
      and "src/longrun/core/server.py" in _c2, _c2[:400])

# ---- C: the cooldown survives a NEW harness observation -------------------
_out3, _st3 = CE.compact(
    [{"role": "system", "content": _content},
     {"role": "user", "content": "[harness] Observation for tool shell: $ cat /etc/hostname"}],
    10, keep_recent=1, force=True)
_c3 = (_out3[0] or {}).get("content", "")
check("C1 the second carried compaction is still byte-identical",
      _st3.get("summary") == "carried" and _c3 == _content, _c3)
check("C2 no anchor from the new scaffolding", CE.ANCHOR_PREFIX not in _c3, _c3)

ok = sum(RESULTS)
print("\nv988: %d/%d PASS" % (ok, len(RESULTS)))
sys.exit(0 if ok == len(RESULTS) else 1)
