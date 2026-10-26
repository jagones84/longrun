"""Schema-driven structured editors for ``config/*.yaml`` (JAG-491).

JAG-488 made the whole ``config/`` store editable from the WebUI, but only as a
raw YAML textarea. The operator asked for *objects*: a checkbox for a boolean, a
number field with its bounds, a select for an enum, a repeatable row per hook —
never hand-typed YAML.

This module is the single declaration of those forms. One schema covers the
files that have no bespoke panel (and the keys the bespoke panels do not show):

  * ``index.yaml``            chunking, size caps, knowledge knobs
  * ``compaction.yaml``       summarizer input/output caps + instruction
  * ``routing.yaml``          role patterns/models/fallbacks not owned by Subagents
  * ``decisions.yaml``        decision layer + speculative execution
  * ``hooks.yaml``            the lifecycle-hook table
  * ``mcp_clients.yaml``      env_files (clients are the MCP panel's job)

Files (or individual keys) owned by a dedicated panel are listed in
``DEDICATED`` and are DELIBERATELY absent here, so there is exactly one writer
per setting. ``tests/acceptance/v491_settings_forms.py`` walks every leaf of
every config file and fails if it is covered by neither.

JAG-499b: each section also declares its home Settings ``panel`` (harness /
hooks / tools / models / mcp / knowledge). The WebUI renders every section inside
that panel, so Settings ▸ Config — marked ``DO NOT REMOVE! ITS BACKUP`` — is no
longer needed for a normal change: everything in ``config/*.yaml`` is settable
from the panels around the Settings window.

Writes reuse the existing per-domain persistence:
  * ``index.yaml``      -> ``indexcfg.save_config`` (gitignored overlay)
  * ``compaction.yaml`` -> ``compaction_config.save`` (compaction.local.yaml)
  * ``routing.yaml``    -> ``routing.save_config`` (whole document, as before)
  * ``hooks.yaml``      -> ``data/hooks.overlay.yaml`` (base file keeps its docs)
  * ``decisions.yaml``  -> ``data/decisions.overlay.yaml``
  * ``mcp_clients.yaml``-> ``config/mcp_clients.local.json`` (gitignored)
No base file is rewritten, so the commented shipped config stays intact.
"""
import os

from longrun.util import dataio
from longrun.util import paths

CONFIG_DIR = os.path.join(paths.REPO_ROOT, "config")
HOOKS_OVERLAY = os.path.join(paths.DATA_DIR, "hooks.overlay.yaml")
DECISIONS_OVERLAY = os.path.join(paths.DATA_DIR, "decisions.overlay.yaml")
TRACE_OVERLAY = os.path.join(paths.DATA_DIR, "trace_policy.overlay.yaml")
JOBS_OVERLAY = os.path.join(paths.DATA_DIR, "jobs.overlay.yaml")


def _f(path, label, type_="text", **kw):
    """One field descriptor. `path` is dotted inside the effective document."""
    out = {"path": path, "label": label, "type": type_}
    out.update(kw)
    return out


