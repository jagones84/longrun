#!/usr/bin/env python3
"""v796 — the self-improvement reviewer is not the model that produced the artifact.

Evidence for the need (2026-11-04): `improve.review()` asks for `role="reviewer"`
(`util/improve.py:254-265`), but `config/routing.yaml` defined no `reviewer` role and
`default_fallbacks: []`, so `routing.pick("reviewer")` returned None and
`stream_with_fallback` fell back to `default_model()` — the same model the turn ran
on. Every "review" of the improvement backlog was therefore the producing model
agreeing with itself; 14 review files existed from that path.

Contract locked here:
  * `config/routing.yaml` carries a `reviewer` role with an explicit `model`;
  * that model is NOT the model of any role that produces work (chat/agent/
    subagent/longrun_agent) and NOT the providers default — so the review is a
    second opinion, not a repeat;
  * `single_shot` PASSES the role pin as the primary model (before this, the pin
    was reachable only as a failover candidate);
  * an explicit `model=` argument still wins over the pin;
  * with no configured role, `single_shot` passes None and the old behaviour is
    byte-identical (nothing new can break a caller that never configured it).

Deterministic, no live model, no network, no server.

Run: python3 tests/acceptance/v796_reviewer_role.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v796-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.model import routing                   # noqa: E402
from longrun.core import server                    # noqa: E402
from longrun.util import improve                   # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


PRODUCERS = ("chat", "agent", "subagent", "longrun_agent")


def _providers_default():
    """The shipped `default:` of config/providers.yaml, read WITHOUT providers.load."""
    try:
        from longrun.util.dataio import load_yaml
        with open(os.path.join(REPO, "config", "providers.yaml"), encoding="utf-8") as f:
            return str((load_yaml(f.read(), default={}) or {}).get("default") or "")
    except Exception as exc:  # noqa: BLE001
        print("     (providers.yaml unreadable: %s)" % exc)
        return ""


# ---------------------------------------------------------------- A. the config --
cfg = routing.load_config(reload=True)
roles = cfg.get("roles") or {}
rev = routing.role_model("reviewer")
check("A1 routing.yaml defines a reviewer role", "reviewer" in roles, sorted(roles))
check("A2 reviewer has an explicit model pin", bool(rev), rev)
check("A3 the pin is a provider:model ref", ":" in str(rev or ""), rev)

for _r in PRODUCERS:
    other = routing.role_model(_r)
    check("A4 reviewer != %s model" % _r,
          (not other) or (str(other) != str(rev)),
          "%s=%r reviewer=%r" % (_r, other, rev))
check("A5 reviewer != providers default", str(rev or "") != _providers_default(),
      "default=%r reviewer=%r" % (_providers_default(), rev))
check("A6 reviewer declares at least one fallback",
      bool((roles.get("reviewer") or {}).get("fallbacks")),
      (roles.get("reviewer") or {}).get("fallbacks"))

# ------------------------------------------- B. single_shot passes it as PRIMARY --
_calls = []


def _fake_stream(messages, model, role, on_delta, **kw):
    _calls.append({"model": model, "role": role})
    return "ok", "", (model or "default")


_orig = server.stream_with_fallback
server.stream_with_fallback = _fake_stream
try:
    improve.single_shot([{"role": "user", "content": "x"}])
    check("B1 single_shot sends the reviewer pin as the primary model",
          bool(rev) and _calls and _calls[-1]["model"] == rev,
          _calls[-1] if _calls else None)
    check("B2 single_shot keeps asking for the reviewer role",
          _calls and _calls[-1]["role"] == "reviewer", _calls[-1] if _calls else None)

    _calls.clear()
    improve.single_shot([{"role": "user", "content": "x"}], model="openrouter:explicit/one")
    check("B3 an explicit model= still wins over the pin",
          _calls and _calls[-1]["model"] == "openrouter:explicit/one", _calls[-1] if _calls else None)

    # C. no configured role -> no pin (the pre-E-1 behaviour, byte-identical)
    # CONFIG_PATH is repo-anchored, so it is redirected to a temp file: a test
    # must never rewrite the checkout's own routing.yaml.
    _real_path = routing.CONFIG_PATH
    _tmp_cfg = dict(cfg)
    _tmp_cfg["roles"] = {k: v for k, v in (cfg.get("roles") or {}).items() if k != "reviewer"}
    try:
        routing.CONFIG_PATH = os.path.join(TMP, "routing-no-reviewer.yaml")
        routing.save_config(_tmp_cfg)
        routing.load_config(reload=True)
        _calls.clear()
        improve.single_shot([{"role": "user", "content": "x"}])
        check("C1 with no reviewer role, single_shot passes model=None",
              _calls and _calls[-1]["model"] is None, _calls[-1] if _calls else None)
    finally:
        routing.CONFIG_PATH = _real_path
        routing.load_config(reload=True)
finally:
    server.stream_with_fallback = _orig

# ------------------------------------------------------- D. source wiring pins --
_src = open(os.path.join(REPO, "src", "longrun", "util", "improve.py"),
            encoding="utf-8").read()
check("D1 single_shot resolves the role pin", "routing.role_model(role)" in _src)
_fn_at = _src.find("def single_shot")
_pin_at = _src.find("routing.role_model(role)", _fn_at)
_call_at = _src.find("server.stream_with_fallback(", _fn_at)
check("D2 the pin is applied BEFORE the call, not after",
      _fn_at >= 0 and _pin_at > _fn_at and _call_at > _pin_at,
      "fn=%d pin=%d call=%d" % (_fn_at, _pin_at, _call_at))

# -------------------------------------------------------------- E. never raises --
try:
    from longrun.util import improve as _imp2
    _imp2.single_shot.__doc__  # trivial attribute access must not throw
    check("E1 the module still imports cleanly", True)
except Exception as exc:  # noqa: BLE001
    check("E1 the module still imports cleanly", False, exc)

print("\n%d/%d passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
