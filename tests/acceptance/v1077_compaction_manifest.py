#!/usr/bin/env python3
"""v1077 — the compacted view carries a mechanical MANIFEST of the calls it folded.

Folio (arXiv:2611.16627) keeps three linked levels: the model's turn note, a
runtime EVENT MANIFEST of every call, and the source records. Longrun had the note
(the summary) and the sources (tool cards on disk) but no manifest in the compacted
view: a failure older than `keep_recent` survived only as prose the summarizer is
free to drop — and the summarization failure mode ("assume the task finished") is
exactly what the operator-facing research named.

Contract:
  M1 no cards -> no block; the summary is unchanged
  M2 the last `MANIFEST_MAX` cards are listed, and an older FAILURE is kept even
     when the window would have pushed it out
  M3 `until` drops a card created AFTER the compacted turns
  M4 `compact(manifest=...)` appends the block and reports `stats["manifest"]`
  M5 without a manifest the summary is byte-identical to before
  M6 the carried-summary path stays byte-identical (no manifest on a cooldown)
  M7 the three callers pass the session's cards (assemble_turn, preview, manual)

Deterministic: pure functions, no model, no network.
Run: python3 tests/acceptance/v1077_compaction_manifest.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.model import context_engine as CE  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


CARDS = [{"tool": "f%02d" % i, "ok": True, "ts": float(i)} for i in range(1, 31)]
CARDS[2] = {"tool": "shell.exec", "ok": False, "exit_code": 1,
            "error": "boom\nsecond line", "ts": 3.0}

# ---- M1 ----------------------------------------------------------------------
check("M1 no cards -> no block", CE.manifest_block([]) == ""
      and CE.manifest_block(None) == "")

# ---- M2 ----------------------------------------------------------------------
_b = CE.manifest_block(CARDS)
check("M2a the last card is listed", "f30 ok" in _b, _b[-120:])
check("M2b the age-out FAILURE is preserved",
      "shell.exec FAILED (exit=1): boom second line" in _b, _b)
check("M2c an ordinary card outside the window is not listed",
      "f01 ok" not in _b, _b[:160])
check("M2d the block is bounded", len(_b) <= CE.MANIFEST_CHARS, len(_b))

# ---- M3 ----------------------------------------------------------------------
_b2 = CE.manifest_block(CARDS, until=10.0)
check("M3 a card after the cutoff is excluded",
      "f10 ok" in _b2 and "f11 ok" not in _b2, _b2)

# ---- M4/M5 -------------------------------------------------------------------
MSGS = [{"role": "user" if i % 2 else "assistant", "content": "m%d" % i,
         "ts": float(i)} for i in range(1, 11)]
_out, _st = CE.compact(MSGS, 100000, keep_recent=2, force=True, manifest=CARDS)
_summary = (_out[0].get("content") or "") if _out else ""
check("M4a the summary carries the manifest", "MANIFEST" in _summary, _summary[-200:])
check("M4b the failure is named in it",
      "shell.exec FAILED (exit=1)" in _summary, _summary[-400:])
check("M4c only the compacted window is listed",
      "f08 ok" in _summary and "f10 ok" not in _summary, _summary[-400:])
check("M4d stats reports it", (_st.get("manifest") or 0) > 0, _st.get("manifest"))
_out2, _st2 = CE.compact(MSGS, 100000, keep_recent=2, force=True)
_sum2 = (_out2[0].get("content") or "") if _out2 else ""
check("M5 no manifest -> no section, same body",
      "MANIFEST" not in _sum2
      and _sum2.rstrip("\n") == _summary.split("\n\n" + CE.MANIFEST_PREFIX)[0].rstrip("\n"),
      _sum2[-160:])

# ---- M6 ----------------------------------------------------------------------
PRIOR = CE.SUMMARY_PREFIX + "prior body"
CARRIED = [{"role": "system", "content": PRIOR, "ts": 1.0},
           {"role": "user", "content": "[harness] Observation for tool x", "ts": 2.0},
           {"role": "assistant", "content": "tail", "ts": 3.0}]
_out3, _st3 = CE.compact(CARRIED, 100000, keep_recent=1, force=True, manifest=CARDS)
check("M6 the carried summary is byte-identical (no manifest)",
      _st3.get("summary") == "carried" and _out3[0].get("content") == PRIOR,
      (_st3.get("summary"), _out3[0].get("content")[:80] if _out3 else None))

# ---- M7: wiring -------------------------------------------------------------
AGENT = open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"),
             encoding="utf-8").read()
HTTP = open(os.path.join(REPO, "src", "longrun", "core", "httpapi.py"),
            encoding="utf-8").read()
check("M7a assemble_turn passes the session's cards",
      'manifest=(sess or {}).get("tool_cards")' in AGENT)
check("M7b the manual compaction passes them",
      '"manifest": (sess or {}).get("tool_cards")' in HTTP)
check("M7c preview passes them", 'manifest=sess.get("tool_cards")' in
      open(os.path.join(REPO, "src", "longrun", "model", "context_engine.py"),
           encoding="utf-8").read())

print("\n---\nv1077: %d/%d PASS" % (sum(RESULTS), len(RESULTS)))
raise SystemExit(0 if all(RESULTS) else 1)