# --------------------------------------------------------------- sections ----
SECTIONS = [
    {
        "file": "index.yaml", "id": "index", "panel": "knowledge",
        "title": "Indexing & knowledge",
        "help": ("How the codebase index and the knowledge base cut, cap and "
                 "skip content. The embedding MODEL itself lives in Models."),
        "fields": [
            _f("enabled", "indexing enabled", "bool"),
            _f("automatic", "rebuild automatically", "bool",
               help="Rebuild the workspace index without asking."),
            _f("max_file_kb", "code · file cap (KB)", "int", min=1, max=1048576,
               help="The largest file the CODE index reads."),
            _f("doc_max_kb", "documents · text cap (KB)", "int",
               min=1, max=1048576,
               help="The largest PDF / DOCX / PPTX / ODT, measured as its "
                    "extracted text."),
            _f("chunk_lines", "chunk size (lines)", "int", min=5, max=2000),
            _f("overlap_lines", "chunk overlap (lines)", "int", min=0, max=500),
            _f("ignore", "code · ignore globs", "strlist",
               help="One glob per line. Applies to the CODE index only."),
            # v656: one label per line — the long ones ("documents · extracted
            # text cap (KB)") wrapped onto a second line inside their column and
            # the row tops no longer lined up; the size caps now pair two per row
            # and every label fits its column.
            _f("knowledge_max_file_kb", "knowledge · file cap (KB)", "int",
               min=1, max=1048576),
            _f("url_max_kb", "download cap (KB)", "int", min=1, max=1048576,
               help="A URL fetched for the knowledge base is truncated at this "
                    "size."),
            _f("knowledge_ignore", "knowledge · ignore globs", "strlist",
               help="One glob per line. Empty = index every supported file."),
            _f("image_caption_model", "image caption model", "text", wide=True,
               placeholder="openrouter:google/gemini-2.5-flash",
               help="Empty = OCR only. A vision model ref captions images with "
                    "too little text to be searchable."),
            _f("image_min_chars", "image · min OCR chars", "int", min=0, max=5000,
               help="Images with fewer OCR chars than this go to the caption "
                    "model instead."),
            _f("embed_batch", "embedding batch size", "int", min=1, max=512,
               help="Chunks sent to the embedding model per request."),
        ],
    },
    {
        "file": "compaction.yaml", "id": "compaction", "panel": "compaction",
        "title": "Compaction",
        "help": ("One shared policy for automatic and manual compaction. A transcript "
                 "larger than `input cap` is summarized part by part; the parts are "
                 "merged, bounded by `max parts`. These values are global, not "
                 "session-specific."),
        "fields": [
            _f("trigger_pct", "auto trigger (%)", "int", min=1, max=100),
            _f("target_pct", "auto target (%)", "int", min=0, max=99),
            _f("keep_recent", "keep recent messages", "int", min=1, max=50),
            _f("summarizer.input_max_chars", "input cap (chars)", "int",
               min=1000, max=1000000),
            _f("summarizer.output_max_chars", "output cap (chars)", "int",
               min=200, max=100000),
            _f("summarizer.max_parts", "max parts per compaction", "int",
               min=1, max=64,
               help="Upper bound on the summarizer calls one compaction may make."),
            _f("overflow_note", "overflow note", "bool",
               help="P1/N9: when compaction/trimming cannot fit the prompt in the "
                    "model window, leave a durable `context_overflow_after_"
                    "compaction` note in the transcript. Observability only — "
                    "never blocks a turn."),
            _f("summarizer.instruction", "instruction", "textarea",
               rows=10, help="Reply language follows the transcript."),
        ],
    },
    {
        "file": "routing.yaml", "id": "routing", "panel": "models",
        "title": "Routing · every role",
        "help": ("THE DEFAULTS for every session — which model each ROLE uses, and the "
                 "fallback chain tried when it fails. Not a duplicate of anything else: "
                 "the composer's model picker overrides the CHAT role for one session "
                 "only, and the subagent model lives in Settings ▸ Subagents. "
                 "`model` is a verbatim <provider>:<model> ref; `pattern` is a substring "
                 "of the local llama.cpp router roster and applies to chat/agent only; "
                 "fallbacks are literal refs tried in order. Clear a field to fall back "
                 "to the shipped default."),
        "fields": [],          # filled per role in _sections()
    },
    {
        "file": "decisions.yaml", "id": "decisions", "panel": "harness",
        "title": "Decision layer & speculation",
        "help": ("A pluggable cheap-model layer in front of the loop (route / prune / "
                 "validate). `null` is a strict no-op; every hook fails open."),
        "fields": [
            _f("enabled", "enabled", "bool"),
            _f("mode", "mode", "select", options=["null", "heuristic", "local"]),
            _f("speculative.enabled", "speculative prefetch", "bool"),
            _f("speculative.k", "how many tools to predict", "int", min=1, max=16),
            _f("speculative.readonly_only", "read-only tools only", "bool"),
        ],
    },
    {
        "file": "jobs.yaml", "id": "jobs", "panel": "harness",
        "title": "Team jobs \u00b7 org depth",
        "help": ("A job is goal + who you give it to. The assignee's ORG SUBTREE "
                 "becomes the team and every member becomes a numbered subjob "
                 "(J8.1, J8.2 \u2026); a member who reports to another member nests "
                 "under that lead (J8.1.1), so the ids mirror the organigram. "
                 "`org depth` caps how many levels one job covers (1 = assignee + "
                 "direct reports); `max subjobs` is the hard ceiling per job."),
        "fields": [
            _f("subjob_depth", "org depth (levels)", "int", min=1, max=6,
               help="1 = the assignee plus its direct reports. 2-6 = the whole "
                    "branch, with nested subjob ids."),
            _f("max_subjobs", "max subjobs per job", "int", min=1, max=512,
               help="Hard ceiling: members past this are left out of the run."),
        ],
    },
    {
        "file": "trace_policy.yaml", "id": "trace_policy", "panel": "harness",
        "title": "Trace policy \u00b7 single-trace safety",
        "help": ("Per-trace guardrails (Local-Allow-Global-Deny): delegation "
                 "revalidation (C5), cumulative consent (C4) and the note-only "
                 "intent fence (C1). Escalation only \u2014 these rules never deny, "
                 "and purpose (C2) cannot be enforced per-trace by design."),
        "fields": [
            _f("enabled", "enabled", "bool"),
            _f("delegation_revalidation", "delegation revalidation (C5)", "bool",
               help="A cited subagent id that names nothing escalates auto to required."),
            _f("consent_budget", "cumulative consent budget (C4)", "int", min=0, max=10000,
               help="Executed mutating calls before every auto needs approval. 0 = off."),
            _f("intent_fence", "intent fence notes (C1)", "bool",
               help="Note-only: a subject never named in the run goal earns a harness note, never a block."),
        ],
    },
    {
        "file": "hooks.yaml", "id": "hooks", "panel": "hooks",
        "title": "Lifecycle hooks",
        "help": ("Deterministic shell commands around every tool call. Exit 2 on "
                 "PreToolUse BLOCKS the call. Saved to a gitignored overlay, so the "
                 "shipped file and its examples stay intact (delete "
                 "the data home's hooks.overlay.yaml to revert)."),
        "fields": [
            _f("hooks", "hooks", "rows", item_label="hook", item=[
                _f("event", "event", "select",
                   options=["PreToolUse", "PostToolUse", "Stop"]),
                _f("matcher", "tool matcher (regex)", "text", placeholder="^shell$"),
                _f("command", "command", "text",
                   placeholder="printf '%s' \"$LONGRUN_TOOL\""),
                _f("timeout_secs", "timeout (s)", "int", min=1, max=3600),
                _f("block_on_fail", "block on failure", "bool"),
            ]),
        ],
    },
    {
        "file": "mcp_clients.yaml", "id": "mcp_env", "panel": "mcp",
        "title": "Env files · ${VAR} lookup",
        "help": ("Files loaded (KEY=VALUE) before ${VAR} expansion in MCP headers, e.g. "
                 "the repo's gitignored .env. The servers themselves are the list above."),
        "fields": [
            _f("env_files", "env files", "strlist",
               help="One path per line (e.g. .env — the repo's gitignored file)."),
        ],
    },
]

