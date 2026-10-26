#!/usr/bin/env python3
"""v676 — compaction keeps the recurring DETAILS, not only the narrative (F6).

An LLM summary retains <=16.0% of the recurring details a long task needs to
continue; a mechanical anchor index retains 79.1%
(papers/compactbench_2610.31710.txt:33-43, table-4 note :1337-1339: "at most 40
sorted values per kind"). Longrun kept no mechanical detail when the summarizer
answered — only when it failed.

Contract locked here:
  * `anchors_block(messages)` extracts paths / `$` commands / `pkg==version` pins,
    first-appearance order, deduped, capped, skipping a previous summary block,
    and is deterministic;
  * `exclude` drops what the carried body already lists (no pile-up);
  * `compact()` appends the block AFTER the body is final, on the LLM path, the
    extractive path and past the COMBINED cap;
  * a transcript with nothing mechanical adds no empty header.

Deterministic, no network, no model.
"""
import os
import sys
import tempfile

_tmp = tempfile.mkdtemp(prefix="sf-v676-")
os.environ["LONGRUN_DATA_HOME"] = os.path.join(_tmp, "home")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(_tmp, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_tmp, "config")
for _d in ("LONGRUN_DATA_DIR", "LONGRUN_CONFIG_DIR"):
    os.makedirs(os.environ[_d], exist_ok=True)

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.model import context_engine as CE  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


MSGS = [
    {"role": "user", "content": "read src/longrun/core/server.py first"},
    {"role": "assistant", "content": "opened src/longrun/core/server.py and config/compaction.yaml"},
    {"role": "tool", "content": "[harness] Observation for tool shell.exec:\n$ pytest -q tests/acceptance/v670.py\n1 passed"},
    {"role": "user", "content": "we pinned pytest==8.2.1, keep it"},
    {"role": "assistant", "content": "noted: src/longrun/core/server.py stays as is"},
]

# ---- A: the extractor -------------------------------------------------------
_block = CE.anchors_block(MSGS)
check("A1 it starts with the stable anchor header",
      _block.startswith(CE.ANCHOR_PREFIX), _block[:60])
check("A2 paths are found once each, in first-appearance order",
      _block.count("src/longrun/core/server.py") == 1
      and "config/compaction.yaml" in _block
      and _block.index("src/longrun/core/server.py") < _block.index("config/compaction.yaml"),
      _block)
check("A3 a `$` command line is captured",
      "pytest -q tests/acceptance/v670.py" in _block, _block)
check("A4 a pinned version is captured",
      "pytest==8.2.1" in _block, _block)
check("A5 a previous summary block is not mined (no anchors from a summary)",
      CE.anchors_block([{"role": "system",
                         "content": CE.SUMMARY_PREFIX + "touched /a/b/c.py"}]) == "",
      CE.anchors_block([{"role": "system",
                         "content": CE.SUMMARY_PREFIX + "touched /a/b/c.py"}]))
check("A6 plain prose yields no block at all",
      CE.anchors_block([{"role": "user", "content": "hello there"}]) == "",
      repr(CE.anchors_block([{"role": "user", "content": "hello there"}])))
check("A7 it is deterministic",
      CE.anchors_block(MSGS) == _block, "two calls differ")
check("A8 `exclude` drops what the carried body already lists",
      "src/longrun/core/server.py" not in CE.anchors_block(MSGS, exclude=_block),
      CE.anchors_block(MSGS, exclude=_block))

_many = [{"role": "assistant",
          "content": " ".join("dir%d/file_%03d.py" % (i, i) for i in range(60))}]
_big = CE.anchors_block(_many)
_paths_line = [ln for ln in _big.splitlines() if ln.strip().startswith("paths:")]
_n_paths = len(_paths_line[0].split("paths:", 1)[1].split(",")) if _paths_line else 0
check("A9 the block is capped per kind and in total",
      _n_paths == CE.ANCHOR_MAX_ITEMS and len(_big) <= CE.ANCHOR_MAX_CHARS,
      (_n_paths, len(_big)))

# ---- B: the LLM path keeps them ---------------------------------------------
def _llm_summary(_msgs):
    return "SUMMARY: read a config file and ran the tests."   # omits path+command

_msgs, _st = CE.compact(MSGS, budget_tokens=10, keep_recent=1,
                        summarizer=_llm_summary, force=True)
_content = (_msgs[0] or {}).get("content", "")
check("B1 the summary is the LLM one, not the extractive fallback",
      _st.get("summary") == "llm", _st)
check("B2 the anchors are appended after the summary body",
      CE.ANCHOR_PREFIX in _content
      and _content.index("SUMMARY: read a config file") < _content.index(CE.ANCHOR_PREFIX),
      _content[:200])
check("B3 the path and the command the LLM dropped are still there",
      "src/longrun/core/server.py" in _content
      and "pytest -q tests/acceptance/v670.py" in _content, _content[-300:])
check("B4 stats report the anchor size (observable, not a hidden side effect)",
      isinstance(_st.get("anchors"), int) and _st["anchors"] > 0, _st.get("anchors"))

_msgs2, _st2 = CE.compact([{"role": "user", "content": "just chat"}],
                          budget_tokens=1, keep_recent=0,
                          summarizer=lambda m: "nothing to add", force=True)
check("B5 a transcript with nothing mechanical adds no empty header",
      CE.ANCHOR_PREFIX not in ((_msgs2[0] or {}).get("content", "") if _msgs2 else ""),
      ((_msgs2[0] or {}).get("content", "")[:120] if _msgs2 else ""))

# ---- C: a second compaction does not pile the same anchors up ---------------
_again, _st3 = CE.compact(_msgs + [{"role": "user", "content": "next step"}],
                          budget_tokens=10, keep_recent=1,
                          summarizer=lambda m: "SUMMARY 2", force=True)
_c2 = (_again[0] or {}).get("content", "")
check("C1 the path is listed once, not once per compaction",
      _c2.count("src/longrun/core/server.py") == 1, _c2.count("src/longrun/core/server.py"))

# ---- D: the anchors survive the COMBINED cap (they are appended last) -------
_prev = {"role": "system", "content": CE.SUMMARY_PREFIX + ("old body " * 900) + "\nkept"}
_d_msgs, _d_st = CE.compact([_prev] + MSGS, budget_tokens=10, keep_recent=1,
                            summarizer=_llm_summary, force=True)
_d = (_d_msgs[0] or {}).get("content", "")
check("D1 a 7k-char carried body is pruned but the anchors are still the tail",
      len(_d) > CE.COMBINED_SUMMARY_MAX_CHARS * 0.5
      and CE.ANCHOR_PREFIX in _d
      and _d.rstrip().endswith("pytest==8.2.1")
      and _d.index(CE.ANCHOR_PREFIX) > len(_d) - CE.ANCHOR_MAX_CHARS - 400,
      (len(_d), _d[-220:]))

print("---")
okc = sum(results)
print("v676: %d/%d PASS" % (okc, len(results)))
sys.exit(0 if okc == len(results) else 1)
