#!/usr/bin/env python3
"""v499 — Matrix 3-slot checkpoints, 20-commit capped local Git, and .Matrix/trash runner."""
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
    os.environ["LONGRUN_DATA_DIR"] = os.path.join(tmp, "data")
    from longrun.core import matrix
    from longrun.tools import matrix_guard

    matrix_guard.ensure_layout(tmp)
    fpath = os.path.join(tmp, "src", "Matrix", "util", "helper.py")
    with open(fpath, "w", encoding="utf-8") as f:
        f.write("VAL = 1\n")

    res1 = matrix.checkpoint_save(1, label="v1", repo_root=tmp)
    bad_slot = matrix.checkpoint_save(4, label="bad", repo_root=tmp)
    check("A checkpoint_save accepts only slots 1..3 and rejects slot 4",
          res1.get("ok") is True and bad_slot.get("ok") is False)

    with open(fpath, "w", encoding="utf-8") as f:
        f.write("BROKEN = (\n")
    junk = os.path.join(tmp, "src", "Matrix", "util", "junk.py")
    with open(junk, "w", encoding="utf-8") as f:
        f.write("JUNK = True\n")

    rb = matrix.checkpoint_rollback(1, repo_root=tmp)
    with open(fpath, encoding="utf-8") as f:
        restored_val = f.read()
    check("B checkpoint_rollback atomically restores code and removes newly added junk",
          rb.get("ok") is True and restored_val == "VAL = 1\n" and not os.path.exists(junk))

    seq_file = os.path.join(tmp, "src", "Matrix", "util", "seq.py")
    all_commits_ok = True
    for i in range(23):
        with open(seq_file, "w", encoding="utf-8") as f:
            f.write("STEP = %d\n" % i)
        c = matrix.git_commit("step %d" % i, repo_root=tmp)
        if not c.get("ok"):
            all_commits_ok = False
    log = matrix.git_log(limit=30, repo_root=tmp)
    check("C local Matrix git commits need no token and auto-cap history at 20 commits",
          all_commits_ok and log.get("ok") is True and 1 <= len(log.get("commits", [])) <= 20)

    with open(seq_file, "w", encoding="utf-8") as f:
        f.write("STEP = 999\n")
    diff_res = matrix.git_diff(repo_root=tmp)
    rst_res = matrix.git_reset("HEAD", repo_root=tmp)
    with open(seq_file, encoding="utf-8") as f:
        after_rst = f.read()
    check("D git_diff shows working tree changes and git_reset restores HEAD",
          diff_res.get("ok") is True and "STEP = 999" in diff_res.get("diff", "")
          and rst_res.get("ok") is True and after_rst == "STEP = 22\n")

    t_res = matrix.run_test("smoke.py", code="print('matrix_ok')", repo_root=tmp)
    cl_res = matrix.clean_trash(keep_recent=0, repo_root=tmp)
    check("E run_test executes in .Matrix/trash and clean_trash purges scratch files",
          t_res.get("ok") is True and "matrix_ok" in t_res.get("stdout", "")
          and cl_res.get("ok") is True and cl_res.get("removed", 0) >= 1)

print("---")
print("%d/%d PASS" % (sum(checks), len(checks)))
sys.exit(0 if all(checks) else 1)
