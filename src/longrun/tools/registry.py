#!/usr/bin/env python3
"""Longrun tool registry — declarative tools + allowlist + approval policy.

Loads `config/tools.yaml` (falling back to `config/tools.json`) and answers:
  * which tools exist and are enabled (allowlist)
  * the JSON schema of each tool (for the agent prompt and for MCP tools/list)
  * the approval decision for a concrete action (auto / required / denied / disabled)

Stdlib + PyYAML. No tool is executed here — see tools.py / sandbox.py.
"""

import json
import os
import re
import threading

from longrun.util.paths import REPO_ROOT as REPO
CONFIG_YAML = os.path.join(REPO, "config", "tools.yaml")
CONFIG_JSON = os.path.join(REPO, "config", "tools.json")
# JAG-82: programmatic policy changes (POST /api/tools, the SETTINGS panel) are
# written to a sparse overlay, never back into the hand-edited tools.yaml.
OVERLAY_YAML = os.path.join(REPO, "data", "tools.overlay.yaml")
OVERLAY_JSON = os.path.join(REPO, "data", "tools.overlay.json")

_lock = threading.RLock()
_cfg = None

# --------------------------------------------------------------- defaults ----

DEFAULT_CONFIG = {
    "version": "0.2",
    "sandbox": {
        "backend": "auto", "image": "alpine:latest", "timeout_secs": 25,
        "network": False, "memory_mb": 256, "pids_limit": 128, "cpus": "1.0",
        "workspace": "data/sandbox",
    },
    "approvals": {"timeout_secs": 300},
    "runtime": {},
    "verifier": {},
    "bestofn": {},
    "difficulty": {},
    "selfevolve": {},
    "reasoning": {},
    "tools": {},
}

