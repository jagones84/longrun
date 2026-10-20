#!/usr/bin/env python3
"""v240 — UI/CLI consistency fixes (JAG-240..244).

JAG-240  WebUI: the reloaded/finished turn put the chain-of-thought BELOW its
         answer (`loadHistory` appended it to the message), while the live stream
         puts it ABOVE (ensureThink insertBefore) — the "final thought after the
         message". Now it renders as its own block BEFORE the answer.
JAG-241  CLI: `forge models ls` read `out["models"]` from `/api/models`, which
         returns {providers, router_models} — there is no top-level "models" key,
         so it printed NOTHING. Now it lists the router roster + providers.
JAG-242  `context_display` returned ITALIAN user-facing strings ("nessuna
         sessione", "usati … token", "sopra soglia") shown verbatim in the WebUI,
         the Android app and the CLI — violates the English-only rule.
JAG-243  CLI: `chat --stream` wrote the literal "[90m…think[0m" (ANSI code missing
         the ESC byte).
JAG-244  CLI: `plan show/toggle/set` couldn't target a session (`--session`), so
         they always hit the empty default (the plan is per-session).

Deterministic, no live server. Run:  python3 tests/v240_ui_cli.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="sf-240-")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(_tmp, "sessions")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_tmp, "cfg")
os.makedirs(os.environ["LONGRUN_SESSIONS_DIR"], exist_ok=True)
os.makedirs(os.environ["LONGRUN_CONFIG_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))
from longrun.core import server  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


ui = read("webui", "index.html")
fv = read("src", "longrun", "core/forge.py")
sv = read("src", "longrun", "core/server.py")

# ---- JAG-240: history render inserts the CoT BEFORE the answer -------------
check("JAG-240 loadHistory inserts the CoT before the answer",
      "if (d.parentNode) d.parentNode.insertBefore(t, d);" in ui)
check("JAG-240 the CoT is no longer appended below the answer in loadHistory",
      'd.appendChild(det)' not in ui)

# ---- JAG-255 -> JAG-274: history render never nests under a stale card --------
# Two turns sharing one plan node used to nest the 2nd answer inside the 1st
# turn's card (ABOVE the question it answered). JAG-274 replaced the drawnIdx
# heuristic with the open-at-bottom rule: a node's section is MOVED back to the
# bottom and REUSED (a second copy used to duplicate the whole todo tree).
check("JAG-274 _openSection reuses the node's section instead of duplicating it",
      'last.isConnected && last.parentNode === lg' in ui
      and "if (last.nextElementSibling) lg.appendChild(last);" in ui)
check("JAG-274 a fresh section opens only when the node has none yet",
      'const det = _mkSection(_nodeById(nid)' in ui)
check("JAG-274 loadHistory drives placement through the node id",
      "_activeNodeId = _nid(m.node); _activeScope = null;" in ui)
check("JAG-274 tool cards/injects set the node then reset",
      "_activeNodeId = _nid(v.node); _activeScope = null;" in ui)
check("JAG-255 the brittle nest-scope helper is gone", "nestScope" not in ui)

# ---- JAG-241: models ls reads the right keys -------------------------------
check("JAG-241 cmd_models reads router_models", 'out.get("router_models")' in fv)
check("JAG-241 cmd_models reads providers", 'out.get("providers")' in fv)

# ---- JAG-242: context_display is English -----------------------------------
IT = ("nessuna", "sessione", "usati", "sopra soglia", "contesto n/d",
      "auto-compact al")
d_na = server.context_display(available=False)
d_norm = server.context_display(1000, 10000, 5)
d_near = server.context_display(8000, 10000, 5)
d_over = server.context_display(12000, 10000, 5)
blob = repr(d_na) + repr(d_norm) + repr(d_near) + repr(d_over)
check("JAG-242 no Italian left in context_display output",
      not any(w in blob for w in IT), blob[:120])
check("JAG-242 unavailable reason is English",
      d_na.get("reason") == "no session" and d_na.get("detail") == "context n/d",
      "%r / %r" % (d_na.get("reason"), d_na.get("detail")))
check("JAG-242 normal detail is English",
      d_norm.get("detail", "").startswith("used "), d_norm.get("detail"))
check("JAG-242 near state says auto-compact at",
      "auto-compact at" in d_near.get("detail", ""), d_near.get("detail"))
check("JAG-242 over state says over threshold",
      "over threshold" in d_over.get("detail", ""), d_over.get("detail"))

# ---- JAG-243: chat --stream ANSI has the ESC byte --------------------------
check("JAG-243 stream uses \\x1b[90m", "\\x1b[90m" in fv)
check("JAG-243 the literal [90m write is gone", 'sys.stdout.write("[90m' not in fv)

# ---- JAG-244: `plan` accepts --session -------------------------------------
check("JAG-244 plan subcommand exposes --session",
      'add_parser("plan")' in fv and 'p.add_argument("--session")' in fv)
check("JAG-244 cmd_plan forwards the session to /api/plan",
      '"/api/plan" + ("?session="' in fv)

# ---- JAG-246: CLI URL-encodes query values + req() never tracebacks --------
check("JAG-246 forge has a _q() url-encoder",
      "def _q(value):" in fv and "urllib.parse.quote" in fv)
check("JAG-246 memory search encodes the query", "(_q(query), args.limit)" in fv)
check("JAG-246 blackboard search encodes the query",
      "(_q(args.value), args.limit)" in fv)
check("JAG-246 req() returns an error dict on any client-side failure",
      "request failed:" in fv)
# no raw, unencoded user text left in a query string
check("JAG-246 no raw '&topic=' without _q", '"&topic=" + args.topic' not in fv)
check("JAG-246 no raw '?id=' without _q", '"?id=" + args.value' not in fv)

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)

