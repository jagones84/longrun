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
# v662: the router address has ONE reader (`rllm.ROUTER_BASE`, which honours
# `LONGRUN_ROUTER`) — the health report used to re-type the env var and the default.
from longrun.model.rllm import ROUTER_BASE


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
        "router": ROUTER_BASE,
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


# ------------------------------------------------------------------- trace ----

#: The harness's own interventions, recognised by their leading words in the transcript.
#: `_inject(content, kind)` records `gate: kind` on new messages; the text table below is
#: what older sessions (written before the field existed) can still be read with.
_GATE_HINTS = (
    ("delivery_floor", "DELIVERY FLOOR"),
    ("evidence_gate", "EVIDENCE GATE"),
    ("closure_check", "CLOSING CHECK"),
    ("continue", "CONTINUE"),
    ("plan", "plan updated"),
    ("todos", "Task list saved"),
    ("observation", "Observation"),
    ("off_intent", "off-intent"),
)


def _gate_of(content):
    """The gate name behind a `[harness] …` turn: the stored `gate`, else the prose."""
    text = str(content or "")
    for name, hint in _GATE_HINTS:
        if hint.lower() in text.lower():
            return name
    return "other"


def _is_answer(body):
    """True when an assistant turn is a REPLY the operator could read.

    A turn that carries the model's native tool-call markup (DSML / Hermes /
    `arg_key` template / a JSON action) is MACHINE text, never a chat reply —
    `agent._looks_like_json_action` is the one owner of that judgement, so the
    repeat detector asks it instead of re-deriving the shapes. Measured
    2026-11-02 on session `777378644e9c`: 7 flagged "repeated answers" were really
    6 DISTINCT tool calls whose markup shared the first 160 characters — the
    detector cried wolf on the very loop it exists to catch.
    """
    try:
        from longrun.agent.agent import _looks_like_json_action
        return not _looks_like_json_action(body)
    except Exception:  # noqa: BLE001 — a missing predicate must not kill the trace
        return True


def harness_trace(session, limit=40) -> dict:
    """What the HARNESS did in this session — the half a transcript hides.

    The survey this comes from (Awesome-Agent-Harness, ETCSLV) rates almost every system
    `Partial` on **V (evaluation interface)** because a transcript shows the model's work
    but not the runtime's decisions. Longrun already stores both halves and nothing joined
    them: finding a wasted turn meant reading 435 messages by hand (done 2026-11-01 on
    `9b5db7c6a45f`, where three identical answers followed two `CONTINUE` injects). This
    turns that hour into one call.

    Reads the persisted transcript only: no model call, no write. The gate NAMES come
    from `sess["injects"]` (already written by `stores.persist_inject` with its `kind`),
    so nothing is re-derived when that ledger exists; the prose table is only the fallback
    for sessions written before it.
    """
    if not session:
        return {"ok": False, "error": "session id required"}
    try:
        from longrun.memory import stores
        sess = stores.load_session(session) or {}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "cannot read session: %s" % e}
    msgs = sess.get("messages") or []
    if not msgs:
        return {"ok": False, "error": "session has no messages: %s" % session}
    roles = {"user": 0, "assistant": 0, "other": 0}
    gates, events, repeats = {}, [], []
    inject_chars = 0
    chars_by_kind = {}
    prev_assistant = None
    failed_tools = 0
    for i, m in enumerate(msgs):
        if not isinstance(m, dict):
            continue
        role = str(m.get("role") or "other")
        body = str(m.get("content") or "")
        roles[role if role in roles else "other"] += 1
        # Only a real REPLY can be "the same reply twice": machine tool-call
        # markup is never a chat reply, and comparing the WHOLE normalised body
        # (not a 160-char prefix) is what makes two distinct calls distinct.
        if role == "assistant" and _is_answer(body):
            cur = " ".join(body.split())
            if prev_assistant is not None and cur and cur == prev_assistant:
                repeats.append({"i": i, "text": cur[:160]})
            prev_assistant = cur
    # ONE source for the gates: the injection ledger, when it exists.
    ledger = sess.get("injects") or []
    if ledger:
        for rec in ledger:
            if not isinstance(rec, dict) or rec.get("kind") in (None, "system"):
                continue
            gate = str(rec.get("kind") or "inject")
            text = str(rec.get("text") or "")
            gates[gate] = gates.get(gate, 0) + 1
            inject_chars += len(text)
            chars_by_kind[gate] = chars_by_kind.get(gate, 0) + len(text)
            # A tool result reaches the model AS an observation inject, so a failure is
            # counted here — the assistant messages never carry it.
            if "ok=False" in text or '"ok": false' in text:
                failed_tools += 1
            if len(events) < limit:
                events.append({"after": rec.get("after"), "gate": gate,
                               "text": text[:110].replace("\n", " ")})
    else:
        for i, m in enumerate(msgs):
            if not isinstance(m, dict) or m.get("role") != "user":
                continue
            body = str(m.get("content") or "")
            if not body.startswith("[harness]"):
                continue
            gate = _gate_of(body)
            gates[gate] = gates.get(gate, 0) + 1
            inject_chars += len(body)
            chars_by_kind[gate] = chars_by_kind.get(gate, 0) + len(body)
            if "ok=False" in body or '"ok": false' in body:
                failed_tools += 1
            if len(events) < limit:
                events.append({"i": i, "gate": gate,
                               "text": body[:110].replace("\n", " ")})
    # An assistant echo that reports a failure counts once too (some tools answer inline).
    failed_tools += sum(1 for m in msgs if isinstance(m, dict)
                        and m.get("role") == "assistant"
                        and ("ok=False" in str(m.get("content") or "")
                             or '"ok": false' in str(m.get("content") or "")))
    # `observation` carries the model's OWN tool results back to it — necessary
    # context, not harness talk. Counting it inside "what the harness spent" made
    # a healthy session look like 678 kB of overhead (measured 2026-11-02: 88% of
    # the total was observations), so the harness's own words are reported apart.
    harness_chars = sum(v for k, v in chars_by_kind.items() if k != "observation")
    return {
        "ok": True, "session": session, "messages": len(msgs), "roles": roles,
        "gate_source": "injects" if ledger else "messages",
        "harness_turns": sum(gates.values()), "inject_chars": inject_chars,
        "harness_chars": harness_chars,
        "inject_chars_by_kind": dict(sorted(chars_by_kind.items(), key=lambda kv: -kv[1])),
        "gates": dict(sorted(gates.items(), key=lambda kv: -kv[1])),
        "repeated_answers": repeats, "events": events,
        "tool_calls_reported_failed": failed_tools,
        "reading": ("`repeated_answers` is the loop signature: the same reply twice means "
                    "a gate kept the turn alive after the work was done (machine "
                    "tool-call markup is never a reply, so it never counts). "
                    "`harness_chars` is what the harness spent of the context talking "
                    "about its own bookkeeping; `inject_chars_by_kind` shows the split, "
                    "and `observation` (the model's own tool results) is not harness talk."),
    }


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


