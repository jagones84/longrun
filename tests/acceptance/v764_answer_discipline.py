#!/usr/bin/env python3
"""v764 — the ANSWER is a value, and a REJECTION is a contract (2026-11-01).

Three defects found by reading the GAIA transcripts of the sandbox arms, all of them
in the harness rather than in the model:

  T  `strip_think` matched the LITERAL `<think>` only, so the routed model's real
     markup (`<think signature="reasoning-details://…">`) reached the answer
     surface and the graded answer became the whole thinking block.
  R  an invalid action was rejected with no tool name and no schema, so the model
     guessed `{"action":"web"}`, `{"action":"http"}`, `{"action":"browser"}` in a
     row instead of reading the registry.
  N  a failed tool told the model to "say plainly in your answer WHAT failed",
     which turned a finished answer (`17`) into `17 Note: all network lookups…`.
  E  a factual question could be closed with ZERO tool calls: `5d0080cb` was
     answered from memory (`2.4`, golden `0.1777`) while the same question, when
     the model chose to look, was solved by web.search → web.fetch.
  S  the keyless search engine every sandboxed arm depends on returned nothing.

Deterministic: no live model, no network, no server.
Run: python3 tests/acceptance/v764_answer_discipline.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v764-")
os.environ.setdefault("LONGRUN_DATA_DIR", os.path.join(TMP, "data"))
os.environ.setdefault("LONGRUN_CONFIG_DIR", os.path.join(TMP, "cfg"))
os.environ.setdefault("LONGRUN_DB", os.path.join(TMP, "events.db"))
os.environ.setdefault("LONGRUN_SESSIONS_DIR", os.path.join(TMP, "sessions"))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.util.textkit import strip_think                       # noqa: E402
# `agent` imports `core.server` at module scope, and `core.server` imports names
# BACK from `agent`: importing the agent first is a circular import. Load the
# server first, the way every other acceptance test does.
from longrun.core import server as _server                        # noqa: E402,F401
from longrun.agent import agent as A                               # noqa: E402
from longrun.model import rllm as R                                # noqa: E402
from longrun.tools import registry                                 # noqa: E402

registry._external_tools = lambda: {}

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# --------------------- T. reasoning markup, whatever the model calls it ----
clean, think = strip_think('4')
check("T1 plain text is untouched", clean == "4" and think is None, (clean, think))

_signed = ('<think signature="reasoning-details://[{&quot;type&quot;: '
           '&quot;reasoning.text&quot;}]">\nThe answer must be just the number.\n</think>'
           '\n\n3')
clean, think = strip_think(_signed)
check("T2 a SIGNED think block is stripped and kept as reasoning",
      clean.strip() == "3" and "just the number" in (think or ""), (clean, think))

clean, _ = strip_think("a <THINKING>hmm</THINKING> b")
check("T3 case and the `thinking` spelling are stripped", clean.strip() == "a  b", clean)

clean, think = strip_think("<think>one</think>X<think>two</think>")
check("T4 every block is stripped, not just the first",
      clean == "X" and "one" in (think or "") and "two" in (think or ""), (clean, think))

clean, _ = strip_think("<think signature='x'>unclosed body 7")
check("T5 an unclosed tag is dropped but its body survives (never lose the answer)",
      "<think" not in clean and "7" in clean, clean)

clean, _ = strip_think('<reasoning>r</reasoning> 42')
check("T6 the `reasoning` spelling is stripped", clean.strip() == "42", clean)

# ------------------- R. a rejection names the way out (no blind guessing) ----
note = A._invalid_action_note({"action": "web"})
check("R1 a bad action names the tools it probably meant",
      "web.search" in note or "web.fetch" in note, note[:200])
check("R2 the rejection points at the QUERY and the SCHEMA lookup",
      'self.tools {query:' in note and 'self.tools {tool:' in note, note[-220:])
check("R3 it still states the three valid shapes",
      '"action":"tool"' in note and "todo.write" in note and "plain prose" in note)
check("R4 it echoes what the model emitted",
      '"action": "web"' in note or '"action":"web"' in note, note[:120])
_bare = A._invalid_action_note(None, "I will now do it")
check("R5 a non-dict rejection never raises and still teaches",
      "That was not a valid action" in _bare and "self.tools" in _bare, _bare[:120])
_miss = A._tool_near_misses("fs.raed")
check("R6 a MISSPELLED tool name resolves to its real neighbours",
      any(n.startswith("fs.") for n in _miss), _miss)
# Live 2026-11-02: `{"action":"tool","shell":"x"}` — the tool NAME was used as a KEY.
_toolkey = A._invalid_action_note({"action": "tool", "shell": "x"})
check("R7 a tool action with no name says WHERE the name and the args go",
      '"action":"tool" names no tool' in _toolkey and '"args"' in _toolkey
      and "neither the tool name nor an argument" in _toolkey, _toolkey[:240])
check("R8 a well-formed tool action does not get that lecture",
      'names no tool' not in A._invalid_action_note(
          {"action": "tool", "tool": "shell.exec", "args": {"command": "ls"}}))

# ------------------ N. the final answer never carries the diagnostics ----
_src = open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"), encoding="utf-8").read()
check("N1 the failed-tool note no longer invites a failure report in the answer",
      "say plainly in your answer" not in _src)
check("N2 it says where the disclosure belongs and that the answer stays the answer",
      "record WHAT failed" in _src and "never a failure report appended" in _src)

# --------------------- the prompt carries no member catalogue --------------
from longrun.core import api_v02  # noqa: E402

_tctx = api_v02.tool_context()
check("P1 the prompt maps namespaces with counts and no `ns{a,b}` member list",
      "fs(" in _tctx and "fs{" not in _tctx, len(_tctx))
check("P2 the prompt teaches list / search / schema, in that order",
      "self.tools {}" in _tctx and 'self.tools {query:' in _tctx
      and 'self.tools {tool:' in _tctx)
# A value wrapped in a sentence is not the value (2026-11-01: "…are: X (2005),
# Y (2009) and Z (2009)." to a "how many" question — right reasoning, unusable
# answer). The rule lives in the system prompt because the shape of the answer
# belongs to the request.
check("P3 the system prompt fixes the answer SHAPE for a fact question",
      "the answer IS the value" in A.SYSTEM_PROMPT
      and "Explain only when an explanation was asked for" in A.SYSTEM_PROMPT)
# Measured 2026-11-01 (`e1fc63a2`, BOTH arms): "how many thousand hours" → 17000
# instead of 17. The scale is part of the request, so it is stated with the shape.
check("P4 the prompt states the unit and SCALE of the answer",
      "how many thousand hours" in A.SYSTEM_PROMPT
      and "wants 17, not 17000" in A.SYSTEM_PROMPT)

# -------- X. the harness acts on the action the model MEANT, not a quotation ----
# Measured 2026-11-01 on GAIA `5d0080cb`: the model's message quoted the action it had
# been accused of ("… not {"tool":"todo.update"} …") and put the REAL action last;
# `extract_json` returned the quotation, so the harness rejected the correct call four
# times in a row and the plan never closed.
from longrun.util.textkit import extract_json, extract_action_json   # noqa: E402

_quoted = ('Strange, I emitted {"tool":"todo.update"} before; now the real one:\n'
           '{"action":"todo.update","steps":[{"id":"n1","status":"done"}]}')
_a = extract_action_json(_quoted)
check("X1 the LAST action-shaped object wins over a quoted one",
      isinstance(_a, dict) and _a.get("action") == "todo.update"
      and _a.get("steps"), _a)
check("X2 extract_json still returns the FIRST object (the two are not the same job)",
      (extract_json(_quoted) or {}).get("tool") == "todo.update")

_act = A._normalize_action({"tool": "todo.update", "args": {"steps": [{"id": "n1"}]}})
check("X3 a harness action inside the tool envelope is coerced, not rejected",
      _act.get("action") == "todo.update" and _act.get("steps"), _act)

_batch_note = A._batch_note if hasattr(A, "_batch_note") else None
_src_batch = open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"),
                  encoding="utf-8").read()
check("X4 a batch item that is a harness action says which rule it broke",
      "TOP-LEVEL harness action, not a tool" in _src_batch)

# ---- Y/Z. a turn never hands back nothing or an envelope, and discovery is small ----
check("Y1 the reply is sanitised when the turn stops on an action or on nothing",
      "The turn ended before a final answer" in _src
      and "The turn ended without producing an answer." in _src)
_oc = open(os.path.join(REPO, "benchmarks", "inspect_sandbox", "openclaw_turn.sh"),
           encoding="utf-8").read()
check("Y2 the openclaw turn carries an explicit timeout budget",
      '"timeoutSeconds": _budget' in _oc and '"timeoutSeconds": _budget, "model"' in _oc)

from longrun.tools import diag                                        # noqa: E402

_big = diag.tools_report(query="web search fetch page read write run file")
check("Z1 a broad query is CAPPED (a 27 kB discovery answer is not a search)",
      len(_big.get("tools") or {}) <= diag.TOOL_QUERY_LIMIT and _big.get("capped"),
      len(_big.get("tools") or {}))
check("Z2 every listed description is trimmed to one line",
      all(len(v.get("description") or "") <= diag.TOOL_DESC_CHARS + 1
          for v in (_big.get("tools") or {}).values()))

# ---- E. a fact is never closed on a guess (premature-answer guard) ----
# Measured 2026-11-01 on GAIA: `5d0080cb` was answered in 2 turns from memory
# (wrong), while the SAME question, when the model chose to look, was solved by
# `web.search` → `web.fetch`. The capability existed; the trigger did not.
check("E1 a factual question needs evidence",
      A._needs_evidence("What year was the first transistor invented?"))
check("E2 an imperative does not (the harness can see the work already)",
      not A._needs_evidence("fix the typo in the README"))
check("E3 a bare greeting does not",
      not A._needs_evidence("ciao"))
check("E4 a 'how many' request does",
      A._needs_evidence("how many rows does the CSV have"))
_ev = A._evidence_gate_text()
check("E5 the gate names BOTH ways out, forbids a guess, and asks for no narration",
      "web.search" in _ev and "cannot be checked" in _ev
      and "never a sentence about where it came from" in _ev
      and "say so in ONE line" not in _ev, _ev[:160])
check("E6 the gate is a MECHANICAL check wired on all three close paths",
      _src.count("_needs_evidence(message)") == 3
      and "_evidence_used = False" in _src, _src.count("_needs_evidence(message)"))
# Measured 2026-11-01 (GAIA `ec09fa32`): ONE turn, 33k tokens, an EMPTY reply — the
# model spent the whole message on its reasoning block and the harness persisted the
# empty string as the answer. An empty message is never an answer.
check("E7 an empty model message is retried (bounded), never accepted",
      "Your last message was EMPTY" in _src and "_empty_streak <= 2" in _src)
# Measured 2026-11-01 (GAIA `8e867cd7`): the tool call was written INSIDE the signed
# reasoning block and the visible part was a promise, so the harness dropped the action,
# saw "nothing open" and closed the turn mid-work.
_hidden = ('<think signature="reasoning-details://[]">\n'
           '{"action":"tool","tool":"shell.exec","args":{"command":"curl -s x"}}\n'
           '</think>\nThe wikitext is truncated. Let me curl it directly.')
_c2, _t2 = strip_think(_hidden)
check("E8 an action hidden in the reasoning block is DETECTED",
      A._reasoning_only_action(_c2, _t2), (_c2[:60], (_t2 or "")[:60]))
check("E9 a normal action in the message is not flagged",
      not A._reasoning_only_action('{"action":"tool","tool":"fs.read","args":{}}',
                                   "just thinking"))
# Measured 2026-11-01 (`46719c30`, `ec09fa32`): the turn budget was 600 s but each model
# call was capped at 300 s, the loop re-raised, and the arm answered nothing at all.
check("E10 a model-call TIMEOUT is retried once, never fatal",
      "_timeout_retried = False" in _src and 'on_event("model.timeout"' in _src
      and "_is_timeout_err(_e)" in _src)
os.environ["LONGRUN_MODEL_CALL_TIMEOUT"] = "600"
check("E11 the per-call model timeout follows the caller's budget",
      A._model_call_timeout() == 600)
os.environ.pop("LONGRUN_MODEL_CALL_TIMEOUT", None)
check("E12 the default per-call timeout is 300 s",
      A._model_call_timeout() == 300)

# ---- E13/E14. a turn may not close on a PLAN or on a bare reasoning block ----
# Measured 2026-11-01 on GAIA `46719c30` (11 turns): the final message ended
# "…I need to determine which had prior papers and find their first paper" — a status
# update, graded as the answer, while the plan was already closed.
check("E13 a reply that is still describing the next step is not an answer",
      A._narrates_intent("Authors are Pietro Murano and Iram N. Khan. I need to "
                         "determine which had prior papers and find their first paper."
                         " Murano has an extensive publication record; let me grep it.")
      and A._narrates_intent("Let me search the journal index next.")
      and not A._narrates_intent("The Castle")
      and not A._narrates_intent("The word is fluffy, from the 1968 and 1974 reviews.")
      and not A._narrates_intent("17000"))
# Measured 2026-11-01 on GAIA `72e110e7`: the reply was ONLY a `<think …>` block
# carrying `{"action":"tool","tool":"web.search",…}`. `strip_think` left the ACTION,
# it was printed as the answer, and the scorer graded a JSON envelope.
_THINK_ONLY = ('<think signature="reasoning-details://x">{"action":"tool",'
               '"tool":"web.search","args":{"query":"x"}}</think>')
check("E14 a reply with no VISIBLE part after the reasoning strip is not an answer",
      A._visible_reply(_THINK_ONLY) == ""
      and A._visible_reply(_THINK_ONLY + "fluffy") == "fluffy"
      and A._visible_reply("17") == "17")

# ---- E15/E16/E17. the reasoning parameter has a DIALECT per provider ----
# Measured 2026-11-01 (`.agent/docs/research/2026-11-01_reasoning-effort.md`): a single
# shape for every provider is the defect. On `z-ai/glm-5.3-flash` a flat
# `reasoning_effort: high` bought 107 mean reasoning tokens against 1419 for the provider
# default — the "level" was CAPPING the thinking. On a local llama.cpp model the flat
# field is dropped entirely (its template only reads `chat_template_kwargs`, where
# `reasoning_effort: "none"` is the one value with a measurable effect). Vendor docs, read
# the same day: z.ai `thinking:{type}` + `reasoning_effort: max|high|low` (default `max`),
# OpenRouter `reasoning:{effort|max_tokens}` (never both), Qwen `enable_thinking` +
# `thinking_budget`, DeepSeek `thinking:{type}` + `reasoning_effort`.
_po = R._provider_of
R._provider_of = lambda m: {"id": "openrouter", "kind": "openrouter"}
check("E15 the dialect follows the PROVIDER first (one model, two APIs)",
      R._reasoning_format({}, "z-ai/glm-5.3-flash") == "openrouter")
R._provider_of = lambda m: {"id": "dgx", "kind": "llamacpp", "local": True}
check("E15b a local llamacpp provider gets the llamacpp dialect",
      R._reasoning_format({}, "nex-n25-mini-uncensored-q8") == "llamacpp")
R._provider_of = lambda m: {"id": "deepseek", "kind": "deepseek"}
check("E15c a direct vendor endpoint keeps its own dialect",
      R._reasoning_format({}, "deepseek-v4-pro") == "deepseek")
R._provider_of = lambda m: {"id": "anthropic", "kind": "anthropic"}
check("E15e Anthropic's compat layer takes a THINKING block (it IGNORES "
      "`reasoning_effort` — documented, read 2026-11-01)",
      R._reasoning_format({}, "claude-sonnet-5") == "anthropic")
R._provider_of = lambda m: {"id": "vllm", "kind": "openai", "local": True}
check("E15f a LOCAL openai-compatible server (vLLM) gets the template dialect, "
      "a CLOUD one keeps the flat field",
      R._reasoning_format({}, "deepseek-v4-flash-0731-exl3-k2") == "qwen-chat-template")
R._provider_of = lambda m: {"id": "openai", "kind": "openai"}
check("E15g a cloud openai-compatible endpoint keeps the flat field",
      R._reasoning_format({}, "gpt-5.6-sol") == "openai")
R._provider_of = _po
check("E15d with no provider the MODEL family decides, and an explicit format wins",
      R._reasoning_format({}, "glm-4.6") == "zai"
      and R._reasoning_format({}, "deepseek/deepseek-r1") == "deepseek"
      and R._reasoning_format({}, "qwen/qwen3.7-max") == "qwen"
      and R._reasoning_format({}, "anthropic/claude-4") == "openai"
      and R._reasoning_format({"format": "openrouter"}, "glm-4.6") == "openrouter")
_LV = R._LEVEL_BUDGET                                                        # noqa: E305
check("E16 a level is a FLOOR, not a cap: `high` asks for most of the budget",
      _LV["high"] == 24000 and _LV["xhigh"] == 32000 and _LV["minimal"] == 1024)
_F = R._reasoning_fields                                                    # noqa: E305
check("E17 each dialect sends ITS OWN field and never a foreign one",
      _F("x", {"enabled": True, "effort": "high", "format": "openai"}) ==
      {"reasoning_effort": "high"}
      and _F("x", {"enabled": True, "effort": "xhigh", "format": "openai"}) ==
      {"reasoning_effort": "high"}
      and _F("x", {"enabled": True, "effort": "none", "format": "openai"}) ==
      {"reasoning_effort": "none"}
      and _F("x", {"enabled": True, "effort": "high", "format": "superpowers"}) ==
      {"reasoning_effort": "high"})
check("E17b z.ai `high` becomes its documented MAX (default is already max)",
      _F("glm-5.3", {"enabled": True, "effort": "high", "format": "zai"}) ==
      {"thinking": {"type": "enabled"}, "reasoning_effort": "max"}
      and _F("glm-5.3", {"enabled": True, "effort": "none", "format": "zai"}) ==
      {"thinking": {"type": "disabled"}})
check("E17c OpenRouter gets a NUMBER and never effort+max_tokens together",
      _F("x", {"enabled": True, "effort": "high", "format": "openrouter"},
         max_tokens=64000) == {"reasoning": {"max_tokens": 24000}}
      and _F("x", {"enabled": True, "effort": "high", "format": "openrouter"},
             max_tokens=8000) == {"reasoning": {"max_tokens": 6976}}
      and _F("x", {"enabled": True, "effort": "high", "format": "openrouter"},
             max_tokens=1500) == {"reasoning": {"effort": "high"}}
      and _F("x", {"enabled": True, "effort": "none", "format": "openrouter"}) ==
      {"reasoning": {"enabled": False}})
check("E17f a GLM through OpenRouter asks for `max` — the only shape measured to RAISE "
      "it — and never for a disable it would reject",
      _F("z-ai/glm-5.3-flash", {"enabled": True, "effort": "high",
                                "format": "openrouter"}) == {"reasoning": {"effort": "max"}}
      and _F("z-ai/glm-5.3-flash", {"enabled": True, "effort": "low",
                                    "format": "openrouter"}) == {"reasoning": {"effort": "low"}}
      and _F("z-ai/glm-5.3-flash", {"enabled": True, "effort": "none",
                                    "format": "openrouter"}) == {})
check("E17d qwen carries a budget, llama.cpp carries the template kwargs",
      _F("qwen3.8-max", {"enabled": True, "effort": "low", "format": "qwen"},
          max_tokens=64000) == {"enable_thinking": True, "thinking_budget": 4096}
      and _F("qwen3.8-max", {"enabled": True, "effort": "none", "format": "qwen"}) ==
      {"enable_thinking": False}
      and _F("nex-n25", {"enabled": True, "effort": "high", "format": "llamacpp"}) ==
      {"chat_template_kwargs": {"enable_thinking": True, "reasoning_effort": "high"}}
      and _F("nex-n25", {"enabled": True, "effort": "none", "format": "llamacpp"}) ==
      {"chat_template_kwargs": {"enable_thinking": False, "reasoning_effort": "none"}})
check("E17e OFF sends nothing; enabled-without-a-level sends nothing either",
      _F("x", {"enabled": False, "effort": "high", "format": "openai"}) == {}
      and _F("x", {"enabled": True, "effort": "", "format": "openai"}) == {}
      and _F("x", {}) == {})
check("E17g anthropic carries a thinking block with a budget that fits max_tokens",
      _F("claude", {"enabled": True, "effort": "high", "format": "anthropic"},
         max_tokens=64000) == {"thinking": {"type": "enabled", "budget_tokens": 24000}}
      and _F("claude", {"enabled": True, "effort": "high", "format": "anthropic"},
             max_tokens=1500) == {"thinking": {"type": "enabled", "budget_tokens": 1024}}
      and _F("claude", {"enabled": True, "effort": "none", "format": "anthropic"}) ==
      {"thinking": {"type": "disabled"}})
# E18 is the MATRIX: it walks the REAL config/providers.yaml, so a provider added to the
# repo cannot silently land on a dialect its API ignores. The three known no-op shapes are
# named: a flat `reasoning_effort` on llama.cpp / vLLM / the Anthropic compat layer.
from longrun.model import providers as _P                                        # noqa: E402
_matrix, _noop = [], []
for _p in _P.providers():
    if _p.get("embed_only") or not (_p.get("models") or []):
        continue
    _ref = "%s:%s" % (_p.get("id"), _p["models"][0].get("id"))
    _kind = str(_p.get("kind") or "").strip().lower()
    _fmt = R._reasoning_format({}, _ref)
    _hi = R._reasoning_fields(_ref, {"enabled": True, "effort": "high"}, max_tokens=64000)
    _off = R._reasoning_fields(_ref, {"enabled": True, "effort": "none"}, max_tokens=64000)
    _matrix.append("%s(%s)->%s %s|%s" % (_p.get("id"), _kind, _fmt,
                                         json.dumps(_hi, sort_keys=True)[:60],
                                         json.dumps(_off, sort_keys=True)[:40]))
    _local_openai = _p.get("local") and _kind in ("openai", "gemini", "google")
    if (_kind in ("llamacpp", "llama.cpp", "anthropic") or _local_openai) \
            and "reasoning_effort" in _hi:
        _noop.append("%s:%s" % (_p.get("id"), _fmt))
check("E18 every provider in the REAL config gets a field its API actually reads",
      bool(_matrix) and not _noop, _noop or _matrix)

# ---- E19: every thinking LIMIT is a config value (RH-15) ---------------------
# Operator: *"mica ci sono limiti di pensiero? … se proprio devono esserci siano alti e
# non hardcoded messi in un config file"*. The level table and the clamp live in
# `config/tools.yaml` → `reasoning:`; the dict in rllm.py is only the fallback for a
# caller that passes a bare {enabled, effort, format}, and the envelope was silently
# clipping `high` (24000 asked, 15360 sent, with max_tokens 16384).
_rc = (registry.load_config(reload=True).get("reasoning") or {})
check("E19 config/tools.yaml owns the thinking limits (none of them is a constant)",
      isinstance(_rc.get("budgets"), dict) and _rc["budgets"].get("high") == 24000
      and _rc["budgets"].get("xhigh") == 32000
      and _rc.get("max_tokens") == 32768
      and _rc.get("budget_ceiling") == 32000
      and _rc.get("budget_floor") == 1024
      and _rc.get("budget_reserve") == 1024,
      json.dumps(_rc, sort_keys=True)[:200])
check("E19b the level table and the clamp are READ from the config",
      R._level_budget({"budgets": {"high": 99999, "minimal": 7}}, "high") == 99999
      and R._level_budget({"budgets": {"minimal": 7}}, "high") == 24000   # code fallback
      and R._level_budget(None, "xhigh") == 32000
      and R._fit_budget(99999, 64000, floor=2048, ceiling=40000, reserve=4096) == 40000
      and R._fit_budget(99999, 8000, floor=2048, ceiling=40000, reserve=4096) == 3904
      and R._fit_budget(99999, 5000, floor=2048, ceiling=40000, reserve=4096) == 0
      # the envelope itself comes from `reasoning.max_tokens`
      and R._max_tokens() == 32768)

# ---- S. a keyless search must return real, followable URLs ----
# Measured 2026-11-01: DuckDuckGo's html and lite endpoints answer every query with
# a 14 kB bot page, and the GAIA sandbox has no Tavily/Brave key — so the only path
# `web.search` had there returned nothing at all.
from longrun.tools import tools as T                                    # noqa: E402

_BING_FEED = (
    '<?xml version="1.0" encoding="utf-8" ?><rss version="2.0"><channel>'
    '<title>Bing: Ada Lovelace</title>'
    '<link>http://www.bing.com:80/search?q=Ada+Lovelace</link>'
    '<item><title>Ada Lovelace - Wikipedia</title>'
    '<link>https://en.wikipedia.org/wiki/Ada_Lovelace</link>'
    '<description>Augusta Ada King, Countess of Lovelace, was an English '
    'mathematician.</description></item>'
    '<item><title>not a result</title><link>/relative/path</link></item>'
    '</channel></rss>')
_hits = T._parse_bing_rss(_BING_FEED, 5)
check("S1 the RSS parser yields a title + a real url + a snippet",
      len(_hits) == 1 and _hits[0]["url"] == "https://en.wikipedia.org/wiki/Ada_Lovelace"
      and "mathematician" in _hits[0]["snippet"], _hits)
_src_tools = open(os.path.join(REPO, "src", "longrun", "tools", "tools.py"),
                  encoding="utf-8").read()
check("S2 bing is the LAST resort of the chain, whatever the config order",
      'order.append("bing")' in _src_tools
      and '"bing": (_search_bing, "bing")' in _src_tools)

print("---")
okc = sum(results)
print("\nv764: %d/%d PASS" % (okc, len(results)))
sys.exit(0 if okc == len(results) else 1)
