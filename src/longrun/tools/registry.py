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
import time

from longrun.util.paths import REPO_ROOT as REPO, DATA_DIR as APP_DATA_DIR
CONFIG_YAML = os.path.join(REPO, "config", "tools.yaml")
CONFIG_JSON = os.path.join(REPO, "config", "tools.json")
# JAG-82: programmatic policy changes (POST /api/tools, the SETTINGS panel) are
# written to a sparse overlay, never back into the hand-edited tools.yaml.
# The overlay lives under the app data dir (LONGRUN_DATA_DIR-aware) so isolated
# test runs never write into the real checkout; it defaults to REPO/data.
OVERLAY_YAML = os.path.join(APP_DATA_DIR, "tools.overlay.yaml")
OVERLAY_JSON = os.path.join(APP_DATA_DIR, "tools.overlay.json")

_lock = threading.RLock()
_cfg = None

# --------------------------------------------------------------- defaults ----

DEFAULT_CONFIG = {
    "version": "0.2",
    "sandbox": {
        "backend": "auto", "image": "alpine:latest", "timeout_secs": 25,
        "network": False, "memory_mb": 256, "pids_limit": 128, "cpus": "1.0",
        "workspace": "sandbox",
    },
    "approvals": {"timeout_secs": 300},
    "runtime": {},
    "verifier": {},
    "bestofn": {},
    "difficulty": {},
    "selfevolve": {},
    "reasoning": {},
    # M5: sliding-window frequency guard for the v2 agent loop (warn/hard per
    # tool type over the last `window` calls; `per_tool` overrides one type).
    "loop_detection": {
        "enabled": True, "window": 50, "warn": 30, "hard": 50,
        "per_tool": {"shell": {"warn": 100, "hard": 200}},
    },
    "tools": {},
}

# JAG-513: one authoritative sentence for every `path` argument. The model was
# guessing between absolute/relative and (on a miss) retried with the repo root,
# so the contract is stated where the model actually reads it: the schema.
_P_PATH = ("file path. RELATIVE paths resolve against the session workspace "
           "(the repo when no workspace is open); ABSOLUTE paths are accepted "
           "only inside the tool's allowed roots. Prefer a relative path, e.g. "
           "'src/longrun/tools/registry.py'.")

