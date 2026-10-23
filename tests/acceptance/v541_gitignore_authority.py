#!/usr/bin/env python3
"""v541 — the codebase index never reads git-ignored content.

Two paths must agree:
  * inside a git work tree, `git ls-files --cached --others --exclude-standard`
    is authoritative (nested .gitignore, negation rules, global excludes);
  * without git, the walk applies the workspace-root .gitignore plus every
    nested .gitignore it meets while descending.
"""
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v541-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
sys.path.insert(0, os.path.join(ROOT, "src"))

from longrun.memory import chunk  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


def make_tree(name, git):
    ws = os.path.join(TMP, name)
    os.makedirs(os.path.join(ws, "sub"))
    os.makedirs(os.path.join(ws, "local"))
    with open(os.path.join(ws, ".gitignore"), "w", encoding="utf-8") as f:
        f.write("local/\n*.log\n!important.log\n")
    with open(os.path.join(ws, "sub", ".gitignore"), "w", encoding="utf-8") as f:
        f.write("*.md\n!keep.md\n")
    files = {
        "main.py": "def main():\n    return 1\n",
        "local/hidden.py": "def hidden():\n    return 2\n",
        "noisy.log": "noise\n",
        "important.log": "keep me\n",
        "sub/drop.md": "# drop\n",
        "sub/keep.md": "# keep\n",
        "sub/ok.py": "def ok():\n    return 3\n",
    }
    for rel, text in files.items():
        with open(os.path.join(ws, rel), "w", encoding="utf-8") as f:
            f.write(text)
    if git:
        subprocess.run(["git", "init", "-q", os.path.join(ws)], check=True)
    else:
        os.makedirs(os.path.join(ws, ".git"))   # empty: not a work tree
    return ws


def rels(ws):
    return sorted(rel.replace(os.sep, "/")
                  for rel, _abs, _lang, _kind in chunk.walk(ws, {"ignore": []}))


EXPECTED = ["important.log", "main.py", "sub/keep.md", "sub/ok.py"]
have_git = bool(shutil.which("git"))

if have_git:
    ws_git = make_tree("repo", git=True)
    got = rels(ws_git)
    check("A1 a git work tree indexes only non-ignored, re-included files",
          got == EXPECTED, got)
    check("A2 a nested .gitignore is honoured", "sub/drop.md" not in got, got)
    check("A3 a negation re-includes an otherwise ignored file",
          "important.log" in got and "noisy.log" not in got, got)
    check("A4 an ignored directory is skipped entirely",
          "local/hidden.py" not in got, got)
else:
    print("SKIP git is not installed; the authoritative path cannot be tested")

ws_plain = make_tree("plain", git=False)
got_plain = rels(ws_plain)
check("B1 without git the fallback still applies root + nested .gitignore",
      got_plain == EXPECTED, got_plain)
check("B2 fallback honours the nested negation", "sub/keep.md" in got_plain
      and "sub/drop.md" not in got_plain, got_plain)

check("C1 the walk documents the git-authoritative contract",
      "git ls-files" in (chunk.walk.__doc__ or "")
      and "nested .gitignore" in (chunk.walk.__doc__ or "").lower())

bundle = os.path.join(ws_plain, "sub", "bundle.min.js")
with open(bundle, "w", encoding="utf-8") as f:
    f.write("var a=1;\n")
with_globs = sorted(rel.replace(os.sep, "/")
                    for rel, _abs, _lang, _kind in
                    chunk.walk(ws_plain, {"ignore": ["*.min.js"]}))
check("C2 the configured ignore globs still apply on top of git rules",
      "sub/bundle.min.js" not in with_globs and "sub/ok.py" in with_globs,
      with_globs)

shutil.rmtree(TMP, ignore_errors=True)
print("v541: %d/%d PASS" % (sum(results), len(results)))
raise SystemExit(0 if all(results) else 1)
