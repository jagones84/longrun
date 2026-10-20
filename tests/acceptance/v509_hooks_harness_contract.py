#!/usr/bin/env python3
"""v509 — Hooks and Harness settings DO what the panels claim (JAG-512).

The Settings ▸ Hooks and Settings ▸ Harness panels are only useful if the values
they persist are actually CONSUMED. This locks the contract, deterministically:

  * hooks: PreToolUse exit 2 BLOCKS (reason = stdout), a non-zero exit is advisory
    unless block_on_fail, the matcher is a regex, PostToolUse gets
    $LONGRUN_OBSERVATION, a slow hook is killed at timeout_secs (124), and
    tools.execute() refuses a blocked call (exit 126, hook_blocked);
  * the harness sections are READ by their consumers: keepgoing (runtime),
    verify (apply-only-if-green + rollback), bestofn (n / min_score / choose),
    difficulty (score -> level -> n / rounds), selfevolve (min_len / mine).

Everything runs against a TEMP hooks file and explicit config overrides — no live
server, no network, no model. Run: python3 tests/acceptance/v509_hooks_harness_contract.py
"""
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v509-")
HOOKS = os.path.join(TMP, "hooks.yaml")
with open(HOOKS, "w", encoding="utf-8") as f:
    f.write(
        "hooks:\n"
        "  - event: PreToolUse\n"
        "    matcher: '^shell\\.'\n"
        "    command: \"printf 'blocked-v509'; exit 2\"\n"
        "    timeout_secs: 5\n"
        "  - event: PreToolUse\n"
        "    matcher: '^fs\\.'\n"
        "    command: 'exit 1'\n"
        "    timeout_secs: 5\n"
        "  - event: PreToolUse\n"
        "    matcher: '^glob\\.'\n"
        "    command: 'exit 3'\n"
        "    block_on_fail: true\n"
        "    timeout_secs: 5\n"
        "  - event: PostToolUse\n"
        "    matcher: ''\n"
        "    command: \"printf 'obs=%s' \\\"$LONGRUN_OBSERVATION\\\"\"\n"
        "    timeout_secs: 5\n"
        "  - event: PreToolUse\n"
        "    matcher: '^slow\\.'\n"
        "    command: 'sleep 3'\n"
        "    timeout_secs: 1\n")
# An explicit hooks file disables the WebUI overlay, so the test never picks up the
# operator's live hooks.
os.environ["LONGRUN_HOOKS"] = HOOKS
os.environ.setdefault("LONGRUN_DATA_DIR", os.path.join(TMP, "data"))
os.environ.setdefault("LONGRUN_CONFIG_DIR", os.path.join(TMP, "cfg"))
os.environ.setdefault("LONGRUN_DB", os.path.join(TMP, "events.db"))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import hooks as H            # noqa: E402
from longrun.plan import bestofn as BN          # noqa: E402
from longrun.plan import difficulty as DF       # noqa: E402
from longrun.plan import keepgoing as KG        # noqa: E402
from longrun.plan import verify as VF           # noqa: E402
from longrun.util import selfevolve as SE       # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---------------------------------------------------------------- hooks ------
H.load(reload=True)
check("A1 the temp hooks file is the one loaded (no overlay)",
      len(H.load()) == 5 and H.CONFIG == HOOKS)

blk = H.run("PreToolUse", tool="shell.exec", args={"command": "echo x"})
check("A2 PreToolUse exit 2 BLOCKS and reason = stdout",
      blk["blocked"] is True and "blocked-v509" in blk["reason"], blk["reason"])

adv = H.run("PreToolUse", tool="fs.read")
check("A3 exit 1 without block_on_fail is ADVISORY",
      adv["blocked"] is False and adv["results"][0]["exit_code"] == 1)

strict = H.run("PreToolUse", tool="glob.list")
check("A4 exit 3 WITH block_on_fail DOES block",
      strict["blocked"] is True and strict["results"][0]["exit_code"] == 3,
      strict.get("reason"))

post = H.run("PostToolUse", tool="fs.read", observation="hello-v509")
check("A5 PostToolUse receives $LONGRUN_OBSERVATION",
      post["results"] and "obs=hello-v509" in post["results"][0]["stdout"])

check("A6 the matcher is a REGEX (non-matching tool runs nothing)",
      H.run("PreToolUse", tool="web.search")["results"] == [])

