#!/usr/bin/env python3
"""v665 — a stale rule file must not outrank the code (I-5).

Coding agents follow a project's instruction file even when it disagrees with the
existing code, because the file arrives as an INSTRUCTION and the code as tool
output (`papers/stalefiles_2610.30571.txt:25-37`). One sentence that gives the
existing code precedence moved code-following from 4.2% to 91.4% and stopped the
agents rewriting working code. Longrun's own rules ARE files (`memory/rules.py`),
so the fix is one clause in `RULES_POLICY`.

Contract locked here:
  * `agent.RULES_POLICY` carries the clause (code wins, name the stale rule, do
    not rewrite working code);
  * it reaches the ASSEMBLED prompt (the section renderer), not just the constant;
  * it does not duplicate the existing user-conflict clause, and stays the single
    source (prompt.d override map + the server export point at it).

Deterministic, no network, no model.
"""
import os
import sys
import tempfile

_tmp = tempfile.mkdtemp(prefix="sf-v665-")
os.environ["LONGRUN_DATA_HOME"] = os.path.join(_tmp, "home")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(_tmp, "data")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(_tmp, "sessions")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_tmp, "config")
for _d in ("LONGRUN_DATA_DIR", "LONGRUN_SESSIONS_DIR", "LONGRUN_CONFIG_DIR"):
    os.makedirs(os.environ[_d], exist_ok=True)

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server  # noqa: E402  (first: agent imports server)
from longrun.agent import agent as AG  # noqa: E402
from longrun.model import prompt  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


TXT = str(getattr(AG, "RULES_POLICY", "") or "")
LOW = TXT.lower()

# ---- A: the clause itself ---------------------------------------------------
check("A1 RULES_POLICY exists and is non-empty", bool(TXT.strip()), len(TXT))
check("A2 it gives the code precedence over a contradicting rule",
      "code wins" in LOW and "contradicts the code" in LOW, TXT[-260:])
check("A3 it asks the model to NAME the stale rule instead of silently obeying it",
      "stale" in LOW and "say which rule" in LOW, TXT[-260:])
check("A4 it forbids rewriting working code to match the rule",
      "do not rewrite working code" in LOW, TXT[-260:])

# ---- B: no duplication of the clauses already there -------------------------
check("B1 the user-conflict clause is still stated exactly once",
      LOW.count("say so before proceeding") == 1, LOW.count("say so before proceeding"))
check("B2 global/project precedence is still stated exactly once",
      LOW.count("project rules override global ones") == 1,
      LOW.count("project rules override global ones"))
check("B3 the new clause appears once (not plastered twice)",
      LOW.count("code wins") == 1, LOW.count("code wins"))
check("B4 it does not add a second 'prompt injection' phrase (v557 owns that)",
      "prompt injection" not in LOW, "")

# ---- C: it reaches the model, through the ONE assembly ----------------------
try:
    texts = prompt.section_texts(None, None, None)
    rendered = prompt.render_sections(None, None, None)
except Exception as e:  # noqa: BLE001
    texts, rendered = {}, ""
    print("WARN render_sections failed: %s" % e)
check("C1 the assembled prompt carries the clause",
      "code wins" in str(rendered).lower(), len(str(rendered)))
check("C2 the section name is still 'rules-policy' in the assembly",
      "code wins" in str(texts.get("rules-policy") or "").lower(),
      sorted(texts.keys())[:12])
check("C3 prompt.d overrides still target this one section (not a copy)",
      prompt._STATIC_ATTRS.get("rules-policy") == "RULES_POLICY",
      prompt._STATIC_ATTRS.get("rules-policy"))
check("C4 the chat loop and the agent loop read the SAME object (no second truth)",
      server.RULES_POLICY is AG.RULES_POLICY, id(server.RULES_POLICY) == id(AG.RULES_POLICY))

# ---- D: both loops inject it ------------------------------------------------
for _f, _label in ((os.path.join("src", "longrun", "agent", "agent.py"), "chat loop"),
                   (os.path.join("src", "longrun", "core", "api_v02.py"), "agent v2 loop")):
    with open(os.path.join(REPO, _f), encoding="utf-8") as fh:
        _src = fh.read()
    check("D %s injects RULES_POLICY into its system prompt" % _label,
          "RULES_POLICY" in _src, _f)

print("---")
okc = sum(results)
print("v665: %d/%d PASS" % (okc, len(results)))
sys.exit(0 if okc == len(results) else 1)
