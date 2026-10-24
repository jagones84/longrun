#!/usr/bin/env python3
"""v414 — native self-diagnosis (JAG-426 · Domain 1).

The harness must be able to inspect ITSELF (health, its own event log, its
context occupancy, its tool policy) with NO dependency on an external process/
performance manager, and every probe must DEGRADE instead of raising when a
system tool is missing (no nvidia-smi, no /proc, no session).

Deterministic, no live server, no network. Run: python3 tests/v414_self_diag.py
"""
import os
import shutil
import sys
import tempfile
import urllib.error
from types import SimpleNamespace

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v414-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(TMP, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import diag           # noqa: E402
from longrun.tools import registry       # noqa: E402
from longrun.tools import tools as T     # noqa: E402

registry._external_tools = lambda: {}

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- 1. health() never raises and carries the expected shape ----------------
h = diag.health()
check("1a health() returns ok + the core keys",
      h.get("ok") is True and all(k in h for k in
      ("ts", "version", "python", "cpu", "memory_mb", "disk", "gpu", "service", "ports")),
      sorted(h.keys()))
check("1b cpu count + disk are probed on this host",
      isinstance(h["cpu"].get("count"), int) and (h["disk"] is None or "free_gb" in h["disk"]))
check("1c ports are probed natively (bools)",
      all(isinstance(v, bool) for v in h["ports"].values()), h["ports"])

# ---- 2. graceful degradation when nvidia-smi is absent ----------------------
_real_which = shutil.which
shutil.which = lambda name, *a, **k: None
try:
    h2 = diag.health()
finally:
    shutil.which = _real_which
check("2 no nvidia-smi -> gpu None, still ok (no raise)",
      h2.get("ok") is True and h2.get("gpu") is None)

# ---- 3. tools_report mirrors the registry -----------------------------------
tr = diag.tools_report()
_nat = set(tr.get("native", []))
check("3a tools_report lists native tools incl. shell/self/fs.read",
      tr.get("ok") is True and ({"shell", "self", "fs.read"}.issubset(_nat)
                                or {"shell.exec", "self.info", "fs.read"}.issubset(_nat)),
      tr.get("count"))
check("3b external MCP tools are separated (names contain '__')",
      all("__" in n for n in tr.get("external", [])))
check("3c tools_report agrees with registry.catalog()",
      tr.get("count") == len([t for t in registry.catalog() if t.get("name") and "__" not in t["name"]]))

# ---- 4. log_tail is bounded + safe on an empty event log --------------------
lt = diag.log_tail(limit=5)
check("4 log_tail bounded + no raise", lt.get("ok") is True and len(lt.get("lines", [])) <= 5,
      lt.get("count"))

# ---- 5. the `self` tool routes on `action` (no new tool name) ---------------
info = T.execute("self", {"action": "info"})
check("5a action=info keeps the static self-knowledge (back-compat)",
      info.get("ok") is True and info.get("repo_path") == REPO)
diag_res = T.execute("self", {"action": "diagnose"})
check("5b action=diagnose attaches a health snapshot",
      diag_res.get("diagnose", {}).get("ok") is True
      and diag_res.get("repo_path") == REPO)
t_res = T.execute("self", {"action": "tools"})
check("5c action=tools attaches the tool policy",
      t_res.get("tools", {}).get("ok") is True)
bad = T.execute("self", {"action": "nope"})
check("5d an unknown action reports it but keeps the static info",
      "error" in bad and bad.get("repo_path") == REPO)

# ---- 6. context() introspection (dry run, no LLM) ---------------------------
try:
    from longrun.core import server as s
    s.get_or_create_session("v414s", title="v414 session")
    cx = diag.context("v414s")
    check("6 context() introspects a real session (dry run)",
          cx.get("ok") is True and isinstance(cx.get("context"), dict), str(cx)[:120])
except Exception as e:  # noqa: BLE001
    check("6 context() introspects a real session (dry run)", False, "raised: %s" % e)

# ---- 7. user-config diagnostics are isolated and secret-safe ---------------
try:
    from longrun.core import diagnostics as D  # noqa: E402
except ImportError:
    D = None
check("7a configuration diagnostics module is available", D is not None)

if D is not None:
    _optional_env = ("LONGRUN_HOOKS", "LONGRUN_HOOKS_OVERLAY",
                     "LONGRUN_DECISIONS", "LONGRUN_DECISIONS_OVERLAY")
    _saved_optional_env = {
        key: os.environ.pop(key) for key in _optional_env if key in os.environ
    }
    try:
        try:
            discovered_sources = D._config_sources()
            source_error = None
        except Exception as exc:  # noqa: BLE001
            discovered_sources = []
            source_error = type(exc).__name__
    finally:
        os.environ.update(_saved_optional_env)
    source_names = {source.get("name") for source in discovered_sources}
    tracked_yaml = {
        name for name in os.listdir(os.path.join(REPO, "config"))
        if name.endswith((".yaml", ".yml"))
    }
    known_local_sources = {
        "providers.local.yaml", "subagents.yaml", "mcp_clients.local.json",
        "mcp_clients.local.yaml", "compaction.local.yaml", "tools.overlay.yaml",
        "tools.overlay.json", "hooks.overlay.yaml", "decisions.overlay.yaml",
        "index.overlay.yaml", "config.json",
    }
    check("7a2 unset optional overlays do not break config discovery",
          source_error is None
          and all(isinstance(source.get("path"), str) and source["path"]
                  for source in discovered_sources), source_error or "")
    check("7a3 config discovery includes tracked YAML, local sources, and config-dir JSON",
          tracked_yaml.issubset(source_names)
          and known_local_sources.issubset(source_names)
          and any(source.get("name") == "config.json"
                  and source.get("path") == os.path.join(os.environ["LONGRUN_CONFIG_DIR"],
                                                         "config.json")
                  for source in discovered_sources), source_names)

    cfg_root = os.path.join(TMP, "private-config")
    os.makedirs(cfg_root, exist_ok=True)
    good_yaml = os.path.join(cfg_root, "good.yaml")
    bad_yaml = os.path.join(cfg_root, "broken.yaml")
    with open(good_yaml, "w", encoding="utf-8") as f:
        f.write("enabled: true\n")
    with open(bad_yaml, "w", encoding="utf-8") as f:
        f.write("private-value: NEVER-ECHO-THIS\nbad: [\n")
    cfg_issues = D.validate_config_sources([
        {"name": "good.yaml", "path": good_yaml, "format": "yaml"},
        {"name": "broken.yaml", "path": bad_yaml, "format": "yaml"},
    ])
    check("7b one malformed config produces one safe source-local issue",
          len(cfg_issues) == 1 and cfg_issues[0].get("code") == "config.invalid"
          and cfg_issues[0].get("source") == "broken.yaml"
          and cfg_root not in repr(cfg_issues)
          and "NEVER-ECHO-THIS" not in repr(cfg_issues), cfg_issues)
    setting_issues = D.validate_setting_values([{
        "file": "index.yaml",
        "fields": [{"path": "max_file_kb", "label": "maximum file size",
                    "type": "int", "min": 1, "max": 100}],
        "values": {"max_file_kb": "not-a-number"},
    }])
    check("7b2 invalid structured setting values get field-scoped safe guidance",
          len(setting_issues) == 1
          and setting_issues[0].get("code") == "config.value_invalid"
          and setting_issues[0].get("action") == "config"
          and "not-a-number" not in repr(setting_issues), setting_issues)

    # 7b3/7b4 — REGRESSION (live, 2026-10-22): compaction reported TWO identical
    # "Saved setting is invalid" errors for a perfectly valid policy. The overlay
    # stores percentages as floats (`trigger_pct: 70.0`) while the schema declares
    # `int`, and the old check asked `isinstance(value, int)` only. An INTEGRAL float
    # is a valid integer setting, and every issue must be ISOLATED (file + field +
    # panel + a specific reason) so two issues can never read as one.
    int_field = [{"path": "trigger_pct", "label": "auto trigger (%)",
                  "type": "int", "min": 1, "max": 100},
                 {"path": "target_pct", "label": "auto target (%)",
                  "type": "int", "min": 0, "max": 99}]
    ok_float = D.validate_setting_values([{
        "file": "compaction.yaml", "panel": "compaction", "fields": int_field,
        "values": {"trigger_pct": 70.0, "target_pct": 16.0},
    }])
    check("7b3 an integral float is accepted for an int setting (no false positive)",
          ok_float == [], ok_float)
    iso = D.validate_setting_values([{
        "file": "compaction.yaml", "panel": "compaction", "fields": int_field,
        # a real decimal, and an out-of-range value: two DIFFERENT defects
        "values": {"trigger_pct": 70.5, "target_pct": 120},
    }])
    check("7b4 each invalid setting is isolated (file + field + panel + own reason)",
          len(iso) == 2
          and all(i.get("file") == "compaction.yaml" and i.get("panel") == "compaction"
                  for i in iso)
          and {i.get("field") for i in iso} == {"trigger_pct", "target_pct"}
          and iso[0]["message"] != iso[1]["message"]
          and "decimal part" in iso[0]["message"]
          and "Settings → Compaction" in iso[0]["message"], iso)

    provider_cfg = {
        "default": "openai:gpt-not-listed",
        "providers": [
            {"id": "openai", "local": False, "api_key_env": "OPENAI_API_KEY",
             "base_url": "https://api.openai.com/v1",
             "models": [{"id": "gpt-listed"}]},
            {"id": "optional", "local": False, "api_key_env": "OPTIONAL_API_KEY",
             "base_url": "https://optional.example/v1",
             "models": [{"id": "model"}]},
        ],
    }
    selected_precedence = D.validate_provider_config(
        provider_cfg, {}, {"roles": {}}, "openai:gpt-listed", "v414-ui-session")
    check("7c1 selected UI model takes precedence over an invalid configured default",
          any(issue.get("code") == "provider.key_missing"
              and issue.get("model") == "openai:gpt-listed"
              and issue.get("severity") == "error"
              for issue in selected_precedence)
          and any(issue.get("code") == "model.id_not_configured"
                  and issue.get("model") == "openai:gpt-not-listed"
                  and issue.get("severity") == "warning"
                  for issue in selected_precedence), selected_precedence)

    from longrun.core import server as precedence_server  # noqa: E402
    from longrun.model import providers as precedence_providers  # noqa: E402
    _load_session = precedence_server.load_session
    _load_providers = precedence_providers.load
    _load_provider_env = precedence_providers.load_env
    precedence_providers.load = lambda reload=False: {
        "default": "openai:gpt-listed",
        "providers": [{
            "id": "openai", "local": True,
            "base_url": "https://api.openai.com/v1",
            "models": [{"id": "gpt-listed"}],
        }],
    }
    precedence_providers.load_env = lambda: None
    precedence_server.load_session = lambda _sid: {"model": "openai:gpt-session"}
    try:
        session_precedence = D.collect(session_id="v414-pin")
        ui_precedence = D.collect(session_id="v414-pin", model="openai:gpt-ui")
    finally:
        precedence_server.load_session = _load_session
        precedence_providers.load = _load_providers
        precedence_providers.load_env = _load_provider_env
    check("7c2 session pin takes precedence over configured default",
          any(issue.get("code") == "model.id_not_configured"
              and issue.get("model") == "openai:gpt-session"
              and issue.get("severity") == "error"
              for issue in session_precedence.get("issues", [])), session_precedence)
    check("7c3 explicit UI model takes precedence over the session pin",
          any(issue.get("code") == "model.id_not_configured"
              and issue.get("model") == "openai:gpt-ui"
              and issue.get("severity") == "error"
              for issue in ui_precedence.get("issues", []))
          and not any(issue.get("model") == "openai:gpt-session"
                      for issue in ui_precedence.get("issues", [])), ui_precedence)
    provider_issues = D.validate_provider_config(
        provider_cfg, {}, {"roles": {}}, "openai:gpt-not-listed")
    provider_codes = {issue.get("code") for issue in provider_issues}
    check("7c selected unknown model and missing selected key are diagnosed",
          {"model.id_not_configured", "provider.key_missing"} <= provider_codes
          and not any(issue.get("code") == "provider.key_missing"
                      and issue.get("source") == "optional"
                      for issue in provider_issues), provider_issues)
    sentinel = "sk-test-secret-must-not-appear"
    valid_provider_issues = D.validate_provider_config(
        provider_cfg, {"OPENAI_API_KEY": sentinel}, {"roles": {}}, "openai:gpt-listed")
    check("7d configured key presence is used without exposing its value",
          sentinel not in repr(valid_provider_issues)
          and not any(issue.get("code") == "provider.key_missing"
                      and issue.get("source") == "openai"
                      for issue in valid_provider_issues), valid_provider_issues)
    unknown_provider = D.validate_provider_config(
        provider_cfg, {}, {"roles": {}}, "missing:model")
    check("7e unknown provider reference gets an actionable model issue",
          any(issue.get("code") == "model.provider_unknown"
              and issue.get("action") == "models" for issue in unknown_provider),
          unknown_provider)
    unsafe_url_cfg = {"providers": [{
        "id": "openai", "local": False, "base_url": "file:///private/credentials",
        "models": [{"id": "gpt-listed"}],
    }]}
    unsafe_url = D.validate_provider_config(
        unsafe_url_cfg, {}, {"roles": {}}, "openai:gpt-listed")
    check("7e2 invalid provider URL schemes are diagnosed without echoing the URL",
          any(issue.get("code") == "provider.base_url_invalid"
              and issue.get("action") == "models" for issue in unsafe_url)
          and "credentials" not in repr(unsafe_url), unsafe_url)
    no_model = D.validate_provider_config({
        "providers": [{
            "id": "openai", "local": False, "base_url": "https://api.openai.com/v1",
            "api_key_env": "OPENAI_API_KEY", "models": [{"id": "gpt-listed"}],
        }],
    }, {}, {"roles": {}}, None)
    check("7e3 no ready model names missing key variables without exposing values",
          any(issue.get("code") == "model.none_available"
              and "OPENAI_API_KEY" in issue.get("message", "")
              for issue in no_model), no_model)

    remote_auth = D.auth_issues(False, "0.0.0.0")
    local_auth = D.auth_issues(False, "127.0.0.1")
    check("7f missing server token is distinguished by listener scope",
          any(issue.get("code") == "auth.token_missing"
              and issue.get("severity") == "error" for issue in remote_auth)
          and any(issue.get("code") == "auth.token_missing"
                  and issue.get("severity") == "warning" for issue in local_auth))

    reached = []
    def _broken_check():
        raise RuntimeError("NEVER-ECHO-THIS")
    def _healthy_check():
        reached.append(True)
        return []
    isolated = D.run_checks([("broken-source", _broken_check),
                             ("healthy-source", _healthy_check)])
    check("7g one failed check does not suppress later checks or leak its exception",
          reached == [True]
          and any(issue.get("code") == "diagnostics.check_failed"
                  for issue in isolated)
          and "NEVER-ECHO-THIS" not in repr(isolated), isolated)

    import time as _time
    from longrun.core import events as _events
    _now = _time.time()
    for _code in ("provider.request_failed", "provider.unreachable"):
        _events.publish("settings.diagnostic", code=_code, severity="error",
                        title="Model request failed",
                        message="The model request failed.", source="openrouter",
                        session="v414s", model="stale-phantom:model-x",
                        occurred_at=_now - 60)
    _events.publish("settings.diagnostic", code="provider.auth_rejected",
                    severity="error", title="Provider rejected credentials",
                    message="Check its key.", source="openrouter",
                    session="v414s", model="stale-phantom:model-x",
                    occurred_at=_now - 90000)
    _history_free = D.collect()
    _leaked = [issue for issue in _history_free.get("issues", [])
               if "stale-phantom" in repr(issue)]
    check("7h run checks stay green on past failures: history never resurfaces",
          _leaked == [] and _history_free.get("ok") is True,
          _history_free.get("summary"))
    counts = D.summarize([
        {"severity": "error"}, {"severity": "warning"}, {"severity": "info"}])
    check("7i diagnostics summary counts only errors and warnings as actionable",
          counts == {"errors": 1, "warnings": 1, "info": 1, "actionable": 2}, counts)

    route_seen = {}
    _collect = D.collect
    D.collect = lambda session_id=None, model=None, host="127.0.0.1": (
        route_seen.update(session=session_id, model=model, host=host)
        or {"ok": True, "summary": {"errors": 0, "warnings": 0, "info": 0,
                                    "actionable": 0}, "issues": []})
    try:
        from longrun.core import api_v02  # noqa: E402
        fake = SimpleNamespace(
            server=SimpleNamespace(server_address=("0.0.0.0", 8790)),
            _send=lambda code, obj: setattr(fake, "response", (code, obj)))
        handled = api_v02.handle(
            fake, "GET", "/api/diagnostics",
            {"session": "v414s", "model": "openai:gpt-listed"}, None)
        check("7j diagnostics API forwards session/model and listener scope",
              handled and route_seen == {"session": "v414s", "model": "openai:gpt-listed",
                                         "host": "0.0.0.0"}
              and fake.response[0] == 200, route_seen)
    finally:
        D.collect = _collect

    failures = [
        (urllib.error.HTTPError(
            "https://provider.invalid/v1?token=NEVER-ECHO-THIS",
            401, "Unauthorized", {}, None), "provider.auth_rejected", "keys"),
        (urllib.error.HTTPError(
            "https://provider.invalid/v1", 404, "Not Found", {}, None),
         "provider.model_not_found", "models"),
        (urllib.error.HTTPError(
            "https://provider.invalid/v1", 429, "Too Many Requests", {}, None),
         "provider.rate_limited", "models"),
        (TimeoutError("NEVER-ECHO-THIS"), "provider.unreachable", "models"),
        (RuntimeError("NEVER-ECHO-THIS"), "provider.request_failed", "models"),
    ]
    for exc, expected_code, expected_action in failures:
        issue = D.classify_model_error(exc, "openai:gpt-listed", "v414s")
        check("7k model failure maps to a safe " + expected_code,
              issue.get("code") == expected_code and issue.get("action") == expected_action
              and "NEVER-ECHO-THIS" not in repr(issue)
              and "provider.invalid" not in repr(issue), issue)
    from longrun.core import httpapi  # noqa: E402
    emitted = []
    _publish = httpapi.publish
    httpapi.publish = lambda kind, **data: emitted.append((kind, data))
    try:
        failure = httpapi._chat_failure_issue(
            urllib.error.HTTPError(
                "https://provider.invalid/v1?token=NEVER-ECHO-THIS",
                401, "Unauthorized", {}, None),
            "v414s", "openai:gpt-listed")
    finally:
        httpapi.publish = _publish
    check("7l chat failures publish safe diagnostics for the Settings panel",
          [kind for kind, _data in emitted] == ["chat.error", "settings.diagnostic"]
          and all("NEVER-ECHO-THIS" not in repr(data) for _kind, data in emitted)
          and failure.get("code") == "provider.auth_rejected", emitted)

    from longrun.core import server as server_mod  # noqa: E402
    from longrun.core import api_v02 as api_v02_mod  # noqa: E402
    _chat_once = server_mod.chat_once
    def _fail_model(*_args, **_kwargs):
        raise urllib.error.HTTPError(
            "https://provider.invalid/v1?token=NEVER-ECHO-THIS",
            401, "Unauthorized", {}, None)
    server_mod.chat_once = _fail_model
    try:
        bridge_result = api_v02_mod.LocalApi().chat(
            "diagnostic failure fixture", session="v414-error-session",
            model="openai:gpt-listed")
    finally:
        server_mod.chat_once = _chat_once
    failed_session = server_mod.load_session("v414-error-session") or {}
    error_text = "\n".join(str(message.get("content") or "")
                           for message in (failed_session.get("messages") or []))
    check("7m in-process chat stores and returns only the safe classified failure",
          bridge_result.get("diagnostic", {}).get("code") == "provider.auth_rejected"
          and "NEVER-ECHO-THIS" not in repr(bridge_result)
          and "NEVER-ECHO-THIS" not in error_text
          and "Check the selected provider key" in error_text, bridge_result)

print("---")
okc = sum(results)
print("\nv414: %d/%d PASS" % (okc, len(results)))
sys.exit(0 if okc == len(results) else 1)