# JSON-schema-ish descriptions exposed to the agent prompt and to MCP clients.
_LEGACY_SCHEMAS = {
    "shell": {
        "description": ("Run a shell command. When the sandbox backend is 'none' the "
                        "command runs in THIS SESSION'S persistent terminal — the same "
                        "one the operator sees in the Terminal panel — so they can watch "
                        "it, its cwd/env carry over between calls, and you can read what "
                        "they typed. Under docker/bwrap/nsjail it runs isolated instead. "
                        "Returns exit code + captured stdout/stderr. "
                        "action=read returns the last `lines` of the terminal session "
                        "(including the operator's own commands); action=reset kills it."),
        "type": "object",
        "properties": {
            "action": {"type": "string",
                       "enum": ["run", "read", "reset"],
                       "default": "run",
                       "description": ("run (default) = execute `command`; read = the "
                                       "recent terminal session; reset = fresh shell")},
            "command": {"type": "string",
                        "description": "shell command to execute (action=run)"},
            "lines": {"type": "integer",
                      "description": "action=read: how many trailing lines (default 80)"},
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
        # JAG-530: `command` IS required for action=run (the default), so it stays
        # declared — that is what makes the model supply it and what lets the
        # validator name it when it is missing. The actions that execute nothing
        # (read/reset) waive it, declared below instead of hidden in code.
        "required": ["command"],
        "required_waived_by": {"action": ["read", "reset"]},
        "subject": "command",
    },
    "fs.read": {
        "description": ("Read a text file from the harness filesystem (inside allowed "
                        "roots). Return the whole file, or ONE LINE RANGE with "
                        "start_line/end_line (1-based, inclusive) — use that to inspect "
                        "a slice of a large file instead of re-reading it truncated. "
                        "max_bytes caps the returned content."),
        "type": "object",
        "properties": {"path": {"type": "string", "description": _P_PATH},
                       "start_line": {"type": "integer",
                                      "description": "first line to return (1-based; omit for the start of the file)"},
                       "end_line": {"type": "integer",
                                    "description": "last line to return (1-based, inclusive; omit for end of file)"},
                       "max_bytes": {"type": "integer", "default": 65536,
                                     "description": "cap on returned bytes (default 65536)"}},
        "required": ["path"],
        "subject": "path",
    },
    "fs.write": {
        "description": "Write a text file (inside allowed roots; default: the sandbox workspace).",
        "type": "object",
        "properties": {"path": {"type": "string", "description": _P_PATH},
                       "content": {"type": "string",
                                   "description": "full text to write (the whole file, not a patch)"},
                       "append": {"type": "boolean", "default": False,
                                  "description": "append instead of overwriting (default: overwrite)"}},
        "required": ["path", "content"],
        "subject": "path",
    },
    "fs.edit": {
        "description": ("Surgical file edit: replace a search string with a replacement "
                        "(default: first occurrence; replace_all=true for every "
                        "occurrence). Fails if the search string is not found or is "
                        "ambiguous (multiple matches with replace_all=false)."),
        "type": "object",
        "properties": {"path": {"type": "string", "description": _P_PATH},
                       "search": {"type": "string", "description": "exact text to find"},
                       "replace": {"type": "string", "description": "replacement text"},
                       "replace_all": {"type": "boolean", "default": False,
                                       "description": "replace every occurrence (default: only if unambiguous)"}},
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
        "properties": {"url": {"type": "string", "description": "absolute http(s) URL to fetch"},
                       "method": {"type": "string", "default": "GET",
                                  "description": "HTTP method (default GET)"},
                       "max_bytes": {"type": "integer", "default": 32768,
                                     "description": "cap on returned body bytes (default 32768)"}},
        "required": ["url"],
        "subject": "url",
    },
    "browser": {
        "description": ("Fetch a page and extract readable text (lightweight; not a headless browser). "
                        "Disabled by default."),
        "type": "object",
        "properties": {"url": {"type": "string", "description": "absolute http(s) URL to fetch"},
                       "max_bytes": {"type": "integer", "default": 32768,
                                     "description": "cap on returned text bytes (default 32768)"}},
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
                        "action=tools: TOOL DISCOVERY — every enabled tool with its "
                        "one-line description; add `query` to filter, or `tool` to get "
                        "that tool's FULL input schema (properties, types, defaults, "
                        "required). ALWAYS read the schema before the first use of a "
                        "tool you have not called in this session. "
                        "action=sj: this session's Session Jobs (SJ) — the "
                        "dependency-ordered subagents a `batch` action spawned, with "
                        "each subjob's deps, status and output. "
                        "action=diagnostics: the EXACT Settings diagnostics report "
                        "(same collector, no duplicate checks) with file/field/panel/"
                        "session/model isolation; filter with `code` or `source`. "
                        "Read-only, always safe, no external dependency."),
        "type": "object",
        "properties": {
            "action": {"type": "string",
                       "enum": ["info", "diagnose", "logs", "context", "tools",
                                "diagnostics", "sj"],
                       "description": "what to report (default: info)"},
            "session": {"type": "string",
                        "description": "session id for action=logs|context|diagnostics|sj (default: this run's session)"},
            "job": {"type": "string",
                    "description": "action=sj: one Session Job id (e.g. 'SJ1'); omit for every job of the session"},
            "limit": {"type": "integer", "description": "max rows for action=logs (default 100) or action=diagnostics (default 50)"},
            "kind": {"type": "string", "description": "event kind filter for action=logs"},
            "model": {"type": "string",
                      "description": "action=diagnostics: model ref to validate"},
            "code": {"type": "string",
                     "description": "action=diagnostics: exact issue code filter, e.g. 'provider.auth_rejected'"},
            "source": {"type": "string",
                       "description": "action=diagnostics: case-insensitive source filter, e.g. 'openrouter'"},
            "tool": {"type": "string",
                     "description": ("action=tools: exact tool name, e.g. 'fs.read' — "
                                     "returns its FULL input schema")},
            "query": {"type": "string",
                      "description": ("action=tools: substring filter over name + "
                                      "description, e.g. 'pdf' or 'read'")},
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
                        "skills/ tree, search by keyword, or read a full SKILL.md "
                        "to follow its instructions/entrypoint."),
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["list", "search", "read"], "default": "list"},
            "name": {"type": "string", "description": "skill name (for action=read)"},
            "query": {"type": "string", "description": "keywords to find matching skills (action=search)"},
            "limit": {"type": "integer", "default": 10, "description": "max skills to return (action=search)"},
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
            "workspace": {"type": "string", "description": "workspace path (default: this session's workspace)"},
            "force": {"type": "boolean", "default": False, "description": "force a full rebuild (action=reindex)"},
        },
    },
    "knowledge": {
        "description": ("Knowledge has shared notebooks and a private notebook for this chat. "
                        "Binary documents attached through Chat > Attach files are auto-indexed "
                        "once into the session notebook. `list_notebooks` shows shared notebooks "
                        "and only this chat's session notebook. `search` returns full matching "
                        "chunks from the session first, then shared notebooks; use `read_source` "
                        "to read the full extracted document (bounded by `max_chars`). Do NOT "
                        "call `add_source` for an attached path again. Without an explicit "
                        "notebook, add_source/add_text/import target this session; name a "
                        "notebook explicitly to add shared content. "
                        "action=list_notebooks | create_notebook | add_source | add_text | "
                        "search | read_source | discover (web search -> candidate URLs) | "
                        "import (URLs -> a notebook) | status."),
        "type": "object",
        "properties": {
            "action": {"type": "string",
                       "enum": ["search", "read_source", "list_notebooks", "create_notebook",
                                "add_source", "add_text", "discover", "import", "status"],
                       "default": "search"},
            "notebook": {"type": "string",
                         "description": "notebook ID or exact name from list_notebooks; omit to use this session"},
            "session": {"type": "string",
                        "description": "optional assertion only; must match the current chat session"},
            "name": {"type": "string", "description": "notebook name (action=create_notebook)"},
            "query": {"type": "string", "description": "search text / discovery query"},
            "ref": {"type": "string",
                    "description": "exact indexed source path or source id (action=read_source)"},
            "max_chars": {"type": "integer", "default": 20000,
                          "description": "maximum extracted source chars to return (action=read_source; capped at 50000)"},
            "refs": {"type": "string", "description": "one new URL/path per line; existing session paths are skipped"},
            "url": {"type": "string", "description": "one source URL (action=add_source)"},
            "title": {"type": "string", "description": "note title (action=add_text)"},
            "text": {"type": "string", "description": "pasted note body (action=add_text)"},
            "content": {"type": "string", "description": "alias for text (action=add_text)"},
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
                        "injections, in order. action=send -> asynchronously message "
                        "another session (session|to + message|text); it steers a "
                        "running peer or starts a turn for an idle peer, then returns "
                        "a message_id. Continue other work. action=wait with that id "
                        "waits for the peer turn to finish and returns its reply; "
                        "action=read can inspect the live transcript meanwhile."),
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["list", "read", "send", "wait"],
                       "default": "list"},
            "session": {"type": "string",
                        "description": "session id (action=read|send)"},
            "to": {"type": "string", "description": "alias for session (action=send)"},
            "message": {"type": "string",
                        "description": "text delivered to the peer (action=send)"},
            "text": {"type": "string",
                     "description": "alias for message (action=send)"},
            "message_id": {"type": "string",
                           "description": "message_id returned by action=send (action=wait)"},
            "timeout_secs": {"type": "integer", "minimum": 0, "maximum": 900,
                             "default": 180,
                             "description": "maximum wait; 0 checks once, then retry with the same id"},
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
                        "action=compact -> compaction now (summarizer model, merges "
                        "old turns into one summary). It REFUSES below the policy "
                        "trigger; pass force=true only when the user explicitly asked "
                        "to compact early. The harness auto-compacts at the trigger %."),
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["status", "compact"], "default": "status"},
            "session": {"type": "string",
                        "description": "session id (default: this run's session)"},
            "force": {"type": "boolean", "default": False,
                      "description": "compact even below the policy trigger (only on "
                                     "an explicit user request)"},
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
                        "action=supersede invalidates AND links the replacement "
                        "(superseded_by=replacement id) so the correction chain is "
                        "visible; action=restore re-admits a tombstoned memory "
                        "(target=id — the full history is kept); "
                        "action=forget TRULY deletes it (target=id, or query as a "
                        "case-insensitive LITERAL substring; nothing else is "
                        "touched); "
                        "action=purge drops invalidated/expired records; "
                        "action=health reports counts. action=core reads / set_core "
                        "rewrites / clear_core clears the always-visible CORE block. Relevant memories are "
                        "also auto-injected each turn, so store what's worth keeping."),
        "type": "object",
        "properties": {
            "action": {"type": "string",
                       "enum": ["store", "recall", "recent", "core", "set_core",
                                "clear_core", "invalidate", "supersede", "restore",
                                "forget", "purge", "health"],
                       "default": "recall",
                       "description": "what to do (default: recall = search)"},
            "content": {"type": "string", "description": "text to save (action=store)"},
            "query": {"type": "string", "description": "what to look for (recall/invalidate/forget)"},
            "kind": {"type": "string", "description": "optional category filter"},
            "limit": {"type": "integer", "default": 5,
                      "description": "max records to return (default 5)"},
            "source": {"type": "string", "description": "provenance tag (store)"},
            "ttl_secs": {"type": "number", "description": "optional lifetime in seconds (store)"},
            "target": {"type": "string", "description": "memory id to retire or delete"},
            "superseded_by": {"type": "string",
                              "description": "id of the REPLACING record (action=supersede)"},
            "reason": {"type": "string", "description": "why it's retired (action=invalidate)"},
            "include_invalid": {"type": "boolean", "description": "also return expired/invalidated (action=recall)"},
            "semantic": {"type": "boolean", "default": False,
                         "description": "use semantic embedding search (action=recall; default false uses keyword search)"},
        },
        "required": [],
        "subject": "action",
    },
    "improve": {
        "description": ("Self-improvement. propose registers a rule/skill proposal; "
                        "mine/evolve/verify/promote drive the self-evolving skill "
                        "miner; review audits THE WHOLE backlog (proposals + "
                        "distilled lessons) with an LLM against the current "
                        "codebase and reports keep/implemented/obsolete/update/"
                        "conflict for each artifact."),
        "type": "object",
        "properties": {
            "action": {"type": "string",
                       "enum": ["propose", "mine", "evolve", "verify", "promote",
                                "review"],
                       "default": "propose"},
            "scope": {"type": "string",
                      "enum": ["skill", "project", "global", "mine", "review"],
                      "description": ("what the proposal targets: skill | project | "
                                      "global | mine (distilled lessons) | review")},
            "content": {"type": "string",
                        "description": "the proposed rule/skill text (action=propose)"},
            "path": {"type": "string",
                     "description": "proposal folder (for verify/promote)"},
            "reason": {"type": "string",
                       "description": "why this proposal exists (action=propose)"},
            "limit": {"type": "integer",
                      "description": "review: how many artifacts to audit (max 60)"},
            "model": {"type": "string",
                      "description": "review: model ref (default: routing role "
                                     "'reviewer', then the general default)"},
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
            "max_results": {"type": "integer", "default": 5,
                            "description": "number of hits to return (action=search, default 5)"},
            "max_bytes": {"type": "integer", "default": 8192,
                          "description": "cap on returned page text (action=fetch, default 8192)"},
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
            "context": {"type": "integer", "default": 3,
                        "description": "unified-diff context lines (default 3)"},
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
            "limit": {"type": "integer", "default": 40,
                      "description": "max rows to return (default 40)"},
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
            "limit": {"type": "integer", "default": 200,
                      "description": "max paths to return (default 200)"},
        },
        "required": ["pattern"],
        "subject": "pattern",
    },
    "matrix": {
        "description": ("Self-evolving Matrix suite (code in src/Matrix, runtime in the matrix "
                        "dir from `matrix.status.matrix_dot`; `.Matrix` is its legacy name). "
                        "Full tool lifecycle: "
                        "scaffold -> edit the generated schema/description -> hotload -> "
                        "test -> verify_target -> promote_to_nucleus, or remove to uninstall. "
                        "Actions: status | seams | scaffold | remove | hotload | "
                        "enable/disable | checkpoint_save/checkpoint_rollback (slot 1..3) | "
                        "git_commit/git_log/git_diff/git_reset (separate matrix git repo) | "
                        "test/clean_trash (matrix trash dir) | webui_init/webui_reset | restart."),
        "type": "object",
        "properties": {
            "action": {"type": "string",
                       "enum": ["status", "seams", "scaffold", "remove", "hotload", "enable", "disable",
                                "checkpoint_save", "checkpoint_rollback",
                                "git_commit", "git_log", "git_diff", "git_reset",
                                "test", "clean_trash", "webui_init", "webui_reset", "restart",
                                "verify_target", "promote_to_nucleus"],
                       "default": "status"},
            "description": {"type": "string", "description": "for matrix.scaffold: one sentence stating exactly what the artifact does"},
            "slot": {"type": "integer", "description": "checkpoint slot (1, 2, or 3)"},
            "label": {"type": "string", "description": "checkpoint label (action=checkpoint_save)"},
            "message": {"type": "string", "description": "commit message (action=git_commit)"},
            "rev": {"type": "string", "description": "git revision (action=git_diff|git_reset)"},
            "script": {"type": "string", "description": "script filename in the matrix trash dir (action=test)"},
            "code": {"type": "string", "description": "optional Python code to write & run in the matrix trash dir (action=test)"},
            "target": {"type": "string", "description": "target tested e.g. 'tool:foo' or 'hook:plan' (action=test)"},
            "kind": {"type": "string", "enum": ["tool", "hook", "module", "skill", "rule", "webui"],
                     "description": "artifact kind to remove, verify, or promote"},
            "name": {"type": "string", "description": "artifact name (tool namespace or <ns>.<subtool>); required for remove/verify/promote"},
            "install_deps": {"type": "array", "items": {"type": "string"},
                             "description": "pip packages to install in .Matrix/venv (action=test)"},
            "timeout_secs": {"type": "integer", "default": 60,
                             "description": "command timeout in seconds (default 60)"},
            "limit": {"type": "integer", "default": 20,
                      "description": "maximum commits to return (action=git_log)"},
            "keep_recent": {"type": "integer", "default": 0,
                            "description": "keep only the N most recent artifacts (0 = keep all)"},
            "session": {"type": "string", "description": "session id to resume after warm restart"},
            "reason": {"type": "string", "description": "reason for warm restart"},
            "dry_run": {"type": "boolean", "default": False,
                        "description": "report what would change without changing anything"},
        },
        "required": [],
        "subject": "action",
    },
}

