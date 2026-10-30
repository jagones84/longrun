#!/usr/bin/env python3
"""v732 — a batched observation is never SHORTENED behind the model's back.

Found 2026-10-30 by reading the transcript of the Longrun arm on JobBench
`online_merchants/task1` (session `b56a88b42136`, 30/58 vs opencode's 48/58).
The turn asked for two reference files in ONE batch. `_chat_batch` cut every
observation at 4000 chars with no marker, so `customer_inquiries.csv` (5061
chars, 12 rows) reached the model ending at `INQ-010`: `INQ-011` — the one row
the rubric was about — never appeared in the session at all, and the turn wrote
"Read customer_inquiries.csv (10 inquiries)" as if the file ended there.

The single-call path had already been fixed (JAG-88: offload, never truncate);
the batch path kept the old silent cut. This test locks the shared rule:

  A  everything that fits is handed over WHOLE, in the order it was asked for
  B  what does not fit is OFFLOADED (written out in full, referenced), not cut
  C  the real case: 5061 + 1733 chars, 6000 budget -> the file survives intact
  D  a failing offload yields a marker, never a crash and never a cut
  E  both paths share one policy (no per-call cap, one budget)

Deterministic and offline: temp dirs, no model, no network.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="longrun-v732-")
for name, tail in {
    "LONGRUN_DATA_DIR": "data",
    "LONGRUN_CONFIG_DIR": "cfg",
    "LONGRUN_DB": "events.db",
    "LONGRUN_SESSIONS_DIR": "sessions",
    "LONGRUN_GRAPH_DIR": "graphs",
}.items():
    os.environ[name] = os.path.join(TMP, tail)
sys.path.insert(0, os.path.join(REPO, "src"))

# import order matters: `agent` imports `server`, which imports `agent` back.
from longrun.core import server  # noqa: E402,F401
from longrun.agent import agent as A  # noqa: E402

SRC = open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"),
           encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


def _row(i):
    """One CSV row shaped like a customer inquiry, ~420 chars."""
    return ("INQ-%03d,Customer %d,c%d@example.com,2024-01-%02d,Subject %d,"
            "Returns,Product %d,ORD-%05d,\"%s\",Medium,Open\n"
            % (i, i, i, i % 28 + 1, i, i, 78000 + i, "x" * 380))


CSV12 = "Inquiry_ID,Customer_Name\n" + "".join(_row(i) for i in range(1, 13))
PERF = "Product_ID,Return_Rate\n" + "".join(
    "SKU-%03d,4.%d%%\n" % (i, i % 10) for i in range(1, 18))

# A — everything fits: nothing is touched -------------------------------------
_small = [{"tool": "fs.read", "ok": True, "obs": "abc"},
          {"tool": "fs.read", "ok": True, "obs": "def"}]
_fit = A._fit_batch_observations(_small, 6000, lambda t, o: "REF")
check("A1 a batch inside the budget is handed over verbatim",
      [o for _r, o in _fit] == ["abc", "def"], _fit)
check("A2 the order the model asked for is preserved",
      [r["obs"] for r, _o in _fit] == ["abc", "def"])

# B — overflow is offloaded, never cut ----------------------------------------
_big = [{"tool": "fs.read", "ok": True, "obs": "y" * 5000},
        {"tool": "shell.exec", "ok": True, "obs": "z" * 5000}]
_seen = []


def _fake_offload(tool, text):
    _seen.append((tool, len(text)))
    return "[offloaded %s: %d chars]" % (tool, len(text))


_fit_b = A._fit_batch_observations(_big, 6000, _fake_offload)
check("B1 the first observation is whole (5000 chars, not a 4000-char cut)",
      len(_fit_b[0][1]) == 5000, len(_fit_b[0][1]))
check("B2 the one that no longer fits is offloaded WHOLE, not shortened",
      _fit_b[1][1] == "[offloaded shell.exec: 5000 chars]"
      and _seen == [("shell.exec", 5000)], (_fit_b[1][1], _seen))
check("B3 the batch never exceeds the shared budget",
      sum(len(o) for _r, o in _fit_b) <= 6000,
      sum(len(o) for _r, o in _fit_b))

# C — the real case ----------------------------------------------------------
_real = [{"tool": "fs.read", "ok": True, "obs": CSV12},
         {"tool": "fs.read", "ok": True, "obs": PERF}]
_fit_c = A._fit_batch_observations(_real, 6000, _fake_offload)
check("C1 the 12-row CSV reaches the model with its LAST row intact",
      "INQ-012" in _fit_c[0][1] and len(_fit_c[0][1]) == len(CSV12),
      len(_fit_c[0][1]))
check("C2 the second file is referenced rather than silently truncated",
      _fit_c[1][1].startswith("[offloaded fs.read: "), _fit_c[1][1][:80])

# D — a failing offload ------------------------------------------------------
def _boom(tool, text):
    raise RuntimeError("disk full")


_fit_d = A._fit_batch_observations(_big, 6000, _boom)
check("D1 a failing offload is named, not hidden and not fatal",
      _fit_d[1][1].startswith("[shell.exec: 5000 chars, could not be written"),
      _fit_d[1][1][:80])
check("D2 the turn still gets both results back",
      len(_fit_d) == 2 and _fit_d[0][1] == "y" * 5000)

# E — one policy for both paths ----------------------------------------------
_batch_src = SRC.split("def _apply_chat_batch")[1].split("\ndef ")[0]
check("E1 no model-facing observation is cut at 4000 chars any more "
      "(a UI card may still bound its own preview)",
      'str(obs)[:4000]' not in SRC and '"obs": _dobs[:4000]' not in SRC,
      "still cutting an observation")
check("E2 the batch path spends ONE shared budget through the helper",
      "_fit_batch_observations(" in _batch_src and "CHAT_TOOL_OBS_LIMIT" in _batch_src)
check("E3 a single tool result is bounded by the SAME ceilings, not 4000",
      "str(obs)[:CHAT_OBS_FULL]" in SRC)
check("E4 the limit is the documented 6000 unless the operator overrides it",
      A.CHAT_TOOL_OBS_LIMIT >= 6000, A.CHAT_TOOL_OBS_LIMIT)

# E5 — the real offload keeps the WHOLE text on disk -------------------------
_sess = {"id": "v732"}
_ref = A._offload_observation(_sess, "fs.read", CSV12)
_written = open(os.path.join(TMP, "data", "offload", "v732", "001_fs.read.txt"),
                encoding="utf-8").read()
check("E5 the offloaded file holds every row (INQ-012 included) and the model "
      "is told where it is", "INQ-012" in _written and "FULL OUTPUT FILE" in _ref,
      _ref[:200])

print("\n---")
print("v732: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
