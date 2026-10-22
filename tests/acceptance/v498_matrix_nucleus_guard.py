#!/usr/bin/env python3
"""v498 — Matrix scaffold & deterministic Nucleus write-guard (deny-only)."""
import os
import sys
import threading
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(REPO, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

checks = []


def check(name, passed, detail=""):
    checks.append(bool(passed))
    print(("PASS " if passed else "FAIL ") + name
          + ((" :: " + str(detail)) if (detail and not passed) else ""))


with tempfile.TemporaryDirectory() as tmp:
    os.makedirs(os.path.join(tmp, "src", "longrun", "core"), exist_ok=True)
    os.makedirs(os.path.join(tmp, "webui"), exist_ok=True)
    os.makedirs(os.path.join(tmp, "config"), exist_ok=True)
    srv_file = os.path.join(tmp, "src", "longrun", "core", "server.py")
    rules_file = os.path.join(tmp, "RULES.md")
    with open(srv_file, "w", encoding="utf-8") as f:
        f.write("# nucleus\n")
    with open(rules_file, "w", encoding="utf-8") as f:
        f.write("# rules\n")

    from longrun.tools import matrix_guard

    info = matrix_guard.ensure_layout(tmp)
    check("A ensure_layout creates mirrored src/Matrix and .Matrix folders",
          info.get("ok") is True
          and os.path.isdir(os.path.join(tmp, "src", "Matrix", "tools"))
          and os.path.isdir(os.path.join(tmp, "src", "Matrix", "agent"))
          and os.path.isdir(os.path.join(tmp, "src", "Matrix", "webui"))
          and os.path.isdir(os.path.join(tmp, ".Matrix", "trash"))
          and os.path.isdir(os.path.join(tmp, ".Matrix", "docs"))
          and os.path.isdir(os.path.join(tmp, ".Matrix", "rules"))
          and os.path.isdir(os.path.join(tmp, ".Matrix", "skills"))
          and os.path.isdir(os.path.join(tmp, ".Matrix", "checkpoints"))
          and os.path.isfile(os.path.join(tmp, ".Matrix", "docs", "HANDOFF.md"))
          and os.path.isfile(os.path.join(tmp, ".Matrix", "docs", "MANUAL.md")))

    ok_nuc, err_nuc = matrix_guard.check_write_allowed(srv_file, tmp)
    ok_rul, err_rul = matrix_guard.check_write_allowed(rules_file, tmp)
    check("B check_write_allowed deterministically rejects Nucleus and RULES.md",
          not ok_nuc and "NUCLEUS_PROTECTED" in err_nuc
          and not ok_rul and "NUCLEUS_PROTECTED" in err_rul)

    ok_mat, _ = matrix_guard.check_write_allowed(
        os.path.join(tmp, "src", "Matrix", "tools", "custom.py"), tmp)
    ok_dot, _ = matrix_guard.check_write_allowed(
        os.path.join(tmp, ".Matrix", "trash", "test_x.py"), tmp)
    check("C check_write_allowed allows writes inside src/Matrix and .Matrix",
          ok_mat and ok_dot)

    ok_sh, err_sh = matrix_guard.check_shell_command(
        "echo hacked > src/longrun/core/server.py", cwd=tmp, repo_root=tmp)
    ok_sh_mat, _ = matrix_guard.check_shell_command(
        "python3 .Matrix/trash/test.py", cwd=tmp, repo_root=tmp)
    check("D check_shell_command blocks destructive shell writes targeting Nucleus",
          not ok_sh and "NUCLEUS_PROTECTED" in err_sh and ok_sh_mat)

    # ---- E) the harness NEVER reverts: deny-only, no snapshot machinery ------
    # Operator decision: a post-hoc whole-tree diff cannot attribute a change to
    # its author, so it silently destroyed concurrent legitimate work. The
    # snapshot/restore transaction is GONE — no revert callable exists at all.
    check("E the revert machinery is removed entirely (deny-only by design)",
          not hasattr(matrix_guard, "restore_if_nucleus_tampered")
          and not hasattr(matrix_guard, "snapshot_nucleus_digests")
          and not hasattr(matrix_guard, "shell_command_is_read_only"))

    from longrun.tools import tools
    res_fw = tools.execute("fs.write", {"path": "src/longrun/core/server.py", "content": "x"})
    res_fe = tools.execute("fs.edit", {"path": "src/longrun/core/server.py",
                                       "search": "def", "replace": "DEF"})
    check("F tools.execute(fs.write/fs.edit) deterministically blocks Nucleus paths",
          not res_fw.get("ok") and "NUCLEUS_PROTECTED" in str(res_fw.get("error"))
          and not res_fe.get("ok") and "NUCLEUS_PROTECTED" in str(res_fe.get("error")))

    # ---- write passed the gate is NEVER undone by some later sweep -----------
    with open(srv_file, "w", encoding="utf-8") as f:
        f.write("# operator edit kept\n")
    with open(os.path.join(tmp, "src", "longrun", "core", "_probe.py"), "w",
              encoding="utf-8") as f:
        f.write("# newly created\n")
    with open(srv_file, encoding="utf-8") as f:
        kept_content = f.read()
    check("E2 a write that passed the gates is left untouched on disk (no revert)",
          kept_content == "# operator edit kept\n"
          and os.path.isfile(os.path.join(tmp, "src", "longrun", "core", "_probe.py")))

    # ---------------------------------------------------------------- JAG-510 --
    # Red-team report: the shell gate matched the RAW COMMAND TEXT, so
    #   t=$(printf 'c3JjL2xvbmdydW4=' | base64 -d); printf x > "$t/f"
    # wrote into src/longrun (C1) and `tests/`+`deploy/` were not even in the
    # token list (C2). The gate now inspects the paths a command could WRITE.

    # ---- G) reads and redirected runs stay legal; writes are refused ---------
    g_read, _ = matrix_guard.check_shell_command(
        "cat config/tools.yaml", cwd=tmp, repo_root=tmp)
    g_grep, _ = matrix_guard.check_shell_command(
        "grep -rn TODO src/longrun", cwd=tmp, repo_root=tmp)
    g_pytest, _ = matrix_guard.check_shell_command(
        "python3 -m pytest tests/acceptance -q > /tmp/nucleus-probe.log",
        cwd=tmp, repo_root=tmp)
    g_outside, _ = matrix_guard.check_shell_command(
        "printf x > /tmp/outside.txt", cwd="/tmp", repo_root=tmp)
    check("G reading the Nucleus (cat/grep/pytest > log) is NOT blocked",
          g_read and g_grep and g_pytest and g_outside)

    g_redir, g_redir_err = matrix_guard.check_shell_command(
        "echo x >> config/tools.yaml", cwd=tmp, repo_root=tmp)
    g_sedi, g_sedi_err = matrix_guard.check_shell_command(
        "sed -i s/a/b/ webui/index.html", cwd=tmp, repo_root=tmp)
    g_rm, g_rm_err = matrix_guard.check_shell_command(
        "rm -rf tests", cwd=tmp, repo_root=tmp)
    g_touch, g_touch_err = matrix_guard.check_shell_command(
        "touch .longrun/rules/09-evil.md", cwd=tmp, repo_root=tmp)
    g_abs, g_abs_err = matrix_guard.check_shell_command(
        "printf x > " + os.path.join(tmp, "src", "longrun", "x.py"),
        cwd=tmp, repo_root=tmp)
    check("G2 every write TARGET inside the Nucleus is refused",
          not any((g_redir, g_sedi, g_rm, g_touch, g_abs))
          and all("NUCLEUS_PROTECTED" in e for e in (g_redir_err, g_sedi_err,
                                                     g_rm_err, g_touch_err, g_abs_err)),
          " ".join((g_redir_err, g_sedi_err, g_rm_err, g_touch_err, g_abs_err)))

    g_nested, g_nested_err = matrix_guard.check_shell_command(
        "bash -c 'rm -rf tests/acceptance'", cwd=tmp, repo_root=tmp)
    g_b64, g_b64_err = matrix_guard.check_shell_command(
        "t=$(printf 'c3JjL2xvbmdydW4=' | base64 -d); printf x > \"$t/_probe.txt\"",
        cwd=tmp, repo_root=tmp)
    g_case, _ = matrix_guard.check_shell_command(
        "echo x > SRC/LONGRUN/core/server.py", cwd=tmp, repo_root=tmp)
    check("G3 a nested shell, a base64 payload and a case variant are refused",
          not g_nested and not g_b64 and not g_case
          and "NUCLEUS_PROTECTED" in g_nested_err
          and "NUCLEUS_PROTECTED" in g_b64_err)

    # ---- H) python.run is no longer the open front door ----------------------
    # The shell gate cannot see what Python code does, so previously `python.run`
    # was "covered" only by the post-hoc restore. With deny-only enforcement a
    # snippet whose LITERAL write target is inside the Nucleus is refused up
    # front; dynamic targets fail OPEN (a miss can only mean "not blocked").
    h_w, h_w_err = matrix_guard.check_python_write(
        'open("src/longrun/core/server.py", "w").write("x")',
        workspace=tmp, repo_root=tmp)
    h_rm, h_rm_err = matrix_guard.check_python_write(
        'import os; os.remove("src/longrun/core/server.py")',
        workspace=tmp, repo_root=tmp)
    h_sh, h_sh_err = matrix_guard.check_python_write(
        'import shutil; shutil.copy("a", "config/tools.yaml")',
        workspace=tmp, repo_root=tmp)
    h_pl, h_pl_err = matrix_guard.check_python_write(
        'from pathlib import Path; Path("webui/index.html").write_text("x")',
        workspace=tmp, repo_root=tmp)
    check("H check_python_write refuses literal Nucleus write targets (open/os/shutil/pathlib)",
          not any((h_w, h_rm, h_sh, h_pl))
          and all("NUCLEUS_PROTECTED" in e for e in (h_w_err, h_rm_err, h_sh_err, h_pl_err)),
          " ".join((h_w_err, h_rm_err, h_sh_err, h_pl_err)))

    h_ok, _ = matrix_guard.check_python_write(
        'import os; print(os.listdir("src/longrun"))', workspace=tmp, repo_root=tmp)
    h_dyn, _ = matrix_guard.check_python_write(
        'import os; p="src/longrun/x.py"; open(p, "w").write("x")',
        workspace=tmp, repo_root=tmp)
    h_scratch, _ = matrix_guard.check_python_write(
        'open("/tmp/scratch.txt", "w").write("ok")', workspace=tmp, repo_root=tmp)
    check("H2 reads, dynamic targets and outside-repo writes pass (fail OPEN on non-literals)",
          h_ok and h_dyn and h_scratch)

    _abs_nucleus = os.path.join(REPO, "src", "longrun", "core", "server.py")
    res_py = tools.execute("python.run", {
        "code": 'open(%r, "w").write("pwned")' % _abs_nucleus})
    check("H3 tools.execute(python.run) refuses a literal Nucleus write",
          not res_py.get("ok") and "NUCLEUS_PROTECTED" in str(res_py.get("error")),
          str(res_py.get("error")))

    # ---- I) the prompt-bearing surfaces are Nucleus now ----------------------
    prompt_files = [os.path.join(tmp, ".longrun", "RULES.md"),
                    os.path.join(tmp, ".longrun", "rules", "01-evil.md"),
                    os.path.join(tmp, "AGENTS.md")]
    for p in prompt_files:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write("# injected\n")
    ok_prompt = [matrix_guard.check_write_allowed(p, tmp)[0] for p in prompt_files]
    check("I the files that land in the system prompt are write-protected",
          not any(ok_prompt), str(ok_prompt))

    # ---- J) the DANGEROUS operator opt-in -----------------------------------
    from longrun.tools import registry as _reg
    _orig_load = _reg.load_config
    try:
        _reg.load_config = lambda reload=False: {"approvals": {"allow_nucleus_write": True}}
        j_write, _ = matrix_guard.check_write_allowed(
            os.path.join(tmp, "src", "longrun", "core", "server.py"), tmp)
        j_shell, _ = matrix_guard.check_shell_command(
            "echo x > src/longrun/core/server.py", cwd=tmp, repo_root=tmp)
        j_py, _ = matrix_guard.check_python_write(
            'open("src/longrun/core/server.py", "w")', workspace=tmp, repo_root=tmp)
        check("J the dangerous opt-in unlocks writes (fs/shell/python)",
              j_write and j_shell and j_py)
        _reg.load_config = lambda reload=False: {"approvals": {}}
        j_locked, _ = matrix_guard.check_write_allowed(
            os.path.join(tmp, "src", "longrun", "core", "server.py"), tmp)
        check("K the guard is CLOSED unless the flag is explicitly true", not j_locked)
    finally:
        _reg.load_config = _orig_load

    _tools_yaml = open(os.path.join(REPO, "config", "tools.yaml"), encoding="utf-8").read()
    _ui_html = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
    _api_src = open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"),
                    encoding="utf-8").read()
    check("L the shipped config ships the danger flag OFF with a warning comment",
          "allow_nucleus_write: false" in _tools_yaml)
    check("M the Settings panel exposes a DANGEROUS confirm + the API persists it",
          "apNucleusUnlock" in _ui_html and "DANGEROUS" in _ui_html
          and "allow_nucleus_write" in _api_src)

    # ---- N) the `git` tool is a second front door, and it is guarded too -------
    n_git, n_git_err = matrix_guard.check_shell_command(
        "git restore -- src/longrun/core/server.py", cwd=tmp, repo_root=tmp)
    _tools_src = open(os.path.join(REPO, "src", "longrun", "tools", "tools.py"),
                      encoding="utf-8").read()
    _git_start = _tools_src.find("def _git(")
    _git_body = _tools_src[_git_start:_tools_src.find("def _http(", _git_start)]
    check("N the git tool is a second front door and runs the same write-target gate",
          not n_git and "NUCLEUS_PROTECTED" in n_git_err
          and "matrix_guard.check_shell_command" in _git_body,
          "%s | guard wired: %s" % (n_git_err, "matrix_guard.check_shell_command" in _git_body))

    # ---- P) a SYMLINK to the Nucleus is a write channel ----------------------
    # Live audit bypass: `ln -sfn <nucleus>/tools /tmp/nl && echo probe >
    # /tmp/nl/_p.txt` exited 0 and the file was born inside the Nucleus. The gate
    # judges the path AS WRITTEN before the command runs, so at check time
    # /tmp/nl did not exist and resolved to itself. Linking a Nucleus source is
    # now refused outright.
    p_ln, p_ln_err = matrix_guard.check_shell_command(
        "ln -sfn %s /tmp/nl_probe" % os.path.join(tmp, "src", "longrun", "core"),
        cwd=tmp, repo_root=tmp)
    p_chain, p_chain_err = matrix_guard.check_shell_command(
        "ln -sfn %s /tmp/nl_probe && echo probe > /tmp/nl_probe/_p.txt"
        % os.path.join(tmp, "src", "longrun"),
        cwd=tmp, repo_root=tmp)
    p_ok, _ = matrix_guard.check_shell_command(
        "ln -sfn /tmp/somewhere /tmp/elsewhere", cwd=tmp, repo_root=tmp)
    check("P a symlink whose source is in the Nucleus is refused (chain form too)",
          not p_ln and "write channel" in p_ln_err
          and not p_chain and "NUCLEUS_PROTECTED" in p_chain_err
          and p_ok,
          " ".join((p_ln_err, p_chain_err)))

    # ---- R) the shared lock only serializes cooperative writers --------------
    # `matrix_guard.run_nucleus_guarded` never snapshots or reverts now; it just
    # holds the process-wide mutex so two legitimate writers cannot interleave.
    # Its return shape stays `(result, [])` for callers that expect it.
    def _guarded_peer():
        return matrix_guard.run_nucleus_guarded(lambda: "peer", tmp)

    res_r, reverted_r = _guarded_peer()
    check("R run_nucleus_guarded returns (result, []) and never reverts anything",
          res_r == "peer" and reverted_r == [])

    _mg_src = open(os.path.join(REPO, "src", "longrun", "tools", "matrix_guard.py"),
                   encoding="utf-8").read()
    check("R2 the module carries no snapshot/restore transaction any more",
          "snapshot_nucleus_digests" not in _mg_src
          and "restore_if_nucleus_tampered" not in _mg_src
          and "hashlib" not in _mg_src)

    # T) every application writer into protected paths shares the mutex.
    from longrun.core import server as _server  # noqa: F401 — break the import cycle
    from longrun.core import httpapi, matrix
    from longrun.model import compaction_config
    promote_entered = threading.Event()
    original_promote = matrix.promote_to_nucleus
    matrix.promote_to_nucleus = lambda *a, **kw: (
        promote_entered.set() or {"ok": True})
    try:
        with matrix_guard.NUCLEUS_EXEC_LOCK:
            promote_thread = threading.Thread(
                target=lambda: tools._matrix(
                    {"action": "promote_to_nucleus", "name": "probe"}, "v498"))
            promote_thread.start()
            promote_entered_during_guard = promote_entered.wait(0.1)
        promote_thread.join(2)
    finally:
        matrix.promote_to_nucleus = original_promote
    check("T Matrix promotion waits until a guarded writer releases the mutex",
          not promote_entered_during_guard and promote_entered.is_set())

    policy_entered = threading.Event()
    original_save = compaction_config.save
    original_policy = httpapi.compaction_policy
    compaction_config.save = lambda **kw: (policy_entered.set() or {})
    httpapi.compaction_policy = lambda: {"ok": True}
    try:
        with matrix_guard.NUCLEUS_EXEC_LOCK:
            policy_thread = threading.Thread(
                target=lambda: httpapi.set_compaction_policy({"trigger_pct": 70}))
            policy_thread.start()
            policy_entered_during_guard = policy_entered.wait(0.1)
        policy_thread.join(2)
    finally:
        compaction_config.save = original_save
        httpapi.compaction_policy = original_policy
    check("T2 compaction-policy writes wait for the shared writer mutex",
          not policy_entered_during_guard and policy_entered.is_set())

print("---")
print("%d/%d PASS" % (sum(checks), len(checks)))
sys.exit(0 if all(checks) else 1)