# Single-action plain tools mapped to their canonical `<namespace>.<subtool>` name.
_SINGLE_SUBTOOL_MAP = {
    "shell": "shell.exec",
    "git": "git.run",
    "http": "http.fetch",
    "browser": "browser.fetch",
    "reconcile": "reconcile.run",
    "python": "python.run",
    "glob": "glob.list",
}

# Default subtool when a legacy plain tool name is referenced without an explicit action.
LEGACY_DEFAULT_SUBTOOL = {
    "shell": "shell.exec",
    "git": "git.run",
    "http": "http.fetch",
    "browser": "browser.fetch",
    "reconcile": "reconcile.run",
    "python": "python.run",
    "glob": "glob.list",
    "self": "self.info",
    "skills": "skills.list",
    "index": "index.search",
    "knowledge": "knowledge.search",
    "sessions": "sessions.list",
    "chapters": "chapters.list",
    "context": "context.status",
    "memory": "memory.recall",
    "improve": "improve.propose",
    "web": "web.search",
    "diff": "diff.files",
    "process": "process.list",
    "matrix": "matrix.status",
}

# Canonical schemas are per-subtool contracts, not copies of every property in
# a namespace-level compatibility schema.
_SUBTOOL_FIELDS = {
    "self": {
        "info": [], "diagnose": [], "logs": ["session", "limit", "kind"],
        "context": ["session"], "tools": ["tool", "query"],
        "diagnostics": ["session", "model", "code", "source", "limit"],
        "sj": ["session", "job"],
    },
    "skills": {
        "list": [], "search": ["query", "limit"], "read": ["name"],
    },
    "index": {
        "search": ["query", "k", "kind"], "reindex": ["workspace", "force"],
        "status": ["workspace"],
    },
    "knowledge": {
        "search": ["query", "notebook", "session", "k", "kind"],
        "read_source": ["ref", "notebook", "session", "max_chars"],
        "list_notebooks": [], "create_notebook": ["name"],
        "add_source": ["notebook", "session", "refs", "ref", "url", "query"],
        "add_text": ["notebook", "session", "title", "text", "content"],
        "discover": ["query", "n"], "import": ["notebook", "session", "urls", "refs"],
        "status": [],
    },
    "sessions": {
        "list": ["query", "limit"], "read": ["session", "limit", "tail"],
        "send": ["session", "to", "message", "text"],
        "wait": ["message_id", "timeout_secs"],
    },
    "chapters": {
        "list": ["session"], "untitled": ["session", "limit"],
        "read": ["session", "id"], "title": ["session", "id", "title", "summary"],
    },
    "context": {"status": ["session"], "compact": ["session"]},
    "memory": {
        "store": ["content", "kind", "source", "ttl_secs"],
        "recall": ["query", "kind", "limit", "include_invalid", "semantic"],
        "recent": ["kind", "limit"], "list": ["kind", "limit"],
        "core": [], "set_core": ["content"], "clear_core": [],
        "invalidate": ["target", "query", "kind", "reason"],
        "supersede": ["target", "superseded_by", "reason"],
        "restore": ["target", "reason"],
        "forget": ["target", "query", "kind"], "purge": [], "health": [],
    },
    "improve": {
        "propose": ["scope", "content", "reason"],
        "mine": ["reason"], "evolve": [],
        "verify": ["path"], "promote": ["path"],
        "review": ["limit", "model"],
    },
    "web": {
        "search": ["query", "max_results"], "fetch": ["url", "max_bytes"],
    },
    "diff": {
        "files": ["a", "b", "context"],
        "text": ["text_a", "text_b", "context"],
    },
    "process": {
        "list": ["match", "limit"], "kill": ["pid"],
    },
    "matrix": {
        "status": [], "seams": [], "scaffold": ["kind", "name", "description"],
        "remove": ["kind", "name"],
        "hotload": [], "enable": [], "disable": [],
        "checkpoint_save": ["slot", "label"],
        "checkpoint_rollback": ["slot"],
        "git_commit": ["message"], "git_log": ["limit"],
        "git_diff": ["rev"], "git_reset": ["rev"],
        "test": ["script", "code", "target", "install_deps", "timeout_secs"],
        "clean_trash": ["keep_recent"], "webui_init": [], "webui_reset": [],
        "restart": ["session", "reason", "dry_run"],
        "verify_target": ["kind", "name"],
        "promote_to_nucleus": ["kind", "name"],
    },
}

