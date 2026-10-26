"""v659 — the Matrix extension layer answers the same on every path.

Operator's extension-layer audit (10 probes, 6 defects): "6 difetti nel layer di
estensione vanno corretti prima che sia affidabile al 100%", backlog item by item:

  a) the `augment_recall` hook was REGISTERED but never ran on `memory.recall` —
     the tool called `mem.search` directly, so the one path an agent actually uses
     bypassed `call_hook` while the prompt's memory section did not;
  b) `matrix.scaffold kind=webui` wrote the name the caller typed, and the server
     loads ONLY `src/Matrix/webui/plugins.js` — the plugin was never active;
  c) `skills.search` read `_cache["bodies"]` BEFORE `list_skills()` filled it, so a
     content-only query missed a just-added skill (and the answer depended on the
     cache state, which is why two sessions disagreed);
  d) `matrix.remove kind=skill` tested `isdir` on a FILE path and deleted nothing;
  e) a routine asked for with `disabled:true` came back ENABLED, a routine bound by
     SESSION id vanished from every agent-id comparison, and an unknown/empty patch
     was a silent ok=True.

Deterministic, no model, no network, no server.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v659-")
for name, tail in {
    "LONGRUN_DATA_DIR": "data",
    "LONGRUN_CONFIG_DIR": "cfg",
    "LONGRUN_DB": "events.db",
    "LONGRUN_SESSIONS_DIR": "sessions",
    "LONGRUN_GRAPH_DIR": "graphs",
    "LONGRUN_ROLES_DIR": "roles",
    "LONGRUN_MATRIX_SRC": "matrix_src",
    "LONGRUN_MATRIX_DOT": "matrix_dot",
    "LONGRUN_APPROVALS": "approvals.json",
}.items():
    os.environ[name] = os.path.join(TMP, tail)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import matrix  # noqa: E402
from longrun.tools import matrix_guard  # noqa: E402

TOOLS_SRC = open(os.path.join(REPO, "src", "longrun", "tools", "tools.py"), encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


matrix_guard.ensure_layout(TMP)
_ROOT, MSRC, MDOT = matrix._roots(TMP)

# ---- (a) the recall hook is reached from the TOOL path too -------------------
check("A1 the tool recalls through the governed entry point",
      "mem.recall_governed(query, args.get(\"kind\"), limit, sem_flag," in TOOLS_SRC
      and "mem.search(query, args.get(\"kind\"), limit, sem_flag)" not in TOOLS_SRC)
try:
    from longrun.core import matrix as mtx
    from longrun.memory import memory as mem

    calls = []
    real_hook = mtx.call_hook

    def fake_hook(ns, hook, *a, **kw):
        calls.append((ns, hook))
        return kw.get("default")

    mtx.call_hook = fake_hook
    mem.write("memory.store", "v659 probe sentence about the battery gate")
    tool_hits = mem.recall_governed("battery", limit=5)
    check("A2 a text recall fires augment_recall",
          ("memory", "augment_recall") in calls, calls)
    check("A3 the recall still returns the scored hit",
          any("battery gate" in (r.get("content") or "") for _s, r in tool_hits), tool_hits)
    calls.clear()
    mem.governed_query(limit=5)
    check("A4 the prompt's memory section fires the SAME hook (one caller helper)",
          ("memory", "augment_recall") in calls, calls)
    mtx.call_hook = real_hook
    check("A5 the hook path is one helper, not two copies",
          "def _augment(kind, results, limit):" in open(
              os.path.join(REPO, "src", "longrun", "memory", "memory.py"),
              encoding="utf-8").read())
except Exception as e:  # noqa: BLE001 — a broken import is the failure
    check("A6 the governed recall imports and runs offline", False, repr(e))

# ---- (c) search ranks against the bodies the CURRENT tree produced ----------
try:
    from longrun.memory import skills as sk

    def fake_list():
        sk._cache["bodies"] = {"/x/SKILL.md": "alpha beta gamma instructions"}
        return [{"name": "probe-skill", "category": "created", "title": "",
                 "description": "", "abspath": "/x/SKILL.md"}]

    real_list = sk.list_skills
    sk.list_skills = fake_list
    hits = sk.search_skills("alpha beta")
    sk.list_skills = real_list
    check("C1 a body-only query finds the skill (bodies are read AFTER the list)",
          hits and hits[0]["name"] == "probe-skill", hits)
except Exception as e:  # noqa: BLE001
    check("C2 search_skills imports and runs offline", False, repr(e))

# ---- (b)(d) skill / rule / webui lifecycle answers the same on both sides ----
made_sk = matrix.scaffold("skill", "My Probe Skill", "Probe skill.", repo_root=TMP)
# the sanitiser maps every run of non [A-Za-z0-9_-] to one "-" and keeps the CASE
sk_dir = os.path.join(MDOT, "skills", "My-Probe-Skill")
check("B1 scaffold writes the SANITISED folder",
      made_sk.get("ok") is True and made_sk.get("path") == os.path.join(sk_dir, "SKILL.md"),
      made_sk)
check("B2 the skill file really exists",
      os.path.isfile(os.path.join(sk_dir, "SKILL.md")))
rem_sk = matrix.remove("skill", "My Probe Skill", repo_root=TMP)
check("B3 remove deletes the skill FOLDER (isdir on a file was always False)",
      rem_sk.get("ok") is True and not os.path.exists(sk_dir), rem_sk)

made_ru = matrix.scaffold("rule", "probe-rule", "Probe rule.", repo_root=TMP)
ru_p = os.path.join(MDOT, "rules", "probe-rule.md")
check("B4 scaffold writes the one .md rule file",
      made_ru.get("ok") is True and os.path.isfile(ru_p), made_ru)
rem_ru = matrix.remove("rule", "probe-rule.md", repo_root=TMP)
check("B5 remove takes the rule away (name with or without .md)",
      rem_ru.get("ok") is True and not os.path.exists(ru_p), rem_ru)

plug = os.path.join(MSRC, "webui", "plugins.js")
wrong = matrix.scaffold("webui", "demo", "Probe plugin.", repo_root=TMP)
check("B6 a webui plugin under another name is REFUSED (never loaded anyway)",
      wrong.get("ok") is False and "plugins.js" in str(wrong.get("error")), wrong)
made_w = matrix.scaffold("webui", "plugins.js", "Probe plugin.", repo_root=TMP)
check("B7 the ONE plugin file is created",
      made_w.get("ok") is True and os.path.isfile(plug), made_w)
again = matrix.scaffold("webui", "plugins.js", "Probe plugin.", repo_root=TMP)
check("B8 an existing plugin is never clobbered", again.get("ok") is False, again)
matrix.remove("webui", "plugins.js", repo_root=TMP)
check("B9 the plugin removes cleanly", not os.path.exists(plug))

# ---- (e) routines: one switch, one id-space, no silent no-op ----------------
try:
    from longrun.agent import agents as agents_mod
    from longrun.orchestrate import routines as rr

    agents_mod.REGISTRY.designate("sess-v659", name="Probe Agent")
    aid = (agents_mod.REGISTRY.resolve("sess-v659") or {}).get("id")
    check("E1 the probe agent is designated", bool(aid), aid)

    off = rr.REGISTRY.create("sess-v659", "probe goal", 60, disabled=True)
    check("E2 `disabled:true` is honoured (was ignored -> enabled)",
          off.get("ok") is True and off["routine"]["enabled"] is False, off)
    check("E3 the routine stores the AGENT id, not the session id",
          off["routine"]["agent"] == aid, off["routine"].get("agent"))
    rid = off["routine"]["id"]
    check("E4 get sees it (the id-space every view compares)",
          (rr.REGISTRY.get(rid) or {}).get("id") == rid)
    check("E5 list sees it too", any(r["id"] == rid for r in rr.REGISTRY.list()["routines"]))

    silent = rr.REGISTRY.update(rid)
    check("E6 an empty patch is REFUSED, not a silent ok",
          silent.get("ok") is False and "nothing to update" in str(silent.get("error")), silent)

    up = rr.REGISTRY.update(rid, goal="probe goal v2", disabled=False)
    check("E7 update applies the new goal",
          up.get("ok") is True and (rr.REGISTRY.get(rid) or {}).get("goal") == "probe goal v2", up)
    check("E8 `disabled:false` re-enables it", (rr.REGISTRY.get(rid) or {}).get("enabled") is True)
except Exception as e:  # noqa: BLE001
    check("E9 the routines registry imports and runs offline", False, repr(e))

print("\n---\nv659: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
