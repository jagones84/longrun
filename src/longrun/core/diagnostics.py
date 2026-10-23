"""Independent, secret-safe diagnostics for user-owned Longrun settings."""

from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
import time
from collections.abc import Callable, Mapping
from urllib.parse import urlsplit

from longrun.util.paths import DATA_DIR, REPO_ROOT

_SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}
_SAFE_REF = re.compile(r"^[A-Za-z0-9._:/~+-]{1,180}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,96}$")
_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
_RUNTIME_MESSAGES = {
    "provider.auth_rejected": (
        "error", "Provider rejected credentials",
        "The provider rejected its API key. Check the selected provider key in Settings → Keys.",
        "keys",
    ),
    "provider.model_not_found": (
        "error", "Model or endpoint not found",
        "The provider could not find this model or endpoint. Check its URL and model ID in Settings → Models.",
        "models",
    ),
    "provider.request_rejected": (
        "error", "Provider rejected the model request",
        "The provider rejected this request. Check its model ID and supported settings in Settings → Models.",
        "models",
    ),
    "provider.rate_limited": (
        "warning", "Provider limit reached",
        "The provider rejected this request because of a rate or usage limit. Check the provider account.",
        "models",
    ),
    "provider.unreachable": (
        "error", "Provider is unreachable",
        "Longrun could not reach the configured provider. Check its URL and network connection in Settings → Models.",
        "models",
    ),
    "provider.unavailable": (
        "error", "Provider is temporarily unavailable",
        "The model provider returned a server error. Check the provider status before retrying.",
        "models",
    ),
    "provider.request_failed": (
        "error", "Model request failed",
        "The model request failed. Review its provider and model settings before retrying.",
        "models",
    ),
}


