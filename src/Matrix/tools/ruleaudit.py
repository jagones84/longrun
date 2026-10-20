"""Matrix experimental tool: ruleaudit -- audit WHICH .Matrix/rules are injected into a prompt.

The question this answers is the one `matrix.seams` cannot: *is this specific rule
actually inside that prompt right now?* `.Matrix/rules/*.md` are injected as dynamic
addenda into every agent/subagent system prompt, but until now there was no way to
assert it mechanically -- the audit was done by eye and by asking a child agent
"do you see it?", which is a self-report, not a measurement.

Two subtools:
  ruleaudit.list  -- enumerate `.Matrix/rules/*.md` with the exact marker each one
                     contributes (its first H1 heading), so a caller knows what to grep for.
  ruleaudit.scan  -- take a prompt TEXT (or a file holding one) and report PASS/FAIL
                     per rule, with the evidence snippet or an explicit MISSING verdict.

Design constraints (same lessons as diskrot/sysprobe):
  - read-only: never writes, never deletes, never spawns a process
  - every path is explicit and clamped to the repo; no unbounded walk of $HOME
  - a missing/empty prompt is a FAIL, not a vacuous PASS: an oracle that cannot
    fail is not an oracle (.Matrix/rules/01-oracle-must-be-able-to-fail.md)
"""

import glob
import os
import re

TOOL_SCHEMA_LIST = {
    "description": (
        "[MATRIX] List `.Matrix/rules/*.md` with the exact marker each rule contributes "
        "(its first H1 heading) plus size. Read-only; use before ruleaudit.scan."
    ),
    "type": "object",
    "properties": {
        "dir": {"type": "string", "description": "Rules directory (default: <repo>/.Matrix/rules)."},
    },
    "required": [],
    "approval": "auto",
}

TOOL_SCHEMA_SCAN = {
    "description": (
        "[MATRIX] Audit whether `.Matrix/rules/*.md` are really present inside a given prompt: "
        "PASS/FAIL per rule with quoted evidence, explicit MISSING otherwise. Read-only. "
        "An empty prompt FAILS (no vacuous pass)."
    ),
    "type": "object",
    "properties": {
        "prompt_text": {"type": "string", "description": "The prompt/system prompt to audit."},
        "prompt_file": {"type": "string", "description": "Path to a file holding the prompt (used when prompt_text is absent)."},
        "rules": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Restrict the audit to these rule filenames (default: every rule).",
        },
        "dir": {"type": "string", "description": "Rules directory (default: <repo>/.Matrix/rules)."},
        "context": {"type": "integer", "default": 60, "description": "Characters of evidence around a hit."},
    },
    "required": [],
    "approval": "auto",
}

TOOL_SCHEMAS = {
    "ruleaudit.list": dict(TOOL_SCHEMA_LIST),
    "ruleaudit.scan": dict(TOOL_SCHEMA_SCAN),
}

# `verify_target` (src/longrun/core/matrix.py:1323) still requires the legacy
# singular TOOL_SCHEMA, while the real loader reads TOOL_SCHEMAS. Declaring both
# keeps the promotion gate honest instead of failing for a naming convention.
TOOL_SCHEMA = dict(TOOL_SCHEMA_LIST)

_H1 = re.compile(r"^\s*#\s+(.+?)\s*$")


def _repo_root():
    try:
        from longrun.util.paths import REPO_ROOT  # noqa: WPS433
        return str(REPO_ROOT)
    except Exception:  # noqa: BLE001
        here = os.path.abspath(__file__)
        return os.path.abspath(os.path.join(os.path.dirname(here), "..", "..", ".."))


def _rules_dir(args):
    d = args.get("dir") or os.path.join(_repo_root(), ".Matrix", "rules")
    return os.path.abspath(os.path.expanduser(str(d)))


def _norm(s):
    """Whitespace-insensitive lowercase form, so a re-wrapped rule still matches."""
    return re.sub(r"\s+", " ", str(s)).strip().lower()


def _marker_of(text):
    """The exact marker a rule contributes: its first H1 heading, else its first non-empty line."""
    for line in str(text).splitlines():
        m = _H1.match(line)
        if m:
            return m.group(1).strip()
    for line in str(text).splitlines():
        s = line.strip().lstrip("#").strip()
        if s:
            return s
    return ""


