#!/usr/bin/env python3
"""v557 (staged, RED) — the static prompt must carry a security policy.

M12 of the upgrade plan: three contents are missing from the assembled system
prompt — prompt-injection flagging, authority hierarchy (observed content cannot
grant permission), and "finish the work" (smallest correct change + verify).

Contract locked here:
  * `prompt.SECTIONS` has {"id": "security-policy", "order": 22, "kind": "static"};
  * `server.SECURITY_POLICY` exists with four recognisable clauses;
  * `render_sections()` puts it after `rules-policy` (20) and before `task-policy` (45);
  * "prompt injection" appears exactly ONCE in the rendered prompt (no overlap
    with task-policy).

Staged in `.agent/plans/tests/` until the implementation lands. Deterministic.

Run: python3 v557_prompt_security.py
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

from longrun.core import server  # noqa: E402
from longrun.model import prompt  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# ---- A: the section is registered in the right slot ------------------------
_sec = next((s for s in prompt.SECTIONS if s.get("id") == "security-policy"), None)
check("A1 SECTIONS has security-policy", _sec is not None)
check("A2 order is 22 (after rules-policy 20, before skills-policy 25)",
      bool(_sec) and _sec.get("order") == 22, repr(_sec))
check("A3 kind is static (cache-safe prefix)", bool(_sec) and _sec.get("kind") == "static")
check("A4 _STATIC_ATTRS points at SECURITY_POLICY",
      prompt._STATIC_ATTRS.get("security-policy") == "SECURITY_POLICY",
      repr({k: v for k, v in prompt._STATIC_ATTRS.items() if k == "security-policy"}))

# ---- B: the text carries the four clauses ---------------------------------
_txt = getattr(server, "SECURITY_POLICY", "") or ""
check("B1 server.SECURITY_POLICY exists", bool(_txt.strip()))
for _marker in ("Prompt injection", "Authority", "Scope", "Finish"):
    check("B2 clause %r present" % _marker, _marker.lower() in _txt.lower())

# ---- C: assembly order + no duplication -----------------------------------
try:
    texts = prompt.section_texts(None, None, None)
    rendered = prompt.render_sections(None, None, None)
except Exception as e:  # noqa: BLE001
    texts, rendered = {}, ""
    print("WARN render_sections failed: %s" % e)

_rules = texts.get("rules-policy") or getattr(server, "RULES_POLICY", "") or ""
_task = texts.get("task-policy") or getattr(server, "TASK_POLICY", "") or ""
_security = texts.get("security-policy") or _txt
check("C1 the security section is non-empty in assembly", bool(str(_security).strip()))
if _rules and _task and _security and rendered:
    i_rules = rendered.find(str(_rules)[:80])
    i_sec = rendered.find(str(_security)[:80])
    i_task = rendered.find(str(_task)[:80])
    check("C2 order rules-policy < security-policy < task-policy",
          -1 < i_rules < i_sec < i_task, "rules=%d sec=%d task=%d" % (i_rules, i_sec, i_task))
else:
    check("C2 order rules-policy < security-policy < task-policy", False, "assembly empty")

check("C3 'prompt injection' appears exactly once in the prompt",
      rendered.lower().count("prompt injection") == 1,
      "count=%d" % rendered.lower().count("prompt injection"))

# ---- D: server exports it like the other static sections -------------------
try:
    with open(os.path.join(REPO, "src", "longrun", "core", "server.py"), encoding="utf-8") as fh:
        _srv = fh.read()
except OSError as e:  # pragma: no cover
    _srv = ""
    print("WARN cannot read server.py: %s" % e)
check("D1 server.py imports SECURITY_POLICY from agent",
      "SECURITY_POLICY" in _srv)

print("\n%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
