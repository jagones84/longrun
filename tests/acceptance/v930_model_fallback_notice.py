#!/usr/bin/env python3
"""v930 — a reply produced by a FALLBACK model must say so in that chat.

Operator (2026-11-10): *"he reply came from a REMOTE model … not from local llama.cpp
— port 8080 is NOT listening. se si usa un modello di fallback deve apparire un
messaggio, altrimenti l'utente che ne sa."* Reproduced from the live event log: twice
that day `dgx:nex-n25-mini-uncensored-q8` failed and the turn silently continued on
`openrouter:z-ai/glm-5.3-flash` (`model.fallback` at 13:32:07 and 13:54:29) — those
events carried no session, so nothing could appear in the chat, and the reply itself
shows no model.

`agent.model_fallback_notice` is the ONE sentence; the chat loop emits it once per
fallback (live) and persists it (reload). It is a NOTICE, not a `harness → LLM` chip:
the model never received that text, and the chip label promises the wire bytes.

  A) the decision: silent when the model is the one asked, one line when it is not;
  B) the wiring: both chat call sites and the best-of-N sample report it, once;
  C) the surface: published + persisted, rendered as `.hnote`, never as a chip;
  D) what must not change: an ordinary reply still uses the `.hinj` chip path.

Deterministic, no live model, no network, no server.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v930-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(TMP, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_PROJECTS_DIR"] = os.path.join(TMP, "projects")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server                # noqa: E402,F401 — breaks the import cycle
from longrun.agent import agent                # noqa: E402

results = []
DGX = "dgx:nex-n25-mini-uncensored-q8"
REMOTE = "openrouter:z-ai/glm-5.3-flash"


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as fh:
        return fh.read()


# ---- A. the decision -------------------------------------------------------
check("A1 the model the session asked for produces NO notice",
      agent.model_fallback_notice(DGX, DGX) == "")
check("A2 a different model produces ONE line naming BOTH",
      DGX in agent.model_fallback_notice(DGX, REMOTE)
      and REMOTE in agent.model_fallback_notice(DGX, REMOTE)
      and "continue" in agent.model_fallback_notice(DGX, REMOTE),
      agent.model_fallback_notice(DGX, REMOTE))
check("A3 nothing is said when a side is unknown (never a guess)",
      agent.model_fallback_notice(None, REMOTE) == ""
      and agent.model_fallback_notice(DGX, "") == "")
state = {}
check("A4 the SAME fallback is announced once per turn",
      bool(agent.model_fallback_notice(DGX, REMOTE, state))
      and agent.model_fallback_notice(DGX, REMOTE, state) == "")
check("A5 a DIFFERENT fallback model later in the turn is announced again",
      bool(agent.model_fallback_notice(DGX, "openrouter:openrouter/auto", state)))
check("A6 a foreign state object never raises",
      bool(agent.model_fallback_notice(DGX, REMOTE, "not-a-dict")))

# ---- B. the wiring in the chat loop ---------------------------------------
_src = _read("src", "longrun", "agent", "agent.py")
check("B1 the intended model is captured before BOTH streaming call sites",
      _src.count("_requested_model = model") == 2,
      "_requested_model = model x%d" % _src.count("_requested_model = model"))
check("B2 both call sites report the model that answered",
      _src.count("_note_fallback(_requested_model, model)") == 2,
      "_note_fallback x%d" % _src.count("_note_fallback(_requested_model, model)"))
check("B3 the best-of-N extra samples report it too",
      "_note_fallback(model, _m2)" in _src)

# ---- C. the surface --------------------------------------------------------
check("C1 published with its own inject kind",
      'inject_kind="model-fallback"' in _src)
check("C2 persisted, so a reload still shows which model answered",
      'persist_inject(sess, "model-fallback", _txt' in _src)
check("C3 it is NOT injected into the model context (not a harness chip)",
      "_inject(_txt" not in _src and "msgs.append(_txt" not in _src)
check("C4 the notice is never claimed as a harness→LLM package",
      '"model-fallback"' in _src and "harness_wrap(_txt" not in _src)

_web = _read("webui", "index.html")
check("C5 the UI renders the kind as a visible notice, before the chip builder",
      'kind === "model-fallback"' in _web
      and _web.index('kind === "model-fallback"') < _web.index('det.className = "hinj"'),
      "")
check("C6 the notice has its own style and is announced to assistive tech",
      ".hnote" in _web and 'n.setAttribute("role", "status")' in _web)
check("C7 the reloaded record goes through the SAME renderer",
      "harnessInject({ inject_kind: v.kind" in _web)

# ---- D. no regression on the ordinary chip ---------------------------------
check("D1 an ordinary inject still builds the collapsed chip",
      'det.className = "hinj"' in _web and 'det.querySelector(".hbody").textContent = text' in _web)
check("D2 the fallback notice did not replace any existing inject kind",
      _web.count('kind === "model-fallback"') == 1)

print("%d/%d checks" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
