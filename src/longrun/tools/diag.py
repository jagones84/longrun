#!/usr/bin/env python3
"""Native self-diagnosis helpers (JAG-426 · Domain 1).

The harness must be able to inspect ITSELF without depending on any external
process/performance manager (PMC). Everything here uses only the Python stdlib
plus core system primitives (`/proc`, `shutil`, `socket`, `subprocess`), and
every probe DEGRADES to a partial result instead of raising, so a missing tool
(no nvidia-smi, no systemd, no /proc) can never break a diagnosis.

Consumed by the `self` tool (action=diagnose|logs|context|tools). Pure module:
no dependency on the server at import time (lazy imports only).
"""

import os
import shutil
import socket
import sys
import time

from longrun.util.paths import REPO_ROOT as REPO


def _safe(fn, default=None):
    """Run a probe and swallow any failure into `default` (never raise)."""
    try:
        return fn()
    except Exception:  # noqa: BLE001 — a probe must never break the diagnosis
        return default


# ------------------------------------------------------------------ health ----

def _meminfo():
    """(total_mb, available_mb) from /proc/meminfo, or (None, None)."""
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            rows = {}
            for line in f:
                k, _, v = line.partition(":")
                rows[k.strip()] = v.strip()
        tot = int(rows["MemTotal"].split()[0]) // 1024
        avail = int(rows.get("MemAvailable", "0").split()[0]) // 1024
        return tot, avail
    except Exception:  # noqa: BLE001 — non-Linux / restricted /proc
        return None, None


def _loadavg():
    try:
        return [round(x, 2) for x in os.getloadavg()]
    except (OSError, AttributeError):
        return None


def _disk(root=REPO):
    try:
        u = shutil.disk_usage(root)
        return {"path": root, "total_gb": round(u.total / 1e9, 1),
                "free_gb": round(u.free / 1e9, 1),
                "used_pct": round(100.0 * (u.total - u.free) / u.total, 1)}
    except OSError:
        return None


def _gpu():
    """Best-effort GPU line via nvidia-smi; None when absent (graceful)."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    import subprocess as sp
    try:
        out = sp.run([exe, "--query-gpu=name,utilization.gpu,temperature.gpu,memory.used,memory.total",
                      "--format=csv,noheader,nounits"],
                     capture_output=True, text=True, timeout=4)
        line = (out.stdout or "").strip().splitlines()
        if not line:
            return None
        parts = [p.strip() for p in line[0].split(",")]
        return {"name": parts[0], "util_pct": parts[1] if len(parts) > 1 else None,
                "temp_c": parts[2] if len(parts) > 2 else None,
                "mem_used_mb": parts[3] if len(parts) > 3 else None,
                "mem_total_mb": parts[4] if len(parts) > 4 else None}
    except Exception:  # noqa: BLE001 — no driver / timeout
        return None


def _port_open(host, port, timeout=0.3):
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def _service(name="longrun.service"):
    from longrun.util import osutil
    state = "n/a"
    if getattr(osutil, "IS_POSIX", False) and shutil.which("systemctl"):
        import subprocess as sp
        try:
            state = (sp.run(["systemctl", "--user", "is-active", name],
                            capture_output=True, text=True, timeout=4).stdout or "").strip() or "unknown"
        except Exception:  # noqa: BLE001
            state = "unknown"
    return {"unit": name, "active": state, "restart": osutil.service_hint()}


def health(host="127.0.0.1", port=8790) -> dict:
    """A one-shot health snapshot. Always returns a dict; probes may be None."""
    tot, avail = _meminfo()
    try:
        from longrun.core import server as _srv
        version = str(getattr(_srv, "VERSION", "unknown"))
    except Exception:  # noqa: BLE001
        version = "unknown"
    return {
        "ok": True,
        "ts": round(time.time(), 3),
        "version": version,
        "python": sys.version.split()[0],
        "host": host,
        "cpu": {"count": os.cpu_count(), "loadavg": _loadavg()},
        "memory_mb": ({"total": tot, "available": avail} if tot else None),
        "disk": _disk(),
        "gpu": _gpu(),
        "service": _service(),
        "ports": {str(port): _port_open(host, port), str(port + 1): _port_open(host, port + 1)},
        "router": os.environ.get("LONGRUN_ROUTER", "http://127.0.0.1:8080"),
        "sandbox": _safe(lambda: __import__("longrun.tools.sandbox", fromlist=["probe"]).probe()),
    }


# -------------------------------------------------------------------- logs ----

def log_tail(session=None, limit=100, kind=None) -> dict:
    """The harness's own execution history, from the durable event log.

    There is no plain-text log file: the event store (`data/events.db`) IS the
    structured log (every turn, tool call, approval, error). Newest first.
    """
    try:
        from longrun.core import events
        rows = events.query_events(session=session, kind=kind, limit=int(limit or 100))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "event log unavailable: %s" % e, "lines": []}
    lines = []
    for r in rows:
        t = time.strftime("%H:%M:%S", time.localtime(r.get("ts") or 0))
        extra = {k: v for k, v in r.items() if k not in ("id", "ts", "kind")}
        lines.append("%s %-22s %s" % (t, r.get("kind"), extra if extra else ""))
    return {"ok": True, "source": "events.db", "count": len(lines),
            "session": session, "lines": lines}


# ----------------------------------------------------------------- context ----

def context(session) -> dict:
    """How full is THIS session's context window (dry-run, no LLM call)."""
    if not session:
        return {"ok": False, "error": "session id required"}
    try:
        from longrun.model import context_engine
        st = context_engine.preview(session)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "context preview failed: %s" % e}
    if isinstance(st, dict) and st.get("error"):
        return {"ok": False, "error": st["error"]}
    return {"ok": True, "session": session, "context": st}