#: A discovery answer must stay READABLE: a broad query used to return the whole
#: registry (27 kB), the harness offloaded it to a file and the model burned steps
#: shell-grepping its own discovery result (measured 2026-11-01, GAIA).
TOOL_QUERY_LIMIT = 12
TOOL_INDEX_LIMIT = 60
TOOL_DESC_CHARS = 160


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
    index = {}
    for t in cat:
        if not t.get("name"):
            continue
        entry = {"enabled": t.get("enabled", True),
                 "origin": t.get("origin"),
                 "approval": t.get("approval"),
                 "description": (t.get("description") or "").strip()}
        # The REQUIRED names on the index line: without them the only way to learn
        # that `grep.search` wants `pattern` was a second call the model skipped,
        # so it guessed a neighbour's vocabulary (live 2026-11-03).
        required = list((t.get("inputSchema") or {}).get("required") or [])
        if required:
            entry["required"] = required
        index[t["name"]] = entry
    capped = False
    total = len(index)
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
        # v647: this used to require the WHOLE query string as a literal
        # substring of a name or a description, so `query:"job dispatch"` answered
        # "0 tools" while `job.get` existed (its description says "Read ONE job in
        # full"). Every query word now scores against name + description and the
        # best matches come back first; the exact phrase still wins outright.
        import re
        words = list(dict.fromkeys(
            [w for w in re.split(r"\W+", str(query).lower()) if len(w) > 2]))
        phrase = str(query).strip().lower()
        hits, exact = {}, {}
        for n, e in index.items():
            hay = (n + " " + (e.get("description") or "")).lower()
            score = sum(1 for w in words if w in hay)
            if not score:
                continue
            if phrase and phrase in hay:
                exact[n] = score
            hits[n] = score
        # v647: a FULL-phrase hit is the answer, not one candidate among many.
        # `query:"diff.text"` scores both words on dozens of tools ("text"),
        # so ranking alone flooded the result; when one name/description holds
        # the whole phrase, those are the only hits returned.
        if exact:
            hits = exact

        def _rank(name):
            # A NAME hit outranks a description hit: the cap below must never drop
            # `web.search` because a dozen unrelated descriptions mention "web".
            low = name.lower()
            if phrase and phrase in low:
                boost = 4
            elif any(w in low for w in words):
                boost = 2
            else:
                boost = 0
            return (-(hits[name] + boost), name)

        index = {n: index[n] for n in sorted(hits, key=_rank)}
        native = [n for n in native if n in index]
        external = [n for n in external if n in index]
        enabled = [n for n in enabled if n in index]
        # 2026-11-01: a broad query ("web search fetch page") matched every tool and
        # the answer was 27 kB — the harness offloaded it to a file and the model spent
        # steps SHELL-GREPPING its own discovery result (GAIA a1e91b78/46719c30). A
        # search that returns everything is not a search: cap it and say so.
        if len(index) > TOOL_QUERY_LIMIT:
            keep = list(index)[:TOOL_QUERY_LIMIT]
            index = {n: index[n] for n in keep}
            native = [n for n in native if n in index]
            external = [n for n in external if n in index]
            enabled = [n for n in enabled if n in index]
            capped = True
    if not query and len(index) > TOOL_INDEX_LIMIT:
        index = {n: index[n] for n in sorted(index)[:TOOL_INDEX_LIMIT]}
        capped = True
    out = {"ok": True, "count": len(native), "external_count": len(external),
           "native": sorted(native), "external": sorted(external),
           "enabled_count": len(enabled), "tools": {
               n: {k: (v[:TOOL_DESC_CHARS] + "…" if k == "description"
                       and isinstance(v, str) and len(v) > TOOL_DESC_CHARS else v)
                   for k, v in e.items()}
               for n, e in index.items()}}
    if query:
        out["query"] = query
    if capped:
        if query:
            out["capped"] = ("showing the %d best matches — narrow the words, or ask "
                             "for one tool by name" % TOOL_QUERY_LIMIT)
        else:
            out["capped"] = ("showing %d of %d tools (alphabetical) — search the rest "
                             "with self {action:'tools', query:'<words>'} or ask for one "
                             "tool by name" % (len(index), total))
    out["hint"] = ("read a schema with self {action:'tools', tool:'<name>'} "
                   "BEFORE calling a tool you have not used in this session")
    if query and not native and not external:
        out["hint"] = ("no tool matches those words — try fewer/other words, or "
                       "call self {action:'tools'} without a query for the index")
    return out


