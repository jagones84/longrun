#!/usr/bin/env python3
"""v498 — Matrix scaffold & deterministic Nucleus write-guard."""
import os
import sys
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

    snap = matrix_guard.snapshot_nucleus_digests(tmp)
    with open(srv_file, "w", encoding="utf-8") as f:
        f.write("# tampered!\n")
    reverted = matrix_guard.restore_if_nucleus_tampered(snap, tmp)
    with open(srv_file, encoding="utf-8") as f:
        restored_content = f.read()
    check("E snapshot_nucleus_digests detects and reverts Nucleus tampering",
          len(reverted) == 1 and restored_content == "# nucleus\n")

    from longrun.tools import tools
    res_fw = tools.execute("fs.write", {"path": "src/longrun/core/server.py", "content": "x"})
    res_fe = tools.execute("fs.edit", {"path": "src/longrun/core/server.py",
                                       "search": "def", "replace": "DEF"})
    check("F tools.execute(fs.write/fs.edit) deterministically blocks Nucleus paths",
          not res_fw.get("ok") and "NUCLEUS_PROTECTED" in str(res_fw.get("error"))
          and not res_fe.get("ok") and "NUCLEUS_PROTECTED" in str(res_fe.get("error")))

    # ---------------------------------------------------------------- JAG-510 --
    # Red-team report: the shell gate matched the RAW COMMAND TEXT, so
    #   t=$(printf 'c3JjL2xvbmdydW4=' | base64 -d); printf x > "$t/f"
    # wrote into src/longrun (C1), `tests/`+`deploy/` were not even in the token
    # list (C2), and a CREATED file survived the restore (C3). The gate now
    # inspects the paths a command could WRITE, and the restore removes creations.

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

    # ---- H) a CREATED Nucleus file does not survive the restore --------------
    snap_created = matrix_guard.snapshot_nucleus_digests(tmp)
    made = [os.path.join(tmp, "src", "longrun", "core", "_probe.py"),
            os.path.join(tmp, "tests", "acceptance", "_probe.py"),
            os.path.join(tmp, "deploy", "_probe.sh")]
    for p in made:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write("PWNED\n")
    reverted_created = matrix_guard.restore_if_nucleus_tampered(snap_created, tmp)
    check("H a file CREATED inside a Nucleus dir is removed by the restore",
          not any(os.path.exists(p) for p in made) and len(reverted_created) >= 3,
          str(reverted_created))

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
        j_restore = matrix_guard.restore_if_nucleus_tampered(
            {os.path.join(tmp, "src", "longrun", "core", "server.py"):
             ("deadbeef", b"# old\n")}, tmp)
        check("J the dangerous opt-in unlocks writes AND skips the restore",
              j_write and j_shell and j_restore == [], str(j_restore))
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

    # ---- O) the sweep must not delete what the snapshot never tracked ---------
    # Regression: the first version removed EVERY unknown file, so the shipped
    # WebUI icons (`assets/*.png`) and `manifest.webmanifest` were deleted as
    # "creations" after any shell command. The sweep now uses exactly the
    # snapshot predicate, while still removing created artefacts.
    keep_png = os.path.join(tmp, "webui", "assets", "icon-512.png")
    os.makedirs(os.path.dirname(keep_png), exist_ok=True)
    with open(keep_png, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
    snap_png = matrix_guard.snapshot_nucleus_digests(tmp)
    created_yaml = os.path.join(tmp, "src", "longrun", "core", "rogue.yaml")
    with open(created_yaml, "w", encoding="utf-8") as f:
        f.write("pwned\n")
    matrix_guard.restore_if_nucleus_tampered(snap_png, tmp)
    check("O the sweep never deletes a pre-existing untracked-extension file",
          os.path.isfile(keep_png) and not os.path.exists(created_yaml),
          "png kept=%s rogue removed=%s" % (os.path.isfile(keep_png),
                                            not os.path.exists(created_yaml)))

print("---")
print("%d/%d PASS" % (sum(checks), len(checks)))
sys.exit(0 if all(checks) else 1)