# ------------------------------------------------------------------- tools ----

def settings_report(session=None, model=None, code=None, source=None, limit=50) -> dict:
    """The SAME diagnostics the Settings panel runs, filtered for isolation.

    No check is reimplemented here: `longrun.core.diagnostics.collect()` is the
    single source. Each finding carries `code`, `severity`, `scope`, `source`
    and, when known, `file`/`field`/`panel`/`session`/`model`, so an agent can
    isolate one failure (`code=` / `source=`) instead of guessing from a prose
    error. Local only: this never contacts a provider.
    """
    try:
        from longrun.core import diagnostics
        report = diagnostics.collect(session_id=session or None, model=model or None)
    except Exception as e:  # noqa: BLE001 — diagnosis must degrade, never raise
        return {"ok": False, "error": "diagnostics failed: %s" % e, "issues": []}
    issues = [i for i in (report.get("issues") or []) if isinstance(i, dict)]
    if code:
        want = str(code).strip().lower()
        issues = [i for i in issues if str(i.get("code") or "").lower() == want]
    if source:
        want = str(source).strip().lower()
        issues = [i for i in issues if want in str(i.get("source") or "").lower()]
    try:
        cap = max(1, min(int(limit or 50), 200))
    except (TypeError, ValueError):
        cap = 50
    filtered = bool(code or source)
    out = {
        "ok": bool(report.get("ok", True)),
        "total": len(issues),
        "summary": (diagnostics.summarize(issues) if filtered
                    else (report.get("summary") or {})),
        "issues": issues[:cap],
    }
    if code:
        out["code"] = code
    if source:
        out["source"] = source
    return out


