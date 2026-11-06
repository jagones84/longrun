#!/usr/bin/env python3
"""v839 — a request that FORBIDS a file is not a request for a file (read-back).

Live evidence (session bfce1004dd85, 2026-11-06): the user asked for the answer in
the chat — "do not write any file: the answer belongs in the chat" — and the
read-back then told the model "you have written NO file … the request names a
deliverable file, so a prose answer is not the result". The model spent its closing
round arguing with the harness instead of reporting the two command outputs.

Cause: `names_artifact` looked for a produce VERB (`write`) and an artifact WORD
(`file`) anywhere in the text, so a negation read as an instruction. A negation
about a DESTINATION ("do not write to /tmp") must still leave the deliverable
itself required.

Deterministic, offline, no model. Run: python3 tests/acceptance/v839_negated_artifact.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.plan import artifacts as A  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail else ""))


# The request that produced the bad round, verbatim (only whitespace normalised).
LIVE = ("I need a small operational audit of this machine, done carefully and reported "
        "in full. First run `uname -s` with the shell tool. Then run `python3 -c "
        "'print(6*7)'` with the shell tool and keep the raw output. Then look at the two "
        "outputs together and tell me, in plain prose, whether both commands succeeded, "
        "what each of them printed, and anything surprising you noticed while running "
        "them. Do not skip a step, do not guess what a command would print if you have "
        "not actually run it, and do not write any file: the answer belongs in the chat. "
        "If a command fails, report the failure verbatim instead of substituting a value "
        "you think is more plausible. I care about the exact text the machine produced, "
        "including the platform name and the arithmetic result, and I will compare your "
        "report against my own run of the same two commands, so accuracy matters more "
        "than speed here. Take the time you need, but do not pad the answer with a "
        "narrative of your process: end with the findings, not with a description of "
        "what you intended to do or of the tools you chose to use, because the intent is "
        "already known to me and only the measured result is new information for me.")

# --- A: the live request is not an artifact request ---------------------------
check("A1 names_artifact says NO for the live request",
      A.names_artifact(LIVE) is False, A.names_artifact(LIVE))

ws = tempfile.mkdtemp(prefix="v839-")
check("A2 nothing_written stays silent for it",
      A.nothing_written(LIVE, workspace=ws, since=0.0) is None,
      A.nothing_written(LIVE, workspace=ws, since=0.0))

# --- B: the same request without the negation still names a deliverable -------
asked = LIVE.replace("do not write any file: the answer belongs in the chat",
                     "write the result to out/report.md")
check("B1 the same text WITH a deliverable is still a file request",
      A.names_artifact(asked) is True)

# --- C: a negation about a DESTINATION leaves the deliverable required --------
check("C1 'do not write to /tmp' is about the place, not the deliverable",
      A.names_artifact("Create the CSV in out/ but do not write to /tmp.") is True,
      A.names_artifact("Create the CSV in out/ but do not write to /tmp."))
check("C2 an explicit path wins over any negation",
      A.names_artifact("Do not write anything else; produce out/report.md.") is True)

# --- D: regressions this guard must not reintroduce --------------------------
check("D1 a GAIA question with a list is not a deliverable",
      A.names_artifact("Extract a comma separated list of numbers and/or strings "
                       "from the page and answer with it.") is False)
check("D2 a plain request for a report is still a deliverable",
      A.names_artifact("Write a short report on the Q3 revenue numbers.") is True)
check("D3 'no file' alone is not a request either",
      A.names_artifact("Summarise the ledger in one sentence; no file needed.") is False,
      A.names_artifact("Summarise the ledger in one sentence; no file needed."))

print("---")
ok = sum(RESULTS)
print("%d/%d PASS" % (ok, len(RESULTS)))
sys.exit(0 if ok == len(RESULTS) else 1)
