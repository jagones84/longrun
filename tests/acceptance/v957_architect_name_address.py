#!/usr/bin/env python3
"""v957 — the Architect is addressed as "Architect", not by its legacy session id.

Operator, 2026-11-11: *"la sessione Architect va chiamata con Architect dai tool send
message etcetera, no longrunAgent"*.

Why it happened: the session id `longrunAgent` is a permanent machine key (the file,
the API path, the roles key, the `allow_longrun_agent` flag) and it was also the ONLY
spelling `sessions.*` accepted — while the name the operator and the model read is
`Architect` (the session title and the agent record). An agent therefore had to write
the machine id, and kept repeating it.

Locked here — ONE resolver, so no call site can drift:
  * `agents.REGISTRY.resolve` finds an agent by session id, by A-id OR by NAME
    (case-insensitive), which is what the permission gates (`_may_message`,
    `_may_manage`) already use;
  * `tools._session_id` turns any of those into the canonical session id, and the
    `sessions` tool applies it to read / send / compact / reset;
  * `sessions.list` ADDRESSES an agent by its name + A-id, and falls back to the raw
    id only for a session with no agent record;
  * the tool schema says the name works, so the model is taught the right word;
  * the reporting-line rule is unchanged (a worker still cannot reach the Architect).

Deterministic: temp stores, no server, no model, no network, no delivery.
Run: python3 tests/acceptance/v957_architect_name_address.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v957-")
os.environ["LONGRUN_DATA_DIR"] = TMP
os.environ["LONGRUN_AGENTS_FILE"] = os.path.join(TMP, "agents.json")
os.environ["LONGRUN_JOBS_FILE"] = os.path.join(TMP, "jobs.json")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.makedirs(os.environ["LONGRUN_SESSIONS_DIR"], exist_ok=True)
os.makedirs(os.environ["LONGRUN_GRAPH_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.agent import agents as AG            # noqa: E402
from longrun.memory import stores as STORES        # noqa: E402
from longrun.tools import registry as REG          # noqa: E402
from longrun.tools import tools as T               # noqa: E402
from longrun.util import inbox as INBOX            # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


reg = AG.REGISTRY
ARCH_SID = "longrunAgent"
ARCH = reg.designate(ARCH_SID, name="Architect")["agent"]["id"]          # A1, no manager
LEAD = reg.designate("s-lead", name="Crew Lead")["agent"]["id"]          # top leader
WORKER = reg.designate("s-worker", name="Writer", reports_to="s-lead")["agent"]["id"]
for _sid in (ARCH_SID, "s-lead", "s-worker", "s-plain"):
    sess = STORES.get_or_create_session(_sid)
    sess["messages"] = [{"role": "user", "content": "hello from " + _sid, "ts": 1}]
    STORES.save_session(sess)

# --- A: the resolver accepts the name, the A-id and the id -------------------
check("A1 a NAME resolves to the agent (what the operator asked for)",
      (reg.resolve("Architect") or {}).get("id") == ARCH, reg.resolve("Architect"))
check("A2 the name is case-insensitive",
      (reg.resolve("architect") or {}).get("id") == ARCH)
check("A3 the A-id still works", (reg.resolve(ARCH) or {}).get("id") == ARCH)
check("A4 the legacy session id still works (no regression)",
      (reg.resolve(ARCH_SID) or {}).get("id") == ARCH)
check("A5 an unknown name resolves to nothing", reg.resolve("nobody-here") is None)

# --- B: every target becomes the canonical session id ------------------------
check("B1 _session_id('Architect') -> the Architect session",
      T._session_id("Architect") == ARCH_SID, T._session_id("Architect"))
check("B2 _session_id(A-id) -> the same session", T._session_id(ARCH) == ARCH_SID)
check("B3 _session_id(raw id) is unchanged", T._session_id(ARCH_SID) == ARCH_SID)
check("B4 a session with no agent keeps its id",
      T._session_id("s-plain") == "s-plain")
check("B5 an unknown target is returned unchanged (the caller names the error)",
      T._session_id("s-nope") == "s-nope")

# --- C: the `sessions` tool resolves the name before it acts ------------------
_r = T._sessions({"action": "read", "session": "Architect"}, None)
check("C1 action=read accepts the NAME", _r.get("ok") is True, _r.get("error"))
check("C2 ... and reads the Architect's transcript",
      "hello from " + ARCH_SID in (_r.get("stdout") or ""))
check("C3 ... and reports the canonical session id",
      _r.get("session") == ARCH_SID, _r.get("session"))
check("C3b the transcript header ADDRESSES the agent by name",
      ("agent Architect (%s)" % ARCH) in (_r.get("stdout") or ""),
      (_r.get("stdout") or "").splitlines()[:1])

_seen = {}
_saved = INBOX.deliver
INBOX.deliver = lambda sid, text, from_session=None: (
    _seen.update({"sid": sid, "text": text}) or
    {"ok": True, "mode": "steer", "session": sid, "messages": 0, "queue_depth": 1})
try:
    _r2 = T._sessions({"action": "send", "session": "Architect", "message": "ping"},
                      LEAD)   # the top leader: the only one who may address it
finally:
    INBOX.deliver = _saved
check("C4 action=send accepts the NAME and delivers to the canonical session",
      _r2.get("ok") is True and _seen.get("sid") == ARCH_SID, (_r2.get("error"), _seen))

# --- D: the reporting line is unchanged --------------------------------------
_ok, _why = T._may_message(WORKER, "Architect")
check("D1 a worker still cannot reach the Architect BY NAME", _ok is False, _why)
check("D2 the refusal still explains the rule (no id needed)",
      "top leader" in _why and ARCH_SID not in _why, _why)
_ok2, _why2 = T._may_message(LEAD, "Architect")
check("D3 a top leader can reach the Architect by name", _ok2 is True, _why2)
_r3 = T._sessions({"action": "send", "session": "Architect", "message": "x"}, WORKER)
check("D4 the tool refuses the worker with exit 126", _r3.get("exit_code") == 126,
      _r3.get("exit_code"))

# --- E: the list ADDRESSES the agent by name ---------------------------------
_l = T._sessions({"action": "list"}, None)
_out = _l.get("stdout") or ""
check("E1 the list shows the name + A-id", "Architect (%s)" % ARCH in _out, _out.splitlines()[:3])
check("E2 ... and no longer uses the legacy id as the address",
      ARCH_SID not in _out, _out.splitlines()[:3])
# EV-30 gives EVERY stored session an agent record, so the list always has a name to
# show; the raw-id fallback stays in the code for a session with no record at all.
check("E3 every listed address is `name (A-id)`",
      all(("(" in ln.split("|")[0] and ")" in ln.split("|")[0])
          for ln in _out.splitlines()[1:] if ln.strip()),
      _out.splitlines()[1:])
check("E4 the raw id is still the fallback in the source",
      'if _who else r.get("id")' in open(
          os.path.join(REPO, "src", "longrun", "tools", "tools.py"), encoding="utf-8").read())
check("E5 the header teaches the accepted spellings",
      "name, A-id or id" in _out, _out.splitlines()[0] if _out else "")

# --- F: the schema teaches the model the same word ---------------------------
_sch = REG.TOOL_SCHEMAS.get("sessions") or {}
_sdesc = str(((_sch.get("properties") or {}).get("session") or {}).get("description") or "")
check("F1 the `session` field says the NAME works, for ANY session",
      "NAME" in _sdesc and "for ANY session" in _sdesc, _sdesc[:160])
check("F2 ... and still lists the A-id and the raw id", "A-id" in _sdesc and "session id" in _sdesc)
check("F3 ... and never narrows the tool to one agent",
      "Architect" not in _sdesc and "longrunAgent" not in _sdesc, _sdesc[:160])

# --- G: the Architect's OWN prompt introduces it by name ---------------------
from longrun.model import prompt as P            # noqa: E402

_txt = P._provider_longrun_agent({"id": ARCH_SID, "system": True}, None, None)
check("G1 the Architect's own prompt introduces it by NAME",
      "You are Architect" in _txt)
check("G2 ... and never as the legacy session id",
      "You are longrunAgent" not in _txt)
check("G3 the legacy id is named once as a machine key, never as an identity",
      "legacy machine key" in _txt)
_g = P._provider_longrun_agent({"id": "granted-x", "allow_longrun_agent": True}, None, None)
check("G4 a granted session sees the Architect's namespace, not an identity",
      "The Architect's namespace" in _g and "You are Architect" not in _g)

ok = sum(1 for r in results if r)
print("\n%d/%d checks passed" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