# Settings owned by a dedicated panel: file -> {path prefix: panel}.
# A leaf is covered when it is under one of these prefixes (or its exact path).
DEDICATED = {
    "routing.yaml": {
        "roles.subagent.model": "Settings ▸ Subagents",
        "roles.subagent.fallbacks": "Settings ▸ Subagents",
    },
    "tools.yaml": {
        "sandbox": "Settings ▸ Tools & approvals",
        "approvals": "Settings ▸ Tools & approvals",
        "runtime": "Settings ▸ Harness",
        "verifier": "Settings ▸ Harness",
        "budget": "Settings ▸ Harness",
        "bestofn": "Settings ▸ Harness",
        "difficulty": "Settings ▸ Harness",
        "selfevolve": "Settings ▸ Harness",
        "loop_detection": "Settings ▸ Harness",
        "reasoning": "Settings ▸ Models",
        "tools": "Settings ▸ Tools & approvals",
        "version": "internal",
    },
    "providers.yaml": {"*": "Settings ▸ Models"},
    # gitignored user overlays written by those same panels
    "providers.local.yaml": {"*": "Settings ▸ Models"},
    "compaction.local.yaml": {"*": "Settings ▸ Compaction"},
    "embedding.yaml": {"*": "Settings ▸ Models"},
    # JAG-516: hand-maintained rate table for models the OpenRouter cache cannot
    # price (provider-direct APIs). Model METADATA, so it belongs to the Models
    # panel exactly like embedding.yaml — never to the generic Config form.
    "prices.yaml": {"*": "Settings ▸ Models"},
    "subagents.yaml": {"*": "Settings ▸ Subagents"},
    "mcp_clients.yaml": {"clients": "Settings ▸ MCP"},
    "index.yaml": {
        "embed_model": "Settings ▸ Models",
        "auto_index": "right rail ▸ Codebase",
        "custom_models": "Settings ▸ Models",
        "disabled_models": "Settings ▸ Models",
        "research_model": "Settings ▸ Models + Knowledge ▸ Research",
        "research_active": "Settings ▸ Models + Knowledge ▸ Research",
    },
}

