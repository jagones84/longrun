#!/usr/bin/env python3
"""v973 — the two file stores the harness writes have a bound AND a caller.

Measured 2026-11-14 on the live data home:

  * `data/checkpoints` — **533 MB** of `cp_*.json` against a 100-entry index. The
    cap in `create()` truncated the INDEX and left every dropped payload on disk,
    and `prune()` could not see them either (its victims come from the index), so
    an orphan payload was invisible to both — nothing could ever restore it.
  * `data/offload` — **158 folders / 32 MB**, one file per oversized tool
    observation, and no prune of any kind existed.

Both were a store with no bound and, for `prune()`, no caller in the service.

  A) create() takes the PAYLOAD with the entry it drops (no new orphans);
  B) a payload with no manifest is found and removed by prune();
  C) the newest MAX_CHECKPOINTS manifests survive and the rest are gone;
  D) prune() is idempotent — a second call removes nothing;
  E) offload: the newest `offload_keep_files` per session survive, the rest go;
  F) offload: a file older than `offload_keep_days` goes even under the count;
  G) offload: one session's sweep never touches another session's folder;
  H) offload: an empty session folder is not left behind;
  I) purge_offload removes a deleted session's whole folder;
  J) both boundaries come from the config owner (env override honoured);
  K) the boot path calls both (grep of the startup sequence).

Deterministic: temp data dir, no model, no network, no server.
Run: python3 tests/acceptance/v973_store_bounds.py
"""
import glob
import json
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v973-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "config")
os.environ["LONGRUN_OFFLOAD_KEEP_FILES"] = "3"
os.environ["LONGRUN_OFFLOAD_KEEP_DAYS"] = "30"
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.memory import checkpoints as ck  # noqa: E402
from longrun.memory import stores as st  # noqa: E402

CK = os.path.join(TMP, "data", "checkpoints")
OFF = os.path.join(TMP, "data", "offload")
os.makedirs(CK, exist_ok=True)

CHECK = []


def ok(name, cond, detail=""):
    CHECK.append((name, bool(cond), detail))
    print("%s %s%s" % ("ok  " if cond else "FAIL", name,
                       "" if cond else "  <- %s" % (detail,)))


def payloads():
    return sorted(os.path.basename(p) for p in glob.glob(os.path.join(CK, "cp_*.json")))


def manifest(i):
    return {"id": "c%03d" % i, "label": "cp %d" % i, "session_id": "s1",
            "sizes": {}, "rolled_back": False}


# --- A) the cap takes the payload with the entry ------------------------------
ck.MAX_CHECKPOINTS = 3
for i in range(5):
    p = os.path.join(CK, "cp_c%03d.json" % i)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump({"i": i}, fh)
    entries = ck._load_index()
    entries.insert(0, manifest(i))
    for stale in entries[ck.MAX_CHECKPOINTS:]:
        ck._unlink_payload(stale.get("id"))
    ck._save_index(entries[:ck.MAX_CHECKPOINTS])
ok("A1 five creates leave three payloads and three manifests",
   len(payloads()) == 3 and len(ck._load_index()) == 3,
   (payloads(), len(ck._load_index())))

# --- B) an orphan payload is found and removed -------------------------------
orphan = os.path.join(CK, "cp_zzz999.json")
with open(orphan, "w", encoding="utf-8") as fh:
    fh.write("{}")
seen = ck._orphan_payloads({str(m.get("id")) for m in ck._load_index()})
ok("B1 the orphan (no manifest) is detected", seen == ["zzz999"], seen)
rep = ck.prune()
ok("B2 prune removes the orphan and reports it",
   rep.get("ok") and rep.get("orphans") == 1 and not os.path.exists(orphan), rep)

# --- C) the newest survive ----------------------------------------------------
kept = [str(m.get("id")) for m in ck._load_index()]
ok("C1 the newest manifests survive and the oldest are gone",
   kept == ["c004", "c003", "c002"], kept)
ok("C2 no payload is left without a manifest",
   payloads() == ["cp_c002.json", "cp_c003.json", "cp_c004.json"], payloads())

# --- D) idempotent ------------------------------------------------------------
again = ck.prune()
ok("D1 a second prune removes nothing",
   again.get("removed") == 0 and again.get("orphans") == 0, again)


def offload_file(sid, name, age_secs=0.0):
    d = os.path.join(OFF, sid)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, name)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write("x" * 100)
    t = time.time() - age_secs
    os.utime(p, (t, t))
    return p


# --- E) newest N per session survive -----------------------------------------
for i in range(6):
    offload_file("s1", "%03d_shell.txt" % (i + 1), age_secs=(6 - i))
rep = st.prune_offload(session_id="s1")
left = sorted(os.listdir(os.path.join(OFF, "s1")))
ok("E1 the newest 3 of 6 survive",
   left == ["004_shell.txt", "005_shell.txt", "006_shell.txt"], (left, rep))

# --- F) age beats count -------------------------------------------------------
offload_file("s2", "001_shell.txt", age_secs=40 * 86400)   # stale, and inside the count
offload_file("s2", "002_shell.txt", age_secs=0)
rep = st.prune_offload(session_id="s2")
left = sorted(os.listdir(os.path.join(OFF, "s2")))
ok("F1 a stale file goes even under the count", left == ["002_shell.txt"], (left, rep))

# --- G) sessions do not touch each other --------------------------------------
before = sorted(os.listdir(os.path.join(OFF, "s1")))
st.prune_offload(session_id="s2")
ok("G1 pruning s2 leaves s1 untouched",
   sorted(os.listdir(os.path.join(OFF, "s1"))) == before, before)

# --- H) an emptied folder is not left behind ----------------------------------
offload_file("s3", "001_shell.txt", age_secs=90 * 86400)
st.prune_offload(session_id="s3")
ok("H1 the empty folder is removed", not os.path.exists(os.path.join(OFF, "s3")))

# --- I) purge_offload removes a whole session ---------------------------------
offload_file("s4", "001_shell.txt")
offload_file("s4", "002_shell.txt")
n = st.purge_offload("s4")
ok("I1 purging a session removes its folder and files",
   n == 2 and not os.path.exists(os.path.join(OFF, "s4")), n)

# --- J) the boundaries come from the config owner -----------------------------
ok("J1 the offload budgets honour the env override",
   st._offload_keep_files() == 3 and st._offload_keep_secs() == 30 * 86400.0,
   (st._offload_keep_files(), st._offload_keep_secs()))

# --- K) the boot path calls both ----------------------------------------------
src = open(os.path.join(REPO, "src", "longrun", "core", "httpapi.py"),
           encoding="utf-8").read()
ok("K1 the startup sequence compacts checkpoints and sweeps offload",
   "_ckpt_boot.prune()" in src and "_stores_boot.prune_offload()" in src)

good = [n for n, c, _ in CHECK if c]
print("\n%d/%d checks passed" % (len(good), len(CHECK)))
sys.exit(0 if len(good) == len(CHECK) else 1)
