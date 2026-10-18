#!/usr/bin/env python3
"""v489 — the three headline capability claims are REAL (JAG-489).

The repo description says: "AI agent harness with bounded context, a verification
gate, and tool-output offload." Each claim is exercised here against the real
modules (no server, no network, no model):

  1. bounded context      -> the compaction policy drives the live trigger, and
                             oversized tool observations are offloaded.
  2. verification gate    -> fs.write is rolled back when the verify command fails.
  3. tool-output offload  -> the full payload lands in data/offload and the model
                             gets a bounded head+tail reference.

It also pins the retraction of the discontinued SparkPulse client claim.

Run: python3 tests/acceptance/v489_description_claims.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v489-")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.model import compaction_config as cc  # noqa: E402
from longrun.model import rllm                      # noqa: E402
# Import order matters: server.py imports agent.py, so importing the latter
# first leaves a partially initialized module (circular ImportError).
from longrun.core import server as _srv              # noqa: E402,F401
from longrun.agent import agent                     # noqa: E402
from longrun.plan import verify as vf               # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- A) bounded context ------------------------------------------------------
pol = cc.load(force=True)
check("A1 the compaction policy is loaded from the repo file",
      os.path.isfile(cc.path()) and os.path.normpath(cc.path())
      == os.path.normpath(os.path.join(REPO, "config", "compaction.yaml")), cc.path())
check("A2 the trigger/target/keep values are sane",
      0 < pol["trigger_pct"] <= 100 and 0 <= pol["target_pct"] < pol["trigger_pct"]
      and pol["keep_recent"] >= 1, pol)
check("A3 the legacy agent constants read the SAME policy",
      float(rllm.AUTOCOMPACT_PCT) == float(pol["trigger_pct"])
      and float(rllm.AUTOCOMPACT_TARGET_PCT) == float(pol["target_pct"])
      and int(rllm.KEEP_RECENT) == int(pol["keep_recent"]),
      (rllm.AUTOCOMPACT_PCT, rllm.AUTOCOMPACT_TARGET_PCT, rllm.KEEP_RECENT))
check("A4 the tool-observation budget is bounded and configurable",
      1000 <= agent.CHAT_TOOL_OBS_LIMIT <= 1_000_000
      and agent.CHAT_OBS_FULL > agent.CHAT_TOOL_OBS_LIMIT,
      (agent.CHAT_TOOL_OBS_LIMIT, agent.CHAT_OBS_FULL))

# ---- B) tool-output offload --------------------------------------------------
agent.DATA_DIR = os.path.join(TMP, "data")
payload = "x" * agent.CHAT_TOOL_OBS_LIMIT + \
          "\nEND-MARKER-" + ("y" * 12000) + "-TAIL"
ref = agent._offload_observation({"id": "sess-v489"}, "shell", payload)
files = []
root = os.path.join(agent.DATA_DIR, "offload", "sess-v489")
if os.path.isdir(root):
    files = sorted(os.listdir(root))
check("B1 an oversized observation is written to data/offload",
      len(files) == 1 and files[0].endswith("_shell.txt"), files)
full = ""
if files:
    with open(os.path.join(root, files[0]), encoding="utf-8") as f:
        full = f.read()
check("B2 the file keeps the FULL payload (no silent truncation)",
      full == payload and len(full) == len(payload), len(full))
check("B3 the model receives a file reference + a head+tail preview",
      "FULL OUTPUT FILE:" in ref and "Preview — last" in ref
      and payload[:300] in ref and payload[-300:] in ref, ref[:300])
check("B4 the reference is much smaller than the payload (context is bounded)",
      len(ref) < len(payload) // 2, (len(ref), len(payload)))
check("B5 the observation wrapper is stripped before the file write",
      agent._clean_offload("[shell] exit=0 backend=none\nstdout: hello\n") == "hello\n",
      repr(agent._clean_offload("[shell] exit=0 backend=none\nstdout: hello\n")))

# ---- C) verification gate ----------------------------------------------------
target = os.path.join(TMP, "gate.txt")
with open(target, "w", encoding="utf-8") as f:
    f.write("NEW\n")
snap = {"exists": True, "content": "OLD\n"}
off = {"enabled": False, "command": "false", "timeout_secs": 5, "paths": []}
check("C1 the gate is OFF by default (the shipped config)",
      vf.should_verify("fs.write", target, off) is False)
bad = {"enabled": True, "command": "false", "timeout_secs": 5, "paths": []}
out, report = vf.verify("fs.write", target, snap, {"ok": True}, workspace=TMP, c=bad)
check("C2 a red verify command rolls the write back",
      out.get("verifier_failed") is True and report.get("rolled_back") is True
      and open(target, encoding="utf-8").read() == "OLD\n", (out, report))
good = dict(bad, command="true")
with open(target, "w", encoding="utf-8") as f:
    f.write("NEW2\n")
out2, report2 = vf.verify("fs.write", target, snap, {"ok": True}, workspace=TMP, c=good)
check("C3 a green verify command keeps the change",
      out2.get("ok") is True and report2.get("green") is True
      and open(target, encoding="utf-8").read() == "NEW2\n", (out2, report2))
scoped = dict(bad, paths=["only/here"])
with open(target, "w", encoding="utf-8") as f:
    f.write("NEW3\n")
check("C4 an out-of-scope path is not verified",
      vf.should_verify("fs.write", target, scoped) is False)

# ---- D) the description is truthful -----------------------------------------
readme = open(os.path.join(REPO, "README.md"), encoding="utf-8").read().lower()
check("D1 the README documents the three headline mechanisms",
      "tool-output offload" in readme and "bounded context" in readme
      and "verification gates" in readme, "")
hits = []
for root_dir, dirs, fs in os.walk(os.path.join(REPO, "src")):
    for name in fs:
        if name.endswith(".py"):
            p = os.path.join(root_dir, name)
            if "SparkPulse" in open(p, encoding="utf-8", errors="replace").read():
                hits.append(p)
check("D2 the discontinued SparkPulse client is not claimed by the code", not hits, hits)
cl = open(os.path.join(REPO, "CHANGELOG.md"), encoding="utf-8").read()
check("D3 the retraction is documented in the changelog",
      "SparkPulse" in cl and "dropped" in cl)

print("\n%d/%d checks passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