_SUBTOOL_REQUIRED = {
    "skills.search": ["query"], "skills.read": ["name"],
    "index.search": ["query"],
    "knowledge.search": ["query"], "knowledge.read_source": ["ref"],
    "knowledge.create_notebook": ["name"], "knowledge.discover": ["query"],
    "sessions.read": ["session"],
    "sessions.wait": ["message_id"],
    "chapters.read": ["id"], "chapters.title": ["id", "title"],
    "memory.store": ["content"], "memory.recall": ["query"],
    "memory.set_core": ["content"],
    "improve.propose": ["scope", "content"],
    "improve.mine": [], "improve.evolve": [],
    "improve.verify": ["path"],
    "improve.promote": ["path"],
    "improve.review": [],
    "web.search": ["query"], "web.fetch": ["url"],
    "diff.files": ["a", "b"], "diff.text": ["text_a", "text_b"],
    "process.kill": ["pid"],
    "matrix.checkpoint_save": ["slot"],
    "matrix.checkpoint_rollback": ["slot"],
    "matrix.remove": ["name"],
    "matrix.verify_target": ["name"],
    "matrix.promote_to_nucleus": ["name"],
}

_SUBTOOL_ANY_OF = {
    "knowledge.add_source": [
        {"required": ["refs"]}, {"required": ["ref"]},
        {"required": ["url"]}, {"required": ["query"]},
    ],
    "knowledge.add_text": [
        {"required": ["title", "text"]},
        {"required": ["title", "content"]},
    ],
    "knowledge.import": [{"required": ["urls"]}, {"required": ["refs"]}],
    "memory.invalidate": [{"required": ["target"]}, {"required": ["query"]}],
    "memory.forget": [{"required": ["target"]}, {"required": ["query"]}],
    "sessions.send": [
        {"required": ["session", "message"]}, {"required": ["session", "text"]},
        {"required": ["to", "message"]}, {"required": ["to", "text"]},
    ],
}

_SUBTOOL_GUIDANCE = {
    "self.tools": (
        "Discover enabled tools. Set `query` to filter names/descriptions, or "
        "`tool` to return one exact tool schema; provide one of those fields."
    ),
    "skills.search": (
        "Find skills by keyword. Use the returned exact skill name with "
        "`skills.read` before following that skill."
    ),
    "skills.read": "Read the complete SKILL.md for the exact `name` returned by skills.search.",
    "knowledge.read_source": (
        "Read one indexed source. `ref` is its exact indexed path or source ID; "
        "when scoping with `notebook`, use its ID or exact name from "
        "`knowledge.list_notebooks`."
    ),
    "knowledge.list_notebooks": (
        "List shared notebooks and this chat's notebook. Use the returned `id` "
        "as `notebook` in other knowledge tools."
    ),
    "knowledge.search": (
        "Search indexed text. Omit `notebook` to search this chat and shared "
        "content; use an ID from knowledge.list_notebooks to select one notebook. "
        "Do NOT call add_source for an attached chat path; attachments are indexed automatically."
    ),
    "knowledge.add_source": (
        "Index new paths or URLs. Supply one or more newline-separated values "
        "in `refs` (or one `ref`, `url`, or `query`); do not add an attached "
        "chat path again."
    ),
    "knowledge.add_text": "Add a note by providing `title` and either `text` or `content`.",
    "knowledge.create_notebook": "Create a shared notebook with the requested `name`.",
    "knowledge.discover": "Search the web for candidate sources; this does not index them.",
    "knowledge.import": "Index the supplied candidate URLs or refs into the selected notebook.",
    "memory.recall": (
        "Search persistent memory by required `query`. This uses keyword search "
        "by default; set `semantic=true` only to request embedding search."
    ),
    "memory.recent": "List recent memory records, newest first; optional `kind` and `limit` filters.",
    "memory.invalidate": "Soft-retire a memory by `target` ID or search `query`; provide one.",
    "memory.set_core": (
        "Replace the always-visible CORE block. `content` must be non-empty; "
        "use memory.clear_core for intentional clearing. Requires approval unless "
        "the operator explicitly selects global approvals.mode=full."
    ),
    "memory.clear_core": (
        "Clear all always-visible CORE memory. This is an explicit destructive "
        "action with no recovery; requires approval unless the operator "
        "explicitly selects global approvals.mode=full."
    ),
    "memory.forget": (
        "Permanently delete the memory identified by `target`, or the records whose "
        "content contains `query` as a case-insensitive substring. Verify the target "
        "before use. Requires approval unless the operator explicitly selects global "
        "approvals.mode=full."
    ),
    "sessions.send": (
        "Asynchronously send `message` (or `text`) to `session` (or `to`). A running "
        "peer receives a steer; an idle peer gets a server-side chat turn. This returns "
        "a `message_id` immediately so you can continue your work. Use `sessions.read` "
        "to inspect the peer's live transcript and `sessions.wait` with that id to get "
        "the final assistant reply after its turn ends."
    ),
    "sessions.wait": (
        "Wait for a message sent by `sessions.send` to finish. Pass its exact "
        "`message_id`; returns the peer's last assistant reply when the turn ends. "
        "Default timeout is 180 seconds; if state is `running`, continue other work "
        "and retry with the same id. Use `sessions.read` to inspect the live chat."
    ),
    "memory.purge": (
        "Permanently remove all invalidated or expired memory records. This is "
        "bulk cleanup; use memory.forget to delete one known record. Requires approval "
        "unless the operator explicitly selects global approvals.mode=full."
    ),
    "improve.propose": (
        "Create ONE proposal. `scope` must be exactly `skill`, `project` or "
        "`global`; `content` must state WHAT the proposal accomplishes — the "
        "purpose, the steps and the observable outcome. A bare tool sequence "
        "is not a proposal: name what it does first."
    ),
    # v656: the miner writes drafts; the AGENT is the one who decides whether a
    # repeated sequence deserves a purpose. Say so where the model reads it.
    "improve.mine": (
        "Mine repeated tool patterns and write DRAFT skill proposals under "
        "data/proposals/skills/ (>= 3 distinct steps). A draft is material, "
        "not a proposal: read its SKILL.md, and only when you can state what "
        "the sequence accomplishes, call improve.propose (scope=skill) with "
        "that content."
    ),
    "improve.evolve": (
        "Full self-evolution cycle: mine patterns, synth + verify each draft in "
        "the sandbox, and archive only the ones that pass. Approval-gated: ask "
        "before running it."
    ),
    "improve.verify": (
        "Run the sandbox check of ONE draft returned by improve.mine — provide "
        "its exact `path`. Green = promotable, red = the reason."
    ),
    "improve.promote": (
        "Archive ONE verified draft (provide its `path`) into skills/created/. "
        "Refused unless the verify went green."
    ),
    "improve.review": (
        "LLM-audit the whole backlog (proposals + distilled lessons) against the "
        "current code: keep / implemented / obsolete / update / conflict. "
        "Nothing is decided by the review."
    ),
    "matrix.status": (
        "Report the live Matrix inventory: discovered tools and hooks, load errors, "
        "checkpoints, verified targets, skills, and the active WebUI shadow. "
        "Call this before and after creating or removing an artifact."
    ),
    "matrix.seams": (
        "List the 13 live Matrix -> Nucleus seams with the exact file path and function "
        "signature each artifact must implement. Read this before scaffolding a hook or module."
    ),
    "matrix.scaffold": (
        "Create a compliant Matrix artifact file (`tool`, `hook`, `module`, `skill`, `rule`, "
        "`webui`) and hotload it immediately. For a tool, `name` must be `<namespace>` or "
        "`<namespace>.<subtool>`. The generated tool is a skeleton: next use fs.read + fs.edit "
        "to replace its placeholder description with a precise one (what it does, every input, "
        "the output), define real properties and required fields, then call matrix.hotload and "
        "matrix.test with target='tool:<namespace>'. The tool is live after hotload; no restart "
        "and no manual registry edit are needed. It is not permanent until promote_to_nucleus."
    ),
    "matrix.hotload": (
        "Rescan `src/Matrix/tools/*.py` and Matrix hook modules and replace the live tool map. "
        "Discovery also reloads automatically when a tool file mtime changes, so call this to "
        "confirm and to surface load errors. A broken module is isolated and reported in "
        "`errors`; it never crashes the harness."
    ),
    "matrix.remove": (
        "Uninstall one Matrix artifact from every live surface: source file, compiled bytecode, "
        "imported module, discovery cache, matching tool-policy entries, and verification record, "
        "then hotload. `kind` defaults to `tool`; `name` is required. A tool module that defines "
        "several subtools must be removed by namespace (the call says which subtools would go). "
        "A promoted Nucleus copy is reported, never deleted. Requires approval unless the "
        "operator explicitly selects global approvals.mode=full."
    ),
    "matrix.git_commit": (
        "Commit Matrix changes in its separate Git repository: git dir "
        "`.Matrix/git`, worktree `src/Matrix`. This does not commit the Longrun repo."
    ),
    "matrix.git_log": "Read commit history from Matrix's separate `.Matrix/git` repository (worktree `src/Matrix`).",
    "matrix.git_diff": "Compare revisions in Matrix's separate `.Matrix/git` repository (worktree `src/Matrix`).",
    "matrix.git_reset": (
        "Reset Matrix's separate `.Matrix/git` repository (worktree `src/Matrix`). "
        "This discards tracked and untracked Matrix worktree changes; inspect "
        "matrix.status and matrix.git_diff first. Requires approval unless the "
        "operator explicitly selects global approvals.mode=full."
    ),
    "matrix.checkpoint_rollback": (
        "Restore a Matrix checkpoint slot. This replaces the current checkpointed "
        "Matrix code, rules, skills, and docs; inspect the slot before rollback. "
        "Requires approval unless the operator explicitly selects global approvals.mode=full."
    ),
    "matrix.clean_trash": (
        "Delete scratch files from `.Matrix/trash`. `keep_recent=0` deletes all "
        "entries; set a positive value to retain that many newest entries. "
        "Requires approval unless the operator explicitly selects global approvals.mode=full."
    ),
    "matrix.webui_reset": (
        "Delete the Matrix shadow `src/Matrix/webui/index.html`, making the "
        "Nucleus WebUI serve at `/`. Requires approval unless the operator "
        "explicitly selects global approvals.mode=full."
    ),
    "matrix.promote_to_nucleus": (
        "Promote a verified Matrix artifact into protected Nucleus code. Requires "
        "the configured dangerous-write gate and successful verification."
    ),
}


