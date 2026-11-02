#!/usr/bin/env python3
"""v774 — an unexecutable reply must be REPAIRED or SHOWN, never loop into a stopped goal.

Operator report (2026-11-02, "GRAVISSIMO"): a goal stopped with
`no_valid_action` while the plan was incomplete, the model "kept getting it wrong",
and the chat showed three bare `harness → LLM RETRY` messages with no agent turn
between them.

Evidence (session 777378644e9c, ~21:54, transcript on disk):

    [1198] assistant | {"action":"tool","shell.exec","args":{"command":"… sed -n '850,868p' …"}}
    [1199] user      | [harness] That JSON was invalid or incomplete (it did not parse). …
    [1200] assistant | {"action":"tool","shell.exec","args":{"command":"…sed -n '850,868p'…"}}
    [1201] user      | [harness] That JSON was invalid or incomplete (it did not parse). …
    [1202] assistant | {"action":"tool","shell.exec","args":{"command":"… awk 'NR>=850 && NR<=870' …"}}
    [1203] assistant | ⏸ Goal incomplete: stopped with reason 'no_valid_action' …

Three facts, three defects:
1. `{"action":"tool","shell.exec","args":{…}}` is the tool NAME where a KEY belongs
   — not valid JSON, but the intent is exact. It has to be REPAIRED (the same rule
   as the `<arg_key>` dialect, v751). It was not, so each reply burned a round-trip.
2. The retry never quoted the reply and never named the malformation, so the model
   repeated the SAME broken shape until the four-invalid-reply breaker fired.
3. Only the stray-action branch had a last-chance closure round; the unparseable
   branch stopped a GOAL outright, and the stop message named a reason CODE the
   operator could not read. The replies between two RETRYs are `internal`, so the
   UI hid the agent's own turn — hence "harness messages in a row with nothing
   between them".

Deterministic: no live model, no network, no server.
Run: python3 tests/acceptance/v774_invalid_reply_recovery.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v774-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(TMP, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server                       # noqa: E402,F401 — import cycle
from longrun.agent import agent as A                  # noqa: E402

SRC = open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"), encoding="utf-8").read()
HTML = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ============================================================================
# A — the misplaced tool name is REPAIRED (v751's rule applied to a new shape)
# ============================================================================
check("A1 the pure form is repaired into a real action",
      A._extract_action('{"action":"tool","shell.exec","args":{"command":"ls"}}')
      == {"action": "tool", "tool": "shell.exec", "args": {"command": "ls"}},
      A._extract_action('{"action":"tool","shell.exec","args":{"command":"ls"}}'))

# the EXACT bytes from the transcript (leading newlines, single quotes in the command)
LIVE1 = ('\n\n{"action":"tool","shell.exec","args":'
         '{"command":"cd /home/jagones/Repositories/jevarium && sed -n \'850,868p\' '
         'web/index.html"}}')
LIVE2 = ('\n\n{"action":"tool","shell.exec","args":'
         '{"command":"cd /home/jagones/Repositories/jevarium && awk \'NR>=850 && NR<=870\' '
         'web/index.html"}}')
LIVE3 = ('\n\n{"action":"tool","tool":"shell.exec","args":'
         '{"command":"cd /x && node s.mjs 2>&1 | tail -6"}}')
_l1, _l2, _l3 = (A._extract_action(LIVE1), A._extract_action(LIVE2), A._extract_action(LIVE3))
check("A2 the live reply (1198) resolves to the call the model meant",
      isinstance(_l1, dict) and _l1.get("tool") == "shell.exec"
      and "sed -n '850,868p'" in (_l1.get("args") or {}).get("command", ""), _l1)
check("A2b the live variant (1202) resolves too (pipes and quotes intact)",
      isinstance(_l2, dict) and "awk 'NR>=850 && NR<=870'" in (_l2.get("args") or {}).get("command", ""), _l2)
check("A2c an already-valid envelope is untouched (no false dialect)",
      isinstance(_l3, dict) and _l3.get("tool") == "shell.exec", _l3)

for _k in ("args", "arguments", "input", "parameters"):
    _t = '{"action":"tool","shell.exec","%s":{"command":"ls"}}' % _k
    check("A3 the repair covers the %r key" % _k,
          (A._extract_action(_t) or {}).get("tool") == "shell.exec", A._extract_action(_t))

check("A4 prose is returned unchanged by the repair (nothing to fix)",
      A._repair_misplaced_tool_name("just an answer") == "just an answer")
check("A5 the degenerate {\"action\":\"tool\",\"shell\":\"x\"} is NOT guessed into a tool",
      (A._extract_action('{"action":"tool","shell":"x"}') or {}).get("tool") != "shell",
      A._extract_action('{"action":"tool","shell":"x"}'))

# ============================================================================
# B — a retry must SHOW the reply it rejected
# ============================================================================
_n = A._rejected_reply_note('{"action":"tool","shell.exec","args":{"command":"ls"}}')
check("B1 the note quotes the rejected reply", "shell.exec" in _n and "It was:" in _n, _n[:160])
check("B2 it names the malformation (the name where the KEY belongs)",
      "KEY" in _n and '"tool":"<name>"' in _n, _n)
check("B3 it survives a reply with no known shape (still quotes it)",
      "gibberish" in A._rejected_reply_note("gibberish {"))
check("B4 the J-16 action note keeps its published contract (v764)",
      "That was not a valid action" in A._invalid_action_note({"action": "tool", "shell": "x"})
      and "self.tools" in A._invalid_action_note({"action": "tool", "shell": "x"}))

# ============================================================================
# C — the breaker: ONE owner, bounded, with a last chance in goal mode
# ============================================================================
check("C1 the cap is the documented 4 and one owner decides", A.INVALID_REPLY_CAP == 4)
check("C2 below the cap it retries", A._after_invalid_reply(1, 0, False) == "retry"
      and A._after_invalid_reply(3, 0, False) == "retry")
check("C3 at the cap it SWITCHES STRATEGY — a tool-use mistake never ends the turn",
      A._after_invalid_reply(4, 0, False) == "prose"
      and A._after_invalid_reply(9, 0, False) == "prose")
check("C4 at the cap on an UNFINISHED goal it spends the last closure round first",
      A._after_invalid_reply(4, 1, True) == "selfcheck")
check("C5 all THREE kinds of invalid reply go through the one owner",
      SRC.count("_decision = _after_invalid_reply(") == 3
      and SRC.count('if _decision == "selfcheck":') == 3
      and SRC.count('if _decision == "prose":') == 3)
_selfcheck_blocks = SRC.split('if _decision == "selfcheck":')[1:]
check("C6 no branch appends the rejected reply TWICE (the old double transcript entry)",
      len(_selfcheck_blocks) == 3
      and all("msgs.append" not in b.split("continue")[0] for b in _selfcheck_blocks),
      [b.split("continue")[0][:60] for b in _selfcheck_blocks])
check("C7 the harness no longer STOPS the turn on a tool mistake",
      all(l.strip() != '_kg_stop_reason = "no_valid_action"' for l in SRC.splitlines())
      and 'on_event("plan.invalid_reply_recovery"' in SRC
      and SRC.count('_last_rejected = str(answer or "").strip()[:240]') == 3)
check("C8 the strategy switch shows the count and the rejected reply, and names names",
      A._prose_recovery_note('{"action":"tool","shell.exec","args":{}}', 3).count("3") >= 1
      and "shell.exec" in A._prose_recovery_note("x shell.exec", 2)
      and "PLAIN PROSE" in A._prose_recovery_note("x", 1)
      and "self.tools" in A._prose_recovery_note("x", 1))

# ============================================================================
# D — the operator can read WHY it stopped, and WHAT was rejected
# ============================================================================
check("D1 the unparseable retry is the quoting note",
      "_inject(_rejected_reply_note(answer), \"retry\")" in SRC)
check("D2 the DSML retry quotes the reply too", '"named no tool the harness can run. It was: "' in SRC)
check("D3 a stop that does happen still names the cause and quotes the reply",
      "not an executable action" in SRC and "Last rejected reply: " in SRC)
check("D4 the reason is carried on the message meta for replay",
      '"last_rejected": _last_rejected' in SRC)

# ============================================================================
# E — the harness chatter has ONE owner per instruction
# ============================================================================
check("E1 the observation keeps the permission to act or finish",
      "Continue: call the next tool, or report the result." in SRC)
check("E2 the task-list half is no longer repeated in every observation",
      "task list current (mark a finished step done with evidence)" not in SRC)
check("E3 the CONTINUE inject still owns the open list + the discipline",
      "CONTINUE — %d task(s) are still OPEN" in SRC)

# ============================================================================
# F — the running state says WHAT it is waiting for (an idle GPU is not a hang)
# ============================================================================
_evs = []
A._phase(lambda kind, **d: _evs.append((kind, d)), "sid1", "model", model="local:big")
check("F1 the harness publishes its phase with the model it is waiting for",
      _evs and _evs[0][0] == "chat.phase" and _evs[0][1].get("phase") == "model"
      and _evs[0][1].get("model") == "local:big" and _evs[0][1].get("at"), _evs)
check("F2 a broken event sink cannot break the turn",
      A._phase(lambda kind, **d: (_ for _ in ()).throw(RuntimeError("x")), "s", "model") is None)
check("F3 every model call is bracketed by the phase (3 sites, one helper)",
      SRC.count('_phase(on_event, sess["id"], "model"') == 3
      and SRC.count('_phase(on_event, sess["id"], "idle")') == 3)
check("F4 the composer carries the phase line with its own styles",
      '<div id="turnPhase" hidden></div>' in HTML
      and "#turnPhase .tp-dot" in HTML and "@keyframes tpPulse" in HTML)
check("F5 the UI draws it from the event and clears it when the tokens arrive",
      'es.addEventListener("chat.phase"' in HTML
      and "turnPhaseShow(d.session, d.model" in HTML
      and "turnPhaseClear(d.session)" in HTML)
check("F6 a finished turn cannot leave the phase on screen",
      "delete runningSessions[sid]; turnPhaseClear(sid);" in HTML)
check("F7 the phase is LIVE-only: a replayed feed event never claims a stale wait",
      "chat.phase" not in HTML.split("function _feedReplay(")[1].split("function _resyncDurable(")[0])

print()
print("%d/%d checks passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
