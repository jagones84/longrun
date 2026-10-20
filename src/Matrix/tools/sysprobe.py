"""Matrix experimental tool: sysprobe - host/runtime snapshot without a shell.

Reads /proc and shutil.disk_usage directly, so it still works when the shell
tool is denied, approval-gated, or the host is too loaded to fork a process.
Read-only: it never writes, never signals, never spawns anything.
"""

import os
import platform
import shutil
import sys
import time

TOOL_SCHEMA = {
    "description": (
        "[MATRIX experimental] Report a compact host/runtime snapshot (cpu, memory, "
        "disk, python) by reading /proc directly - no shell, read-only."
    ),
    "type": "object",
    "properties": {
        "section": {
            "type": "string",
            "enum": ["all", "cpu", "mem", "disk", "runtime"],
            "description": "Which section to report (default: all).",
        },
        "path": {
            "type": "string",
            "description": "Filesystem path to measure for the disk section (default: cwd).",
        },
    },
    "required": [],
    "approval": "auto",
}

TOOL_SCHEMAS = {
    "sysprobe.snapshot": dict(TOOL_SCHEMA),
    "sysprobe.cpu": {"description": "[MATRIX experimental] Host CPU load & cores via /proc.", "type": "object", "properties": {}, "required": [], "approval": "auto"},
    "sysprobe.mem": {"description": "[MATRIX experimental] Host RAM & swap usage via /proc/meminfo.", "type": "object", "properties": {}, "required": [], "approval": "auto"},
    "sysprobe.disk": {"description": "[MATRIX experimental] Filesystem capacity & free space.", "type": "object", "properties": {"path": {"type": "string"}}, "required": [], "approval": "auto"},
    "sysprobe.runtime": {"description": "[MATRIX experimental] Python/OS runtime snapshot.", "type": "object", "properties": {}, "required": [], "approval": "auto"},
}

_SECTIONS = ("all", "cpu", "mem", "disk", "runtime")


def _cpu():
    load = None
    try:
        with open("/proc/loadavg", "r", encoding="utf-8") as f:
            load = f.read().split()[:3]
    except OSError:
        pass
    model = ""
    try:
        with open("/proc/cpuinfo", "r", encoding="utf-8") as f:
            for line in f:
                low = line.lower()
                if low.startswith(("model name", "hardware")) and ":" in line:
                    model = line.split(":", 1)[1].strip()
                    if model:
                        break
    except OSError:
        pass
    return {
        "cores": os.cpu_count() or 0,
        "loadavg_1_5_15": load,
        "cpu_model": model or platform.processor() or "unknown",
    }


def _mem():
    keys = ("MemTotal", "MemAvailable", "MemFree", "SwapTotal", "SwapFree")
    info = {}
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            for line in f:
                k, _, rest = line.partition(":")
                if k in keys:
                    info[k] = int(rest.strip().split()[0])
    except (OSError, ValueError, IndexError):
        return {"error": "cannot read /proc/meminfo"}
    gb = {k: round(v / 1048576.0, 2) for k, v in info.items()}
    used = None
    if info.get("MemTotal") and info.get("MemAvailable"):
        used = round((info["MemTotal"] - info["MemAvailable"]) / 1048576.0, 2)
    return {"totals_gb": gb, "used_gb": used}


def _disk(path):
    p = os.path.abspath(os.path.expanduser(path or os.getcwd()))
    while p and not os.path.exists(p):
        parent = os.path.dirname(p)
        if parent == p:
            break
        p = parent
    try:
        du = shutil.disk_usage(p)
    except OSError as e:
        return {"path": p, "error": str(e)}
    return {
        "path": p,
        "total_gb": round(du.total / 1073741824.0, 1),
        "used_gb": round(du.used / 1073741824.0, 1),
        "free_gb": round(du.free / 1073741824.0, 1),
        "used_pct": round(100.0 * du.used / du.total, 1) if du.total else None,
    }


def _runtime():
    return {
        "python": sys.version.split()[0],
        "implement": platform.python_implementation(),
        "machine": platform.machine(),
        "system": platform.system(),
        "kernel": platform.release(),
        "hostname": platform.node(),
        "pid": os.getpid(),
        "now": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def execute(args, run_id=None, subtool=None):
    """Return the requested host snapshot section(s). Never raises."""
    args = args or {}
    raw = args.get("section")
    if raw is None and subtool in ("cpu", "mem", "disk", "runtime"):
        raw = subtool
    section = str(raw if raw is not None else "all").strip().lower()
    if section not in _SECTIONS:
        return {"ok": False, "error": "unknown section %r" % section, "valid": list(_SECTIONS)}
    out = {"ok": True, "section": section}
    try:
        if section in ("all", "cpu"):
            out["cpu"] = _cpu()
        if section in ("all", "mem"):
            out["mem"] = _mem()
        if section in ("all", "disk"):
            out["disk"] = _disk(args.get("path"))
        if section in ("all", "runtime"):
            out["runtime"] = _runtime()
    except Exception as e:
        return {"ok": False, "error": "%s: %s" % (type(e).__name__, e), "section": section}
    return out