def _build_canonical_schemas():
    out = {}
    for k, sch in _LEGACY_SCHEMAS.items():
        if "." in k:
            out[k] = dict(sch)
            continue
        if k in _SINGLE_SUBTOOL_MAP:
            cname = _SINGLE_SUBTOOL_MAP[k]
            csch = dict(sch)
            csch["_namespace"] = k
            csch["_subtool"] = cname.split(".", 1)[1]
            out[cname] = csch
            continue
        props = dict(sch.get("properties") or {})
        act_prop = props.get("action") or {}
        actions = list(act_prop.get("enum") or ["run"])
        if k == "memory" and "list" not in actions:
            actions.insert(0, "list")
        if k == "skills" and "search" not in actions:
            actions.append("search")
        field_map = _SUBTOOL_FIELDS.get(k, {})
        sub_req = [r for r in (sch.get("required") or []) if r != "action"]
        # JAG-513: keep the WHOLE description. Cutting at the first sentence threw
        # away exactly the usage instructions a model needs (fs.read's line range,
        # knowledge's "do not re-add an attached path", improve's review contract),
        # so the canonical tool looked like a bare name in the prompt and in
        # `self {action:"tools"}`.
        base_desc = str(sch.get("description") or "").strip().rstrip(".")
        for act in actions:
            cname = "%s.%s" % (k, act)
            fields = field_map.get(act)
            sub_props = ({pk: props[pk] for pk in fields if pk in props}
                         if fields is not None else
                         {pk: pv for pk, pv in props.items() if pk != "action"})
            if k == "improve" and act == "propose":
                sub_props["scope"] = {
                    **(props.get("scope") or {}),
                    "enum": ["skill", "project", "global"],
                    "description": "exact proposal scope (singular)",
                }
            action_required = _SUBTOOL_REQUIRED.get(cname, sub_req)
            if k == "web":
                action_required = {"search": ["query"], "fetch": ["url"]}.get(act, sub_req)
            guidance = _SUBTOOL_GUIDANCE.get(cname)
            if guidance is None:
                fields_note = ", ".join(sub_props) or "no arguments"
                guidance = ("%s This tool performs only action=%s; use only: %s."
                            % (base_desc, act, fields_note))
            out[cname] = {
                "description": ("%s — %s" % (cname, guidance)
                                if guidance else cname),
                "type": "object",
                "properties": dict(sub_props),
                "required": list(action_required),
                "subject": sch.get("subject"),
                "_namespace": k,
                "_subtool": act,
            }
            alternatives = _SUBTOOL_ANY_OF.get(cname)
            if alternatives:
                out[cname]["anyOf"] = [dict(item) for item in alternatives]
    try:
        from longrun.agent import longrun_agent as _lra
        for cname, csch in (_lra.TOOL_SCHEMAS or {}).items():
            out[cname] = dict(csch)
    except Exception:  # noqa: BLE001
        pass
    return out


class _NamespacedSchemasDict(dict):
    """Canonical `<namespace>.<subtool>` schema map with read-only fallback for legacy namespace keys."""

    def __init__(self, canonical, legacy):
        super().__init__(canonical)
        self._legacy = legacy

    def __getitem__(self, key):
        if super().__contains__(key):
            return super().__getitem__(key)
        if key in self._legacy:
            return self._legacy[key]
        raise KeyError(key)

    def get(self, key, default=None):
        if super().__contains__(key):
            return super().__getitem__(key)
        return self._legacy.get(key, default)

    def __contains__(self, key):
        return super().__contains__(key) or (key in self._legacy)


_CANONICAL_SCHEMAS = _build_canonical_schemas()
TOOL_SCHEMAS = _NamespacedSchemasDict(_CANONICAL_SCHEMAS, _LEGACY_SCHEMAS)
KNOWN_NAMESPACES = frozenset(k.split(".", 1)[0] for k in TOOL_SCHEMAS.keys()) | frozenset(_LEGACY_SCHEMAS.keys())