# JSON-schema-ish descriptions exposed to the agent prompt and to MCP clients.
TOOL_SCHEMAS = {
    "shell": {
        "description": ("Run a shell command inside the sandbox (no network, "
                        "read-only rootfs, tmpfs /tmp, scratch /work). Returns "
                        "exit code + captured stdout/stderr."),
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "shell command to execute"},
            "timeout_secs": {"type": "integer", "description": "optional timeout override"},
            # JAG-386: the model naturally reaches for `cwd` (the `git` tool
            # documents it), but the shell only honoured an undocumented
            # `workspace` key — so an explicit working directory was silently
            # ignored and the command ran in the session workspace. `cwd` is now
            # the advertised name (mirrors `git`); a relative `cwd` resolves
            # against the server process cwd, like any shell.
            "cwd": {"type": "string",
                    "description": ("optional working directory (default: the "
                                    "session workspace); relative paths resolve "
                                    "against the session workspace, mirroring "
                                    "shell.rs implementation")},
        },
        "required": ["command"],
        "subject": "command",
    },
    "fs.read": {
        "description": "Read a text file from the harness filesystem (inside allowed roots).",
        "type": "object",
        "properties": {"path": {"type": "string"},
                       "max_bytes": {"type": "integer", "default": 65536}},
        "required": ["path"],
        "subject": "path",
    },
    "fs.write": {
        "description": "Write a text file (inside allowed roots; default: the sandbox workspace).",
        "type": "object",
        "properties": {"path": {"type": "string"}, "content": {"type": "string"},
                       "append": {"type": "boolean", "default": False}},
        "required": ["path", "content"],
        "subject": "path",
    },
    "fs.edit": {
        "description": ("Surgical file edit: replace a search string with a replacement "
                        "(default: first occurrence; replace_all=true for every "
                        "occurrence). Fails if the search string is not found or is "
                        "ambiguous (multiple matches with replace_all=false)."),
        "type": "object",
        "properties": {"path": {"type": "string"},
                       "search": {"type": "string", "description": "exact text to find"},
                       "replace": {"type": "string", "description": "replacement text"},
                       "replace_all": {"type": "boolean", "default": False}},
        "required": ["path", "search", "replace"],
        "subject": "path",
    },
    "git": {
        "description": "Run a git subcommand in a repository (read-only ones are auto-approved; push is denied).",
        "type": "object",
        "properties": {"args": {"type": "string", "description": "e.g. 'status --short'"},
                       "cwd": {"type": "string", "description": "optional repo path (default: longrun repo)"}},
        "required": ["args"],
        "subject": "args",
    },
    "http": {
        "description": ("Fetch a URL from the LOCAL allowlist only (default: "
                        "127.0.0.1/localhost). For anything on the public internet "
                        "use the `web` tool instead. Host allowlist enforced."),
        "type": "object",
        "properties": {"url": {"type": "string"}, "method": {"type": "string", "default": "GET"},
                       "max_bytes": {"type": "integer", "default": 32768}},
        "required": ["url"],
        "subject": "url",
    },
    "browser": {
        "description": ("Fetch a page and extract readable text (lightweight; not a headless browser). "
                        "Disabled by default."),
        "type": "object",
        "properties": {"url": {"type": "string"}, "max_bytes": {"type": "integer", "default": 32768}},
        "required": ["url"],
        "subject": "url",
    },
    "self": {
        "description": ("Self-knowledge + native self-diagnosis (JAG-426). action=info "
                        "(default): where the harness is installed (repo, data, config "
                        "paths), how to install a skill/MCP server, the systemd service "
                        "state. action=diagnose: live health (cpu/mem/disk/gpu/service/"
                        "ports). action=logs: this session's event history. "
                        "action=context: how full this session's context window is. "
                        "action=tools: the tools enabled right now + their policy. "
                        "Read-only, always safe, no external dependency."),
        "type": "object",
        "properties": {
            "action": {"type": "string",
                       "enum": ["info", "diagnose", "logs", "context", "tools"],
                       "description": "what to report (default: info)"},
            "session": {"type": "string",
                        "description": "session id for action=logs|context (default: this run's session)"},
            "limit": {"type": "integer", "description": "max log rows for action=logs (default 100)"},
            "kind": {"type": "string", "description": "event kind filter for action=logs"},
        },
    },
    "reconcile": {
        "description": ("Recover a stalled/abandoned session: close any session "
                        "whose last turn is a `user` message with no reply (an "
                        "orphan left by a hard restart/crash) with an explicit "
                        "assistant notice, and release any todo left 'doing'. Safe "
                        "and idempotent. CALL IT WHEN a session looks stuck: its "
                        "last message is a user turn with no answer AND no turn is "
                        "running (check /api/chat/live — empty means nothing is "
                        "active). Pass `session` to fix just one session, or omit "
                        "it to sweep all."),
        "type": "object",
        "properties": {
            "session": {"type": "string",
                        "description": "optional: only this session id"},
        },
    },
    "skills": {
        "description": ("Agent skills registry: list available skills (from the "
                        "skills/ tree, one SKILL.md per skill) or read a full "
                        "SKILL.md to follow its instructions/entrypoint."),
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["list", "read"], "default": "list"},
            "name": {"type": "string", "description": "skill name (for action=read)"},
        },
    },
    "index": {
        "description": ("CODEBASE index for the CURRENT workspace (per path, like project "
                        "rules) — NOT global. action=search -> the top matching chunks as "
                        "path:line + a snippet, so you read the RIGHT code instead of scanning "
                        "the tree. action=reindex -> rebuild THIS workspace's index now. "
                        "action=status -> counts. Lexical (bm25) always; semantic when an "
                        "embedding model is set."),
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["search", "reindex", "status"],
                       "default": "search"},
            "query": {"type": "string", "description": "what to look for (action=search)"},
            "k": {"type": "integer", "default": 8, "description": "max results (action=search)"},
            "kind": {"type": "string", "enum": ["code", "doc"],
                     "description": "restrict to code or docs (action=search)"},
        },
    },
    "knowledge": {
        "description": ("GLOBAL knowledge base (separate from the workspace codebase index), "
                        "organised in NOTEBOOKS of sources (URLs / files / pasted text). "
                        "Binary docs attached to THIS chat (PDF/DOCX/...) are auto-indexed into "
                        "this session's own notebook: action=search queries it FIRST, then the "
                        "global notebooks — so prefer `search` over shell text-extraction for an "
                        "attached PDF. "
                        "action=list_notebooks | create_notebook | add_source | add_text | "
                        "search | discover (web search -> candidate URLs) | import (URLs -> a "
                        "notebook) | status."),
        "type": "object",
        "properties": {
            "action": {"type": "string",
                       "enum": ["search", "list_notebooks", "create_notebook", "add_source",
                                "add_text", "discover", "import", "status"],
                       "default": "search"},
            "notebook": {"type": "string", "description": "target notebook id (default: this session's notebook, then global)"},
            "name": {"type": "string", "description": "notebook name (action=create_notebook)"},
            "query": {"type": "string", "description": "search text / discovery query"},
            "refs": {"type": "string", "description": "one URL/path per line (action=add_source)"},
            "title": {"type": "string", "description": "note title (action=add_text)"},
            "text": {"type": "string", "description": "pasted note body (action=add_text)"},
            "urls": {"type": "array", "items": {"type": "string"}, "description": "URLs (action=import)"},
            "k": {"type": "integer", "default": 8, "description": "max results (action=search)"},
            "n": {"type": "integer", "default": 5, "description": "max web hits (action=discover)"},
        },
    },
    "sessions": {
        "description": ("Inspect OTHER sessions' chats to understand why a "
                        "teammate (e.g. 'coder 1') is failing, and help it. "
                        "action=list -> sessions with agent name, title, age, "
                        "running. action=read -> one session's FULL transcript "
                        "(session=<id>): messages, tool calls + results, harness "
                        "injections, in order. Read-only."),
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["list", "read"], "default": "list"},
            "session": {"type": "string", "description": "session id (action=read)"},
            "query": {"type": "string",
                      "description": "filter by agent name/title/id (action=list)"},
            "limit": {"type": "integer", "default": 30,
                      "description": "max transcript entries (action=read)"},
            "tail": {"type": "boolean", "default": False,
                     "description": "read the LAST <limit> entries (action=read)"},
        },
        "required": [],
        "subject": "session",
    },
    "chapters": {
        "description": ("THIS session's THREAD — every chat GROUP in order (task = a "
                        "todo node; free = 'Free.N' chat with no todo behind it). "
                        "list -> the ordered outline (ids, ranges, previews) WITH each "
                        "group's JUSTIFICATION (a todo's evidence / a free group's "
                        "summary), so you can recall WHY even after many compactions; "
                        "untitled -> a compact batch of FREE groups missing a title "
                        "(IDs + short request/context previews; title these, then repeat "
                        "until it returns none; use this instead of list to name all groups); "
                        "an unnamed FREE group is flagged [UNTITLED] in the list so you "
                        "can find every one that still needs a name; "
                        "read id=<gN> -> a group's full record; title id=<gN> "
                        "title=\"…\" summary=\"…\" -> name a FREE group (it is a user "
                        "request + its answer, so title it \"request to <short ask>\" "
                        "and give a one-line summary). Read-only except title."),
        "type": "object",
        "properties": {
            "action": {"type": "string",
                       "enum": ["list", "untitled", "read", "title"], "default": "list"},
            "id": {"type": "string", "description": "group id (gN) for read/title"},
            "title": {"type": "string", "description": "new title (action=title)"},
            "summary": {"type": "string",
                        "description": "one-line justification for a free group (action=title)"},
            "limit": {"type": "integer", "default": 8,
                      "description": "max results for action=untitled (1-16)"},
            "session": {"type": "string",
                        "description": "session id (default: this run's session)"},
        },
        "required": [],
        "subject": "id",
    },
    "context": {
        "description": ("THIS session's context meter + compaction. "
                        "action=status -> tokens/budget/pct + over_threshold flag. "
                        "action=compact -> manual compaction now (summarizer model, "
                        "merges old turns into one summary). The harness auto-compacts "
                        "at the trigger %, so use compact only to free headroom early."),
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["status", "compact"], "default": "status"},
            "session": {"type": "string",
                        "description": "session id (default: this run's session)"},
        },
        "required": [],
        "subject": "action",
    },
    "memory": {
        "description": ("Persistent memory across sessions. action=store saves a "
                        "durable fact/preference/decision (ttl_secs expires it; "
                        "source=provenance); action=recall searches; action=recent "
                        "lists newest; action=invalidate tombstones a wrong/outdated "
                        "memory (target=id|query) so recall stops surfacing it; "
                        "action=forget TRULY deletes it (target=id|query); "
                        "action=purge drops invalidated/expired records; "
                        "action=health reports counts. action=core reads / set_core "
                        "rewrites the always-visible CORE block. Relevant memories are "
                        "also auto-injected each turn, so store what's worth keeping."),
        "type": "object",
        "properties": {
            "action": {"type": "string",
                       "enum": ["store", "recall", "recent", "core", "set_core",
                                "invalidate", "forget", "purge", "health"],
                       "default": "recall"},
            "content": {"type": "string", "description": "text to save (action=store)"},
            "query": {"type": "string", "description": "what to look for (recall/invalidate/forget)"},
            "kind": {"type": "string", "description": "optional category filter"},
            "limit": {"type": "integer", "default": 5},
            "source": {"type": "string", "description": "provenance tag (store)"},
            "ttl_secs": {"type": "number", "description": "optional lifetime in seconds (store)"},
            "target": {"type": "string", "description": "memory id to retire or delete"},
            "reason": {"type": "string", "description": "why it's retired (action=invalidate)"},
            "include_invalid": {"type": "boolean", "description": "also return expired/invalidated (action=recall)"},
        },
        "required": [],
        "subject": "action",
    },
    "improve": {
        "type": "object",
        "properties": {
            "action": {"type": "string",
                       "enum": ["propose", "mine", "evolve", "verify", "promote"],
                       "default": "propose"},
            "scope": {"type": "string", "enum": ["skill", "project", "global", "mine"]},
            "content": {"type": "string"},
            "path": {"type": "string",
                     "description": "cartella proposta (per verify/promote)"},
            "reason": {"type": "string"},
        },
        "required": ["action", "scope"],
    },
    "web": {
        "description": ("Public-internet access (JAG-83). action=search runs a web "
                        "search and returns titles/urls/snippets (Tavily or Brave "
                        "when a key is configured, else keyless DuckDuckGo); "
                        "action=fetch downloads a URL and returns readable text "
                        "(via r.jina.ai, else direct HTML->text). Read-only: use it "
                        "for news, docs and facts, then cite the URLs you used."),
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["search", "fetch"], "default": "search"},
            "query": {"type": "string", "description": "search query (action=search)"},
            "url": {"type": "string", "description": "page URL (action=fetch)"},
            "max_results": {"type": "integer", "default": 5},
            "max_bytes": {"type": "integer", "default": 8192},
        },
        "required": [],
        "subject": "query",
    },
    "diff": {
        "description": ("Compare two files or two texts and return a unified diff "
                        "(stdlib difflib). action=files compares two paths (honouring "
                        "the read roots); action=text compares two strings. Read-only."),
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["files", "text"], "default": "files"},
            "a": {"type": "string", "description": "first file path (action=files)"},
            "b": {"type": "string", "description": "second file path (action=files)"},
            "text_a": {"type": "string", "description": "first text (action=text)"},
            "text_b": {"type": "string", "description": "second text (action=text)"},
            "context": {"type": "integer", "default": 3},
        },
        "required": [],
        "subject": "a",
    },
    # --- JAG-426: baseline tools every standard harness ships -----------------
    "python": {
        "description": ("Execute a Python snippet in the sandbox and return its "
                        "stdout/stderr + exit code (a REPL substitute; no host "
                        "filesystem beyond the sandbox workspace)."),
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "the Python source to run"},
            "timeout_secs": {"type": "integer", "description": "optional timeout override"},
        },
        "required": ["code"],
        "subject": "code",
    },
    "process": {
        "description": ("List running processes (pid, RSS, cmdline) or send SIGTERM "
                        "to one. action=list (optional `match` substring + `limit`); "
                        "action=kill requires `pid`. Never signals pid<=1 or the harness."),
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["list", "kill"], "default": "list"},
            "match": {"type": "string", "description": "cmdline substring filter (action=list)"},
            "limit": {"type": "integer", "default": 40},
            "pid": {"type": "integer", "description": "target pid (action=kill)"},
        },
        "required": [],
        "subject": "action",
    },
    "glob": {
        "description": ("List files matching a glob pattern under an allowed root "
                        "(read-only, capped). e.g. {\"pattern\": \"**/*.py\", \"root\": \".\"}."),
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "glob pattern (supports **)"},
            "root": {"type": "string", "description": "directory to search (default: the workspace/repo)"},
            "limit": {"type": "integer", "default": 200},
        },
        "required": ["pattern"],
        "subject": "pattern",
    },
}


