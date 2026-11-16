#!/usr/bin/env python3
"""v504 — Deterministic Matrix -> Nucleus promotion, line-number diagnostics, mandatory test gate & checkbox-only policy."""
import json
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
        from longrun.core import api_v02, matrix
        from longrun.tools import matrix_guard, registry, tools
        registry._external_tools = lambda: {}

        matrix_guard.ensure_layout(tmp)
        os.makedirs(os.path.join(tmp, "src", "longrun", "tools"), exist_ok=True)
        os.makedirs(os.path.join(tmp, "src", "longrun", "plan"), exist_ok=True)

        # A: Line-number error reporting in try/catch for both syntax and runtime errors
        bad_tool = os.path.join(tmp, "src", "Matrix", "tools", "line_bug.py")
        with open(bad_tool, "w", encoding="utf-8") as f:
            f.write(
                "# line 1\n"
                "# line 2\n"
                "TOOL_SCHEMA = {'description': 'buggy'}\n"
                "def execute(args, run_id=None):\n"
                "    x = 1 / 0  # line 5 boom\n"
            )
        hl = matrix.hotload(tmp)
        rt_out = matrix.execute_tool("line_bug", {}, repo_root=tmp)
        os.remove(bad_tool)
        check("A runtime exception in Matrix tool reports exact line number (line 5) for debugging",
              not rt_out.get("ok")
              and rt_out.get("line") == 5
              and "line 5" in str(rt_out.get("error", "")))

        # Write a valid tool fast_calc.py
        calc_tool = os.path.join(tmp, "src", "Matrix", "tools", "fast_calc.py")
        with open(calc_tool, "w", encoding="utf-8") as f:
            f.write(
                'TOOL_SCHEMA = {"description": "Add two ints", "type": "object", '
                '"properties": {"a": {"type": "integer"}, "b": {"type": "integer"}}}\n'
                "def execute(args, run_id=None):\n"
                '    return {"ok": True, "stdout": str(int(args.get("a", 0)) + int(args.get("b", 0)))}\n'
            )
        matrix.hotload(tmp)

        # B: Even approvals.mode == "full" NEVER authorizes promote_to_nucleus without allow_matrix_promote checkbox
        orig_load = registry.load_config
        cfg_full_no_cb = json.loads(json.dumps(orig_load()))
        cfg_full_no_cb.setdefault("approvals", {})["mode"] = "full"
        cfg_full_no_cb["approvals"]["allow_matrix_promote"] = False
        registry.load_config = lambda reload=False: cfg_full_no_cb
        dec_no_cb, reason_no_cb = registry.classify("matrix", {"action": "promote_to_nucleus", "kind": "tool", "name": "fast_calc"})
        prom_denied = matrix.promote_to_nucleus("tool", "fast_calc", repo_root=tmp)
        check("B approvals.mode='full' still DENIES promote_to_nucleus when allow_matrix_promote checkbox is unchecked",
              dec_no_cb == "denied"
              and "allow_matrix_promote" in reason_no_cb
              and not prom_denied.get("ok")
              and "PROMOTE_DENIED" in str(prom_denied.get("error", "")))

        # C: Enable the dedicated checkbox; promoting an UNTESTED tool must be rejected (PROMOTE_UNVERIFIED)
        cfg_full_with_cb = json.loads(json.dumps(cfg_full_no_cb))
        cfg_full_with_cb["approvals"]["allow_matrix_promote"] = True
        registry.load_config = lambda reload=False: cfg_full_with_cb
        dec_with_cb, _ = registry.classify("matrix", {"action": "promote_to_nucleus", "kind": "tool", "name": "fast_calc"})
        prom_untested = matrix.promote_to_nucleus("tool", "fast_calc", repo_root=tmp)
        check("C even with checkbox enabled, promote_to_nucleus refuses untested Matrix code (PROMOTE_UNVERIFIED)",
              dec_with_cb == "auto"
              and not prom_untested.get("ok")
              and "PROMOTE_UNVERIFIED" in str(prom_untested.get("error", "")))

        # D: Run test in .Matrix/trash targeting tool:fast_calc -> green -> promote_to_nucleus moves to Nucleus & deletes from Matrix
        test_res = matrix.run_test(
            "test_fast_calc.py",
            code=(
                "from Matrix.tools import fast_calc\n"
                "r = fast_calc.execute({'a': 7, 'b': 5})\n"
                "assert r['ok'] and r['stdout'] == '12'\n"
            ),
            target="tool:fast_calc",
            repo_root=tmp,
        )
        prom_ok = matrix.promote_to_nucleus("tool", "fast_calc", repo_root=tmp)
        promoted_path = os.path.join(tmp, "src", "longrun", "tools", "promoted", "fast_calc.py")
        exec_promoted = matrix.execute_promoted_tool("fast_calc", {"a": 10, "b": 20}, repo_root=tmp)
        check("D after passing test, promote_to_nucleus auto-commits, moves tool to Nucleus, deletes from Matrix, and runs as Nucleus",
              test_res.get("ok") is True
              and prom_ok.get("ok") is True
              and prom_ok.get("deleted_from_matrix") is True
              and bool(prom_ok.get("pre_commit"))
              and not os.path.exists(calc_tool)
              and os.path.isfile(promoted_path)
              and exec_promoted.get("ok") is True
              and exec_promoted.get("stdout") == "30"
              and exec_promoted.get("origin") == "nucleus")

        # E: Promote a subpackage hook (src/Matrix/plan/hooks.py) -> moves to src/longrun/plan/matrix_promoted_hooks.py & deletes from Matrix
        plan_hook = os.path.join(tmp, "src", "Matrix", "plan", "hooks.py")
        with open(plan_hook, "w", encoding="utf-8") as f:
            f.write(
                "def score_candidate(text, base_score):\n"
                "    return round(min(1.0, float(base_score) + 0.11), 3)\n"
            )
        t_hook = matrix.run_test(
            "test_plan_hook.py",
            code=(
                "from Matrix.plan import hooks\n"
                "assert hooks.score_candidate('x', 0.5) == 0.61\n"
            ),
            target="hook:plan",
            repo_root=tmp,
        )
        prom_hook = matrix.promote_to_nucleus("hook", "plan", repo_root=tmp)
        hook_val = matrix.call_hook("plan", "score_candidate", "x", 0.5, default=0.5, repo_root=tmp)
        check("E promoting hook:plan moves it to Nucleus matrix_promoted_hooks.py, deletes from Matrix, and stays active",
              t_hook.get("ok") is True
              and prom_hook.get("ok") is True
              and not os.path.exists(plan_hook)
              and os.path.isfile(os.path.join(tmp, "src", "longrun", "plan", "matrix_promoted_hooks.py"))
              and hook_val == 0.61)

        registry.load_config = orig_load

        # F: WebUI Settings > Tools & approvals has #apMatrixPromote checkbox and api_v02 persists allow_matrix_promote
        with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
            html = f.read()
        with open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"), encoding="utf-8") as f:
            api_src = f.read()
        check("F WebUI Tools & approvals renders #apMatrixPromote checkbox and api_v02 persists allow_matrix_promote",
              'id="apMatrixPromote"' in html
              and "allow_matrix_promote" in html
              and "allow_matrix_promote" in api_src)
    finally:
        os.environ.pop("LONGRUN_MATRIX_SRC", None)
        os.environ.pop("LONGRUN_MATRIX_DOT", None)
        os.environ.pop("LONGRUN_DATA_DIR", None)

print("---")
print("%d/%d PASS" % (sum(checks), len(checks)))
sys.exit(0 if all(checks) else 1)
