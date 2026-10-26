#!/usr/bin/env python3
"""v680 — Enter sends in the composer, and a launcher is found on the PATH we launch with.

Two operator-reported defects, 2026-10-26:

1. **Composer.** `Enter` inserted a newline and demanded `Ctrl+Enter`. It must send;
   `Shift+Enter` (and `Ctrl/Cmd+Enter`) insert a newline; an IME composition and the
   open `/` menu must NOT send (the menu picks the highlighted command).

2. **`npx` reported missing while installed.** `/home/jagones/.local/bin/npx` -> npm
   (node v22.11.0) exists, but the systemd USER service inherits a PATH without
   `~/.local/bin`, so `shutil.which("npx")` failed inside the service: the MCP panel
   disabled every `command: npx` client and the spawn would have died with ENOENT.
   `osutil.launcher_path()` is the ONE PATH builder, used by `mcp_client.runtimes()`,
   `_command_available()` and the actual spawn — probe and launch cannot disagree.

Deterministic: stdlib only, no model, no network, no server, no real child process.
"""
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v680-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
sys.path.insert(0, os.path.join(ROOT, "src"))

from longrun.util import osutil  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


def read_src(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


UI = read_src("webui", "index.html")
MCP = read_src("src", "longrun", "interop", "mcp_client.py")
OSUTIL = read_src("src", "longrun", "util", "osutil.py")
CHANGELOG = read_src("CHANGELOG.md")
REQS = read_src("requirements.txt")
README = read_src("README.md")

# ------------------------------------------------------- A: the composer key
_key = UI[UI.index('$("inp").addEventListener("keydown", e => {'):]
_key = _key[:_key.index("});") + 3]
check("A1 Enter alone sends (the pre-existing handler no longer demands Ctrl)",
      "e.preventDefault(); send();" in _key
      and 'e.key !== "Enter"' in _key and "e.shiftKey" in _key)
check("A2 an IME composition never sends mid-word",
      "e.isComposing" in _key and "e.keyCode === 229" in _key)
check("A3 the open slash menu is not pre-empted (it owns Enter)",
      'const menu = $("slashMenu");' in _key and "!menu.hidden && _slashItems.length" in _key)
check("A4 Shift still inserts a newline (no preventDefault on Shift)",
      "if (e.shiftKey) return;" in _key
      and _key.index("if (e.shiftKey) return;") < _key.index("e.preventDefault(); send();"))
check("A5 the old Ctrl-only send rule is gone",
      '(e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); send(); }'
      not in UI)
check("A6 the slash picker takes Enter with or without Ctrl, but not Shift",
      'if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); const it = _slashItems[_slashHi]; if (it) it.pick(); return; }'
      in UI)
check("A7 no tooltip still promises `Ctrl+Enter` (the UI would lie)",
      "send (Ctrl+Enter)" not in UI and "Ctrl+⏎" not in UI
      and "send (Enter — Shift+Enter for a newline)" in UI)

# ------------------------------------------------------------ B: launcher PATH
UNIQ = os.path.join(TMP, "userbin")
os.makedirs(UNIQ, exist_ok=True)
_real_expanduser = os.path.expanduser
osutil._USER_BIN_DIRS = ("~/.local/bin",)          # deterministic, small
_orig = osutil._USER_BIN_DIRS
# Point `~/.local/bin` at a directory we own for the duration of the test.
os.path.expanduser = lambda p: UNIQ if p == "~/.local/bin" else _real_expanduser(p)
try:
    got = osutil.launcher_path({"PATH": "/usr/bin:/bin"})
    check("B1 a per-user bin dir is PREPENDED to the launcher PATH",
          got.split(os.pathsep)[0] == UNIQ and "/usr/bin" in got and "/bin" in got, got)
    check("B2 an absent directory is not invented",
          osutil.launcher_path({"PATH": "/usr/bin"}) == "/usr/bin"
          if not os.path.isdir(UNIQ) else True)
    check("B3 a directory already on the PATH is not duplicated",
          osutil.launcher_path({"PATH": UNIQ + os.pathsep + "/usr/bin"}).count(UNIQ) == 1)
    check("B4 an empty PATH is tolerated",
          osutil.launcher_path({"PATH": ""}).startswith(UNIQ))
finally:
    os.path.expanduser = _real_expanduser
    osutil._USER_BIN_DIRS = _orig

check("B5 Windows keeps its own resolution (no POSIX dirs injected, on_windows=True)",
      osutil.launcher_path({"PATH": r"C:\Tools"}, on_windows=True) == r"C:\Tools"
      and osutil.launcher_path({"PATH": r"C:\Tools"}, on_windows=False) != r"C:\Tools"
      if osutil.IS_POSIX else True)
check("B6 the resolution is documented as the launcher's PATH, not ours",
      "the PATH a launched" in " ".join(OSUTIL.split()) or "A systemd USER service" in OSUTIL)

# a REAL executable in a dir that is NOT on the process PATH: the probe must find it
BIN = os.path.join(TMP, "fakebin")
os.makedirs(BIN, exist_ok=True)
FAKE = os.path.join(BIN, "npx")
with open(FAKE, "w", encoding="utf-8") as f:
    f.write("#!/bin/sh\necho fake-npx\n")
os.chmod(FAKE, 0o755)
os.environ["PATH"] = "/usr/bin:/bin"
check("B7 a launcher absent from the process PATH is invisible without the fix",
      shutil.which("npx") is None, shutil.which("npx"))
_orig_dirs = osutil._USER_BIN_DIRS
osutil._USER_BIN_DIRS = (BIN,)
try:
    p = osutil.launcher_path()
    check("B8 ... and found as soon as launcher_path supplies its directory",
          p.split(os.pathsep)[0] == BIN and shutil.which("npx", path=p) == FAKE)
    check("B9 the resolved path is a real executable",
          os.access(shutil.which("npx", path=p), os.X_OK))
finally:
    osutil._USER_BIN_DIRS = _orig_dirs
    os.environ.pop("PATH", None)

# ------------------------------------------------- C: one owner, three callers
check("C1 the availability probe uses the launcher PATH (panel == launch)",
      "def runtimes():" in MCP and "path = osutil.launcher_path()" in MCP
      and 'shutil.which(c, path=path)' in MCP)
check("C2 the pre-save `mcp.test` check uses it too",
      "shutil.which(command, path=osutil.launcher_path(launch_env))" in MCP)
check("C3 the SPAWN sets that PATH on the child env before resolving the command",
      'full_env["PATH"] = osutil.launcher_path(full_env)' in MCP
      and MCP.index('full_env["PATH"] = osutil.launcher_path(full_env)')
      < MCP.index('resolved_command = shutil.which(command, path=full_env.get("PATH")) or command'))
check("C4 there is exactly ONE definition of the builder (no copy in mcp_client)",
      OSUTIL.count("def launcher_path(") == 1 and MCP.count("def launcher_path(") == 0)

# ------------------------------------------------------------- D: the record
check("D1 the changelog states both changes",
      "Enter sends the message in the composer" in CHANGELOG
      and "not installed on this host" in CHANGELOG)
check("D2 requirements.txt says WHY a system runtime cannot live there",
      "SYSTEM prerequisites are NOT here" in REQS and "Node.js" in REQS)
check("D3 the README's MCP step explains the per-user install resolution",
      "osutil.launcher_path" in README)

shutil.rmtree(TMP, ignore_errors=True)

print("\n%d/%d checks passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