_FILE_SECTIONS = {s["file"]: s for s in SECTIONS}

# JAG-2.5: the human name of every Settings panel that can own a config section.
# ONE declaration: the WebUI's SETTINGS_CATS labels match these, and the diagnostics
# report names the panel the operator must open to fix an invalid setting.
PANEL_LABELS = {
    "appearance": "Appearance", "keys": "Keys", "models": "Models",
    "subagents": "Subagents", "tools": "Tools & approvals", "sandbox": "Sandbox",
    "mcp": "MCP", "skills": "Skills", "rules": "Rules", "knowledge": "Knowledge",
    "compaction": "Compaction", "hooks": "Hooks", "harness": "Harness",
    "config": "Config files", "improvement": "Improvements",
    "diagnostics": "Diagnostics", "info": "Info",
}


# ---------------------------------------------------------------- helpers ----
def _get(doc, path):
    """Value at a dotted path (None when absent)."""
    cur = doc
    for key in str(path or "").split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _set(doc, path, value):
    """Set a dotted path, creating intermediate mappings."""
    keys = str(path or "").split(".")
    cur = doc
    for key in keys[:-1]:
        nxt = cur.get(key)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[key] = nxt
        cur = nxt
    cur[keys[-1]] = value


def _coerce(field, raw):
    """Validate/convert one wire value for `field`. Raises ValueError."""
    t = field.get("type")
    label = field.get("label") or field.get("path")
    if t == "bool":
        return bool(raw)
    if t == "int":
        try:
            n = int(raw)
        except (TypeError, ValueError):
            raise ValueError("%s must be an integer" % label)
        lo, hi = field.get("min"), field.get("max")
        if lo is not None and n < lo:
            raise ValueError("%s must be >= %s" % (label, lo))
        if hi is not None and n > hi:
            raise ValueError("%s must be <= %s" % (label, hi))
        return n
    if t == "float":
        try:
            n = float(raw)
        except (TypeError, ValueError):
            raise ValueError("%s must be a number" % label)
        lo, hi = field.get("min"), field.get("max")
        if lo is not None and n < lo:
            raise ValueError("%s must be >= %s" % (label, lo))
        if hi is not None and n > hi:
            raise ValueError("%s must be <= %s" % (label, hi))
        return n
    if t == "select":
        v = str(raw if raw is not None else "").strip()
        opts = [str(o) for o in (field.get("options") or [])]
        if opts and v not in opts:
            raise ValueError("%s must be one of %s" % (label, ", ".join(opts)))
        return v
    if t == "strlist":
        if isinstance(raw, str):
            raw = raw.replace(",", "\n").splitlines()
        if not isinstance(raw, list):
            raise ValueError("%s must be a list" % label)
        out, seen = [], set()
        for item in raw:
            s = str(item or "").strip()
            if s and s not in seen:
                seen.add(s)
                out.append(s[:500])
        if len(out) > 500:
            raise ValueError("%s: too many entries (max 500)" % label)
        return out
    if t == "rows":
        if not isinstance(raw, list):
            raise ValueError("%s must be a list" % label)
        if len(raw) > 200:
            raise ValueError("%s: too many rows (max 200)" % label)
        items = field.get("item") or []
        out = []
        for r in raw:
            if not isinstance(r, dict):
                raise ValueError("%s: each row must be an object" % label)
            row = {}
            for sub in items:
                key = sub["path"]
                row[key] = _coerce(sub, r.get(key))
            out.append(row)
        return out
    # text / textarea
    s = "" if raw is None else str(raw)
    limit = int(field.get("max_chars") or (200000 if t == "textarea" else 4000))
    return s[:limit]


