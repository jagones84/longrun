#!/usr/bin/env python3
"""v487 — the compaction policy is really FILE-driven and settable from the WebUI (JAG-487).

Regression: `compaction_config._PATH` went up only THREE parents from
`src/longrun/model/compaction_config.py`, landing on `src/config/compaction.yaml`
(nonexistent). The loader therefore served the hard-coded defaults forever and every
edit to `config/compaction.yaml` was dead — while the old source-lock tests passed
because the defaults equal the shipped values.

This test drives the REAL loader against a scratch pair of files, proves the overlay
precedence and validation, and source-locks the WebUI half (Context-panel inputs +
`/api/compaction/policy`).

Run: python3 tests/acceptance/v487_compaction_policy.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v487-")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.model import compaction_config as cc   # noqa: E402
from longrun.model import rllm                      # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- A) the shipped path is the REPO config, not src/config ------------------
check("A1 the policy path resolves to <repo>/config/compaction.yaml",
      os.path.isfile(cc.path())
      and os.path.normpath(cc.path()) == os.path.normpath(os.path.join(REPO, "config", "compaction.yaml")),
      cc.path())
check("A2 the overlay lives next to it as config/compaction.local.yaml",
      os.path.dirname(cc.local_path()) == os.path.dirname(cc.path())
      and os.path.basename(cc.local_path()) == "compaction.local.yaml",
      cc.local_path())

# ---- B) isolate the loader on a scratch pair --------------------------------
MAIN = os.path.join(TMP, "compaction.yaml")
LOCAL = os.path.join(TMP, "compaction.local.yaml")
with open(MAIN, "w", encoding="utf-8") as f:
    f.write("compaction:\n  trigger_pct: 70\n  target_pct: 30\n  keep_recent: 4\n")
cc._PATH, cc._LOCAL_PATH = MAIN, LOCAL
cc.reset_cache()
cur = cc.load(force=True)
check("B1 the shipped file drives the values", cur["trigger_pct"] == 70.0
      and cur["target_pct"] == 30.0 and cur["keep_recent"] == 4, cur)
check("B2 the overlay does not exist yet", not os.path.isfile(LOCAL))

with open(MAIN, "w", encoding="utf-8") as f:
    f.write("compaction:\n  trigger_pct: 66\n  target_pct: 20\n  keep_recent: 6\n")
cc.reset_cache()
cur = cc.load(force=True)
check("B3 editing the file changes the LIVE policy (no restart)",
      cur["trigger_pct"] == 66.0 and cur["target_pct"] == 20.0 and cur["keep_recent"] == 6, cur)
check("B4 rllm's legacy constants read the SAME file",
      float(rllm.AUTOCOMPACT_PCT) == 66.0 and float(rllm.AUTOCOMPACT_TARGET_PCT) == 20.0
      and int(rllm.KEEP_RECENT) == 6,
      (rllm.AUTOCOMPACT_PCT, rllm.AUTOCOMPACT_TARGET_PCT, rllm.KEEP_RECENT))

# ---- C) the overlay wins and the shipped file is untouched ------------------
saved = cc.save(trigger_pct=60, target_pct=25, keep_recent=3)
check("C1 save() writes the overlay and returns the NEW policy",
      os.path.isfile(LOCAL) and saved["trigger_pct"] == 60.0
      and saved["target_pct"] == 25.0 and saved["keep_recent"] == 3, saved)
check("C2 the shipped file is not rewritten (comments survive)",
      open(MAIN, encoding="utf-8").read().strip()
      == "compaction:\n  trigger_pct: 66\n  target_pct: 20\n  keep_recent: 6")
check("C3 the overlay wins over the shipped file",
      cc.load(force=True)["trigger_pct"] == 60.0)
check("C4 rllm reflects the overlay immediately (next turn, no restart)",
      float(rllm.AUTOCOMPACT_PCT) == 60.0 and float(rllm.AUTOCOMPACT_TARGET_PCT) == 25.0
      and int(rllm.KEEP_RECENT) == 3)

# ---- D) validation -----------------------------------------------------------
for name, kw in (("trigger <= 0", {"trigger_pct": 0}),
                 ("trigger > 100", {"trigger_pct": 101}),
                 ("target >= trigger", {"target_pct": 99}),
                 ("keep < 1", {"keep_recent": 0}),
                 ("keep > 50", {"keep_recent": 51}),
                 ("non-numeric", {"trigger_pct": "abc"})):
    try:
        cc.save(**kw)
        ok = False
        err = "accepted"
    except (TypeError, ValueError) as e:
        ok, err = True, str(e)
    check("D " + name + " is rejected", ok, err)
check("D6 a rejected save leaves the policy intact",
      cc.load(force=True)["trigger_pct"] == 60.0)

# ---- E) the WebUI half --------------------------------------------------------
ui = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
api = open(os.path.join(REPO, "src", "longrun", "core", "httpapi.py"), encoding="utf-8").read()
check("E1 the API exposes GET/POST /api/compaction/policy",
      api.count('"/api/compaction/policy"') >= 2
      and "def compaction_policy(" in api and "def set_compaction_policy(" in api)
check("E2 the Context panel has trigger/target/keep inputs that auto-save on change",
      'id="cmpTrigger"' in ui and 'id="cmpTarget"' in ui and 'id="cmpKeep"' in ui
      and "async function saveCompactionPolicy(" in ui
      and ui.count('data-change="saveCompactionPolicy"') == 3
      and 'data-call="saveCompactionPolicy"' not in ui)
check("E3 the panel shows the live policy and where it is stored",
      "async function loadCompactionPolicy(" in ui
      and 'api("GET", "/api/compaction/policy")' in ui
      and "config/compaction.local.yaml" in ui)
check("E4 the panel names the current trigger in the context detail",
      "auto-compact at" in api)
# JAG-523: a manual compaction that fails for a SEMANTIC reason (unknown session,
# nothing to compact) used to answer 404 — a logic error disguised as a missing
# route, and inconsistent with /api/compaction/policy right below it.
_route_head = 'if path == "/api/context/compact":'
_cmp_route = api.split(_route_head, 1)[1].split("if path == ", 1)[0] if _route_head in api else ""
check("E5 a failed manual compaction is a 400 (bad request), never a 404",
      "else 400, res)" in _cmp_route and "else 404, res)" not in _cmp_route,
      _cmp_route.strip().splitlines()[0][:90] if _cmp_route.strip() else "route missing")

# ---- F) a reasoning summarizer that returns ONLY thoughts must be retried ----
from longrun.core import server as _srv      # noqa: E402,F401  (import order)
from longrun.core import httpapi             # noqa: E402

_calls = []


def _fake_stream(messages, model, role, cb, **kw):
    _calls.append(kw.get("max_tokens"))
    if len(_calls) == 1:
        return "", "thinking about the transcript…", model
    return "- decision: keep SQLite", "", model


httpapi.stream_with_fallback = _fake_stream
out = httpapi._summarize_with_llm(
    [{"role": "user", "content": "decision: keep SQLite"},
     {"role": "assistant", "content": "noted"}])
check("F1 an empty answer (only thoughts) triggers ONE retry with a bigger budget",
      len(_calls) == 2 and _calls[1] > _calls[0], _calls)
check("F2 the retry's answer is the summary", out == "- decision: keep SQLite", out)

_calls.clear()


def _fake_ok(messages, model, role, cb, **kw):
    _calls.append(kw.get("max_tokens"))
    return "- already good", "", model


httpapi.stream_with_fallback = _fake_ok
out = httpapi._summarize_with_llm([{"role": "user", "content": "x"}])
check("F3 a normal answer is NOT retried", len(_calls) == 1 and out == "- already good",
      (_calls, out))
check("F4 the retry is source-locked in httpapi",
      "if not (answer or \"\").strip() and (think or \"\").strip():" in api
      and "output_chars * 3 // 4" in api)

# ---- G) JAG-533: the summarizer reads the WHOLE old transcript --------------
# `input_max_chars` is the window of ONE call. The old code cut the transcript to
# head 70% + tail 30% and DROPPED the middle, so a 100k-token session was
# summarized from ~10k tokens: a cheap call whose summary could not contain what
# the model never read. Now every part is summarized and the parts are merged.
from longrun.core import httpapi as _h  # noqa: E402

prompts = []


def _fake_map(messages, model, role, cb, **kw):
    body = messages[0]["content"]
    prompts.append(body)
    n = len(prompts)
    return ("SUM%d:" % n) + ("s" * 2500), "", model


_orig_stream = _h.stream_with_fallback
try:
    _h.stream_with_fallback = _fake_map
    markers = ["MARKER%02d" % i for i in range(30)]
    msgs = [{"role": "user", "content": m + " " + ("x" * 3000)} for m in markers]
    meta = {}
    out = _h._summarize_with_llm(msgs, meta=meta)
    joined = "\n".join(prompts)
    window = int(rllm.SUMMARIZER_INPUT_CHARS)
    check("G1 a transcript bigger than one window is split into several calls",
          len(prompts) > 1, len(prompts))
    check("G2 NO message is dropped: every marker reaches the model",
          all(m in joined for m in markers)
          and "middle omitted" not in joined,
          [m for m in markers if m not in joined])
    check("G3 each part says which part it is", "PART 1 of" in prompts[0])
    check("G4 no prompt exceeds the per-call window",
          all(len(p) <= window + 1200 for p in prompts),
          [len(p) for p in prompts])
    check("G5 the part summaries are merged into one block",
          "PARTIAL SUMMARIES" in joined and out.startswith("SUM"))
    check("G6 meta reports how many parts were summarized",
          meta.get("parts") == 3 and int(meta.get("parts")) == len(prompts) - 1,
          (meta, len(prompts)))
finally:
    _h.stream_with_fallback = _orig_stream

# G7: the part cap is stated in the input, never a silent gap.
_lines = ["user: " + ("y" * 900) for _ in range(20)]
_parts = _h._summarizer_parts(_lines, 1000, 4)
check("G7 past max_parts the omission is STATED in the input, not silent",
      len(_parts) == 4 and any("omitted from the middle" in p for p in _parts),
      len(_parts))
# G8: one oversized message is truncated with a marker instead of overflowing.
_big = _h._summarizer_parts(["user: " + ("z" * 5000)], 1000, 8)
check("G8 an oversized single message is truncated with a visible marker",
      len(_big) == 1 and len(_big[0]) <= 1200 and "oversized message truncated" in _big[0],
      len(_big[0]))

print("---")
okc = sum(results)
print("\nv487: %d/%d PASS" % (okc, len(results)))
sys.exit(0 if okc == len(results) else 1)
