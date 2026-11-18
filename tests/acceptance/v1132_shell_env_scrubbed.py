#!/usr/bin/env python3
"""v1132 — a child the harness starts for an agent action carries no credential.

Round 66 (arXiv:2611.15223 guardscope — a control is CHECKED, BYPASSED or
PREVENTED). `shell.auto_approve` lists `^env$` as a read-only command, and the
session shell inherited the SERVICE's environment: measured live 2026-11-18, one
`env` printed the ten credential variables the harness holds —

  BRAVE_API_KEY  COHERE_API_KEY  DEEPSEEK_API_KEY  DEFAULT_HF_TOKEN
  GITHUB_PERSONAL_ACCESS_TOKEN  GITHUB_TOKEN  LONGRUN_TOKEN
  OPENROUTER_API_KEY  TAVILY_API_KEY  VLLM_API_KEY

— straight into the model's context. No command rule can see `env > /tmp/e` plus
a read; the object is the child's WORLD, so the fix removes the variables from it
(`osutil.scrubbed_env`) at all three spawners the agent can reach.

  A  the scrub drops every credential-shaped name and keeps everything else
  B  an operator passthrough re-admits exactly the named variable
  C  the session shell starts without them and works normally
  D  host execution inside a run gets the same environment
  E  a background job gets the same environment
  F  `shell.env_passthrough` is one config read (`context_limits.shell_list`)

Deterministic: no server, no model, no network (`printenv` only).
Run: python3 tests/acceptance/v1132_shell_env_scrubbed.py
"""
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1132-")
os.environ["LONGRUN_DATA_DIR"] = TMP
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.makedirs(os.environ["LONGRUN_RUNS_DIR"], exist_ok=True)
# The fake credentials the scrub must remove.
FAKE = {"FAKE_DEEPSEEK_API_KEY": "sk-secret-1",
        "FAKE_HF_TOKEN": "hf-secret-2",
        "FAKE_DB_PASSWORD": "pw-secret-3",
        "fake_github_token": "gh-secret-4"}
KEEP = {"FAKE_PLAIN_VALUE": "visible-5"}
os.environ.update(FAKE)
os.environ.update(KEEP)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.util import osutil  # noqa: E402
from longrun.tools import term  # noqa: E402
from longrun.tools import sandbox  # noqa: E402
from longrun.tools import bgjobs  # noqa: E402
from longrun.model import context_limits as ctx_limits  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


# --- A: the rule of the scrub ------------------------------------------------
env = osutil.scrubbed_env()
check("A1 a KEY name is dropped", "FAKE_DEEPSEEK_API_KEY" not in env, sorted(env)[:6])
check("A2 a TOKEN name is dropped", "FAKE_HF_TOKEN" not in env)
check("A3 a PASSWORD name is dropped", "FAKE_DB_PASSWORD" not in env)
check("A4 the match is case-insensitive", "fake_github_token" not in env)
check("A5 an ordinary name is kept", env.get("FAKE_PLAIN_VALUE") == "visible-5")
for keep in ("PATH", "HOME"):
    check("A6 %s is kept" % keep, keep in env)
check("A7 an SSH socket is not a credential", "SSH_AUTH_SOCK" not in os.environ or
      "SSH_AUTH_SOCK" in env)

# --- B: the operator's allowlist --------------------------------------------
env2 = osutil.scrubbed_env(["FAKE_HF_TOKEN"])
check("B1 the passthrough re-admits exactly what it names",
      env2.get("FAKE_HF_TOKEN") == "hf-secret-2", env2.get("FAKE_HF_TOKEN"))
check("B2 and nothing else", "FAKE_DEEPSEEK_API_KEY" not in env2)
check("B3 the spelling is case-insensitive",
      osutil.scrubbed_env(["fake_hf_token"]).get("FAKE_HF_TOKEN") == "hf-secret-2")

# --- C: the session shell ----------------------------------------------------
sh = term.get("v1132", cwd=TMP)
try:
    got = sh.run_capture("printenv FAKE_DEEPSEEK_API_KEY; echo END", timeout=20)
    out = (got.get("stdout") or "").strip()
    check("C1 the shell does not see the provider key", out == "END", out)
    got = sh.run_capture("printenv FAKE_PLAIN_VALUE", timeout=20)
    check("C2 and an ordinary variable survives",
          (got.get("stdout") or "").strip() == "visible-5", got.get("stdout"))
    got = sh.run_capture("printenv PATH | head -c 20", timeout=20)
    check("C3 the shell still has a PATH", bool((got.get("stdout") or "").strip()),
          got.get("stdout"))
finally:
    term.reset("v1132")

# --- D: host execution inside a run -----------------------------------------
res = sandbox.run("printenv FAKE_HF_TOKEN; echo END", backend="none", workspace=TMP,
                  timeout=30)
check("D1 host execution runs", res.get("exit_code") == 0, res)
check("D2 it does not see the token",
      (res.get("stdout") or "").strip() == "END", res.get("stdout"))
res = sandbox.run("printenv FAKE_PLAIN_VALUE", backend="none", workspace=TMP, timeout=30)
check("D3 and an ordinary variable survives",
      (res.get("stdout") or "").strip() == "visible-5", res.get("stdout"))

# --- E: a background job ----------------------------------------------------
started = bgjobs.start("printenv FAKE_DB_PASSWORD; echo END", cwd=TMP)
check("E1 the job starts", started.get("ok") is True, started)
log = started.get("log") or ""
text = ""
for _ in range(60):
    try:
        with open(log, "rb") as f:
            text = f.read().decode("utf-8", "replace")
    except OSError:
        text = ""
    if "END" in text:
        break
    time.sleep(0.1)
check("E2 the job does not see the password", text.strip() == "END", text)

# --- F: one config read -----------------------------------------------------
check("F1 the shipped default is an empty list",
      ctx_limits.shell_list("env_passthrough") == [],
      ctx_limits.shell_list("env_passthrough"))
check("F2 the override is read",
      ctx_limits.shell_list("env_passthrough", {"env_passthrough": ["A_KEY"]}) == ["A_KEY"],
      ctx_limits.shell_list("env_passthrough", {"env_passthrough": ["A_KEY"]}))
check("F3 a comma string is accepted",
      ctx_limits.shell_list("env_passthrough", {"env_passthrough": "A_KEY, B_KEY"})
      == ["A_KEY", "B_KEY"],
      ctx_limits.shell_list("env_passthrough", {"env_passthrough": "A_KEY, B_KEY"}))

print("\n---\nv1132: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
