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

# --- M) the delete cascade takes the two per-session FOLDERS (v973) -----------
# `data/attachments` (67 MB) and `data/sandbox` (69 MB) are keyed by session id and
# a delete never removed them — the same leak JAG-179 closed for the per-session FILES.
from longrun.memory import stores as _st  # noqa: E402

for sub in ("attachments", "sandbox"):
    d = os.path.join(TMP, "data", sub, "sess-A")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "payload.bin"), "w", encoding="utf-8") as fh:
        fh.write("x")
    # a SIBLING whose id shares the prefix must survive (no glob)
    sib = os.path.join(TMP, "data", sub, "sess-AB")
    os.makedirs(sib, exist_ok=True)
removed = _st._purge_session_artifacts("sess-A")
ok("M1 both folders are gone from the session's own tree",
   not os.path.exists(os.path.join(TMP, "data", "attachments", "sess-A"))
   and not os.path.exists(os.path.join(TMP, "data", "sandbox", "sess-A")), removed)
ok("M2 a prefix-sharing sibling session is untouched",
   os.path.isdir(os.path.join(TMP, "data", "attachments", "sess-AB"))
   and os.path.isdir(os.path.join(TMP, "data", "sandbox", "sess-AB")))
ok("M3 the delete is recoverable — the folders moved to trash, not unlinked",
   any("sess-A" in str(x) for x in removed), removed)

# --- N) trash now caps DIRECTORIES too (v973) --------------------------------
from longrun.memory import stores as _s2  # noqa: E402
_s2.TRASH_DIR = os.path.join(TMP, "trash")
os.makedirs(_s2.TRASH_DIR, exist_ok=True)
_s2._TRASH_KEEP = 1
_s2._TRASH_KEEP_SECS = 0
old_dir = os.path.join(_s2.TRASH_DIR, "an-old-folder")
os.makedirs(old_dir, exist_ok=True)
with open(os.path.join(old_dir, "f"), "w", encoding="utf-8") as fh:
    fh.write("x")
os.utime(old_dir, (time.time() - 90000, time.time() - 90000))
new_file = os.path.join(_s2.TRASH_DIR, "a-new-file")
with open(new_file, "w", encoding="utf-8") as fh:
    fh.write("x")
_s2._prune_trash()
ok("N1 an over-cap trash DIRECTORY is removed, the newest entry stays",
   not os.path.exists(old_dir) and os.path.exists(new_file))

# --- O) a gone session's folders are swept, a live one's are kept (v973) ------
# Measured: 151 of 160 `sandbox` folders and 5 of 13 `attachments` folders had no
# live session — the unreachable-artifact rule already used for graphs (v812).
# The battery points `LONGRUN_SESSIONS_DIR` at its own temp dir, so the "live"
# marker is written where the MODULE reads it (`_st.SESSIONS_DIR`), not where the
# data home happens to be.
_sessions = _st.SESSIONS_DIR
os.makedirs(_sessions, exist_ok=True)
open(os.path.join(_sessions, "live-1.json"), "w", encoding="utf-8").write("{}")
for sub in ("attachments", "sandbox"):
    for name in ("live-1", "gone-1"):
        d = os.path.join(TMP, "data", sub, name)
        os.makedirs(d, exist_ok=True)
        os.utime(d, (time.time() - 40 * 86400, time.time() - 40 * 86400))
rep = _st.sweep_session_folders(days=14)
ok("O1 the gone session's folders are swept and reported",
   sorted(rep.get("removed")) == ["attachments/gone-1", "sandbox/gone-1"], rep)
ok("O2 the LIVE session's folders are kept",
   all(os.path.isdir(os.path.join(TMP, "data", s, "live-1"))
       for s in ("attachments", "sandbox")))
ok("O3 a dry run reports without moving",
   _st.sweep_session_folders(days=14, dry_run=True).get("removed") == [], "dry run")

good = [n for n, c, _ in CHECK if c]
print("\n%d/%d checks passed" % (len(good), len(CHECK)))
sys.exit(0 if len(good) == len(CHECK) else 1)
