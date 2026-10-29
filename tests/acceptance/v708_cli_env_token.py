#!/usr/bin/env python3
"""v708 — the CLI authenticates from the same `.env` the service uses.

The cross-lane probe found `forge` answering `unauthorized` while the token sat
in the gitignored `.env`: the server loads it (`providers.load_env`, JAG-492)
and the CLI did not, so every terminal command looked like a broken service.

  A  the CLI reads LONGRUN_TOKEN from a configured `.env` (no flag, no export)
  B  an explicit LONGRUN_TOKEN still wins over the file
  C  a missing/unreadable env file harms nothing (no crash, no token)
  D  the bootstrap runs BEFORE the TOKEN constant is read (source order)

No network, no server, no model.
"""
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="longrun-v708-")
FORGE = os.path.join(REPO, "src", "longrun", "core", "forge.py")
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


def probe(env, extra_env_file=True):
    """Import forge in a clean interpreter and return its resolved TOKEN."""
    code = ("import importlib.util, json, sys;"
            "spec = importlib.util.spec_from_file_location('forge_probe', %r);"
            "m = importlib.util.module_from_spec(spec);"
            "spec.loader.exec_module(m);"
            "print(json.dumps({'token': m.TOKEN}))" % FORGE)
    clean = {k: v for k, v in env.items()}
    p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                       timeout=90, env=clean, cwd=TMP)
    line = (p.stdout or "").strip().splitlines()[-1:] or [""]
    try:
        return __import__("json").loads(line[0]).get("token")
    except ValueError:
        return {"stdout": p.stdout[-200:], "stderr": p.stderr[-300:]}


def base_env(env_file):
    env = {k: v for k, v in os.environ.items() if not k.startswith("LONGRUN_")}
    env["LONGRUN_ENV_FILE"] = env_file
    return env


# ------------------------------------------------- A: token comes from .env --
env_path = os.path.join(TMP, "cli.env")
with open(env_path, "w", encoding="utf-8") as f:
    f.write("# probe\nLONGRUN_TOKEN='file-token'\n")
check("A1 the CLI resolves the token from the configured .env",
      probe(base_env(env_path)) == "file-token", probe(base_env(env_path)))

# ------------------------------------------------- B: an explicit value wins --
env = base_env(env_path)
env["LONGRUN_TOKEN"] = "explicit-token"
check("B1 an exported LONGRUN_TOKEN still wins", probe(env) == "explicit-token",
      probe(env))

# ------------------------------------------------- C: a missing file is safe --
missing = os.path.join(TMP, "nope.env")
got = probe(base_env(missing))
check("C1 a missing env file neither crashes nor reuses the probe value",
      not isinstance(got, dict) and got != "file-token",
      {"crashed": isinstance(got, dict), "has_token": bool(got)})

# ------------------------------------------------------------ D: source order --
src = open(FORGE, encoding="utf-8").read()
head = src.split("TOKEN = ")[0]
check("D1 the env bootstrap runs before TOKEN is read",
      "load_env()" in src and src.index("load_env()") < src.index("TOKEN = "), "")
check("D2 it is the SAME loader the server uses (no second parser)",
      "from longrun.model import providers" in head and "load_env()" in head
      and "def load_env" not in src, "")

print("\n---\nv708: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