def canonical_name(name, args=None):
    """Canonicalise a LEGACY call onto its `<namespace>.<subtool>` tool name.

    JAG-535: the registry ADVERTISES dotted names (`self.info`, `skills.read`, ...)
    and the chat card shows the name a call was made with, so a legacy call like
    `self` + ``{"action": "info"}`` rendered as a bare `self` — the same tool under
    two names, with its canonical `required` list never enforced. When
    ``<name>.<action>`` (or the namespace's default subtool) is a registered
    CANONICAL tool, return it; anything else is returned UNCHANGED, so plain tools,
    external MCP ``client__tool`` names and Matrix names are never touched.
    """
    n = str(name or "").strip()
    if not n or "." in n or "__" in n:
        return name
    act = ""
    if isinstance(args, dict):
        act = str(args.get("action") or "").strip()
    if act and ("%s.%s" % (n, act)) in _CANONICAL_SCHEMAS:
        return "%s.%s" % (n, act)
    if not act:
        d = LEGACY_DEFAULT_SUBTOOL.get(n)
        if d and d in _CANONICAL_SCHEMAS:
            return d
    return name


# M11 (upgrade plan): approval override for a DESTRUCTIVE subtool, consulted
# by classify(). `improve` is `approval: auto`, but `action=evolve` mines,
# verifies AND archives a skill — that last step changes the live skill set
# and must ask, even though the end-of-turn skills-category path also checks.
_SUBTOOL_GATES = {
    "improve.evolve": "self-evolution writes a skill (mine + verify + archive)",
}


def subtool_gate(tool, args):
    """Approval override for a destructive SUBTOOL, or None.

    Never raises: an unknown tool or odd args simply have no override, so a
    gate failure can never break a turn.
    """
    try:
        name = canonical_name(tool, args or {})
    except Exception:  # noqa: BLE001 — no override is the safe answer
        return None
    reason = _SUBTOOL_GATES.get(name)
    return ("required", reason) if reason else None



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
                "difficulty", "selfevolve", "reasoning", "loop_detection"):
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


def section_config(section, defaults, override=None):
    """Effective config for one ``config/tools.yaml`` block (JAG-483).

    Every plan / self-evolution module carried its own copy of "DEFAULTS <- the
    YAML block -> the explicit override", and they had drifted apart (some let a
    ``None`` in the YAML clobber a real default, some did not). This is the one
    contract: the block is merged over ``defaults``, ``None`` values are ignored
    so a hand-edited file cannot blank a field, and the ``override`` (highest
    priority) wins last.
    """
    out = dict(defaults)
    try:
        got = load_config().get(section) or {}
        if isinstance(got, dict):
            out.update({k: v for k, v in got.items() if v is not None})
    except Exception:  # noqa: BLE001 — a missing config is just the defaults
        pass
    if isinstance(override, dict):
        out.update(override)
    return out


_OVERLAY_HEADER = (
    "# Longrun policy overlay — written automatically by POST /api/tools\n"
    "# (the SETTINGS panel in the Longrun WebUI). Only the keys that DIFFER from\n"
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
    from longrun.util.fswrite import write_json, write_text
    try:
        import yaml
        body = _OVERLAY_HEADER + (
            yaml.safe_dump(overlay, sort_keys=False, allow_unicode=True,
                           default_flow_style=False) if overlay else "{}\n")
        write_text(OVERLAY_YAML, body)
    except ImportError:
        write_json(OVERLAY_JSON, overlay)


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


def forget_tool_policies(names):
    """Drop policy entries for uninstalled tools from the live config + overlay.

    A key that also exists in the hand-edited `config/tools.yaml` cannot be
    deleted through the overlay; it is reported as `base_locked` so the caller
    can tell the operator the truth instead of claiming a complete cleanup.
    """
    global _cfg
    wanted = [str(n) for n in (names or []) if str(n).strip()]
    with _lock:
        cfg = load_config()
        tools_cfg = cfg.get("tools") or {}
        removed = [n for n in wanted if n in tools_cfg]
        for n in removed:
            tools_cfg.pop(n, None)
        base, _src = _load_raw()
        base_tools = base.get("tools") or {}
        base_locked = [n for n in wanted if n in base_tools]
        if removed:
            save_config(cfg)
        return {"removed": removed, "base_locked": base_locked}


def workspace_dir():
    """The sandbox scratch root (JAG-533: USER DATA, so it lives under the data
    home). A relative `sandbox.workspace` is resolved against DATA_DIR; an
    absolute one is honoured. A leading "data/" is dropped so a config written
    before the move does not nest `<home>/data/data/sandbox`."""
    rel = str(load_config()["sandbox"].get("workspace") or "sandbox").strip()
    if os.path.isabs(rel):
        return rel
    if rel.startswith("data/"):
        rel = rel[5:]
    return os.path.join(APP_DATA_DIR, rel)


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


def _matrix_tools():
    """Dynamically discovered Matrix tools (`src/Matrix/tools/*.py`); empty on any error."""
    try:
        from longrun.core import matrix
        return matrix.discover_tools()
    except Exception:
        return {}


def _promoted_tools():
    """Tools permanently promoted from Matrix into Nucleus (`src/longrun/tools/promoted/*.py`)."""
    try:
        from longrun.core import matrix
        return matrix.discover_promoted_tools()
    except Exception:
        return {}


def tool_names():
    """All known tools: canonical namespaced tools + promoted + Matrix + external MCP (+ legacy aliases)."""
    cfg_tools = set(load_config()["tools"])
    return sorted(cfg_tools | set(TOOL_SCHEMAS.keys()) | set(_LEGACY_SCHEMAS.keys())
                  | set(_promoted_tools()) | set(_matrix_tools()) | set(_external_tools()))


def tool_spec(name, ext_snapshot=None, mtx_snapshot=None):
    """Merged {name, enabled, approval, ...policy, schema} or None if unknown.

    `ext_snapshot` (optional) is a pre-fetched `_external_tools()` map so callers
    that iterate many names use ONE consistent view (JAG-253).
    """
    schema = TOOL_SCHEMAS.get(name)
    ext = None
    mtx = None
    prom = None
    pmap = _promoted_tools() if schema is None else {}
    if schema is None:
        prom = pmap.get(name) or (pmap.get(name + ".run") if "." not in name and "__" not in name else None)
        if prom:
            schema = prom.get("schema")
    if schema is None:
        m_map = mtx_snapshot if mtx_snapshot is not None else _matrix_tools()
        mtx = m_map.get(name) or (m_map.get(name + ".run") if "." not in name and "__" not in name else None)
        if mtx:
            schema = mtx.get("schema")
    if schema is None:
        ext = (ext_snapshot if ext_snapshot is not None else _external_tools()).get(name)
        if ext:
            ins = ext.get("inputSchema") or {}
            schema = {"description": ext.get("description", ""),
                      "type": ins.get("type", "object"),
                      "properties": ins.get("properties", {}),
                      "required": ins.get("required", []),
                      "anyOf": ins.get("anyOf", [])}
    tools_cfg = load_config()["tools"] or {}
    ns_entry = None
    if "." in name and "__" not in name:
        ns_prefix = name.split(".", 1)[0]
        if isinstance(tools_cfg.get(ns_prefix), dict):
            ns_entry = dict(tools_cfg[ns_prefix])
    exact_entry = tools_cfg.get(name)
    if isinstance(exact_entry, dict) and isinstance(ns_entry, dict):
        entry = {**ns_entry, **exact_entry}
    elif isinstance(exact_entry, dict):
        entry = dict(exact_entry)
    elif isinstance(ns_entry, dict):
        entry = ns_entry
    else:
        entry = exact_entry
    if entry is None and name in LEGACY_DEFAULT_SUBTOOL:
        c_entry = tools_cfg.get(LEGACY_DEFAULT_SUBTOOL[name])
        if isinstance(c_entry, dict):
            entry = dict(c_entry)
    # JAG-462: an external tool name is `<client>__<tool>`; the client key in the
    # user's mcp config may differ in CASE from the policy key in config/tools.yaml.
    # Fall back to a case-insensitive match for the namespaced form so a client named
    # `PMCP` is not silently DISABLED by an exact-match lookup.
    if entry is None and "__" in name:
        _low = name.lower()
        for _k, _v in tools_cfg.items():
            if str(_k).lower() == _low:
                entry = _v
                break
    is_mtx_family = bool(mtx or prom or name == "matrix" or name.startswith("matrix."))
    if entry is None and is_mtx_family:
        entry = {"enabled": True, "approval": (mtx or prom or {}).get("approval", "auto")}
    is_exclusive = bool((schema or {}).get("_origin") == "exclusive")
    if entry is None and is_exclusive:
        entry = {"enabled": True, "approval": "auto"}
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
        "origin": "exclusive" if is_exclusive else ("matrix" if mtx else ("mcp" if ext else "nucleus")),
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
        "rate_limit": entry.get("rate_limit"),
        "argument_filters": list(entry.get("argument_filters") or []),
        "workspace": entry.get("workspace"),
        "schema": schema,
    }


