#!/usr/bin/env python3
"""v556 (staged, RED) — loop detection by TOOL TYPE frequency.

M5 of the upgrade plan: the v2 loop only stops on an IDENTICAL action
(`api_v02.py:703-727`). A model that calls `fs.read` 50 times with different
paths is not stopped. DeerFlow covers this with a sliding-window frequency
detector per tool type.

Contract locked here:
  * `_ToolFreq(window, warn, hard, per_tool)` lives in `longrun.core.api_v02`;
  * `.observe(name)` -> {tool, count, decision in ok|warn|hard_stop};
  * the window holds the last `window` calls ACROSS all tools; `count` is how
    many of those are the observed tool (so 49 reads + 49 greps do not add up);
  * `per_tool` overrides warn/hard for one tool (shell is the legitimate
    high-frequency case);
  * `from_config()` falls back to defaults when the YAML block is absent.

Staged in `.agent/docs/plans/staged-tests/` until the implementation lands. Deterministic.

Run: python3 v556_tool_frequency.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _repo(start):
    p = start
    while True:
        if os.path.isdir(os.path.join(p, "src", "longrun")):
            return p
        parent = os.path.dirname(p)
        if parent == p:
            raise SystemExit("repository root not found from %s" % start)
        p = parent


REPO = _repo(HERE)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import api_v02  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


_ToolFreq = getattr(api_v02, "_ToolFreq", None)
check("A1 api_v02._ToolFreq exists", _ToolFreq is not None)


def _decisions(freq, tool, n):
    out = []
    for _ in range(n):
        out.append(freq.observe(tool)["decision"])
    return out


# ---- B: thresholds ----------------------------------------------------------
if _ToolFreq is not None:
    f = _ToolFreq(window=50, warn=30, hard=50)
    d = _decisions(f, "fs.read", 49)
    check("B1 first 29 reads are ok", all(x == "ok" for x in d[:29]), str(d[:29]))
    check("B2 the 30th read warns", d[29] == "warn", d[29] if len(d) > 29 else "n/a")
    last = f.observe("fs.read")
    check("B3 the 50th read hard-stops",
          last["decision"] == "hard_stop" and last["count"] == 50, repr(last))

    # per type, not global: interleaving keeps each count under the window
    f2 = _ToolFreq(window=50, warn=30, hard=50)
    mixed = []
    for _ in range(30):
        mixed.append(f2.observe("fs.grep")["decision"])
        mixed.append(f2.observe("fs.read")["decision"])
    check("B4 interleaved greps/reads never hard-stop",
          "hard_stop" not in mixed, ",".join(sorted(set(mixed))))

    # per-tool override
    f3 = _ToolFreq(window=300, warn=100, hard=200, per_tool={"shell": {"warn": 100, "hard": 200}})
    ds = _decisions(f3, "shell", 199)
    check("B5 shell override: 199 calls do not stop", "hard_stop" not in ds)
    stop = f3.observe("shell")
    check("B6 shell override: the 200th stops",
          stop["decision"] == "hard_stop" and stop["count"] == 200, repr(stop))

    # rolling window
    f4 = _ToolFreq(window=5, warn=99, hard=99)
    f4.observe("fs.read")
    for _ in range(4):
        f4.observe("fs.write")
    rolled = f4.observe("fs.read")
    check("B7 the window rolls over old calls", rolled["count"] == 1, repr(rolled))

    # config defaults
    try:
        fc = _ToolFreq.from_config()
        check("B8 from_config falls back to sane defaults",
              (fc.window, fc.warn, fc.hard) == (50, 30, 50),
              "window=%s warn=%s hard=%s" % (fc.window, fc.warn, fc.hard))
    except Exception as e:  # noqa: BLE001
        check("B8 from_config falls back to sane defaults", False, str(e)[:120])
else:
    for name in ("B1 first 29 reads are ok", "B2 the 30th read warns",
                 "B3 the 50th read hard-stops", "B4 interleaved greps/reads never hard-stop",
                 "B5 shell override: 199 calls do not stop", "B6 shell override: the 200th stops",
                 "B7 the window rolls over old calls", "B8 from_config falls back to sane defaults"):
        check(name, False, "_ToolFreq missing")

# ---- C: the loop really uses it --------------------------------------------
try:
    with open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"), encoding="utf-8") as fh:
        _src = fh.read()
except OSError as e:  # pragma: no cover
    _src = ""
    print("WARN cannot read api_v02.py: %s" % e)

check("C1 agent_run_v2 observes tool frequency", "freq.observe(" in _src)
check("C2 a hard stop publishes agent.loop_capped", "agent.loop_capped" in _src)
check("C3 the stop reuses the no_progress termination",
      "loop_capped" in _src and '"no_progress"' in _src)

print("\n%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