def _safe_label(value: object, fallback: str = "configuration") -> str:
    """Reduce an untrusted label to a harmless basename or identifier."""
    raw = str(value or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    if raw and len(raw) <= 120 and not any(ord(char) < 32 for char in raw):
        return raw
    return fallback


def _safe_ref(value: object) -> str | None:
    """Keep model references useful without rendering arbitrary URLs or secrets."""
    raw = str(value or "").strip()
    return raw if _SAFE_REF.fullmatch(raw) else None


def _safe_session(value: object) -> str | None:
    """Return a bounded session id only when it has the normal identifier shape."""
    raw = str(value or "").strip()
    return raw if _SAFE_ID.fullmatch(raw) else None


def _issue(code: str, severity: str, title: str, message: str,
           source: str, action: str | None = None, scope: str = "global",
           session: str | None = None, model: str | None = None,
           occurred_at: float | None = None, file: str | None = None,
           field: str | None = None, panel: str | None = None) -> dict:
    """Create the stable, safe issue shape used by API and WebUI.

    JAG-2.5: `file`/`field`/`panel` carry the ISOLATION of one issue — WHICH file,
    WHICH control and WHICH Settings panel own it. Without them every invalid value
    produced the same generic sentence and two issues were indistinguishable (live
    complaint, 2026-10-22).
    """
    out = {
        "code": code,
        "severity": severity,
        "scope": scope,
        "title": title,
        "message": message,
        "source": _safe_label(source),
    }
    if action in ("keys", "models", "config", "rules"):
        out["action"] = action
    safe_session = _safe_session(session)
    safe_model = _safe_ref(model)
    if safe_session:
        out["session"] = safe_session
    if safe_model:
        out["model"] = safe_model
    if file:
        out["file"] = _safe_label(file)
    if field:
        out["field"] = _safe_label(field)
    if panel and panel in ("keys", "models", "subagents", "tools", "sandbox", "mcp",
                           "skills", "rules", "knowledge", "compaction", "hooks",
                           "harness", "config", "appearance", "diagnostics",
                           "improvement", "info"):
        out["panel"] = panel
    if occurred_at is not None:
        try:
            out["occurred_at"] = float(occurred_at)
        except (TypeError, ValueError):
            pass
    return out


def validate_config_sources(sources: list[dict]) -> list[dict]:
    """Report malformed config files independently without returning file contents."""
    issues = []
    for source in sources or []:
        if not isinstance(source, dict):
            continue
        label = _safe_label(source.get("name") or source.get("path"))
        path = source.get("path")
        if not isinstance(path, str) or not path:
            continue
        if not os.path.isfile(path):
            if source.get("required"):
                issues.append(_issue(
                    "config.missing", "error", "Required config file is missing",
                    "Restore this config file or review the installation.",
                    label, action="config"))
            continue
        try:
            with open(path, "r", encoding="utf-8") as stream:
                text = stream.read()
            fmt = str(source.get("format") or "").lower()
            if fmt == "json" or path.lower().endswith(".json"):
                parsed = json.loads(text or "{}")
            else:
                import yaml
                parsed = yaml.safe_load(text)
            if parsed is None:
                parsed = {}
            if not isinstance(parsed, dict):
                raise ValueError("top level is not a mapping")
        except Exception:  # noqa: BLE001 — one bad file must not stop other checks
            issues.append(_issue(
                "config.invalid", "error", "Config file cannot be read",
                "This file is invalid or unreadable. Open Config files to review or restore it.",
                label, action="config"))
    return issues


def _setting_reason(field: dict, value) -> str:
    """WHY `value` is not usable for `field` — "" when it is fine (JAG-2.5).

    The reason NEVER repeats the field label: the caller puts it in front once, so the
    message reads "auto trigger (%) in compaction.yaml must be <= 100", not the label
    twice.

    The old check asked only `isinstance(value, int)` and reported a generic
    sentence, so ONE float surfaced as two identical errors and nothing said which
    value, why, or where to fix it. This returns a specific, human reason instead.

    An integral float (``70.0``) IS a valid integer setting: YAML/JSON numbers reach
    the harness as floats (``compaction.yaml`` ships ``trigger_pct: 70``, the overlay
    writes ``70.0``), so refusing it was a FALSE POSITIVE — the exact live bug.
    """
    from longrun.core import settings

    kind = field.get("type")
    if kind == "bool":
        if not isinstance(value, bool):
            return "must be true or false"
    elif kind == "int":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return "must be a whole number"
        if isinstance(value, float) and not float(value).is_integer():
            return "must be a whole number, but it has a decimal part"
    elif kind == "float":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return "must be a number"
    elif kind in ("text", "textarea", "select"):
        if not isinstance(value, str):
            return "must be text"
    elif kind == "strlist":
        if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
            return "must be a list of strings"
    elif kind == "rows":
        if not isinstance(value, list) or not all(isinstance(x, dict) for x in value):
            return "must be a list of rows"
    try:
        settings._coerce(field, value)
    except ValueError as exc:
        # `_coerce` names the field and the bound it broke ("auto trigger (%) must be
        # <= 100"); drop the leading label because the caller adds it once.
        text = str(exc)
        label = str(field.get("label") or field.get("path") or "")
        prefix = label + " "
        return text[len(prefix):] if label and text.startswith(prefix) else text
    except Exception:  # noqa: BLE001 — an exotic value must not break the report
        return "is not accepted here"
    return ""


def validate_setting_values(sections: list[dict]) -> list[dict]:
    """Validate effective structured form values without returning bad values.

    Every issue is ISOLATED (JAG-2.5): it names the file, the field path, the owning
    Settings panel and the concrete reason, so two invalid values can never read as
    one duplicated message.
    """
    from longrun.core import settings

    issues = []
    for section in sections or []:
        if not isinstance(section, dict):
            continue
        filename = _safe_label(section.get("file"))
        panel = str(section.get("panel") or "")
        panel_label = settings.PANEL_LABELS.get(panel, "Config files")
        values = section.get("values") if isinstance(section.get("values"), dict) else {}
        for field in section.get("fields") or []:
            if not isinstance(field, dict):
                continue
            path = str(field.get("path") or "")
            value = values.get(path)
            if value is None:
                continue
            reason = _setting_reason(field, value)
            if not reason:
                continue
            label = str(field.get("label") or path or "setting")
            issues.append(_issue(
                "config.value_invalid", "error", "Invalid saved setting",
                "%s in %s %s. Fix it in Settings → %s, or edit the file directly."
                % (label, filename, reason, panel_label),
                "%s · %s" % (filename, label), action="config",
                file=filename, field=path, panel=panel))
    return issues



def auth_issues(token_configured: bool, host: str) -> list[dict]:
    """Warn when this server has no token; severity reflects network exposure."""
    if token_configured:
        return []
    bind = str(host or "").strip().lower()
    local_only = bind == "localhost"
    try:
        local_only = local_only or ipaddress.ip_address(bind.split("%", 1)[0]).is_loopback
    except ValueError:
        pass
    severity = "warning" if local_only else "error"
    message = (
        "No Longrun token is set. This is suitable only for localhost; add one in Settings → Keys."
        if local_only else
        "No Longrun token is set while this server is network-reachable. Set LONGRUN_TOKEN in Settings → Keys."
    )
    return [_issue("auth.token_missing", severity, "Longrun token is not configured",
                   message, "Longrun token", action="keys")]


def _models(provider: dict) -> set[str]:
    """Normalize a provider's configured model roster.

    A LOCAL provider is also completed from its live server roster: the UI lists
    an installed model that providers.yaml does not name, so flagging that same
    selection as "not configured" would be a false positive. The live map is the
    one shared cache (`providers.local_contexts`), never a second fetch.
    """
    result = set()
    rows = provider.get("models") or []
    if isinstance(rows, list):
        for entry in rows:
            value = entry.get("id") if isinstance(entry, dict) else entry
            if value is not None and str(value).strip():
                result.add(str(value).strip())
    if provider.get("local"):
        try:
            from longrun.model import providers as _providers
            result.update(_providers.local_contexts(provider.get("id")) or {})
        except Exception:  # noqa: BLE001 — live metadata is optional
            pass
    return result


def _provider_for_ref(ref: str, providers: dict[str, dict]) -> tuple[dict | None, str]:
    """Resolve a configured or bare model reference without contacting a provider."""
    if ":" in ref:
        provider_id, model_id = ref.split(":", 1)
        provider = providers.get(provider_id)
        return (provider, model_id) if provider else (None, model_id)
    for provider in providers.values():
        if ref in _models(provider):
            return provider, ref
    return None, ref


def validate_provider_config(config: dict, env: Mapping[str, str],
                             routing: dict, selected_model: str | None,
                             session_id: str | None = None) -> list[dict]:
    """Find selected/default/routed model configuration problems without network calls."""
    issues = []
    cfg = config if isinstance(config, dict) else {}
    raw_providers = cfg.get("providers")
    if not isinstance(raw_providers, list):
        return [_issue(
            "config.providers_invalid", "error", "Provider config is invalid",
            "The provider list must be a list. Review the provider configuration in Settings → Config files.",
            "providers.yaml", action="config")]
    providers = {}
    for provider in raw_providers:
        if not isinstance(provider, dict) or not str(provider.get("id") or "").strip():
            issues.append(_issue(
                "provider.entry_invalid", "error", "Provider entry is invalid",
                "Each provider needs a valid ID and mapping in Settings → Models.",
                "providers.yaml", action="models"))
            continue
        provider_id = str(provider["id"]).strip()
        if provider_id in providers:
            issues.append(_issue(
                "provider.id_duplicate", "error", "Provider ID is duplicated",
                "Give each provider a unique ID in Settings → Models.",
                provider_id, action="models"))
            continue
        if "models" in provider and not isinstance(provider.get("models"), list):
            issues.append(_issue(
                "provider.models_invalid", "error", "Provider model list is invalid",
                "Enter model IDs as a list in Settings → Models.",
                provider_id, action="models"))
        providers[provider_id] = provider
    safe_session = _safe_session(session_id)

    def check_ref(ref: object, source: str, severity: str, scope: str,
                  session: str | None = None) -> None:
        model_ref = _safe_ref(ref)
        if not model_ref:
            if ref is not None and str(ref).strip():
                issues.append(_issue(
                    "model.reference_invalid", severity, "Model reference is invalid",
                    "Use a configured provider and model ID in Settings → Models.",
                    source, action="models", scope=scope, session=session))
            return
        provider, model_id = _provider_for_ref(model_ref, providers)
        if provider is None:
            prefix = model_ref.split(":", 1)[0] if ":" in model_ref else ""
            known_provider = prefix in providers
            issues.append(_issue(
                "model.id_not_configured" if known_provider else "model.provider_unknown",
                severity,
                "Model ID is not configured" if known_provider else "Provider is not configured",
                "Add this exact model ID to its provider in Settings → Models."
                if known_provider else
                "Select a configured provider and model in Settings → Models.",
                source, action="models", scope=scope, session=session,
                model=model_ref))
            return
        provider_id = _safe_label(provider.get("id"), "provider")
        if model_id not in _models(provider):
            issues.append(_issue(
                "model.id_not_configured", severity, "Model ID is not in the provider list",
                "Add this model ID to the provider in Settings → Models. Diagnostics do not contact the provider.",
                provider_id, action="models", scope=scope, session=session,
                model=model_ref))
        base_url = str(provider.get("base_url") or "").strip()
        if not base_url:
            issues.append(_issue(
                "provider.base_url_missing", severity, "Provider URL is missing",
                "Set the provider's base URL in Settings → Models.",
                provider_id, action="models", scope=scope, session=session,
                model=model_ref))
        else:
            try:
                parsed_url = urlsplit(base_url)
                valid_url = parsed_url.scheme in ("http", "https") and bool(parsed_url.hostname)
            except ValueError:
                valid_url = False
            if not valid_url:
                issues.append(_issue(
                    "provider.base_url_invalid", severity, "Provider URL is invalid",
                    "Use a reachable HTTP or HTTPS base URL in Settings → Models.",
                    provider_id, action="models", scope=scope, session=session,
                    model=model_ref))
        env_name = str(provider.get("api_key_env") or "").strip()
        if env_name and not _ENV_NAME.fullmatch(env_name):
            issues.append(_issue(
                "provider.key_name_invalid", severity, "Provider key name is invalid",
                "Use an uppercase environment-variable name in Settings → Models.",
                provider_id, action="models", scope=scope, session=session,
                model=model_ref))
        elif env_name and not provider.get("local") and not (env or {}).get(env_name):
            issues.append(_issue(
                "provider.key_missing", severity, "Provider key is missing",
                "Set %s in Settings → Keys." % env_name,
                provider_id, action="keys", scope=scope, session=session,
                model=model_ref))

    configured_default = cfg.get("default")
    if configured_default is not None and not isinstance(configured_default, str):
        issues.append(_issue(
            "provider.default_invalid", "error", "Default model reference is invalid",
            "Set the default to a provider:model reference in Settings → Models.",
            "providers.yaml", action="models"))
        configured_default = None
    active_ref = str(selected_model or configured_default or "").strip()
    active_scope = "session" if safe_session else "global"
    check_ref(active_ref, "Selected chat model", "error", active_scope, safe_session)
    if configured_default and configured_default != active_ref:
        check_ref(configured_default, "Default chat model", "warning", "global")

    route_config = routing if isinstance(routing, dict) else {}
    roles = route_config.get("roles")
    if roles is not None and not isinstance(roles, dict):
        issues.append(_issue(
            "config.routing_invalid", "error", "Model routing config is invalid",
            "The roles setting must be a mapping. Review it in Settings → Config files.",
            "routing.yaml", action="config"))
        roles = {}
    if isinstance(roles, dict):
        for role_name, spec in roles.items():
            if not isinstance(spec, dict):
                issues.append(_issue(
                    "config.routing_role_invalid", "warning", "Routing role is invalid",
                    "This routing entry must be a mapping. Review it in Settings → Config files.",
                    "routing.yaml", action="config"))
                continue
            role = _safe_label(role_name, "routing")
            refs = [spec.get("model")]
            fallbacks = spec.get("fallbacks")
            if fallbacks is not None and not isinstance(fallbacks, list):
                issues.append(_issue(
                    "config.routing_fallbacks_invalid", "warning", "Model fallbacks are invalid",
                    "Routing fallbacks must be a list of model references.",
                    "routing.yaml", action="config"))
            if isinstance(fallbacks, list):
                refs.extend(fallbacks)
            for ref in refs:
                if ref:
                    check_ref(ref, "Routing · " + role, "warning", "global")

    if not active_ref:
        ready = any(
            isinstance(provider, dict) and provider.get("models")
            and (provider.get("local")
                 or not provider.get("api_key_env")
                 or bool((env or {}).get(str(provider.get("api_key_env")))))
            for provider in raw_providers)
        if not ready:
            missing_keys = sorted({
                str(provider.get("api_key_env"))
                for provider in raw_providers
                if isinstance(provider, dict) and not provider.get("local")
                and provider.get("models")
                and _ENV_NAME.fullmatch(str(provider.get("api_key_env") or ""))
                and not (env or {}).get(str(provider.get("api_key_env")))
            })
            key_hint = (" Missing keys: " + ", ".join(missing_keys[:5]) + "."
                        if missing_keys else "")
            issues.append(_issue(
                "model.none_available", "error", "No model is ready",
                "Add a provider key in Settings → Keys or configure a local model in Settings → Models."
                + key_hint,
                "Models", action="models"))
    return issues


def run_checks(checks: list[tuple[str, Callable[[], list[dict]]]]) -> list[dict]:
    """Run all diagnostics independently; a broken check becomes one safe finding."""
    issues = []
    for name, check in checks or []:
        source = _safe_label(name, "settings")
        try:
            result = check()
            if isinstance(result, list):
                issues.extend(issue for issue in result if isinstance(issue, dict))
            elif result:
                issues.append(_issue(
                    "diagnostics.check_failed", "warning", "Settings check returned invalid data",
                    "Longrun could not complete this check. Review this settings area.",
                    source, action="config"))
        except Exception:  # noqa: BLE001 — diagnostics must never break a session
            issues.append(_issue(
                "diagnostics.check_failed", "warning", "Settings check could not complete",
                "Longrun could not inspect this settings area. Review it in Settings.",
                source, action="config"))
    return issues


def _config_sources() -> list[dict]:
    """List tracked YAML and known local overlays; absent optional files are skipped."""
    config_dir = os.path.join(REPO_ROOT, "config")
    data_dir = DATA_DIR
    candidates = []
    try:
        names = sorted(os.listdir(config_dir))
    except OSError:
        names = []
    for name in names:
        if name.endswith((".yaml", ".yml")):
            candidates.append({"name": name, "path": os.path.join(config_dir, name),
                               "format": "yaml",
                               "required": name in ("providers.yaml", "tools.yaml", "routing.yaml")})
    for name in ("providers.yaml", "tools.yaml", "routing.yaml"):
        if name not in names:
            candidates.append({"name": name, "path": os.path.join(config_dir, name),
                               "format": "yaml", "required": True})

    providers_local = os.environ.get("LONGRUN_PROVIDERS_LOCAL") or \
        os.path.join(config_dir, "providers.local.yaml")
    subagents_cfg = os.environ.get("LONGRUN_SUBAGENTS_CFG") or \
        os.path.join(config_dir, "subagents.yaml")
    explicit_hooks = os.environ.get("LONGRUN_HOOKS")
    hooks_overlay = os.environ.get("LONGRUN_HOOKS_OVERLAY") or (
        "" if explicit_hooks else os.path.join(data_dir, "hooks.overlay.yaml"))
    explicit_decisions = os.environ.get("LONGRUN_DECISIONS")
    decisions_overlay = os.environ.get("LONGRUN_DECISIONS_OVERLAY") or (
        "" if explicit_decisions else os.path.join(data_dir, "decisions.overlay.yaml"))
    mcp_json = os.path.join(config_dir, "mcp_clients.local.json")
    mcp_yaml = os.path.join(config_dir, "mcp_clients.local.yaml")
    candidates.extend([
        {"name": "providers.local.yaml", "path": providers_local, "format": "yaml"},
        {"name": "subagents.yaml", "path": subagents_cfg, "format": "yaml"},
        {"name": "mcp_clients.local.json", "path": mcp_json, "format": "json"},
        {"name": "mcp_clients.local.yaml", "path": mcp_yaml, "format": "yaml"},
        {"name": "compaction.local.yaml",
         "path": os.path.join(config_dir, "compaction.local.yaml"), "format": "yaml"},
        {"name": "tools.overlay.yaml",
         "path": os.path.join(data_dir, "tools.overlay.yaml"), "format": "yaml"},
        {"name": "tools.overlay.json",
         "path": os.path.join(data_dir, "tools.overlay.json"), "format": "json"},
        {"name": "hooks.overlay.yaml", "path": hooks_overlay, "format": "yaml"},
        {"name": "decisions.overlay.yaml", "path": decisions_overlay, "format": "yaml"},
        {"name": "index.overlay.yaml",
         "path": os.path.join(data_dir, "index.overlay.yaml"), "format": "yaml"},
        {"name": "config.json",
         "path": os.path.join(os.environ.get("LONGRUN_CONFIG_DIR")
                              or os.path.join(os.path.expanduser("~"), ".config", "longrun"),
                              "config.json"),
         "format": "json"},
    ])
    if explicit_hooks:
        candidates.append({"name": "hooks.active.yaml", "path": explicit_hooks,
                           "format": "yaml"})
    unique = []
    seen = set()
    for source in candidates:
        path = os.path.abspath(source["path"])
        key = os.path.normcase(path)
        if key not in seen:
            seen.add(key)
            unique.append({**source, "path": path})
    return unique


def _read_yaml(path: str) -> dict:
    """Read a YAML mapping without invoking loaders that may create defaults."""
    import yaml
    with open(path, "r", encoding="utf-8") as stream:
        value = yaml.safe_load(stream)
    return value if isinstance(value, dict) else {}


def _raw_routing() -> dict:
    """Read existing routing data without creating a missing config file."""
    path = os.path.join(REPO_ROOT, "config", "routing.yaml")
    if not os.path.isfile(path):
        return {}
    try:
        return _read_yaml(path)
    except Exception:  # noqa: BLE001 — parse issue is reported by config scan
        return {}


def _structured_setting_issues(config_issues: list[dict]) -> list[dict]:
    """Validate each schema-backed setting section independently."""
    from longrun.core import settings

    invalid_files = {
        issue.get("source") for issue in config_issues
        if issue.get("code") in ("config.invalid", "config.missing")
    }
    issues = []
    routing_path = os.path.join(REPO_ROOT, "config", "routing.yaml")
    routing_ready = os.path.isfile(routing_path) and "routing.yaml" not in invalid_files
    try:
        sections = (settings._sections() if routing_ready else
                    [section for section in settings.SECTIONS if section.get("id") != "routing"])
    except Exception:  # noqa: BLE001 — malformed routing must not hide other setting issues
        sections = [section for section in settings.SECTIONS if section.get("id") != "routing"]
        issues.append(_issue(
            "config.routing_invalid", "warning", "Routing settings could not be inspected",
            "Review model routing in Settings → Config files.",
            "routing.yaml", action="config"))
    for section in sections:
        filename = str(section.get("file") or "")
        if filename in invalid_files:
            continue
        path = os.path.join(REPO_ROOT, "config", filename)
        if not os.path.isfile(path):
            continue
        try:
            effective = settings._effective(filename)
            values = {
                field["path"]: settings._get(effective, field["path"])
                for field in (section.get("fields") or [])
                if field.get("path")
            }
            issues.extend(validate_setting_values([{
                "file": filename,
                "panel": section.get("panel") or "",
                "fields": section.get("fields") or [],
                "values": values,
            }]))
        except Exception:  # noqa: BLE001 — preserve other settings checks
            issues.append(_issue(
                "config.load_failed", "warning", "Settings could not be loaded",
                "Longrun could not inspect this settings section. Review it in Settings → Config files.",
                filename, action="config"))
    return issues


def recent_failures(events: list[dict], now: float,
                    session_id: str | None = None) -> list[dict]:
    """Rebuild safe recent model issues from bounded diagnostic events only."""
    cutoff = float(now) - 86400.0
    requested_session = _safe_session(session_id)
    found = {}
    for row in events or []:
        if not isinstance(row, dict):
            continue
        data = row.get("data") if isinstance(row.get("data"), dict) else row
        code = data.get("code")
        template = _RUNTIME_MESSAGES.get(code)
        if not template:
            continue
        try:
            occurred = float(data.get("occurred_at") or row.get("ts") or 0)
        except (TypeError, ValueError):
            continue
        if occurred < cutoff or occurred > float(now) + 60.0:
            continue
        session = _safe_session(data.get("session"))
        if requested_session and session != requested_session:
            continue
        model = _safe_ref(data.get("model"))
        severity, title, message, action = template
        issue = _issue(code, severity, title, message,
                       data.get("source") or "Model provider",
                       action=action, scope="session" if session else "global",
                       session=session, model=model, occurred_at=occurred)
        key = (code, session, model)
        if key not in found or occurred > found[key]["occurred_at"]:
            found[key] = issue
    return sorted(found.values(), key=lambda item: item["occurred_at"], reverse=True)[:10]


def summarize(issues: list[dict]) -> dict:
    """Count findings without treating optional information as actionable."""
    counts = {severity: 0 for severity in ("error", "warning", "info")}
    for issue in issues or []:
        severity = issue.get("severity")
        if severity in counts:
            counts[severity] += 1
    return {"errors": counts["error"], "warnings": counts["warning"],
            "info": counts["info"],
            "actionable": counts["error"] + counts["warning"]}


def classify_model_error(error: BaseException, model: str | None = None,
                         session: str | None = None) -> dict:
    """Map a provider exception to a stable message without returning its body or URL."""
    status = getattr(error, "code", None)
    try:
        status = int(status) if status is not None else None
    except (TypeError, ValueError):
        status = None
    if status is None:
        match = re.search(r"\b(401|403|404|429|5\d{2})\b", str(error))
        status = int(match.group(1)) if match else None
    reason = getattr(error, "reason", None)
    if status in (401, 403):
        code = "provider.auth_rejected"
    elif status == 404:
        code = "provider.model_not_found"
    elif status in (400, 422):
        code = "provider.request_rejected"
    elif status == 429:
        code = "provider.rate_limited"
    elif status is not None and status >= 500:
        code = "provider.unavailable"
    elif isinstance(error, (TimeoutError, socket.timeout)) or isinstance(
            reason, (TimeoutError, socket.timeout, ConnectionError)):
        code = "provider.unreachable"
    elif isinstance(error, OSError) or isinstance(reason, OSError):
        code = "provider.unreachable"
    else:
        code = "provider.request_failed"
    severity, title, message, action = _RUNTIME_MESSAGES[code]
    provider = str(model or "").split(":", 1)[0]
    return _issue(code, severity, title, message,
                  provider if provider else "Model provider",
                  action=action, scope="session" if session else "global",
                  session=session, model=model, occurred_at=time.time())


def report_model_failure(error: BaseException, session: str | None,
                         model: str | None,
                         publisher: Callable[..., object]) -> dict:
    """Classify and publish a model failure without letting diagnostics break chat."""
    try:
        issue = classify_model_error(error, model=model, session=session)
    except Exception:  # noqa: BLE001 — preserve the original chat failure
        issue = _issue(
            "provider.request_failed", "error", "Model request failed",
            "The model request failed. Review its provider and model settings before retrying.",
            "Model provider", action="models", scope="session" if session else "global",
            session=session, model=model, occurred_at=time.time())
    safe_session = issue.get("session")
    try:
        publisher("chat.error", session=safe_session, error=issue["message"],
                  code=issue["code"], model=issue.get("model"))
    except Exception:  # noqa: BLE001 — persistence failure must not hide the user-facing error
        pass
    try:
        publisher("settings.diagnostic", **issue)
    except Exception:  # noqa: BLE001 — diagnostics are additive to the chat failure
        pass
    return issue


def _runtime_issues(session_id: str | None) -> list[dict]:
    """Read only newly emitted, already-sanitized provider failure events."""
    try:
        from longrun.core import events
        if not os.path.isfile(events.DB_PATH):
            return []
        rows = events.query_events(kind="settings.diagnostic", limit=500)
        return recent_failures(rows, time.time(), session_id=session_id)
    except Exception:  # noqa: BLE001 — history is optional for current checks
        return []


def _dedupe(issues: list[dict]) -> list[dict]:
    """Keep one finding for each scope, code, source, model, and session."""
    out, seen = [], set()
    for issue in issues:
        key = (issue.get("scope"), issue.get("code"), issue.get("source"),
               issue.get("model"), issue.get("session"))
        if key not in seen:
            seen.add(key)
            out.append(issue)
    return sorted(out, key=lambda item: (
        _SEVERITY_ORDER.get(item.get("severity"), 3),
        item.get("source", ""), item.get("code", "")))


def collect(session_id: str | None = None, model: str | None = None,
            host: str = "127.0.0.1") -> dict:
    """Collect local-only diagnostics; never sends a model or provider request."""
    safe_session = _safe_session(session_id)

    def _authentication() -> list[dict]:
        from longrun.core import server
        return auth_issues(bool(server.AUTH_TOKEN), host)

    def _configuration() -> list[dict]:
        config_issues = validate_config_sources(_config_sources())
        return config_issues + _structured_setting_issues(config_issues)

    def _models() -> list[dict]:
        from longrun.core import server
        from longrun.model import providers
        selected = model
        if not selected and safe_session:
            try:
                selected = (server.load_session(safe_session) or {}).get("model")
            except Exception:  # noqa: BLE001 — missing session data must not hide global checks
                selected = None
        providers.load_env()
        return validate_provider_config(
            providers.load(reload=True), dict(os.environ), _raw_routing(),
            selected, safe_session)

    checks = [
        ("authentication", _authentication),
        ("configuration", _configuration),
        ("model providers", _models),
        ("recent model failures", lambda: _runtime_issues(safe_session)),
    ]
    issues = _dedupe(run_checks(checks))
    return {
        "ok": True,
        "generated_at": time.time(),
        "summary": summarize(issues),
        "issues": issues,
    }
