#!/usr/bin/env python3
"""v590 (RED) — M10 slice: classify the killed turn, store a resume record.

DeepSeek direction (resume/fork/replay) cut to the honest minimal slice:
Longrun cannot auto-resume at boot (that needs model calls off the request
path), but it CAN tell "nothing executed, replay is safe" apart from "tools
ran, effects unknown" — and persist which checkpoint a later resume must use.

- `stores.classify_interruption(sess, checkpoint)`:
  trailing user message + zero current-turn tool cards + checkpoint
  -> {"effect": "interrupted_before_effect", ...};
  any current-turn card (tool_cards with after >= len(messages)) or no
  checkpoint -> {"effect": "unknown_effect", ...};
  no trailing user message -> None (not an orphan at all).
- `reconcile_orphan_turns()` must consult it, persist
  `sess["interrupted"] = {effect, executed, checkpoint, ...}`, and word the
  assistant notice by effect (resume-from-checkpoint vs send-new-message).

Deterministic: no model, no network, no server.
Run: python3 tests/acceptance/v590_interrupt_classify.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _repo(start):
    p = start
    while True:
        if os.path.isdir(os.path.join(p, "src", "longrun")):
            return p
        parent = os.path.dirname(p)
        if parent == p:
            raise SystemExit("repository root not found from %s" % start)
        p = parent


REPO = _repo(HERE)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.memory import stores  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def _sess(n_user_trailing=True, cards=()):
    msgs = [{"role": "user", "content": "a"},
            {"role": "assistant", "content": "b"},
            {"role": "user", "content": "c"}]
    if not n_user_trailing:
        msgs.append({"role": "assistant", "content": "d"})
    return {"id": "S1", "messages": msgs,
            "tool_cards": [dict(c) for c in cards]}


# ---- A: the classifier exists ------------------------------------------------
check("A1 stores.classify_interruption exists",
      callable(getattr(stores, "classify_interruption", None)))
ci = getattr(stores, "classify_interruption", None)

# ---- B: pure behavior ---------------------------------------------------------
if callable(ci):
    r = ci(_sess(), checkpoint="cp_1")
    check("B1 no cards + checkpoint -> before_effect",
          isinstance(r, dict) and r.get("effect") == "interrupted_before_effect"
          and r.get("executed") == 0 and r.get("checkpoint") == "cp_1", repr(r))
    r = ci(_sess(), checkpoint=None)
    check("B2 no cards but no checkpoint -> unknown_effect",
          isinstance(r, dict) and r.get("effect") == "unknown_effect", repr(r))
    r = ci(_sess(cards=[{"tool": "fs.read", "after": 3}]), checkpoint="cp_1")
    check("B3 one current-turn card -> unknown_effect, executed 1",
          isinstance(r, dict) and r.get("effect") == "unknown_effect"
          and r.get("executed") == 1, repr(r))
    r = ci(_sess(cards=[{"tool": "fs.read", "after": 1},
                        {"tool": "shell.exec", "after": 3},
                        {"tool": "shell.exec", "after": 3}]), checkpoint="cp_1")
    check("B4 old cards ignored, current counted",
          isinstance(r, dict) and r.get("executed") == 2
          and r.get("effect") == "unknown_effect", repr(r))
    check("B5 trailing assistant -> None (not an orphan)",
          ci(_sess(n_user_trailing=False), checkpoint="cp_1") is None)
    check("B6 empty transcript -> None",
          ci({"id": "S1", "messages": [], "tool_cards": []}) is None)
else:
    for n in ("B1", "B2", "B3", "B4", "B5", "B6"):
        check(n, False, "classify_interruption missing")

# ---- C: reconcile consults it, persists the record, words by effect -----------
try:
    with open(os.path.join(REPO, "src", "longrun", "memory", "stores.py"),
              encoding="utf-8") as f:
        _src = f.read()
except OSError as e:
    _src = ""
    print("WARN cannot read stores.py: %s" % e)

_body = _src.split("def reconcile_orphan_turns(", 1)
_body = _body[1] if len(_body) > 1 else ""
_nxt = _body.find("\ndef ")
_block = _body[:_nxt] if _nxt >= 0 else _body
check("C1 reconcile calls classify_interruption",
      "classify_interruption(" in _block)
check("C2 reconcile looks up the turn checkpoint",
      "turn:%s:%s" in _block or "turn:" in _block)
check("C3 reconcile persists sess[\"interrupted\"]",
      'sess["interrupted"]' in _block or "['interrupted']" in _block)
check("C4 notice branches on the effect",
      "interrupted_before_effect" in _block)
check("C5 unknown_effect keeps the send-a-new-message notice",
      "send a new message" in _block)

print("\n%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