def _load_rules(directory):
    out = []
    if not os.path.isdir(directory):
        return out
    for p in sorted(glob.glob(os.path.join(directory, "*.md"))):
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                body = f.read()
        except OSError as e:
            out.append({"file": os.path.basename(p), "error": str(e), "marker": "", "bytes": 0})
            continue
        out.append({
            "file": os.path.basename(p),
            "marker": _marker_of(body),
            "bytes": len(body.encode("utf-8")),
            "lines": body.count("\n") + 1,
        })
    return out


def _sub_list(args):
    directory = _rules_dir(args)
    rules = _load_rules(directory)
    return {
        "ok": True,
        "dir": directory,
        "count": len(rules),
        "rules": rules,
        "note": "read-only: markers are what ruleaudit.scan looks for",
    }


def _sub_scan(args):
    directory = _rules_dir(args)
    prompt = args.get("prompt_text")
    src = "prompt_text"
    if prompt is None or str(prompt) == "":
        pf = args.get("prompt_file")
        if not pf:
            return {"ok": False, "error": "need prompt_text or prompt_file", "pass": False}
        fp = os.path.abspath(os.path.expanduser(str(pf)))
        try:
            with open(fp, "r", encoding="utf-8", errors="replace") as f:
                prompt = f.read()
        except OSError as e:
            return {"ok": False, "error": "cannot read prompt_file: %s" % e, "pass": False}
        src = fp

    haystack = _norm(prompt)
    if not haystack:
        # An empty prompt cannot contain anything: FAIL loudly instead of passing vacuously.
        return {
            "ok": True, "pass": False, "source": src, "prompt_chars": 0,
            "reason": "empty prompt: nothing can be present",
            "results": [], "missing": [], "present": [],
        }

    ctx = args.get("context")
    try:
        ctx = max(0, min(400, int(ctx if ctx is not None else 60)))
    except (TypeError, ValueError):
        ctx = 60

    rules = _load_rules(directory)
    if not rules:
        return {"ok": False, "pass": False, "error": "no rules found in %r" % directory}
    wanted = args.get("rules")
    if isinstance(wanted, str):
        wanted = [wanted]
    if wanted:
        keep = {str(w).strip().lower() for w in wanted}
        rules = [r for r in rules if r["file"].lower() in keep or r["file"].lower()[:-3] in keep]
        if not rules:
            return {"ok": False, "pass": False, "error": "no matching rule files", "wanted": sorted(keep)}

    results = []
    for r in rules:
        needle = _norm(r["marker"])
        if not needle:
            results.append({"file": r["file"], "status": "UNKNOWN", "reason": "rule has no marker"})
            continue
        idx = haystack.find(needle)
        if idx < 0:
            results.append({
                "file": r["file"], "status": "MISSING", "marker": r["marker"],
                "evidence": None,
            })
            continue
        lo = max(0, idx - ctx)
        hi = min(len(haystack), idx + len(needle) + ctx)
        results.append({
            "file": r["file"], "status": "PRESENT", "marker": r["marker"],
            "evidence": haystack[lo:hi],
        })

    present = [x["file"] for x in results if x["status"] == "PRESENT"]
    missing = [x["file"] for x in results if x["status"] != "PRESENT"]
    passed = len(present) > 0 and not missing
    return {
        "ok": True,
        "pass": passed,
        "source": src,
        "prompt_chars": len(prompt),
        "rules_dir": directory,
        "checked": len(results),
        "present": present,
        "missing": missing,
        "results": results,
    }


def execute(args, run_id=None, subtool=None):
    """Run ruleaudit.list or ruleaudit.scan. Never raises."""
    args = args or {}
    raw = args.get("action")
    if raw is None:
        raw = subtool
    action = str(raw if raw is not None else "list").strip().lower().replace("ruleaudit.", "").lstrip(".")
    try:
        if action in ("list", "rules", ""):
            return _sub_list(args)
        if action in ("scan", "audit", "check"):
            return _sub_scan(args)
        return {"ok": False, "error": "unknown subtool %r" % action, "valid": ["list", "scan"]}
    except Exception as e:  # noqa: BLE001 — fail-open boundary like every Matrix tool
        return {"ok": False, "error": "%s: %s" % (type(e).__name__, e), "subtool": action}