t0 = time.time()
slow = H.run("PreToolUse", tool="slow.thing")
check("A7 timeout_secs kills the hook (124) without hanging the run",
      slow["results"] and slow["results"][0]["exit_code"] == 124
      and time.time() - t0 < 3, {"s": round(time.time() - t0, 1)})

from longrun.tools import tools as T            # noqa: E402
res = T.execute("shell.exec", {"command": "echo must-not-run"})
check("A8 tools.execute() refuses a blocked tool call (exit 126)",
      res.get("ok") is False and res.get("hook_blocked") is True
      and res.get("exit_code") == 126, res.get("error"))

# ------------------------------------------------------------- harness -------
RT = {"keepgoing_max": 4, "no_progress_rounds": 1, "max_wall_secs": 60,
      "subagent_max_depth": 1, "autocontinue": False}
kc = KG.cfg(override=RT)
check("B1 keepgoing.cfg honours the runtime block (and the override)",
      kc["keepgoing_max"] == 4 and kc["autocontinue"] is False, kc)

TARGET = os.path.join(TMP, "scope.txt")
with open(TARGET, "w", encoding="utf-8") as f:
    f.write("ORIGINAL\n")
SNAP = {"exists": True, "content": "ORIGINAL\n"}
RED = {"enabled": True, "command": "python3 -c 'import sys; sys.exit(1)'",
       "timeout_secs": 20, "paths": [TARGET]}
GREEN = dict(RED, command="true")

check("B2 the verifier path scope is honoured",
      VF.in_scope(TARGET, RED) is True and VF.in_scope("/etc/passwd", RED) is False)
check("B3 disabled => should_verify is False (zero overhead)",
      VF.should_verify("fs.write", TARGET, dict(RED, enabled=False)) is False)

with open(TARGET, "w", encoding="utf-8") as f:
    f.write("CHANGED\n")
out, rep = VF.verify("fs.write", TARGET, SNAP, {"ok": True}, workspace=TMP, c=RED)
back = open(TARGET, encoding="utf-8").read()
check("B4 RED => the write is ROLLED BACK to the pre-image",
      out.get("ok") is False and out.get("verifier_failed") is True
      and rep.get("rolled_back") is True and back == "ORIGINAL\n",
      {"report": rep, "file": back})

with open(TARGET, "w", encoding="utf-8") as f:
    f.write("CHANGED\n")
out2, rep2 = VF.verify("fs.write", TARGET, SNAP, {"ok": True}, workspace=TMP, c=GREEN)
check("B5 GREEN => the write stands",
      out2.get("ok") is True and rep2.get("green") is True)

BNC = {"enabled": True, "n": 3, "min_score": 0.4, "adaptive": False}
check("B6 best-of-N: n_of / choose / min_score",
      BN.n_of(BNC) == 3
      and BN.choose(["a", "b"], lambda t: 0.9 if t == "b" else 0.1, BNC)[0] == "b"
      and BN.choose(["a"], lambda t: 0.1, BNC)[0] is None
      and BN.n_of(dict(BNC, enabled=False)) == 1)

DFC = {"enabled": True, "easy_n": 1, "medium_n": 2, "hard_n": 5,
       "medium_at": 0.30, "hard_at": 0.60}
# the keys agent.py actually feeds
easy_s = {"open_nodes": 0, "msg_words": 10}
hard_s = {"open_nodes": 3, "msg_words": 150, "prev_error": True}
check("B7 difficulty: the agent's own signals drive level -> n -> rounds",
      DF.estimate(easy_s, DFC)["level"] == "easy"
      and DF.estimate(hard_s, DFC)["level"] == "hard"
      and DF.n_for(hard_s, DFC) == 5
      and DF.rounds_for(4, hard_s, DFC) == 8,
      {"easy": DF.estimate(easy_s, DFC), "hard": DF.estimate(hard_s, DFC)})

SEC = {"min_len": 3, "min_count": 2, "max_len": 4, "category": "auto"}
seqs = [["fs.read", "fs.edit", "shell.exec"], ["fs.read", "fs.edit", "shell.exec"]]
check("B8 selfevolve: min_len / min_count gate the mining",
      len(SE.mine(seqs, SEC)) >= 1 and SE.mine([["fs.read", "fs.edit"]], SEC) == [])

print("---")
ok = sum(results)
print("\nv509: %d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
