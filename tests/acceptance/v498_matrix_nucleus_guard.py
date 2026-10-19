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


def check(name, passed):
    checks.append(bool(passed))
    print(("PASS " if passed else "FAIL ") + name)


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

print("---")
print("%d/%d PASS" % (sum(checks), len(checks)))
sys.exit(0 if all(checks) else 1)