def namespaces(allow=None) -> dict:
    """Which tool NAMESPACES exist, how many tools each exposes, and who admits them.

    v718: `self.info` promised a capability report but answered with a flat list of
    dotted names, so "which namespaces do I have?" had no answer — a disabled
    namespace and an enabled one looked identical in the index. One owner for the
    grouping: `catalog()` names are `ns.sub` for native tools and `<client>__<tool>`
    for MCP, which are two different namespaces and are reported as such.

    `allow` is a delegated role's tool scope (`registry.in_scope`); `None` means
    unrestricted. Per namespace `admitted` counts the tools the scope lets through,
    so a scope that names ONE tool does not read as "the whole namespace is mine".
    """
    try:
        from longrun.tools import registry
        cat = registry.catalog()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "registry unavailable: %s" % e}
    rows = {}
    for t in cat:
        name = str(t.get("name") or "")
        if not name:
            continue
        if "__" in name and "." not in name.split("__", 1)[0]:
            ns = name.split("__", 1)[0]
        else:
            ns = name.split(".", 1)[0]
        row = rows.setdefault(ns, {"tools": 0, "enabled": 0, "admitted": 0})
        row["tools"] += 1
        if t.get("enabled", True):
            row["enabled"] += 1
        if t.get("enabled", True) and registry.in_scope(name, allow):
            # A DISABLED namespace is never admitted: `in_scope` only answers the
            # role question, so a namespace switched off in config could still be
            # listed as admitted and the report contradicted itself. Measured
            # 2026-10-30: MCP server `time` (disabled) appeared in `admitted` and
            # not in `enabled`, failing v718 A7.
            row["admitted"] += 1
    admitted = sorted(n for n, r in rows.items() if r["admitted"])
    return {"ok": True,
            "enabled": sorted(n for n, r in rows.items() if r["enabled"]),
            "disabled": sorted(n for n, r in rows.items() if not r["enabled"]),
            "admitted": admitted,
            "count": len(rows),
            "namespaces": {n: rows[n] for n in sorted(rows)}}


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
