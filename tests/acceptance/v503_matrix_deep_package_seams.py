#!/usr/bin/env python3
"""v501 — Deep Matrix subpackage seams: universal fail-open hook engine across all Nucleus subpackages + .Matrix/docs checkpointing."""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(REPO, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

checks = []


def check(name, passed):
    checks.append(bool(passed))
    print(("PASS " if passed else "FAIL ") + name)


with tempfile.TemporaryDirectory() as tmp:
    os.environ["LONGRUN_MATRIX_SRC"] = os.path.join(tmp, "src", "Matrix")
    os.environ["LONGRUN_MATRIX_DOT"] = os.path.join(tmp, ".Matrix")
    os.environ["LONGRUN_DATA_DIR"] = os.path.join(tmp, "data")
    try:
        from longrun.core import events, matrix
        from longrun.memory import memory
        from longrun.model import routing
        from longrun.plan import keepgoing, prm
        from longrun.tools import matrix_guard

        matrix_guard.ensure_layout(tmp)
        all_13 = ("agent", "core", "integrations", "interop", "memory", "model",
                  "orbit", "orchestrate", "plan", "research", "tools", "util", "webui")
        check("A ensure_layout creates all 13 mirrored subpackages (zero missing counterparts)",
              all(os.path.isdir(os.path.join(tmp, "src", "Matrix", sub)) for sub in all_13))

        # Test .Matrix/docs checkpointing
        handoff_p = os.path.join(tmp, ".Matrix", "docs", "HANDOFF.md")
        with open(handoff_p, "w", encoding="utf-8") as f:
            f.write("# Handoff v1\n")
        matrix.checkpoint_save(1, label="with_docs", repo_root=tmp)
        with open(handoff_p, "w", encoding="utf-8") as f:
            f.write("# Corrupted handoff\n")
        matrix.checkpoint_rollback(1, repo_root=tmp)
        with open(handoff_p, encoding="utf-8") as f:
            restored_handoff = f.read()
        check("B checkpoint_save and checkpoint_rollback preserve and restore .Matrix/docs/HANDOFF.md",
              restored_handoff == "# Handoff v1\n")

        # Write real hooks into model, plan, memory, core, agent, orbit, research, interop, integrations, orchestrate, util
        with open(os.path.join(tmp, "src", "Matrix", "model", "hooks.py"), "w", encoding="utf-8") as f:
            f.write(
                "def pick_model(role, default_model):\n"
                "    return 'matrix-model-for-' + str(role)\n"
            )
        with open(os.path.join(tmp, "src", "Matrix", "plan", "hooks.py"), "w", encoding="utf-8") as f:
            f.write(
                "def score_candidate(text, base_score):\n"
                "    return round(min(1.0, float(base_score) + (0.35 if 'MATRIX_BOOST' in str(text) else 0.0)), 3)\n"
                "def decide_keepgoing(decision, open_nodes, rounds):\n"
                "    if open_nodes == 99:\n"
                "        return {'continue': True, 'reason': 'matrix_override'}\n"
                "    return decision\n"
            )
        with open(os.path.join(tmp, "src", "Matrix", "memory", "hooks.py"), "w", encoding="utf-8") as f:
            f.write(
                "def augment_recall(kind, results, limit):\n"
                "    return [{'content': 'matrix_injected_memory', 'kind': kind or 'agent.note'}] + list(results)\n"
            )
        with open(os.path.join(tmp, "src", "Matrix", "core", "hooks.py"), "w", encoding="utf-8") as f:
            f.write(
                "EVENTS_SEEN = []\n"
                "def on_event(ev):\n"
                "    EVENTS_SEEN.append(ev.get('kind'))\n"
                "def handle_http(method, sub_path, qs, body):\n"
                "    return {'status': 200, 'body': {'ok': True, 'ext_path': sub_path, 'method': method}}\n"
            )
        for sub, fn_def in (
            ("agent", "def transform_turn(sess, msgs, msg): return msgs\n"),
            ("orbit", "def augment_orbit(payload): return {**payload, 'matrix_orbit': True}\n"),
            ("research", "def augment_research(q, out): return {**out, 'matrix_research': True}\n"),
            ("interop", "def extra_mcp_tools(): return [{'name': 'matrix_mcp_probe'}]\n"),
            ("integrations", "def transform_bridge_payload(p): return p\n"),
            ("orchestrate", "def on_job_change(j, ev): return True\n"),
            ("util", "def on_ledger_add(entry): return True\n"),
        ):
            with open(os.path.join(tmp, "src", "Matrix", sub, "hooks.py"), "w", encoding="utf-8") as f:
                f.write(fn_def)

        hl = matrix.hotload(tmp)
        expected_subs = ("model", "plan", "memory", "core", "agent", "orbit",
                         "research", "interop", "integrations", "orchestrate", "util")
        check("C discover_hooks & hotload detect active subpackage hooks across all 11 Python subpackages",
              all(k in (hl.get("active_hooks") or {}) for k in expected_subs))

        picked = routing.pick("coder")
        ranked = prm.rank_text("hello MATRIX_BOOST world")
        base_ranked = prm.rank_text("hello world")
        kg = keepgoing.decide(open_nodes=99, rounds=100, stale=100, started=0)
        recalled = memory.governed_query(kind="agent.note", limit=5)
        check("D Nucleus model/routing, plan/prm, plan/keepgoing, and memory/governed_query execute Matrix hooks live",
              picked == "matrix-model-for-coder"
              and isinstance(ranked, float) and ranked > base_ranked
              and kg.get("continue") is True and kg.get("reason") == "matrix_override"
              and any(r.get("content") == "matrix_injected_memory" for r in recalled))

        # Broken hook in src/Matrix/plan/hooks.py must fail-open and never crash prm or keepgoing
        with open(os.path.join(tmp, "src", "Matrix", "plan", "hooks.py"), "w", encoding="utf-8") as f:
            f.write(
                "def score_candidate(text, base_score):\n"
                "    raise RuntimeError('matrix plan boom')\n"
            )
        matrix.hotload(tmp)
        safe_ranked = prm.rank_text("hello world")
        st = matrix.status(tmp)
        check("E broken subpackage hook raising RuntimeError fails open to Nucleus default and records hook_errors",
              isinstance(safe_ranked, float) and safe_ranked == base_ranked
              and any("matrix plan boom" in str(e.get("error", "")) for e in (st.get("hook_errors") or [])))

        # Custom HTTP route via src/Matrix/core/hooks.py::handle_http and WebUI plugins.js
        ext_resp = matrix.call_ext_http("GET", "/api/matrix/ext/ping", {"a": "1"}, None, repo_root=tmp)
        with open(os.path.join(tmp, "src", "Matrix", "webui", "plugins.js"), "w", encoding="utf-8") as f:
            f.write("window.__MATRIX_PLUGIN_LOADED = true;\n")
        pjs = matrix.webui_plugins_js(tmp)
        check("F /api/matrix/ext/* custom HTTP handler and /api/matrix/plugins.js fail-open wrapper work live",
              isinstance(ext_resp, dict)
              and ext_resp.get("body", {}).get("ext_path") == "ping"
              and "window.__MATRIX_PLUGIN_LOADED = true;" in pjs
              and "try {" in pjs and "catch" in pjs)
    finally:
        os.environ.pop("LONGRUN_MATRIX_SRC", None)
        os.environ.pop("LONGRUN_MATRIX_DOT", None)
        os.environ.pop("LONGRUN_DATA_DIR", None)

print("---")
print("%d/%d PASS" % (sum(checks), len(checks)))
sys.exit(0 if all(checks) else 1)