def _routing_sections():
    """Expose role routing without duplicating the Subagents model controls."""
    try:
        from longrun.model import routing
        cfg = routing.load_config()
    except Exception:  # noqa: BLE001 — the form must still render
        cfg = {}
    roles = cfg.get("roles") if isinstance(cfg.get("roles"), dict) else {}
    fields = []
    for name, spec in roles.items():
        if name != "subagent":
            fields.append(_f("roles.%s.model" % name, "%s · model" % name, "text",
                             placeholder="openrouter:vendor/model"))
        fields.append(_f("roles.%s.pattern" % name, "%s · pattern" % name, "text",
                         help="Local roster substring (chat/agent only)."))
        if name != "subagent":
            fields.append(_f("roles.%s.fallbacks" % name, "%s · fallbacks" % name,
                             "strlist"))
    fields.append(_f("default_fallbacks", "global fallbacks", "strlist"))
    sec = dict(_FILE_SECTIONS["routing.yaml"])
    sec["fields"] = fields
    return [sec]


def _sections():
    out = []
    for s in SECTIONS:
        out.extend(_routing_sections() if s["id"] == "routing" else [s])
    return out


def _effective(name):
    """The REAL values the harness is using for `name` (defaults included)."""
    if name == "index.yaml":
        from longrun.memory import indexcfg
        return indexcfg.load_config()
    if name == "compaction.yaml":
        from longrun.model import compaction_config
        # `load()` already returns the UNWRAPPED policy (trigger/target/
        # keep_recent/summarizer) — the schema paths are relative to it.
        return compaction_config.load()
    if name == "jobs.yaml":
        # v629: same contract as compaction — the form edits the UNWRAPPED job
        # policy, and jobs.config() already merges the shipped file + overlay.
        from longrun.orchestrate import jobs as jobs_mod
        return jobs_mod.config()
    if name == "routing.yaml":
        from longrun.model import routing
        return routing.load_config()
    if name == "decisions.yaml":
        from longrun.model import decision
        return decision.load_config()
    if name == "trace_policy.yaml":
        from longrun.agent import trace_policy
        return trace_policy.load() or {}
    if name == "hooks.yaml":
        from longrun.tools import hooks
        return {"hooks": hooks.load(reload=True)}
    if name == "mcp_clients.yaml":
        from longrun.interop import mcp_client
        return mcp_client.load_doc()
    raise ValueError("no structured form for %s" % name)