_RATE_BUCKETS = {}


def rate_consume(tool, max_calls, window_secs, now=None):
    """Paperclip-grade rate probe (P1/N3): "ok" or a "limited: ..." reason.

    Counts calls per tool in a sliding window anchored at the first call.
    `now` is injectable for deterministic tests (defaults to time.monotonic).
    Invalid config fails CLOSED (denies) like a malformed deny regex.
    """
    try:
        limit = int(max_calls)
        window = float(window_secs)
    except (TypeError, ValueError):
        return "limited: invalid rate_limit config for %r" % (tool,)
    if limit < 1 or window <= 0:
        return "limited: invalid rate_limit config for %r" % (tool,)
    ts = now if now is not None else time.monotonic()
    key = str(tool)
    with _lock:
        bucket = _RATE_BUCKETS.get(key)
        if bucket is None or ts - bucket[0] >= window:
            bucket = [float(ts), 0]
            _RATE_BUCKETS[key] = bucket
        bucket[1] += 1
        if bucket[1] > limit:
            return "limited: %r exceeded %d calls per %gs" % (tool, limit, window)
    return "ok"


def rate_reset(tool):
    """Drop the rate counter for `tool` (tests + operator reset)."""
    with _lock:
        _RATE_BUCKETS.pop(str(tool), None)


def argument_filter_hit(filters, args):
    """Paperclip `argumentFiltersMatch` (P1/N3): decision or None.

    Each filter is {match: {k: v, ...}, decision: required|denied}. ALL match
    pairs must equal the call args (string-compared) for the decision to fire.
    Unknown decisions and malformed filters are ignored, never executed.
    """
    args = args or {}
    for f in filters or []:
        if not isinstance(f, dict):
            continue
        match = f.get("match") or {}
        decision = str(f.get("decision") or "").lower()
        if decision not in ("required", "denied"):
            continue
        if not isinstance(match, dict) or not match:
            continue
        hit = True
        for k, v in match.items():
            try:
                if str(args.get(k)) != str(v):
                    hit = False
                    break
            except Exception:  # noqa: BLE001 — probing never breaks the gate
                hit = False
                break
        if hit:
            return decision
    return None


# F4 (Cline plan-before-act direction): tools blocked while a session is
# locked in plan mode with an unapproved plan. Both the short alias and the
# canonical dotted name are listed (ALIASES maps shell->shell.exec, etc.).
PLAN_GATED_TOOLS = ("fs.write", "fs.edit", "shell", "shell.exec",
                    "git", "git.run", "python", "python.run")


def session_plan_locked(sid):
    """True when `sid` is locked in plan mode with no approved plan.

    Unknown/missing sessions are never locked (session-less one-shot calls
    are unaffected — same rule as the exclusive-tools check). Never raises.
    """
    try:
        from longrun.memory import stores as _st
        s = _st.load_session(sid) if sid else None
    except Exception:  # noqa: BLE001 — the gate must never break classify
        return False
    if not s or not s.get("plan_mode"):
        return False
    return (s.get("plan") or {}).get("status") != "approved"


def catalog():
    """Public catalogue for GET /api/tools and MCP tools/list.

    Every entry in the public catalogue is strictly namespaced (`<namespace>.<subtool>`
    or `<server>__<tool>`). Plain namespace keys in `config/tools.yaml` or
    `data/tools.overlay.yaml` provide namespace-level policy inheritance and are never
    emitted as standalone plain rows.
    """
    ext = _external_tools()
    mtx = _matrix_tools()
    prom = _promoted_tools()
    cfg_names = {k for k in (load_config()["tools"] or {}) if ("." in k or "__" in k)}
    names = sorted(cfg_names | set(TOOL_SCHEMAS.keys()) | set(prom) | set(mtx) | set(ext))
    out = []
    for name in names:
        if "." not in name and "__" not in name:
            continue
        spec = tool_spec(name, ext)
        if not spec:
            continue
        out.append({
            "name": name,
            "origin": spec.get("origin", "nucleus"),
            "enabled": spec["enabled"],
            "approval": spec["approval"],
            "auto_approve": spec["auto_approve"],
            "deny": spec["deny"],
            "allow_hosts": spec["allow_hosts"],
            "roots": spec["roots"],
            "description": (spec["schema"] or {}).get("description", ""),
            "inputSchema": {k: v for k, v in (spec["schema"] or {}).items()
                            if k in ("type", "properties", "required", "anyOf")},
        })
    return out


_ENV_ASSIGN_RE = re.compile(
    r"^\s*(?:[A-Za-z_][A-Za-z0-9_]*=(?:'[^']*'|\"[^\"]*\"|\S*)\s+)+")


def _subject(tool, args):
    """The string a policy regex is matched against for this action."""
    spec = TOOL_SCHEMAS.get(tool) or {}
    key = spec.get("subject")
    args = args or {}
    if tool in ("git", "git.run"):
        return str(args.get("args", ""))
    if tool in ("shell", "shell.exec"):
        # JAG-85: `TZ=Europe/Rome date '…'` is still a read-only `date`. Drop the
        # leading `VAR=value` assignments so the auto-approve patterns (and the
        # hard-deny list) match the REAL command. A pointless approval gate here
        # cost a 30s wait and made a simple "what day is it" turn look stuck.
        return _ENV_ASSIGN_RE.sub("", str(args.get("command", "")))
    if key == "action" and not args.get("action") and spec.get("_subtool"):
        return str(spec.get("_subtool"))
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


from longrun.util.fswrite import path_under as _under


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


def _approvals_full():
    """JAG-516: True when the operator chose `approvals.mode=full` (or the
    `auto`/`yolo` aliases) — the explicit "let the agent work" opt-out.

    In that mode the filesystem tools (fs.read / fs.write / fs.edit / diff /
    glob) are UNRESTRICTED, exactly like `shell.exec`, which never had a root
    allow-list. Any other mode keeps the per-tool roots from config/tools.yaml.
    """
    try:
        ap = load_config().get("approvals") or {}
        return str(ap.get("mode", "normal")).lower() in ("full", "auto", "yolo")
    except Exception:  # noqa: BLE001
        return False


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
    if tool in ("fs.read", "fs.write", "fs.edit", "diff", "diff.files", "diff.text"):
        if a.get("path"):
            paths.append(str(a["path"]))
    elif tool in ("git", "git.run"):
        if a.get("cwd") or a.get("workspace"):
            paths.append(str(a.get("cwd") or a.get("workspace")))
    elif tool in ("shell", "shell.exec"):
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


