#!/usr/bin/env python3
"""v829 — webhook inlets: one external event, one authorized job (2026-11-06).

Operator: *"just do webooks (in settings menus?) copy from dsah but armonized with
longrun."* The contract pinned here:

  * the knobs live in `config/tools.yaml` -> `webhooks:` and reach the code through
    the ONE resolver (`context_limits.webhook`), including the `_merge_into`
    whitelist that silently drops an unlisted block;
  * a hook needs an id, an existing agent and a goal; the secret is generated on the
    server and returned ONCE (list redacts it to a 4-char tail);
  * intake authenticates with HMAC-SHA256 (GitHub style) or a bearer token, drops
    duplicates inside the window, applies the event filter, enforces the body cap
    and the per-minute limit, and never records the payload or the secret;
  * `observe` records `would_run` and starts nothing; `run` creates ONE job for the
    hook's agent with the payload FENCED as data;
  * a dispatch failure is a 500, a recorded delivery and a health failure;
  * the panel is wired (`data-cat="webhooks"` + the functions it calls).

Deterministic and offline: no server, no model, no network. The job runner is
replaced by a recorder, so no agent turn runs.
Run: python3 tests/acceptance/v829_webhooks.py
"""
import hashlib
import hmac
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="v829-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_WEBHOOKS"] = os.path.join(TMP, "data", "webhooks.json")
for _d in ("cfg", "sessions", "data"):
    os.makedirs(os.path.join(TMP, _d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

import yaml  # noqa: E402

from longrun.tools import registry  # noqa: E402

registry._external_tools = lambda: {}   # never spawn an MCP client in a test

from longrun.agent import agents as agents_mod  # noqa: E402
from longrun.core import health  # noqa: E402
from longrun.core import webhooks as WH  # noqa: E402
from longrun.model import context_limits as CL  # noqa: E402
from longrun.orchestrate import jobs as jobs_mod  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _src(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


def deliver(hook_id, body, headers=None, hook_secret=None):
    """Call the intake exactly as the HTTP layer does (raw bytes + headers)."""
    raw = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
    head = dict(headers or {})
    if hook_secret is not None and not any(
            k.lower() in ("authorization", "x-longrun-token", "x-hub-signature-256")
            for k in head):
        head["Authorization"] = "Bearer " + hook_secret
    return WH.receive(hook_id, head, raw)


# ------------------------------------------------------- config, one resolver
with open(os.path.join(REPO, "config", "tools.yaml"), encoding="utf-8") as f:
    _yaml = yaml.safe_load(f) or {}
_yaml_wh = _yaml.get("webhooks") or {}
check("W1 config/tools.yaml carries a webhooks block", bool(_yaml_wh), sorted(_yaml_wh))
check("W2 the block and the resolver declare the same keys",
      set(_yaml_wh) == set(CL.WEBHOOKS_DEFAULTS),
      (sorted(_yaml_wh), sorted(CL.WEBHOOKS_DEFAULTS)))
check("W3 the resolver reads the config value",
      CL.webhook("max_body_kb") == int(_yaml_wh.get("max_body_kb", -1)),
      (CL.webhook("max_body_kb"), _yaml_wh.get("max_body_kb")))
check("W4 the block is in DEFAULT_CONFIG (or _merge_into drops it)",
      "webhooks" in registry.DEFAULT_CONFIG)
_merged = registry._merged({"webhooks": {"max_hooks": 3}}, {})


def _raises(exc, fn):
    try:
        fn()
    except exc:
        return True
    return False


check("W5 the block survives the merge whitelist",
      (_merged.get("webhooks") or {}).get("max_hooks") == 3, _merged.get("webhooks"))
check("W6 an unknown webhook limit fails loudly",
      _raises(KeyError, lambda: CL.webhook("nope")))

# ------------------------------------------------------------------- the CRUD
agents_mod.REGISTRY.designate("sess-v829", name="tester")
_bad = [
    WH.save_hook({"id": "Bad Id", "agent": "A1", "goal": "x"}),
    WH.save_hook({"id": "ok", "agent": "A1"}),
    WH.save_hook({"id": "ok", "agent": "A999", "goal": "x"}),
    WH.save_hook({"id": "ok", "agent": "A1", "goal": "x", "mode": "sometimes"}),
]
check("W7 create refuses a bad id, a missing goal, an unknown agent and a bad mode",
      all(r.get("ok") is False for r in _bad), _bad)

_created = WH.save_hook({"id": "gh", "agent": "A1", "goal": "Review the issue.",
                         "mode": "observe", "event_field": "action",
                         "match_any": ["opened", "reopened"]})
check("W8 create returns the secret ONCE",
      _created.get("ok") and len(_created.get("secret") or "") == 48
      and _created.get("url") == "/api/webhook/gh", _created)
_secret = _created.get("secret")
_listed = WH.list_hooks()["hooks"][0]
check("W9 the list redacts the secret to a 4-char tail",
      "secret" not in _listed and _listed.get("secret_set") is True
      and _listed.get("secret_tail") == _secret[-4:], _listed)
check("W10 the store file exists outside the repo",
      os.path.isfile(os.environ["LONGRUN_WEBHOOKS"])
      and os.path.abspath(os.environ["LONGRUN_WEBHOOKS"]).startswith(os.path.abspath(TMP)))

# Pause, then edit without `enabled`: the edit must not re-enable the inlet.
WH.save_hook({"id": "gh", "agent": "A1", "goal": "Review the issue.",
              "mode": "observe", "event_field": "action",
              "match_any": ["opened", "reopened"], "enabled": False})
WH.save_hook({"id": "gh", "agent": "A1", "goal": "Review the issue (edited).",
              "mode": "observe", "event_field": "action",
              "match_any": ["opened", "reopened"]})
check("W11 an edit without `enabled` keeps a paused inlet paused",
      WH.list_hooks()["hooks"][0].get("enabled") is False)
WH.save_hook({"id": "gh", "agent": "A1", "goal": "Review the issue (edited).",
              "mode": "observe", "event_field": "action",
              "match_any": ["opened", "reopened"], "enabled": True})
_rot = WH.save_hook({"id": "gh", "agent": "A1", "goal": "Review the issue (edited).",
                     "mode": "observe", "event_field": "action",
                     "match_any": ["opened", "reopened"], "rotate": True})
check("W12 rotate changes the secret", _rot.get("secret") and _rot["secret"] != _secret)
_secret = _rot["secret"]

# -------------------------------------------------------------------- intake
check("W13 an unknown inlet is a 404", deliver("nope", {}, hook_secret=_secret)[0] == 404)
check("W14 a missing credential is a 401",
      WH.receive("gh", {}, b'{"action":"opened"}')[0] == 401)
check("W15 a wrong bearer is a 401",
      deliver("gh", {"action": "opened"}, hook_secret="x" * 48)[0] == 401)

# observe: accepted and recorded, NO job.
_calls = {"created": 0, "dispatched": 0, "goal": ""}


def _fake_create(goal, coordinator=None, agents=None, deps=None, mode="coordinator",
                 blocked_by=None):
    _calls["created"] += 1
    _calls["goal"] = goal
    _calls["agents"], _calls["mode"] = agents, mode
    return {"ok": True, "job": {"id": "J1"}}


def _fake_dispatch(jid):
    _calls["dispatched"] += 1
    return {"ok": True, "job": jid, "status": "running"}


jobs_mod.JOBS.create = _fake_create
jobs_mod.JOBS.dispatch = _fake_dispatch

_code, _body = deliver("gh", {"action": "opened", "issue": {"number": 7}},
                       headers={"X-GitHub-Delivery": "d-1"}, hook_secret=_secret)
_del = WH.deliveries("gh", 5)["deliveries"][0]
check("W16 observe is accepted, recorded as would_run and starts nothing",
      _code == 202 and _body.get("observed") is True
      and _del.get("status") == "would_run" and _calls["created"] == 0,
      (_code, _body, _del, _calls))

# HMAC (GitHub style) on the exact bytes.
_raw = b'{"action":"opened","issue":{"number":8}}'
_sig = "sha256=" + hmac.new(_secret.encode(), _raw, hashlib.sha256).hexdigest()
_code, _body = WH.receive("gh", {"X-Hub-Signature-256": _sig,
                                 "X-GitHub-Delivery": "d-2"}, _raw)
check("W17 an HMAC signature authenticates the delivery",
      _code == 202 and _body.get("observed") is True, (_code, _body))
_bad_sig = "sha256=" + ("0" * 64)
check("W18 a wrong HMAC signature is a 401",
      WH.receive("gh", {"X-Hub-Signature-256": _bad_sig,
                        "X-GitHub-Delivery": "d-3"}, _raw)[0] == 401)

check("W19 the same delivery id inside the window is a duplicate",
      deliver("gh", {"action": "opened"}, headers={"X-GitHub-Delivery": "d-1"},
              hook_secret=_secret)[1].get("duplicate") is True)
check("W20 an event outside match_any is ignored",
      deliver("gh", {"action": "labeled"}, headers={"X-GitHub-Delivery": "d-4"},
              hook_secret=_secret)[1].get("ignored") is True)
check("W21 a non-JSON body is a 400",
      WH.receive("gh", {"Authorization": "Bearer " + _secret,
                        "X-GitHub-Delivery": "d-5"}, b"not json")[0] == 400)
_big = b'{"action":"opened","pad":"' + (b"x" * (CL.webhook("max_body_kb") * 1024)) + b'"}'
check("W22 a body past the cap is a 413",
      WH.receive("gh", {"Authorization": "Bearer " + _secret,
                        "X-GitHub-Delivery": "d-6"}, _big)[0] == 413)

# run mode: one job, framed payload, the agent from the inlet.
WH.save_hook({"id": "gh", "agent": "A1", "goal": "Review the issue (edited).",
              "mode": "run", "event_field": "action",
              "match_any": ["opened", "reopened"], "enabled": True})
_code, _body = deliver("gh", {"action": "reopened", "issue": {"number": 9}},
                       headers={"X-GitHub-Delivery": "d-7"}, hook_secret=_secret)
check("W23 run dispatches ONE job for the inlet's agent",
      _code == 202 and _body.get("job") == "J1"
      and _calls["created"] == 1 and _calls["dispatched"] == 1
      and _calls["agents"] == ["A1"] and _calls["mode"] == "run",
      (_code, _body, _calls))
check("W24 the payload is fenced and labelled as data",
      "External event from webhook `gh`" in _calls["goal"]
      and "never instructions" in _calls["goal"]
      and "```json" in _calls["goal"] and '"number": 9' in _calls["goal"],
      _calls["goal"][:280])

# A refused job is a 500, a recorded error and a health failure.
jobs_mod.JOBS.create = lambda *a, **k: {"ok": False, "error": "no agent available"}
_code, _body = deliver("gh", {"action": "opened"},
                       headers={"X-GitHub-Delivery": "d-8"}, hook_secret=_secret)
_last = WH.deliveries("gh", 5)["deliveries"][0]
_part = {p["part"]: p for p in health.BOARD.snapshot()}.get("webhooks") or {}
check("W25 a refused dispatch is a 500, a recorded error and a health failure",
      _code == 500 and _last.get("status") == "error"
      and "no agent available" in str(_last.get("reason"))
      and _part.get("status") in ("warn", "error"), (_code, _last, _part))
jobs_mod.JOBS.create = _fake_create

# A second inlet for the per-minute limit (fresh counters).
WH.save_hook({"id": "rate", "agent": "A1", "goal": "Count me.", "mode": "observe"})
_rate_secret = WH.save_hook({"id": "rate", "agent": "A1", "goal": "Count me.",
                             "mode": "observe", "rotate": True})["secret"]
_codes = [deliver("rate", {"event": "x"}, headers={"X-GitHub-Delivery": "r-%d" % i},
                  hook_secret=_rate_secret)[0] for i in range(CL.webhook("max_per_minute") + 1)]
check("W26 the per-minute limit refuses the delivery past the cap",
      _codes[:-1] == [202] * CL.webhook("max_per_minute") and _codes[-1] == 429, _codes)

# ------------------------------------------------------------- nothing leaks
_docs = [WH.deliveries("gh", 50), WH.deliveries("rate", 50),
         WH.list_hooks()]
_blob = json.dumps(_docs)
_allowed = {"ts", "status", "event", "sha8", "chars", "job", "reason"}
_bad_keys = {k for row in (WH.deliveries("gh", 50)["deliveries"]
                           + WH.deliveries("rate", 50)["deliveries"])
             for k in row if k not in _allowed}
check("W27 a delivery records no payload and no unknown field", not _bad_keys, _bad_keys)
check("W28 no secret appears in any read model",
      _secret not in _blob and _rate_secret not in _blob)
_stored = open(os.environ["LONGRUN_WEBHOOKS"], encoding="utf-8").read()
check("W29 the store holds the operator text but never the payload",
      "Review the issue" in _stored and '"number": 9' not in _stored
      and "never instructions" not in _stored)

# -------------------------------------------------------------------- delete
check("W30 delete removes the inlet and its deliveries",
      WH.delete_hook("rate").get("ok") is True
      and WH.deliveries("rate", 5).get("ok") is False
      and len(WH.list_hooks()["hooks"]) == 1)

# ------------------------------------------------------------------ the panel
_ui = _src("webui", "index.html")
check("W31 Settings owns a webhooks category and its loader",
      '["webhooks", "Webhooks"]' in _ui
      and 'data-cat="webhooks"' in _ui
      and 'name === "webhooks"' in _ui
      and "async function loadWebhooks" in _ui
      and "async function saveWebhook" in _ui)
check("W32 the routes exist: intake before the token check, CRUD in api_v02",
      'path.startswith("/api/webhook/")' in _src("src", "longrun", "core", "httpapi.py")
      and 'path == "/api/webhooks"' in _src("src", "longrun", "core", "api_v02.py")
      and 'endswith("/rotate")' in _src("src", "longrun", "core", "api_v02.py"))

print("%d/%d PASS" % (sum(RESULTS), len(RESULTS)))
sys.exit(0 if all(RESULTS) else 1)