def view():
    """Everything the Settings ▸ Config forms render: sections + live values."""
    out = []
    for sec in _sections():
        doc = _effective(sec["file"])
        out.append({
            "file": sec["file"], "id": sec["id"], "title": sec["title"],
            "panel": sec.get("panel", ""),   # JAG-499b: the Settings panel that owns it
            "files": (["config/" + sec["file"]] +
                      (["config/compaction.local.yaml"]
                       if sec["file"] == "compaction.yaml" and
                       os.path.isfile(os.path.join(CONFIG_DIR, "compaction.local.yaml"))
                       else [])),
            "help": sec.get("help", ""),
            "fields": sec["fields"],
            "values": {f["path"]: _get(doc, f["path"]) for f in sec["fields"]},
        })
    return {"ok": True, "sections": out, "dedicated": DEDICATED,
            "files": sorted({s["file"] for s in out} | set(DEDICATED))}


def _write_overlay(path, doc):
    """Atomic YAML overlay write (gitignored)."""
    from longrun.util.fswrite import write_text
    write_text(path, dataio.dump_yaml(doc or {}))


def _save(name, clean):
    """Persist validated values through the owning module (no base rewrite)."""
    if name == "index.yaml":
        from longrun.memory import indexcfg
        indexcfg.save_config(clean)
    elif name == "compaction.yaml":
        from longrun.model import compaction_config
        patch = {}
        for path, val in clean.items():
            if path.startswith("summarizer."):
                patch.setdefault("summarizer", {})[path.split(".", 1)[1]] = val
        compaction_config.save(trigger_pct=clean.get("trigger_pct"),
                               target_pct=clean.get("target_pct"),
                               keep_recent=clean.get("keep_recent"),
                               patch=patch)
    elif name == "routing.yaml":
        from longrun.model import routing
        cur = routing.load_config()
        for path, val in clean.items():
            _set(cur, path, val)
        routing.save_config(cur)
    elif name == "hooks.yaml":
        _write_overlay(HOOKS_OVERLAY, {"hooks": clean.get("hooks") or []})
        from longrun.tools import hooks
        hooks.load(reload=True)
    elif name == "decisions.yaml":
        _write_overlay(DECISIONS_OVERLAY, clean)
        from longrun.model import decision
        decision.load_config()          # the overlay mtime is part of its cache key
    elif name == "trace_policy.yaml":
        _write_overlay(TRACE_OVERLAY, clean)
        from longrun.agent import trace_policy
        trace_policy.load()             # the overlay stat is part of its cache key
    elif name == "jobs.yaml":
        # v629: team-job policy lives in a gitignored overlay; jobs.config()
        # merges the shipped file with it on every read (hot, no restart).
        _write_overlay(JOBS_OVERLAY, {"jobs": clean})
    elif name == "mcp_clients.yaml":
        from longrun.interop import mcp_client
        doc = mcp_client._load_local_doc()
        doc["env_files"] = clean.get("env_files") or []
        mcp_client._save_local_doc(doc)
        try:
            mcp_client.reload()
        except Exception:  # noqa: BLE001 — the file is already written
            pass
    else:
        raise ValueError("no writer for %s" % name)
    return _effective(name)


def update(body):
    """Apply one section's values. ``{file, values}`` -> ``{ok, ...}``."""
    body = body or {}
    name = str(body.get("file") or "").strip()
    values = body.get("values")
    if not isinstance(values, dict) or not values:
        return {"ok": False, "error": "values must be a non-empty object"}
    sec = next((s for s in _sections() if s["file"] == name), None)
    if sec is None:
        return {"ok": False, "error": "no structured form for %r" % name}
    fields = {f["path"]: f for f in sec["fields"]}
    unknown = sorted(set(values) - set(fields))
    if unknown:
        return {"ok": False, "error": "unknown setting(s): %s" % ", ".join(unknown)}
    clean = {}
    try:
        for path, raw in values.items():
            clean[path] = _coerce(fields[path], raw)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    try:
        doc = _save(name, clean)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    files = ["config/" + name]
    if name == "compaction.yaml":
        from longrun.model import compaction_config
        if os.path.isfile(compaction_config.local_path()):
            files.append("config/compaction.local.yaml")
    return {"ok": True, "file": name,
            "files": files,
            "values": {p: _get(doc, p) for p in clean}}