# ---------------------------------------------------------------- loading ----

def _load_raw():
    if os.path.exists(CONFIG_YAML):
        try:
            import yaml  # PyYAML
            with open(CONFIG_YAML, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            if isinstance(data, dict):
                return data, "yaml"
        except ImportError:
            raise RuntimeError("PyYAML not installed but config/tools.yaml exists")
        except Exception as e:
            raise RuntimeError("cannot parse config/tools.yaml: %s" % e)
    if os.path.exists(CONFIG_JSON):
        with open(CONFIG_JSON, "r", encoding="utf-8") as f:
            return json.load(f), "json"
    return {}, "defaults"


def _merge_into(cfg, data):
    """Deep-merge a raw config dict into `cfg` (tools merge per-tool, key by key)."""
    if not isinstance(data, dict):
        return
    for key in ("sandbox", "approvals", "runtime", "verifier", "bestofn",
                "difficulty", "selfevolve", "reasoning"):
        if isinstance(data.get(key), dict):
            cfg[key].update(data[key])
    for tname, tentry in (data.get("tools") or {}).items():
        if isinstance(tentry, dict):
            cur = cfg["tools"].get(tname)
            if isinstance(cur, dict):
                cur.update(tentry)
            else:
                cfg["tools"][tname] = dict(tentry)
        else:
            cfg["tools"][tname] = tentry
    if "version" in data:
        cfg["version"] = data["version"]


def _merged(base_data, overlay_data=None):
    """DEFAULT_CONFIG <- base file <- overlay (later layers win)."""
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
    _merge_into(cfg, base_data)
    _merge_into(cfg, overlay_data or {})
    return cfg


def load_config(reload=False):
    """Return the merged config (cached). reload=True re-reads from disk."""
    global _cfg
    with _lock:
        if _cfg is not None and not reload:
            return _cfg
        raw, _src = _load_raw()
        cfg = _merged(raw, _load_overlay())
        _cfg = cfg
        return _cfg


_OVERLAY_HEADER = (
    "# Longrun policy overlay — written automatically by POST /api/tools\n"
    "# (the SETTINGS panel in SparkPulse). Only the keys that DIFFER from\n"
    "# config/tools.yaml live here, so that file stays the hand-edited source\n"
    "# of truth and its comments are never rewritten. Delete this file to fall\n"
    "# back entirely to config/tools.yaml.\n\n"
)


def _load_overlay():
    """The programmatic policy overlay (data/tools.overlay.yaml), or {}."""
    if os.path.exists(OVERLAY_YAML):
        try:
            import yaml
            with open(OVERLAY_YAML, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            return {}
    if os.path.exists(OVERLAY_JSON):
        try:
            with open(OVERLAY_JSON, "r", encoding="utf-8") as f:
                return json.load(f) or {}
        except Exception:
            return {}
    return {}


def _diff_overlay(cfg, base_data):
    """Only the keys in `cfg` that differ from the base file's own state."""
    eff = _merged(base_data)  # what the config would be WITHOUT any overlay
    out = {}
    tools_diff = {}
    eff_tools = eff.get("tools") or {}
    for tname, tentry in (cfg.get("tools") or {}).items():
        if not isinstance(tentry, dict):
            continue
        e = eff_tools.get(tname) or {}
        if not isinstance(e, dict):
            e = {}
        d = {k: v for k, v in tentry.items() if e.get(k) != v}
        if d:
            tools_diff[tname] = d
    if tools_diff:
        out["tools"] = tools_diff
    for key in ("sandbox", "approvals", "runtime", "verifier", "bestofn",
                "difficulty", "selfevolve", "reasoning"):
        e = eff.get(key) or {}
        d = {k: v for k, v in (cfg.get(key) or {}).items() if e.get(k) != v}
        if d:
            out[key] = d
    return out


def _write_overlay(overlay):
    """Atomically write the sparse overlay (never touches config/tools.yaml)."""
    os.makedirs(os.path.dirname(OVERLAY_YAML), exist_ok=True)
    try:
        import yaml
        tmp = OVERLAY_YAML + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(_OVERLAY_HEADER)
            if overlay:
                yaml.safe_dump(overlay, f, sort_keys=False, allow_unicode=True,
                               default_flow_style=False)
            else:
                f.write("{}\n")
        os.replace(tmp, OVERLAY_YAML)
    except ImportError:
        with open(OVERLAY_JSON, "w", encoding="utf-8") as f:
            json.dump(overlay, f, indent=2)


def save_config(cfg):
    """Persist ONLY the delta vs config/tools.yaml into data/tools.overlay.yaml.

    JAG-82: the SETTINGS panel flips approval policy per tool. Rewriting
    config/tools.yaml mixed the app's changes with the hand-edited file and
    destroyed its documentation. Now that file is never touched: we diff the
    live config against it and store only the changed keys in a gitignored
    overlay that load_config() merges on top. Delete the overlay to revert.
    """
    global _cfg
    with _lock:
        base, _src = _load_raw()
        _write_overlay(_diff_overlay(cfg, base))
        _cfg = cfg
        return cfg


def workspace_dir():
    return os.path.join(REPO, load_config()["sandbox"]["workspace"])


# ------------------------------------------------------------------ tools ----

def _external_tools():
    """External MCP tools (mcp_client), lazily; empty on any failure."""
    try:
        from longrun.interop import mcp_client
        if not mcp_client.get_manager().sessions:
            mcp_client.get_manager().start_all()
        return {t["name"]: t for t in mcp_client.list_tools()}
    except Exception:
        return {}


def tool_names():
    """All known tools: registry entries from config ∪ shipped schemas ∪ external MCP."""
    return sorted(set(load_config()["tools"]) | set(TOOL_SCHEMAS) | set(_external_tools()))


def tool_spec(name, ext_snapshot=None):
    """Merged {name, enabled, approval, ...policy, schema} or None if unknown.

    `ext_snapshot` (optional) is a pre-fetched `_external_tools()` map so callers
    that iterate many names use ONE consistent view (JAG-253).
    """
    schema = TOOL_SCHEMAS.get(name)
    ext = None
    if schema is None:
        ext = (ext_snapshot if ext_snapshot is not None else _external_tools()).get(name)
        if ext:
            ins = ext.get("inputSchema") or {}
            schema = {"description": ext.get("description", ""),
                      "type": ins.get("type", "object"),
                      "properties": ins.get("properties", {}),
                      "required": ins.get("required", [])}
    entry = load_config()["tools"].get(name)
    # JAG-254: a config entry for an external MCP tool (`<client>__<tool>`) whose
    # server is NOT connected has no schema — the tool does not exist. Return None
    # so a clone without pmcp never advertises (nor tries) a tool it lacks; the
    # entry only supplies policy for WHEN the tool is actually present.
    if schema is None and ("__" in name or not entry):
        return None
    if entry is None and ext:
        entry = {}  # external MCP default policy below
    entry = entry or {}
    return {
        "name": name,
        # JAG-80: external MCP tools (the pmcp gateway) are OPT-IN. Shipping 26
        # gateway tools (23 of them approval-gated) into the chat prompt made the
        # model call `pmcp__gateway.request_capability` instead of its own
        # tools/skills — and that call froze the turn on the approval gate. Only
        # tools explicitly enabled in config/tools.yaml are offered.
        "enabled": bool(entry.get("enabled", False)),
        "approval": entry.get("approval", "required"),
        "auto_approve": list(entry.get("auto_approve") or []),
        "deny": list(entry.get("deny") or []),
        "allow_hosts": list(entry.get("allow_hosts") or []),
        "roots": list(entry.get("roots") or ["."]),
        "workspace": entry.get("workspace"),
        "schema": schema,
    }


def catalog():
    """Public catalogue for GET /api/tools and MCP tools/list."""
    # JAG-253: snapshot the external MCP tools ONCE. `tool_names()` and
    # `tool_spec()` used to re-evaluate `_external_tools()` independently; while a
    # server was (re)connecting the two views disagreed, `tool_spec` returned
    # None, and `None["enabled"]` crashed the handler (dropped HTTP connection).
    ext = _external_tools()
    names = sorted(set(load_config()["tools"]) | set(TOOL_SCHEMAS) | set(ext))
    out = []
    for name in names:
        spec = tool_spec(name, ext)
        if not spec:
            continue
        out.append({
            "name": name,
            "enabled": spec["enabled"],
            "approval": spec["approval"],
            "auto_approve": spec["auto_approve"],
            "deny": spec["deny"],
            "allow_hosts": spec["allow_hosts"],
            "description": (spec["schema"] or {}).get("description", ""),
            "inputSchema": {k: v for k, v in (spec["schema"] or {}).items()
                            if k in ("type", "properties", "required")},
        })
    return out


_ENV_ASSIGN_RE = re.compile(
    r"^\s*(?:[A-Za-z_][A-Za-z0-9_]*=(?:'[^']*'|\"[^\"]*\"|\S*)\s+)+")


def _subject(tool, args):
    """The string a policy regex is matched against for this action."""
    spec = TOOL_SCHEMAS.get(tool) or {}
    key = spec.get("subject")
    if tool == "git":
        return str(args.get("args", ""))
    if tool == "shell":
        # JAG-85: `TZ=Europe/Rome date '…'` is still a read-only `date`. Drop the
        # leading `VAR=value` assignments so the auto-approve patterns (and the
        # hard-deny list) match the REAL command. A pointless approval gate here
        # cost a 30s wait and made a simple "what day is it" turn look stuck.
        return _ENV_ASSIGN_RE.sub("", str(args.get("command", "")))
    if key:
        return str(args.get(key, ""))
    return json.dumps(args, sort_keys=True)


def _match(patterns, text):
    for p in patterns:
        try:
            if re.search(p, text):
                return p
        except re.error as _exc:
            # JAG-431r4b: a malformed deny regex used to be silently skipped,
            # which meant an operator's misconfigured deny list left the action
            # unblocked (fail-open). Fail-CLOSED: treat the broken pattern as
            # a match so the action is denied, AND surface the operator error
            # so it can be fixed.
            try:
                from longrun.core.server import publish as _publish
                _publish("policy.error", kind="deny_regex",
                         pattern=p, error=str(_exc))
            except Exception:
                pass
            return p
    return None


def _under(path, root):
    """True when `path` is inside `root` (both realpath'd)."""
    try:
        p = os.path.realpath(path)
        r = os.path.realpath(root)
        return p == r or p.startswith(r + os.sep)
    except Exception:  # noqa: BLE001
        return False


# JAG-388: THE session workspace is the boundary for EVERY tool. Anything that
# reaches outside it needs approval — governed by approvals.mode ALONE (mode=full
# is the operator's explicit opt-out). These helpers decide, for a concrete
# action, whether it touches a path OUTSIDE the session workspace.
#
# System / scratch trees an ordinary command legitimately references without
# meaning to leave the workspace (`/usr/bin/python3`, `/tmp/...`, `/dev/null`).
# Deliberately NOT included: `/etc`, `/root`, `/home` (other users / other repos)
# — those still escalate.
_SYSTEM_ROOTS = ("/usr", "/bin", "/sbin", "/lib", "/lib64", "/dev", "/proc",
                 "/sys", "/run", "/tmp", "/opt", "/snap")
# a shell word (no quotes / operators); we then look for path-like words
_SHELL_WORD = re.compile(r"[^\s;|&()<>'\"]+")


def _is_system(path):
    return any(path == r or path.startswith(r + "/") for r in _SYSTEM_ROOTS)


def _resolve_any(raw, base):
    """Absolute-ize a path-like token: expand `~`, join a RELATIVE path against
    `base` (the session workspace), then realpath. None when unresolvable."""
    try:
        p = os.path.expanduser(str(raw).strip("'\""))
    except Exception:  # noqa: BLE001
        return None
    if not os.path.isabs(p):
        p = os.path.join(base or os.getcwd(), p)
    return os.path.realpath(p)


def _shell_paths(command):
    """Path-like words in a shell command: absolute, `~`, `./`/`../`, plus the
    argument of a directory-changing builtin/flag (`cd`/`pushd`/`-C`). Best-effort:
    it bounds the EXPLICIT intent, which is what an approval gate can review."""
    out = []
    prev = ""
    for w in _SHELL_WORD.findall(command or ""):
        cand = None
        if w.startswith(("/", "~", "./", "../")) or w == "..":
            cand = w
        elif w.startswith("--directory="):
            cand = w.split("=", 1)[1]
        elif prev in ("cd", "pushd", "-C", "--directory"):
            cand = w
        prev = w
        if cand:
            out.append(cand)
    return out


def touches_outside(tool, args, workspace):
    """JAG-388: a reason string if `tool` reaches OUTSIDE the session workspace,
    else None. Applies to EVERY tool that names a filesystem path: fs.* / diff
    (`path`), git (`cwd`), and shell (its `cwd`, any `cd`/`-C`, and any absolute /
    `~` / `..` word). The agent's own sandbox scratch and the system/scratch trees
    are treated as inside. Only meaningful when a session `workspace` is set."""
    if not workspace:
        return None
    a = args or {}
    paths = []
    if tool in ("fs.read", "fs.write", "fs.edit", "diff"):
        if a.get("path"):
            paths.append(str(a["path"]))
    elif tool == "git":
        if a.get("cwd") or a.get("workspace"):
            paths.append(str(a.get("cwd") or a.get("workspace")))
    elif tool == "shell":
        if a.get("cwd"):
            paths.append(str(a["cwd"]))
        paths.extend(_shell_paths(str(a.get("command", ""))))
    else:
        return None
    for raw in paths:
        p = _resolve_any(raw, workspace)
        if p is None:
            continue
        if _under(p, workspace) or _under(p, workspace_dir()) or _is_system(p):
            continue
        return "path outside the session workspace: %s" % p
    return None


def classify(tool, args, workspace=None):
    """Approval decision for a concrete action.

    JAG-388: when a session `workspace` is given, ANY action — a file op, a git
    repo, or a shell command — that reaches a path OUTSIDE it is `required`,
    regardless of the per-tool policy. Only `approvals.mode=full` relaxes it.
    Returns (decision, reason) with decision in:
      disabled | denied | auto | required
    """
    spec = tool_spec(tool)
    if spec is None:
        return "denied", "unknown tool %r" % tool
    if not spec["enabled"]:
        return "disabled", "tool %r is not in the allowlist (config/tools.yaml)" % tool
    subject = _subject(tool, args)
    hit = _match(spec["deny"], subject)
    if hit:
        return "denied", "matches hard-deny pattern %r" % hit
    if spec["approval"] == "denied":
        return "denied", "tool policy is 'denied'"
    # JAG-127c/388: global approval switch, set from the Config panel (persisted
    # in the overlay). `full` = never ask for anything (hard-deny/disabled still
    # win). It is now the ONLY thing that relaxes the workspace boundary below.
    ap = load_config().get("approvals") or {}
    if str(ap.get("mode", "normal")).lower() in ("full", "auto", "yolo"):
        return "auto", "approvals.mode=full — never ask"
    # JAG-388: ONE rule for EVERY tool — anything that reaches OUTSIDE the session
    # workspace needs approval, governed by approvals.mode ALONE. `mode=full` (the
    # explicit opt-out) already returned above, so here mode != full. Neither the
    # per-tool `approval: auto` nor the old `outside_workspace` toggle can defeat
    # it: they used to let `shell.approval: auto` run `cd /fuori && rm -rf x`
    # silently. Covers fs.* / diff, git, and shell (cwd, `cd`/`-C`, path args).
    if workspace:
        _out = touches_outside(tool, args, workspace)
        if _out:
            return "required", _out
    if spec["approval"] == "auto":
        return "auto", "tool policy is 'auto'"
    hit = _match(spec["auto_approve"], subject)
    if hit:
        return "auto", "matches auto-approve pattern %r" % hit
    return "required", "mutating action requires approval"


def resolve_path(path, roots=None, base=None):
    """Resolve `path` against a base dir (default: the repo) + check allowed roots.

    JAG-191: when a session workspace is open, a RELATIVE path resolves against
    it — not the harness repo — so `fs.write {"path": "foo.txt"}` lands in the
    folder the user actually opened (mirrors the shell tool, which already uses
    the workspace as cwd). Absolute paths are untouched; the roots stay
    repo-relative so the allow-list semantics do not change.
    """
    if roots is None:
        roots = ["."]
    # JAG-207 (v207): a null byte makes os.path.realpath raise ValueError
    # ("embedded null byte"); reject it gracefully instead of crashing a tool.
    if "\x00" in str(path):
        return None, "path contains a null byte"
    base = os.path.realpath(base) if base else REPO
    p = path if os.path.isabs(path) else os.path.join(base, path)
    p = os.path.realpath(p)
    for r in roots:
        root = os.path.realpath(r if os.path.isabs(r) else os.path.join(REPO, r))
        if p == root or p.startswith(root + os.sep):
            return p, None
    return None, "path %r outside allowed roots %s" % (path, roots)