def tools_report(tool=None, query=None) -> dict:
    """What the harness can do right now: native tools + their policy + MCP.

    JAG-513: this is the TOOL DISCOVERY surface the system prompt points at, so
    it answers three questions and nothing more:
      * no args          -> the compact INDEX (names + one-line descriptions);
      * `query="words"`  -> the same index, filtered by name/description;
      * `tool="fs.read"` -> that tool's FULL input schema (every property with
        its type, default and required marker), which is what the model must read
        BEFORE calling a tool it has not used in this session.

    A name the registry does not know is an ERROR with near-miss suggestions —
    never a silent empty answer, which is how the model used to start guessing.
    """
    try:
        from longrun.tools import registry
        cat = registry.catalog()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "registry unavailable: %s" % e}
    native, external, enabled = [], [], []
    for t in cat:
        name = t.get("name")
        if not name:
            continue
        (external if "__" in name else native).append(name)
        if t.get("enabled", True):
            enabled.append(name)
    index = {t["name"]: {"enabled": t.get("enabled", True),
                         "origin": t.get("origin"),
                         "approval": t.get("approval"),
                         "description": (t.get("description") or "").strip()}
             for t in cat if t.get("name")}
    if tool:
        want = str(tool).strip()
        entry = index.get(want)
        if entry is None:
            # Accept a bare subtool name when it is UNIQUE ("read" -> fs.read) and
            # otherwise suggest the real candidates instead of failing blind.
            hits = [n for n in sorted(index)
                    if n.split(".")[-1] == want or n.split("__")[-1] == want]
            if len(hits) == 1:
                want, entry = hits[0], index[hits[0]]
            else:
                near = hits or [n for n in sorted(index) if want.lower() in n.lower()]
                return {"ok": False, "error": "unknown tool %r" % tool,
                        "suggestions": near[:20],
                        "hint": ("call self {action:'tools', query:'<words>'} to "
                                 "search the registry")}
        spec = registry.tool_spec(want) or {}
        schema = spec.get("schema") or {}
        props = schema.get("properties") or {}
        return {"ok": True, "tool": {
            "name": want,
            "enabled": entry["enabled"],
            "origin": entry["origin"],
            "approval": entry["approval"],
            "description": entry["description"],
            "required": list(schema.get("required") or []),
            "anyOf": list(schema.get("anyOf") or []),
            "properties": props,
            "example_args": _example_args(
                props, list(schema.get("required") or []),
                list(schema.get("anyOf") or [])),
            "roots": spec.get("roots"),
        }, "hint": ("`args` is ALWAYS a JSON OBJECT: {\"action\":\"tool\","
                    "\"tool\":\"%s\",\"args\":{...}}" % want)}
    if query:
        q = str(query).strip().lower()
        index = {n: e for n, e in index.items()
                 if q in n.lower() or q in (e.get("description") or "").lower()}
        native = [n for n in native if n in index]
        external = [n for n in external if n in index]
        enabled = [n for n in enabled if n in index]
    out = {"ok": True, "count": len(native), "external_count": len(external),
           "native": sorted(native), "external": sorted(external),
           "enabled_count": len(enabled), "tools": index}
    if query:
        out["query"] = query
    out["hint"] = ("read a schema with self {action:'tools', tool:'<name>'} "
                   "BEFORE calling a tool you have not used in this session")
    return out


def _example_args(props, required, any_of=None) -> dict:
    """The smallest valid call: the REQUIRED args, else `action`, else the first two."""
    if not isinstance(props, dict) or not props:
        return {}
    keys = [k for k in required if k in props]
    if not keys:
        for alternative in any_of or []:
            candidate = [k for k in alternative.get("required", []) if k in props]
            if candidate:
                keys = candidate
                break
    if not keys and "action" in props:
        keys = ["action"]
    if not keys:
        keys = list(props)[:2]
    return {k: _example(props[k]) for k in keys}


def _example(value) -> object:
    """A short plausible value for a schema property, for the discovery example."""
    if not isinstance(value, dict):
        return "?"
    if value.get("enum"):
        return value["enum"][0]
    if value.get("default") is not None:
        return value["default"]
    kind = value.get("type")
    if kind == "integer" or kind == "number":
        return 1
    if kind == "boolean":
        return False
    if kind == "array":
        return []
    if kind == "object":
        return {}
    return "<%s>" % (value.get("description", "value").split(".")[0][:40] or "value")
