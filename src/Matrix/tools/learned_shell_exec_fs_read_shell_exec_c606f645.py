"""Matrix tool forged from a mined tool sequence (Longrun self-evolve).

Sequence: shell.exec → fs.read → shell.exec
Support: 66 run(s). Origin: shell.exec-fs.read-shell.exec.

Each step runs through `longrun.tools.tools.execute`, so the harness's own
approval policy still applies to every single step: this module never bypasses
a gate, it only removes the need to retype the sequence.
"""

STEPS = ['shell.exec', 'fs.read', 'shell.exec']

TOOL_SCHEMAS = {
    'learned_shell_exec_fs_read_shell_exec_c606f645.run': {
        "description": 'Replay the mined tool sequence shell.exec → fs.read → shell.exec in order: `inputs` carries one argument object per step, the run stops at the first failure, and every step keeps its own approval policy.',
        "type": "object",
        "properties": {
            "inputs": {
                "type": "array",
                "description": "one argument object per step, in STEP order",
            },
        },
        "required": ["inputs"],
        "approval": "auto",
    },
}
TOOL_SCHEMA = dict(TOOL_SCHEMAS['learned_shell_exec_fs_read_shell_exec_c606f645.run'])


def execute(args, run_id=None, subtool=None):
    """Run the mined sequence with the caller's arguments, in order."""
    args = args or {}
    inputs = args.get("inputs")
    if not isinstance(inputs, list) or len(inputs) != len(STEPS):
        return {"ok": False, "exit_code": 64,
                "error": "`inputs` must be a list of %d argument objects "
                         "(one per step)" % len(STEPS),
                "steps": list(STEPS)}
    from longrun.tools import tools as _tools
    out = []
    for name, step_args in zip(STEPS, inputs):
        if not isinstance(step_args, dict):
            out.append({"tool": name, "ok": False,
                        "error": "step arguments must be an object"})
            break
        try:
            res = _tools.execute(name, step_args, run_id=run_id) or {}
        except Exception as e:  # noqa: BLE001 — one broken step must not hide the rest
            out.append({"tool": name, "ok": False, "error": str(e)})
            break
        ok = bool(res.get("ok", res.get("exit_code") == 0))
        out.append({"tool": name, "ok": ok})
        if not ok:
            break
    done = sum(1 for s in out if s["ok"])
    return {"ok": len(out) == len(STEPS) and done == len(STEPS),
            "steps": out, "ok_count": done, "step_count": len(STEPS),
            "stdout": "%d/%d step(s) executed" % (done, len(STEPS))}