# I-4: the memory buckets the chat prompt actually emits (`model/prompt.py`,
# `_provider_memory`) are ingress channels — the memory store is written by the
# MODEL from whatever it read, so a poisoned fact/lesson/core note is derived,
# untrusted data (ClawMMU: label derived data, gate the action at runtime).
_TAINT_MARKERS = ("[harness] Observation", "Observation (step ",
                  "Relevant memories", "## Memory \u2014 user facts",
                  "## Memory \u2014 self-distilled lessons", "## Core memory")
_TAINT_REASON = ("untrusted content in proposing context - "
                 "standing auto-approval suspended")


def _standing_suspended(hist):
    """True when a standing auto-approval must not fire (M2a)."""
    return bool(hist) and context_has_untrusted(hist)


def context_has_untrusted(messages):
    """Pure M2a probe (ClawMMU App. B): a standing permission applies only
    when no untrusted content entered the proposing context.

    Scans the passed context for the ingress markers that occur in Longrun
    histories: v2-loop observations ("Observation (step N/M):"), legacy
    harness observations ("[harness] Observation"), and retrieved memory
    blocks ("Relevant memories"). Memory injected at call time via a system
    role (context_engine.build) is NOT in the persisted transcript, so it is
    covered only when present in the passed messages. `None` (one-shot API
    calls with no proposing context) is clean by definition.
    """
    if not messages:
        return False
    for msg in messages:
        content = msg.get("content", "") if isinstance(msg, dict) else msg
        try:
            text = content if isinstance(content, str) else str(content)
        except Exception:  # noqa: BLE001 - probing must never break the gate
            continue
        for marker in _TAINT_MARKERS:
            if marker in text:
                return True
    return False


def classify(tool, args, workspace=None, hist=None):
    """Approval decision for a concrete action.

    JAG-388: when a session `workspace` is given, ANY action — a file op, a git
    repo, or a shell command — that reaches a path OUTSIDE it is `required`,
    regardless of the per-tool policy. Only `approvals.mode=full` relaxes it.
    Returns (decision, reason) with decision in:
      disabled | denied | auto | required
    `hist` (M2a) is the proposing context: when it holds untrusted
    content, standing auto-approvals are suspended (the call needs
    approval). `None` (one-shot API calls) means no context: clean.
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
    # JAG-535/538: exclusive tools enforce a dual-permission model — the tool must
    # be enabled here AND the calling session must be `longrunAgent` or have
    # `allow_longrun_agent: true`. Even `approvals.mode=full` never bypasses the
    # session privilege check when `run_id` / `session` is provided in `args`.
    # The marker is the schema's own `_origin`, not a name prefix: exclusive tools
    # are now named `namespace.tool` (`agent.prompt_set`), with no shared prefix.
    # v616: ONE source of truth — the verdict AND the reason come from
    # `longrun_agent.check_dual_permission`, the same function the execute path
    # uses. A second inline copy of this message lived here and already drifted
    # once (different wording for the same denial).
    if (spec.get("schema") or {}).get("_origin") == "exclusive":
        sess_ref = (args or {}).get("_session") or (args or {}).get("run_id")
        if sess_ref is not None:
            from longrun.agent import longrun_agent as _lra
            _ok, _why = _lra.check_dual_permission(tool, sess_ref)
            if not _ok:
                return "denied", _why
    # F4 (Cline plan-before-act direction): a session locked in plan mode may
    # only EXPLORE — mutating tools are denied until the operator approves the
    # proposed plan (`stores.approve_plan`). An explicit lock: even
    # approvals.mode=full never bypasses it (matrix-promote precedent).
    _sess = (args or {}).get("_session") or (args or {}).get("run_id")
    if tool in PLAN_GATED_TOOLS and session_plan_locked(_sess):
        return "denied", (
            "plan mode: session %r has an unapproved plan — propose the plan "
            "and wait for operator approval; read-only tools still work"
            % (_sess,))
    # PT3: `matrix.promote_to_nucleus` / `matrix{action:"promote_to_nucleus"}` is gated EXCLUSIVELY
    # by the dedicated `approvals.allow_matrix_promote` checkbox — even `approvals.mode=full` never unlocks it.
    if tool == "matrix.promote_to_nucleus" or (
        tool == "matrix" and str((args or {}).get("action") or "").strip().lower() == "promote_to_nucleus"
    ):
        ap_mtx = load_config().get("approvals") or {}
        if not bool(ap_mtx.get("allow_matrix_promote", False)):
            return "denied", (
                "promote_to_nucleus requires the dedicated allow_matrix_promote checkbox "
                "in Settings > Tools & approvals (even FULL mode does not authorize it)"
            )
        return "auto", "allow_matrix_promote checkbox is enabled"
    # JAG-127c/388: global approval switch, set from the Config panel (persisted
    # in the overlay). `full` = never ask for anything (hard-deny/disabled still
    # win). It is now the ONLY thing that relaxes the workspace boundary below.
    ap = load_config().get("approvals") or {}
    if str(ap.get("mode", "normal")).lower() in ("full", "auto", "yolo"):
        return "auto", "approvals.mode=full — never ask"
    # M11: a destructive SUBTOOL overrides the per-tool policy. `improve` is
    # `approval: auto`, but `improve.evolve` archives a live skill — ask.
    # Checked AFTER the global mode (full/auto/yolo still bypasses) and BEFORE
    # the per-tool 'auto' fast path below.
    gate = subtool_gate(tool, args)
    if gate:
        return gate
    # P1 (Paperclip N3): rate_limit + argument_filters from the tool policy
    # (config/tools.yaml). Checked AFTER the global mode (full bypasses, like
    # the M11 gate) and BEFORE the per-tool 'auto' fast path. An invalid
    # rate config fails CLOSED; unknown filter decisions are ignored.
    rl = spec.get("rate_limit")
    if rl is not None:
        _rl = (rate_consume(tool, rl.get("max_calls"), rl.get("window_secs"))
               if isinstance(rl, dict)
               else "limited: invalid rate_limit config for %r" % (tool,))
        if _rl != "ok":
            return "denied", "rate_limit:%s %s" % (tool, _rl)
    _af = argument_filter_hit(spec.get("argument_filters"), args)
    if _af == "denied":
        return "denied", "argument_filter:%s matched denied args" % (tool,)
    if _af == "required":
        return "required", "argument_filter:%s matched approval-gated args" % (tool,)
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
        if _standing_suspended(hist):
            return "required", _TAINT_REASON
        return "auto", "tool policy is 'auto'"
    hit = _match(spec["auto_approve"], subject)
    if hit:
        if _standing_suspended(hist):
            return "required", _TAINT_REASON
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
    # JAG-516: `approvals.mode=full` is the explicit opt-out; with it the fs
    # tools see the WHOLE filesystem (shell.exec already could), so the
    # allow-list below is the boundary for every OTHER mode.
    if _approvals_full():
        return p, None
    for r in roots:
        root = os.path.realpath(r if os.path.isabs(r) else os.path.join(REPO, r))
        if p == root or p.startswith(root + os.sep):
            return p, None
    return None, "path %r outside allowed roots %s" % (path, roots)
