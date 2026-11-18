#!/usr/bin/env python3
"""Self-evolving harness — repeated-sequence miner (JAG-133).

First stage of autonomous skill synthesis (Voyager-style, adapted): if the
harness observes that the agent repeats the SAME tool sequence across different
runs, that sequence is a skill candidate. Here it is detected deterministically
and a skill DRAFT is emitted (proposal + `SKILL.md`), without ever executing
anything and without auto-archiving: promotion remains a human decision (or the
sandbox verification cycle, next step).

PURE module: no dependency on the server, unit-testable.
"""
import hashlib
import json
import math
import os
import re
import time

from longrun.util import paths
from longrun.util.fswrite import write_json
from longrun.util.paths import REPO_ROOT as REPO

DEFAULTS = {
    # v656: min_len 2 -> 3. A two-tool "sequence" (`fs.read` then `shell`) is a
    # generic pair, not a skill — it fires on nearly every run and its draft told
    # the operator nothing. The miner now only packs sequences of >= 3 steps.
    "min_len": 3,      # minimum length of the sequence (number of tools)
    "min_count": 3,    # how many different runs must contain the sequence
    "max_len": 6,      # do not look for sequences longer than this
}


# Header every generated check carries. `ensure_check` refreshes such a check
# (it embeds the tool names known at synth time) and never touches a hand-written
# one.
AUTOGEN = "generated automatically (JAG-135)"


def cfg(override=None):
    """Effective config: DEFAULTS+STAGE2 <- tools.yaml (selfevolve) -> override."""
    from longrun.tools.registry import section_config
    return section_config("selfevolve", {**DEFAULTS, **STAGE2_DEFAULTS}, override)


def _ngrams(seq, k):
    return [tuple(seq[i:i + k]) for i in range(len(seq) - k + 1)]


def mine(sequences, c=None, outcomes=None, purposes=None):
    """Find contiguous tool sequences repeated across different runs.

    Args:
        sequences: list of runs; each run is the list of NAMES of the tools used,
            in execution order.
        outcomes: optional, aligned with `sequences`: how each run ended
            ("ok" | "error" | "corrected" | "" for unknown).
        purposes: optional, aligned with `sequences`: what each run was FOR.
    Returns:
        list of {"pattern": [tool,...], "length": k, "support": n, "runs": [idx],
                 "purpose": str, "support_ok": n, "support_bad": n, "unknown": n}
        sorted by (length*support) descending; the longer patterns with the
        same support win over their sub-patterns.

    OCM (2026-11-14): a candidate made only of runs that FAILED is not a
    procedure — it is a description of something that does not work — so it is
    refused here, before a draft exists. A row with no outcome (everything mined
    before this change, and any caller that passes no outcomes at all) counts as
    `unknown` and is never treated as a success, so legacy history can neither
    mint a false success nor be retroactively blocked.
    """
    c = c or cfg()
    mn = max(1, int(c.get("min_len") or 3))
    mc = max(2, int(c.get("min_count") or 3))
    mx = max(mn, int(c.get("max_len") or 6))
    # v716: a pattern is a skill candidate, and a skill can only replay a real
    # tool. Loop pseudo-actions (`batch`, `subagent`, `dispatch`) are dropped here
    # so neither old history nor a direct caller can mint an unverifiable draft.
    known = set(_known_tools())
    raw = list(sequences or [])
    ocs = list(outcomes) if outcomes is not None else [""] * len(raw)
    pps = list(purposes) if purposes is not None else [""] * len(raw)
    if len(ocs) != len(raw):
        ocs = [""] * len(raw)
    if len(pps) != len(raw):
        pps = [""] * len(raw)
    # The run filter and the outcome filter are the SAME pass: `runs` below holds
    # indices into `seqs`, so anything that drops a run must drop its outcome too.
    seqs, kept_ocs, kept_pps = [], [], []
    for s, o, p in zip(raw, ocs, pps):
        clean = [str(x) for x in (s or []) if _dispatchable(x, known)]
        if len(clean) >= mn:
            seqs.append(clean)
            kept_ocs.append(str(o or "").strip().lower())
            kept_pps.append(" ".join(str(p or "").split()))
    found = {}
    for k in range(mn, mx + 1):
        for idx, s in enumerate(seqs):
            for ng in set(_ngrams(s, k)):
                # Junk filter: a single tool repeated (shell,shell,shell)
                # is a loop, not a skill candidate. Skills need at least
                # two DISTINCT tools (read+edit, search+fetch...), and no
                # consecutive duplicate (shell,shell,read is a retry, not a step).
                if len(set(ng)) < 2:
                    continue
                if any(a == b for a, b in zip(ng, ng[1:])):
                    continue
                e = found.setdefault(ng, set())
                e.add(idx)
    cands = [{"pattern": list(ng), "length": len(ng), "support": len(runs),
              "runs": sorted(runs)}
             for ng, runs in found.items() if len(runs) >= mc]
    # prefer the longer patterns: if a pattern extends another with the
    # same set of runs, keep only the longer one (more specific).
    cands.sort(key=lambda d: (d["length"], d["support"]), reverse=True)
    out = []
    for d in cands:
        rs = set(d["runs"])
        if any(set(o["runs"]) == rs and o["length"] > d["length"] for o in out):
            continue
        d["support_ok"] = sum(1 for i in rs if kept_ocs[i] == "ok")
        d["support_bad"] = sum(1 for i in rs if kept_ocs[i] in ("error", "corrected"))
        d["unknown"] = len(rs) - d["support_ok"] - d["support_bad"]
        seen = {}
        for i in sorted(rs):
            if kept_pps[i]:
                seen[kept_pps[i]] = seen.get(kept_pps[i], 0) + 1
        d["purpose"] = max(seen, key=lambda t: (seen[t], t)) if seen else ""
        # OCM: every run we have an outcome for failed -> refuse the candidate.
        if d["support_ok"] == 0 and d["support_bad"] > 0:
            continue
        out.append(d)
    out.sort(key=lambda d: (d["length"] * d["support"], d["support"]), reverse=True)
    return out


def slug(pattern):
    """Filesystem-safe slug for a tool pattern."""
    raw = "-".join(pattern)
    s = re.sub(r"[^a-zA-Z0-9._-]+", "-", raw).strip("-").lower()
    return (s or "skill")[:64]


def draft(pattern, support, out_dir, note="", purpose=""):
    """Write a skill DRAFT (proposal.json + SKILL.md). Executes nothing.

    `purpose` is optional and empty by default: a sequence mined from history has
    none. A caller that already knows what the sequence is for states it here and
    the draft records it (OCM, 2026-11-14) — it is INFORMATION, not a gate: an
    automatic draft installs on the evidence gates alone, and a purpose is never
    required (the attempt to make it one broke five pins and was withdrawn).

    Returns the path of the proposal folder, or None if the write fails.
    """
    name = slug(pattern)
    d = os.path.join(out_dir, name)
    try:
        os.makedirs(d, exist_ok=True)
        proposal = {"kind": "skill", "status": "proposed", "name": name,
                    "pattern": list(pattern), "length": len(pattern),
                    "support": int(support), "created": round(time.time(), 3),
                    "note": note,
                    "purpose": str(purpose or ""),
                    # JAG-426: provenance — a machine-mined proposal is 'auto', so
                    # promote() can enforce the skills/created/ box on it only.
                    "origin": "auto",
                    "next": "verify in sandbox, then archive to skills/created/"}
        write_json(os.path.join(d, "proposal.json"), proposal)
        steps = "\n".join("%d. `%s`" % (i + 1, t) for i, t in enumerate(pattern))
        # v656: the draft must be readable by the operator who finds it in the
        # file tree — what was observed, why it matters, and the exact commands
        # that turn it into a real skill — instead of a two-line stub.
        # OCM: when the runs behind the sequence said what they were FOR, that
        # purpose is the first thing the reader needs, so it leads.
        asks = ("## What it was for\n\n%s\n\n" % str(purpose)
                if str(purpose or "").strip() else "")
        md = ("# Proposed skill: %s\n\n"
              "The harness observed this tool sequence **%d times** across "
              "distinct runs (JAG-133). A repeated sequence is a skill "
              "CANDIDATE.\n\n"
              "%s"
              "## Sequence\n\n%s\n\n"
              "## What it is\n\n"
              "A deterministic pattern of tool calls: `%s`. A draft is "
              "material, not a proposal — it only becomes one when a human or "
              "the agent states WHAT it accomplishes (proposal `content`) and "
              "it passes the sandbox check.\n\n"
              "## How to verify\n\n"
              "1. `improve` (`scope: skill`, `content: <what it does>`) — "
              "write the purpose once someone can state it.\n"
              "2. Verify the draft: `improve` (`action: verify`, "
              "`path: <this folder>`) runs `check.py` in the sandbox.\n"
              "3. Archive: `improve` (`action: promote`, `path: <this "
              "folder>`) moves it to `skills/created/%s/`.\n\n"
              "## Status\n\n"
              "DRAFT — not verified, not archived."
              % (name, support, asks, steps, " → ".join(pattern), name))
        with open(os.path.join(d, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write(md)
        return d
    except OSError:
        return None


def _split_note(cand):
    """One line naming what the runs behind a candidate did (OCM). Empty when
    no run carries an outcome, so a legacy store produces the same note as
    before."""
    ok = int(cand.get("support_ok") or 0)
    bad = int(cand.get("support_bad") or 0)
    unk = int(cand.get("unknown") or 0)
    if not (ok or bad):
        return ""
    return ("runs behind this candidate: %d ok / %d failed / %d unknown"
            % (ok, bad, unk))


def scan(sequences, out_dir, c=None, note="", outcomes=None, purposes=None):
    """Mine the sequences and write a draft per pattern. Returns the paths."""
    c = c or cfg()
    paths = []
    for cand in mine(sequences, c, outcomes=outcomes, purposes=purposes):
        # Self-maintenance: skip drafts that already exist — a re-mine
        # must not re-emit (and re-flood the chat with) the same patterns.
        name = slug(cand["pattern"])
        if os.path.isfile(os.path.join(out_dir, name, "proposal.json")):
            continue
        split = _split_note(cand)
        full = ("%s | %s" % (note, split)) if (note and split) else (note or split)
        p = draft(cand["pattern"], cand["support"], out_dir, note=full,
                  purpose=cand.get("purpose") or "")
        if p:
            paths.append(p)
        # Flood cap: one mine run deposits at most 10 NEW drafts.
        if len(paths) >= 10:
            break
    return paths


def prune_junk(out_dir, c=None):
    """Self-maintenance sweep: delete junk drafts.

    Removes proposal dirs whose pattern is one tool repeated
    (shell-shell-shell, git.run-git.run...), has a consecutive duplicate
    (a retry, not a step) — or is SHORTER than the configured `min_len`
    (v656: the legacy 2-tool backlog, `fs.read-shell` and friends, which is
    a generic pair and told the operator nothing). Returns {"removed": [names]}.
    Never raises.
    """
    import shutil
    removed = []
    try:
        names = os.listdir(out_dir)
    except OSError:
        return {"removed": removed}
    min_len = max(1, int((c or cfg()).get("min_len") or 3))
    known = set(_known_tools())      # one registry read for the whole sweep
    for name in names:
        d = os.path.join(out_dir, name)
        if not os.path.isdir(d):
            continue
        junk = False
        prop = _read_json(os.path.join(d, "proposal.json"))
        pat = (prop or {}).get("pattern") if isinstance(prop, dict) else None
        if isinstance(pat, list) and len(pat) >= 2:
            strs = list(map(str, pat))
            if len(set(strs)) < 2:
                junk = True
            elif any(a == b for a, b in zip(strs, strs[1:])):
                junk = True
            elif len(strs) < min_len:          # v656: below the quality bar
                junk = True
            elif not all(_dispatchable(t, known) for t in strs):
                # v716: a step the harness cannot execute (`batch`, `subagent`)
                # makes the draft unverifiable by construction — the live store
                # held 29 of them. Same policy as the miner's filter.
                junk = True
        elif pat is None:
            # Fallback on the dirname: shell-shell or shell.exec-shell.exec.
            parts = str(name).split("-")
            if len(parts) >= 2 and len(set(parts)) == 1:
                junk = True
            elif len(parts) >= 2 and len(parts) < min_len:
                junk = True
        if junk:
            try:
                shutil.rmtree(d)
                removed.append(name)
            except OSError:
                pass
    return {"removed": removed}


# ------------------------------------------------------------- history -------

def _history_path():
    return os.path.join(paths.DATA_DIR, "sequences.json")


def _dispatchable(name, known=None):
    """True when the harness can actually EXECUTE this name as a tool.

    v716: the loop records its own pseudo-actions (`batch`, `subagent`,
    `dispatch`) next to real tools, so mining produced drafts whose generated
    check can never pass — the live verify answered `unknown tools: batch` for a
    sequence that had just run. A skill can only replay a real tool, so the miner
    and the recorder both ask this one function. `known` is passed when a caller
    checks many names (one registry read).
    """
    n = str(name or "").strip()
    return bool(n) and n in (known if known is not None else set(_known_tools()))


def record(key, tools, path=None, outcome="", purpose=""):
    """Record the tool sequence of a run (for later mining).

    `outcome` is how the RUN ended ("ok" | "error" | "corrected") and `purpose`
    is what the run was FOR (the turn's request). Both are additive: a row
    written before OCM (2026-11-14) reads as unknown, and unknown is never read
    as a success — see `mine()`.

    Keeps the latest 500 runs. Never blocking: a write error is ignored.
    """
    seq = [str(t) for t in (tools or []) if str(t).strip()]
    # v716: only names the harness can replay belong in a sequence — a mined
    # pattern is a skill candidate, and `batch`/`subagent`/`dispatch` are loop
    # actions, not tools (a draft built on them can never verify).
    known = set(_known_tools())
    seq = [t for t in seq if _dispatchable(t, known)]
    if not seq or not key:
        return False
    oc = str(outcome or "").strip().lower()
    pp = " ".join(str(purpose or "").split())[:160]
    p = path or _history_path()
    try:
        data = {}
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                data = json.load(f) or {}
        if not isinstance(data, dict):
            data = {}
        row = {"tools": seq, "ts": round(time.time(), 3)}
        if oc in ("ok", "error", "corrected"):
            row["outcome"] = oc
        if pp:
            row["purpose"] = pp
        data[str(key)] = row
        if len(data) > 500:
            for k in sorted(data, key=lambda x: data[x].get("ts", 0))[:len(data) - 500]:
                data.pop(k, None)
        write_json(p, data)
        return True
    except OSError:
        return False


def history(path=None):
    """The recorded sequences, as a list of lists of tool names.

    Raw on purpose: the recorded rows are data (a UI or a test may want to see
    what actually ran). The FILTER that keeps loop pseudo-actions out of a
    candidate lives where patterns are built (`mine`), so old rows that still
    carry `batch` cannot produce a draft nobody can verify (v716).
    """
    p = path or _history_path()
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f) or {}
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    return [e.get("tools", []) for e in data.values() if isinstance(e, dict)]


FORGE_MARK = "Matrix tool forged from a mined tool sequence"


def history_rows(path=None):
    """The recorded runs WITH their timestamps, outcome and purpose."""
    p = path or _history_path()
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f) or {}
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    return [{"tools": [str(x) for x in (e.get("tools") or [])],
             "ts": float(e.get("ts") or 0),
             "outcome": str(e.get("outcome") or ""),
             "purpose": str(e.get("purpose") or "")}
            for e in data.values() if isinstance(e, dict)]


def history_split(path=None):
    """The store as three aligned lists: tools, outcome, purpose (OCM).

    One owner for the row -> aligned-lists mapping: `mine` needs the outcome of
    the SAME run its sequence came from, so a caller that built the lists itself
    could silently misalign them after a row is dropped.
    """
    rows = history_rows(path)
    return ([r["tools"] for r in rows],
            [r.get("outcome") or "" for r in rows],
            [r.get("purpose") or "" for r in rows])


def _uses(seq, ns):
    """True when one recorded run CALLED the forged tool `ns`."""
    return any(t == ns or t == ns + ".run" or t.startswith(ns + ".") for t in seq)


def forged_usage(path=None, repo_root=None):
    """Did each forged tool get USED after it landed? (arXiv 2610.34938)

    "Harness self-evolution needs ways to establish whether a change helps on later
    tasks and to revise or remove changes that do not": 4 of 12 implemented changes
    in that study reduced nothing. This is the read-only fact for the same question
    here — per forged module, when it was created, how many runs used it, when it
    was last used, and how many runs happened after it existed, so a dead tool is
    visible instead of accumulating. Removal stays an operator action.

    A module counts as forged when its header carries `FORGE_MARK`, so a tool
    forged under a custom name is tracked too (the name is not the marker).
    """
    from longrun.core import matrix as mtx
    try:
        _root, msrc, _mdot = mtx._roots(repo_root)
    except Exception as e:  # noqa: BLE001 — the report must never raise
        return {"ok": False, "error": "matrix roots unavailable: %s" % e,
                "tools": [], "count": 0, "unused": 0}
    tdir = os.path.join(msrc, "tools")
    rows = history_rows(path)
    out = []
    try:
        names = sorted(os.listdir(tdir))
    except OSError:
        names = []
    for fn in names:
        if not fn.endswith(".py") or fn.startswith("_"):
            continue
        p = os.path.join(tdir, fn)
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                head = f.read(600)
        except OSError:
            continue
        if FORGE_MARK not in head:
            continue
        ns = fn[:-3]
        try:
            created = os.stat(p).st_mtime
        except OSError:
            created = 0.0
        used = [r["ts"] for r in rows if _uses(r["tools"], ns)]
        after = len([r for r in rows if r["ts"] >= created])
        verdict = ("used" if used else ("unused" if after else "new"))
        out.append({"namespace": ns, "tool": ns + ".run", "created": created,
                    "uses": len(used),
                    "last_used": max(used) if used else 0.0,
                    "runs_after": after, "verdict": verdict})
    out.sort(key=lambda r: (r["uses"], r["created"]))
    return {"ok": True, "tools": out, "count": len(out),
            "unused": len([r for r in out if r["verdict"] == "unused"])}


def retire_unused(days=14, path=None, repo_root=None, dry_run=False,
                  usage=None, remove=None, now=None):
    """Remove the forged tools nobody called after `days` (arXiv 2610.34938).

    `forged_usage` is the read-only fact; this is the ACTION the study says a
    harness needs ("revise or remove changes that do not help"). The bar is
    deliberately conservative: verdict `unused`, `last_used == 0`, and older than
    `days`. A tool that was ever called is never touched. Removal goes through
    Matrix's own remover (the same path a failed forge takes), so nothing is
    deleted outside its owner.

    `usage` / `remove` / `now` are injectable so a test never needs a Matrix
    layout; production defaults are the real functions.
    """
    rep = (usage or forged_usage)(path=path, repo_root=repo_root)
    if not rep.get("ok"):
        return rep
    cutoff = float(now if now is not None else time.time()) - max(0, int(days or 0)) * 86400
    victims = [t for t in (rep.get("tools") or [])
               if t.get("verdict") == "unused"
               and not t.get("last_used")
               and float(t.get("created") or 0) <= cutoff]
    if remove is None:
        from longrun.core import matrix as mtx

        def remove(ns):
            return mtx.remove("tool", ns, repo_root=repo_root)

    removed = []
    for t in victims:
        ns = str(t.get("namespace") or "")
        if dry_run:
            removed.append({"namespace": ns, "dry_run": True})
            continue
        try:
            res = remove(ns) or {}
        except Exception as e:  # noqa: BLE001 — one stuck removal must not stop the rest
            res = {"ok": False, "error": str(e)}
        removed.append({"namespace": ns, "ok": bool(res.get("ok")),
                        "error": res.get("error")})
    return {"ok": True, "eligible": len(victims), "removed": removed}


def retire_unused_skills(days=None, skills_dir=None, category=None, dry_run=True,
                         now=None, discovery=None, retire=None):
    """Retire the machine-created skills that were NEVER OPENED after `days`.

    `skills.discovery()["never_opened"]` is the read-only fact (the shared
    attribution ledger says which skills were opened); this is the ACTION the
    learning loop was missing. Nothing is deleted: a candidate goes through
    `_retire_skill`, i.e. the folder is moved under
    `skills/_retired/<category>/<name>-<stamp>/` and one append-only line in
    `skills/_retired/ledger.jsonl` records who moved it, when, why and at which
    content digest — a manual restore is always possible. "Never opened" is the
    ONLY criterion: a skill that was ever opened, that lives in another
    category, or that is younger than the bar is never touched.

    `dry_run=True` (the default) reports the candidates and moves nothing.
    `discovery` / `retire` / `now` are injectable so a test needs no ledger.
    """
    from longrun.memory import skills as skills_mod
    c = cfg()
    category = str(category or c.get("category") or "created")
    try:
        days = int(c.get("retire_days") if days is None else days)
    except (TypeError, ValueError):
        days = int(STAGE2_DEFAULTS["retire_days"])
    days = max(0, days)
    cutoff = float(now if now is not None else time.time()) - days * 86400
    root = skills_dir or skills_mod.SKILLS_DIR
    discovery_fn = discovery or skills_mod.discovery
    retire_fn = retire or _retire_skill
    try:
        never = set((discovery_fn() or {}).get("never_opened") or [])
    except Exception as e:  # noqa: BLE001 — a broken ledger must not crash the loop
        return {"ok": False, "error": str(e)}
    candidates = []
    for s in skills_mod.list_skills(reload=True):
        name = str(s.get("name") or "")
        if not name or name not in never or s.get("category") != category:
            continue
        try:
            mtime = os.stat(s["abspath"]).st_mtime
        except (OSError, KeyError, TypeError):
            continue
        if mtime <= cutoff:
            candidates.append(s)
    removed = []
    if not dry_run:
        for s in candidates:
            try:
                res = retire_fn(os.path.dirname(s["abspath"]), root, category,
                                s["name"], by="selfevolve.retire_unused_skills",
                                reason="never opened in %d days" % days) or {}
            except Exception as e:  # noqa: BLE001 — one stuck skill must not stop the rest
                res = {"ok": False, "error": str(e)}
            row = {"name": s["name"], "ok": bool(res.get("ok"))}
            row["retired_to" if res.get("ok") else "error"] = (
                res.get("retired_to") if res.get("ok")
                else (res.get("error") or "unknown error"))
            removed.append(row)
            # The same changelog hole as `promote` (measured 2026-11-14): the
            # skills library has its own `_retired/ledger.jsonl`, but the operator's
            # improvement ledger — the one place that answers "what did the machine
            # change on its own?" — showed nothing when the loop retired a skill.
            if res.get("ok"):
                try:
                    from longrun.util import improve as _imp
                    _imp.ledger_add("retire", origin="selfevolve", artifact_kind="skill",
                                    name=s["name"], category=category,
                                    path=res.get("retired_to"),
                                    reason=("never opened in %d days" % days))
                except Exception:  # noqa: BLE001 — the audit must never break the loop
                    pass
    return {"ok": True, "eligible": len(candidates), "days": days,
            "category": category, "dry_run": bool(dry_run),
            "candidates": [s["name"] for s in candidates], "removed": removed}


def error_class(text):
    """Normalize an error line into a stable CLASS (paths and numbers abstract).

    "no such file: /a" and "no such file: /b" are the same failure; only the
    argument differs. Without this every occurrence is its own class and the
    ranking says nothing.

    Public since 2026-11-14 (HD-2): `util/runtree` names a failure onset with the
    SAME class this module ranks failures by — two normalizers would be two
    truths.
    """
    s = " ".join(str(text or "").split())[:140]
    s = re.sub(r"/[^\s,;:]+", "<path>", s)
    s = re.sub(r"\b\d+\b", "<n>", s)
    return s[:80] or "(no error text)"


#: Lines that NAME a failure even when the program printed other things first.
#: Round 53 measured the cost of not looking: 12 of the 18 `shell.exec ·
#: tool-error` classes were singleton heads of ordinary output (`dill 0.4.1`, a
#: key list, `aria=…`), because the class was the first 140 chars of the result.
_ERROR_MARKERS = ("fatal:", "no such file", "not found", "permission denied",
                  "illegal option", "syntaxerror", "command not found",
                  "cannot find module")

#: `error:` / `exception:` only as a STANDALONE word: `except ImportError:` is a
#: source line, not an error line, and a letter before it means an identifier.
_ERROR_WORD = re.compile(r"(?<![A-Za-z])(error|exception)\s*:", re.I)


def failure_text(card):
    """The text that NAMES a failed call's failure (round 53).

    Precedence: `error`, then `stderr`, then the line carrying a failure marker
    (a Traceback contributes its EXCEPTION line — stack frames are indented and
    the exception is the first unindented line after them), then
    `exit=<n> (no error text)` when a non-zero code exists, then the first output
    line, then "". Machine text is returned unchanged; `error_class` still
    normalizes it.

    ONE helper for both corpora and for the recorder (`harness/record.py`), so a
    session card and its run-record step always land in the same class — which is
    also what the round-52 dedupe needs.
    """
    card = card if isinstance(card, dict) else {}
    for field in ("error", "stderr"):
        text = str(card.get(field) or "").strip()
        if text:
            return text
    body = str(card.get("result") or "")
    raw = body.splitlines()
    for i, line in enumerate(raw):
        low = line.strip().lower()
        if not low:
            continue
        if "traceback (most recent call last)" in low:
            for nxt in raw[i + 1:]:
                s = nxt.strip()
                if s and not nxt[:1].isspace():
                    return s
            return line.strip()
        if any(m in low for m in _ERROR_MARKERS) or _ERROR_WORD.search(line):
            return line.strip()
    ec = card.get("exit_code")
    if isinstance(ec, int) and ec:
        return "exit=%d (no error text)" % ec
    for line in raw:
        if line.strip():
            return line.strip()
    return ""


#: Deterministic LABELS over the class `error_class` already computes. They group
#: classes into an engineering issue (Signals, arXiv:2611.04507) without a second
#: grouping key: the class stays the identity of a row, the family names the fix.
FAILURE_FAMILIES = (
    ("permission", ("denied", "permission", "hard-deny", "not permitted",
                    "refused", "protected")),
    # Round 24: the GATE doing its job is not a fault. Measured 2026-11-18: 6 of
    # the 24 "shell.exec tool-error" failures were the plan gate refusing — a
    # policy answer that a repair cannot fix. Round 32 adds "approval expired":
    # an expired approval card is a GATE answer (the operator must re-approve),
    # measured 2026-11-18 in two `fs.write` cards.
    ("gate", ("plan mode", "unapproved plan", "waiting for approval",
              "approval required", "requires approval", "needs approval",
              "awaiting approval", "approval pending", "approval expired")),
    ("timeout", ("timeout", "timed out", "exit 124")),
    ("missing-argument", ("missing required argument", "required:")),
    ("not-found", ("no such file", "not found", "does not exist")),
    ("syntax", ("traceback", "syntaxerror", "illegal option", "unexpected token",
                "cannot find module")),
    ("no-change", ("changed nothing", "no steps received")),
)

#: The ONE remediation and the check that would prove it per family. `check` names
#: a test id only when one exists; None means "no check yet", never an invented id.
#:
#: Round 45: two families were uncovered while a test already proved their answer
#: — `timeout` (v1094 A–C/F pin the `background: true` + `action=status` hint and
#: the remedy that says the same thing) and `gate` (v1093 pins that a plan-gate
#: refusal is classified `gate`, capped at `warning`, and never ranked as a real
#: fault — the register's own answer to the family). Measured before: 15 of 37
#: issues named a proving test.
#:
#: Round 46: `not-found`'s remedy ("confirm the path first") is now paid for by
#: the harness — a missing `fs.read`/`fs.edit` target names the names that DO
#: exist near it — so v1114 can prove the family instead of leaving it a label.
#:
#: Round 47: the last two catch-alls were catch-alls because nobody had checked,
#: not because no test proves them. v523 pins exactly what both remedies rest on —
#: "a failed run still shows partial stdout and stderr" plus the verdict line and
#: the error text of a semantic failure — so `nonzero-exit` ("read stderr") and
#: `tool-error` ("read the error text") name it. `no-change` is the one family
#: with no proving test; it stays None.
#:
#: Round 48: that last one was not missing either — v748 F1/F2 pin that an empty
#: step list is REFUSED and that the refusal names `steps`, which is exactly the
#: family's remedy ("send the real steps in the update"). Every family now names
#: a test; the number means "the remedy is pinned", never "the issue is fixed".
FAMILY_FIX = {
    "timeout": ("start long work with background=true and poll with action=status",
                "v1094"),
    "missing-argument": ("re-read the tool's schema; the required key is named there", "v510"),
    "not-found": ("confirm the path first (workspace list / sessions tree)", "v1114"),
    "syntax": ("write the script with fs.write, then run the FILE (no heredoc)", "v747"),
    "no-change": ("send the real steps in the update", "v748"),
    "permission": ("the policy denies it; use the allowed read path", "v1075"),
    "gate": ("this is a GATE, not a fault: in plan mode only read-only tools run — "
             "propose the plan, then call the tool", "v1093"),
    "nonzero-exit": ("read stderr in the observation and correct the command", "v523"),
    "tool-error": ("read the error text and fix the argument", "v523"),
}


#: Families whose needles are specific enough to search the WHOLE error text.
#: Measured 2026-11-18: "timeout" also lives inside a tool's schema listing
#: (`Arg types: {'command': str, 'timeout_secs': int}`) and pulled 19
#: missing-argument failures into `timeout` — so a generic needle reads the class
#: head only, and only these read past it.
#:
#: Round 27 (Trial by Trace, arXiv:2610.32285 — failure attribution): the harness
#: writes SOME tool errors as `[tool] exit=<n> ok=False backend=… \nERROR: <tool>:
#: missing REQUIRED argument…`. The head then says `exit=` and the register filed
#: the same argument-contract failure under `nonzero-exit` — measured 2026-11-18:
#: 14 of 26 "missing REQUIRED argument" cards (10 shell.exec, 2 fs.read, 2
#: web.search) were attributed to the wrong family, where the remedy is "read
#: stderr" instead of "re-read the schema". The wrapper prefix is not the cause.
#:
#: Round 32 (AgentDebugX, arXiv:2607.18754 — the RECOVER axis): the classes that
#: never recover are policy REFUSALS, and the prefixed shape hid them too —
#: `[sessions.read] exit=<n> … ERROR: read refused…` lost the word at the 80-char
#: cut, so a wall was filed as breakage. The tail reads only phrases a refusal
#: really carries; `permission` joins the tail families for that reason.
TAIL_FAMILIES = ("gate", "missing-argument", "permission")

#: A tail search stays narrower than the head search where the head needle is
#: broader than safe for a whole text (`required:` appears in every schema dump;
#: `permission`/`refused` are common words).
TAIL_OVERRIDES = {
    "missing-argument": ("missing required argument", "unknown argument"),
    "permission": ("read refused", "not authorized", "cannot message itself",
                   "not a coordinator"),
}


#: Families where the harness answered a POLICY question, not a fault. Round 24
#: put `gate` here for the severity; round 32 measured the never-recovered
#: residue over the live store and found the same shape everywhere: the classes
#: with `recovery_rate 0.0` are `fs.write · gate` (approval expired), `sessions.read
#: · permission` ("read refused: a session cannot message itself"), `fs.edit ·
#: permission` (a protected nucleus), `job.get` ("not a coordinator"),
#: `webui.inspect` ("not authorized"). A later success from the SAME tool is not
#: the proof that a refusal was fixed — who must act is named by the family.
REFUSAL_FAMILIES = ("gate", "permission")


def is_refusal(family):
    """True when the family is a policy ANSWER (the consumer must not read it as breakage)."""
    return str(family or "") in REFUSAL_FAMILIES


def failure_family(tool, head, text=None):
    """The family label of one class.

    The class head is the identity and the first place the family is read. When
    the caller has the raw text, the families in `TAIL_FAMILIES` may also match
    past the 80-char head — a plan-gate refusal or an argument-contract error can
    begin with the harness's `[shell.exec] exit=<n> …` prefix, which says nothing
    about the cause.
    """
    s = str(head or "").lower()
    for name, needles in FAILURE_FAMILIES:
        if any(n in s for n in needles):
            return name
    tail = str(text or "").lower()[:400]
    if tail:
        for name, needles in FAILURE_FAMILIES:
            if name in TAIL_FAMILIES and any(
                    n in tail for n in TAIL_OVERRIDES.get(name, needles)):
                return name
    return "nonzero-exit" if "exit=" in s else "tool-error"


def _severity(count, sessions):
    """The diagnostics vocabulary (error/warning/info), from reach and volume."""
    if sessions >= 3 or count >= 10:
        return "error"
    if sessions >= 2 or count >= 3:
        return "warning"
    return "info"


#: Round 26 (Trial by Trace, arXiv:2610.32285). A class the agent RETRIES in the
#: same shape is telling the register that the remedy it names did not land, so a
#: high retry share lifts the severity one step (never past the gate cap). The
#: thresholds are deliberately blunt: three or more retries is not one accident,
#: and a third of the class repeating in place is a pattern.
RETRY_ESCALATE = 0.34
RETRY_MIN = 3


def retry_signal(repeats, count):
    """The share of a class' failures the agent retried in the same shape."""
    try:
        n, c = int(repeats or 0), int(count or 0)
    except (TypeError, ValueError):
        return 0.0
    return round(float(n) / c, 3) if c > 0 else 0.0


def severity_for(family, count, sessions, repeats=0):
    """The label a row really gets: a GATE refusal is never `error`.

    Round 24. `_severity` ranks BREAKAGE; a gate refusal is the policy doing its
    job (measured 2026-11-18: 6 of the 24 `shell.exec tool-error` failures were
    the plan gate). It stays a `warning` — the agent kept trying — but it must
    not outrank a real fault, because the repair drafts follow the severity.

    Round 26 adds the retry lift: a class the agent keeps re-hitting at the same
    shape is worse than its raw count says, because the hint beside it did not
    land. One step only, and the gate cap still wins.

    Round 32 measured that `permission` is a refusal too (`REFUSAL_FAMILIES`), yet
    the cap stays gate-only ON PURPOSE: a gate fires while a turn is legitimately
    read-only, whereas 17 `shell.exec · permission` denials across sessions say the
    agents' model of the policy is wrong — a guidance defect that must outrank a
    single gate answer. Changing this needs its own measurement, not the label.
    """
    sev = _severity(count, sessions)
    if (family != "gate" and int(repeats or 0) >= RETRY_MIN
            and retry_signal(repeats, count) >= RETRY_ESCALATE):
        sev = {"info": "warning", "warning": "error"}.get(sev, sev)
    return "warning" if (family == "gate" and sev == "error") else sev


def _since_epoch(value):
    """A window bound as an epoch, or None for "all time".

    Round 28. Accepts an epoch (int/float/numeric string) or an ISO date/time
    (`YYYY-MM-DD`, `YYYY-MM-DDTHH:MM`, `YYYY-MM-DD HH:MM[:SS]`, local time).
    Anything else is "all time": a read of the register is never refused because
    of a lenient query — the answer always states the window it used.
    """
    if value is None or value == "" or value == 0 or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    try:
        return float(s)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return time.mktime(time.strptime(s, fmt))
        except ValueError:
            continue
    return None


def _agents_index():
    """session id → {id, name, role} from the org chart's own reader.

    Round 37 (Who&When Pro, arXiv:2607.09996 — attribution has a WHO axis). The
    register named the tool and the family; measured 2026-11-18 over the live store,
    158 failed cards belong to **37 different agents** (A11 30, A61 21, A54 15 …)
    and the biggest row (`shell.exec · missing-argument` 21) spans four of them, so
    "3 sessions" was the only reachable answer to "whose?". `agents.REGISTRY.list()`
    owns that mapping; a missing store answers `{}` and nothing is invented.
    """
    try:
        from longrun.agent import agents as _ag
        got = _ag.REGISTRY.list() or []
    except Exception:  # noqa: BLE001 — attribution is never worth a crash
        return {}
    # `REGISTRY.list()` answers `{"agents": [...], "seq": N, "count": N}`; a
    # helper that assumed a bare list attributed nothing (measured 2026-11-18:
    # every row's `who` was empty until this unwrap). Accept both shapes.
    rows = got.get("agents") if isinstance(got, dict) else got
    out = {}
    for a in rows or []:
        if not isinstance(a, dict):
            continue
        sid = str(a.get("session") or "")
        if sid:
            out[sid] = {"id": str(a.get("id") or ""), "name": str(a.get("name") or ""),
                        "role": str(a.get("role") or "")}
    return out


def _top_agents(counter, n=3):
    """The named agents behind a class or an issue, most failures first."""
    items = sorted((counter or {}).items(), key=lambda kv: (-kv[1], kv[0][0]))[:n]
    return [{"id": a[0], "name": a[1], "role": a[2], "count": c} for a, c in items]


def session_failures(sessions_dir=None, limit=200, max_sessions=400, since=None):
    """Rank failure classes from the LIVE session cards — the traces agents made.

    `failure_candidates` read only the harness run records: measured 2026-11-18,
    **4** records against **2704** cards / **155** failures in 138 sessions, so the
    ranking saw a few percent of the evidence. This is the same (tool, class)
    grouping over the store the agent itself writes, newest sessions first.

    `since` is the window (session-file mtime): a class fixed in code stays at the
    top of an all-time read forever, so the post-adoption question — "is this
    still happening?" — needs a bound. The answer carries the epoch it used.
    """
    from longrun.util import runtree
    root = sessions_dir or paths.SESSIONS_DIR
    since_ts = _since_epoch(since)
    try:
        entries = []
        for e in os.scandir(root):
            if not e.name.endswith(".json"):
                continue
            try:
                mt = e.stat().st_mtime
            except OSError:
                continue
            if since_ts is None or mt >= since_ts:
                entries.append(e)
    except OSError:
        return {"ok": True, "classes": [], "sessions": 0, "since": since_ts}
    entries.sort(key=lambda e: e.stat().st_mtime, reverse=True)
    entries = entries[:max(1, int(max_sessions or 400))]
    buckets, scanned = {}, 0
    who_by_sid = _agents_index()
    for ent in entries:
        sess = _read_json(ent.path)
        if not isinstance(sess, dict):
            continue
        scanned += 1
        who = who_by_sid.get(ent.name[:-5])
        cards = [c for c in (sess.get("tool_cards") or []) if isinstance(c, dict)]
        # Round 26 (Trial by Trace, arXiv:2610.32285): a failure the agent RETRIES
        # in the same shape is a reliability signal, not noise. Measured 2026-11-18:
        # 19 of 155 failed cards (12.3 %) were followed by the SAME class within
        # three tool calls — the hint did not land.
        seq = []
        for c in cards:
            if not runtree.failed(c):
                seq.append(None)
                continue
            tool = str(c.get("tool") or "?")
            # Round 53: the class is the text that NAMES the failure, not the
            # first line the program printed (`failure_text`).
            head = error_class(failure_text(c))
            seq.append((tool, head))
        # Round 31 (AgentDebugX, arXiv:2607.18754 — Detect/Attribute/RECOVER/Rerun):
        # "the step where an error surfaces is often not the one that caused it".
        # The register counted every failed card as breakage; measured 2026-11-18,
        # 111 of 158 (70 %) are followed by a SUCCESS of the same tool in the same
        # stage — the agent recovered, and the class is a stumble, not a break.
        # The rule is the trace tree's own (`runtree.onset`: same tool, same node);
        # the run-record corpus has no order and therefore no recovery claim.
        last_ok = {}
        for j, c in enumerate(cards):
            if not runtree.failed(c):
                last_ok[(str(c.get("tool") or "?"), c.get("node"))] = j
        for i, (card, key) in enumerate(zip(cards, seq)):
            if not key:
                continue
            tool, head = key
            row = buckets.setdefault((tool, head),
                                     {"count": 0, "repeats": 0, "recovered": 0,
                                      "sessions": set(), "samples": [], "probe": "",
                                      "agents": {}, "keys": set()})
            row["count"] += 1
            row["sessions"].add(ent.name[:-5])
            # Round 52: the event's identity, so the run-record corpus can tell
            # that its copy of this call is the SAME failure. Measured 2026-11-18:
            # run `caef726a6faa` has 25 failed steps and 25 failed cards, all 25
            # matching on (session, ts, tool). A card without a clock adds no
            # key — a guess is worse than a count.
            if card.get("ts"):
                try:
                    row["keys"].add("%s@%.3f" % (ent.name[:-5],
                                                 float(card["ts"])))
                except (TypeError, ValueError):
                    pass
            # Round 37: the WHO axis. A card whose session has no agent row adds
            # nothing — an unknown session is not attributed to a guess.
            if who and who.get("id"):
                akey = (who["id"], who["name"], who["role"])
                row["agents"][akey] = row["agents"].get(akey, 0) + 1
            if any(k == key for k in seq[i + 1:i + 4]):
                row["repeats"] += 1
            if last_ok.get((tool, card.get("node")), -1) > i:
                row["recovered"] += 1
            if not row["probe"]:
                row["probe"] = str(card.get("error") or card.get("result") or "")[:400]
            if len(row["samples"]) < 2:
                row["samples"].append(
                    str(card.get("error") or card.get("result") or "")[:160])
    rows = [{"tool": t, "error": e, "count": v["count"], "repeats": v["repeats"],
             "recovered": v["recovered"],
             "sessions": len(v["sessions"]), "samples": v["samples"],
             # Round 38: the class carries WHICH sessions, not only how many. An
             # issue sums several classes, and `max` over their counts is not the
             # number of sessions the issue reaches (`shell · tool-error` read
             # "32 in 1 session" with 16 of 32 belonging to one agent). The ids
             # stay in this row for the merge; `_issues_from` pops them so no
             # emitted row carries the list back out.
             "session_ids": sorted(v["sessions"]),
             # Round 52: the event keys stay internal (the merge pops them); the
             # run-record corpus uses them to avoid counting a call twice.
             "event_keys": sorted(v["keys"]),
             "probe": v.get("probe") or "",
             "agents": _top_agents(v["agents"])}
            for (t, e), v in buckets.items()]
    rows.sort(key=lambda r: (-r["count"], r["tool"], r["error"]))
    return {"ok": True, "classes": rows[:max(1, int(limit or 200))],
            "sessions": scanned, "since": since_ts}


def failure_candidates(path=None, limit=10, min_count=1, include_sessions=False,
                       sessions_dir=None, max_sessions=400, since=None):
    """Rank failure CLASSES from the durable run records (AHE 2604.25850).

    `mine()` only sees habits: a tool sequence repeated `min_count` times. A
    failure that happens ONCE is invisible to it, which is exactly the case the
    observability-driven literature edits from. This reads the harness run
    records (`harness/record.py` steps already carry `tool`, `ok`, `error`) and
    groups failed steps by (tool, normalized error head), so the next draft can
    target a real failure instead of a coincidence.

    `include_sessions=True` merges the LIVE session tool cards into the same
    (tool, class) buckets — the same grouping, one predicate (`runtune.failed`),
    a second corpus. Measured 2026-11-18: 4 harness records vs 2704 session cards
    (155 failures in 138 sessions), so the records alone are a few percent of the
    evidence. The flag is explicit because a test that pins record counts must
    not start reading an operator's store.

    `since` bounds BOTH corpora by the file's mtime (see `session_failures`): the
    post-adoption read needs a date, because an all-time ranking never tells a
    reader whether the fix landed. The answer carries the epoch it used.

    Every row is LABELLED (`family`, `severity`, `action`, `check`) and the rows
    are also grouped into `issues` — one engineering issue per (tool, family),
    with the classes that support it (Signals, arXiv:2611.04507). Data only:
    turning an issue into a draft is still a model/operator decision.
    """
    from longrun.harness import record as rec_mod
    root = os.path.join(path or rec_mod.dir_path(), "runs")
    since_ts = _since_epoch(since)
    try:
        names = sorted(os.listdir(root))[:1000]
    except OSError:
        names = []
    buckets = {}
    runs = 0
    for fn in names:
        if not fn.endswith(".json"):
            continue
        if since_ts is not None:
            try:
                if os.path.getmtime(os.path.join(root, fn)) < since_ts:
                    continue
            except OSError:
                continue
        rec = _read_json(os.path.join(root, fn))
        if not isinstance(rec, dict):
            continue
        runs += 1
        for step in rec.get("steps") or []:
            if not isinstance(step, dict) or step.get("ok") is not False:
                continue
            tool = str(step.get("tool") or "?")
            # Round 53: the same helper as the session corpus. A record written
            # before this round can still hold the raw `result` in `error`
            # (round 49's fallback), so the marker search applies here too.
            head = error_class(failure_text(step))
            row = buckets.setdefault((tool, head), {"count": 0, "repeats": 0,
                                                    "recovered": 0, "runs": set(),
                                                    "sessions": 0, "sids": set(),
                                                    "from_sessions": 0, "from_runs": 0,
                                                    "samples": [], "probe": "",
                                                    "agents": {}, "run_keys": set(),
                                                    "overlap": 0})
            row["count"] += 1
            row["from_runs"] += 1
            row["runs"].add(fn[:-5])
            # Round 52: a record is built FROM a session, so a call it holds can
            # also be a session card. The key is (session, ts, tool) under the
            # same class; the session corpus carries the same key.
            if step.get("ts"):
                try:
                    row["run_keys"].add("%s@%.3f" % (
                        str(rec.get("session_id") or fn[:-5]),
                        float(step["ts"])))
                except (TypeError, ValueError):
                    pass
            if not row["probe"]:
                row["probe"] = str(step.get("error") or "")[:400]
    scanned = 0
    if include_sessions:
        live = session_failures(sessions_dir=sessions_dir, max_sessions=max_sessions,
                               since=since_ts)
        scanned = int(live.get("sessions") or 0)
        for cls in live.get("classes") or []:
            key = (str(cls.get("tool") or "?"), str(cls.get("error") or ""))
            row = buckets.setdefault(key, {"count": 0, "repeats": 0,
                                           "recovered": 0, "runs": set(),
                                           "sessions": 0, "sids": set(),
                                           "from_sessions": 0, "from_runs": 0,
                                           "samples": [], "probe": "",
                                           "agents": {}, "run_keys": set(),
                                           "overlap": 0})
            # Round 52: the same call seen by both corpora is ONE failure. The
            # run count is already in `count`; the session's copy of a matching
            # event is subtracted, and the event is attributed to the SESSION
            # (the live observation), so `from_sessions + from_runs == count`
            # still holds. Measured 2026-11-18: `shell · tool-error` read 32
            # failures / 16 unresolved, all 16 calls recorded twice.
            seen_session = int(cls.get("count") or 0)
            matched = len(set(cls.get("event_keys") or []) & row["run_keys"])
            row["count"] += seen_session - matched
            row["from_sessions"] += seen_session
            row["from_runs"] -= matched
            row["overlap"] += matched
            row["repeats"] += int(cls.get("repeats") or 0)
            row["recovered"] += int(cls.get("recovered") or 0)
            row["sids"].update(cls.get("session_ids") or [])
            # Round 37: the session corpus is the only one with a WHO; a
            # run-record-only row names nobody instead of guessing.
            for a in (cls.get("agents") or []):
                if not isinstance(a, dict) or not a.get("id"):
                    continue
                akey = (str(a.get("id")), str(a.get("name") or ""),
                        str(a.get("role") or ""))
                row["agents"][akey] = (row["agents"].get(akey, 0)
                                       + int(a.get("count") or 0))
            row["samples"] = (row["samples"] + list(cls.get("samples") or []))[:2]
            if not row["probe"]:
                row["probe"] = str(cls.get("probe") or "")[:400]
    rows = []
    for (tool, head), v in buckets.items():
        in_runs = bool(v["runs"])
        in_sessions = bool(v["sids"]) or bool(v["sessions"])
        family = failure_family(tool, head, v.get("probe"))
        action, check = FAMILY_FIX.get(family, FAMILY_FIX["tool-error"])
        rows.append({"id": "fail-%s-%s-%s" % (
                         re.sub(r"[^a-z0-9]+", "-", tool.lower()).strip("-") or "tool",
                         family, hashlib.sha1(head.encode("utf-8")).hexdigest()[:6]),
                     "tool": tool, "error": head, "count": v["count"],
                     # Round 38: the two corpora count DIFFERENT units (session
                     # tool cards vs run-record steps), so the split travels with
                     # the total instead of hiding behind one number.
                     "from_sessions": int(v.get("from_sessions") or 0),
                     "from_runs": int(v.get("from_runs") or 0),
                     # Round 52: how many of the counted events BOTH corpora saw.
                     # `from_sessions + from_runs == count`, and this number says
                     # how much the run record duplicated.
                     "overlap": int(v.get("overlap") or 0),
                     "repeats": v.get("repeats", 0),
                     "retry_rate": retry_signal(v.get("repeats", 0), v["count"]),
                     "recovered": v.get("recovered", 0),
                     # Round 43: the same measure the issue and its class list use.
                     "unresolved": (int(v["count"] or 0)
                                    - int(v.get("recovered") or 0)),
                     # None = the corpus cannot see order (run records only);
                     # 0.0 is a measured "never recovered".
                     "recovery_rate": (None if not in_sessions else
                                       retry_signal(v.get("recovered", 0), v["count"])),
                     "runs": len(v["runs"]),
                     # Round 38: the session corpus knows WHICH sessions; a
                     # runs-only class keeps its 0 and says nothing else.
                     "sessions": (len(v["sids"]) if v["sids"] else v["sessions"]),
                     "session_ids": sorted(v["sids"]),
                     "source": ("both" if in_runs and in_sessions else
                                "sessions" if in_sessions else "runs"),
                     "family": family,
                     "severity": severity_for(family, v["count"], v["sessions"],
                                              v.get("repeats", 0)),
                     "action": action, "check": check,
                     "agents": _top_agents(v.get("agents")),
                     "samples": v["samples"]})
    rows.sort(key=lambda r: (-r["count"], r["tool"], r["error"]))
    rows = [r for r in rows if r["count"] >= max(1, int(min_count or 1))]
    issues = _issues_from(rows)
    # Round 44: a fix is only provable where a check exists. Measured 2026-11-18:
    # 22 of 37 live issues name no test, including 5 of the top 8 — the register
    # must say so instead of letting a draft read as if the proof exists.
    with_check = sum(1 for i in issues if i.get("check"))
    return {"ok": True, "classes": rows[:max(1, int(limit or 10))],
            "issues": issues[:max(1, int(limit or 10))],
            "checks": {"with_check": with_check,
                       "without_check": len(issues) - with_check,
                       "total": len(issues)},
            "runs": runs, "sessions": scanned, "since": since_ts}


def _issues_from(rows):
    """Group classes into one issue per (tool, family), most severe first."""
    grouped = {}
    for r in rows:
        key = (r["tool"], r["family"])
        g = grouped.setdefault(key, {"tool": r["tool"], "family": r["family"],
                                     "count": 0, "repeats": 0, "recovered": 0,
                                     "sessions": 0, "runs": 0, "classes": [],
                                     "source": set(), "samples": [], "agents": {},
                                     "sids": set(), "from_sessions": 0, "from_runs": 0})
        g["count"] += int(r["count"] or 0)
        g["from_sessions"] += int(r.get("from_sessions") or 0)
        g["from_runs"] += int(r.get("from_runs") or 0)
        g["repeats"] += int(r.get("repeats") or 0)
        g["recovered"] += int(r.get("recovered") or 0)
        # Round 38: an issue's reach is the UNION of its classes' sessions, not
        # the largest class's count. Measured 2026-11-18: `shell · tool-error`
        # said "32 in 1 session(s)" while its classes came from several sessions.
        # The ids are POPPED so no emitted row carries the list back out.
        g["sids"].update(r.pop("session_ids", None) or [])
        g["sessions"] = max(g["sessions"], int(r["sessions"] or 0))
        g["runs"] = max(g["runs"], int(r["runs"] or 0))
        # Round 37: the WHO sums across the classes of one issue — "shell.exec ·
        # missing-argument" is the same remedy whoever hit it.
        for a in (r.get("agents") or []):
            if not isinstance(a, dict) or not a.get("id"):
                continue
            akey = (str(a.get("id")), str(a.get("name") or ""), str(a.get("role") or ""))
            g["agents"][akey] = g["agents"].get(akey, 0) + int(a.get("count") or 0)
        g["source"].add(r["source"])
        for s in (r.get("samples") or [])[:2]:
            if len(g["samples"]) < 2 and s not in g["samples"]:
                g["samples"].append(s)
        g["classes"].append({"error": r["error"], "count": r["count"],
                             "from_sessions": int(r.get("from_sessions") or 0),
                             "from_runs": int(r.get("from_runs") or 0),
                             # Round 52: the class-level evidence that a record
                             # duplicated a live call survives into the issue.
                             "overlap": int(r.get("overlap") or 0),
                             "repeats": int(r.get("repeats") or 0),
                             "recovered": int(r.get("recovered") or 0),
                             # Round 43: the measure the class order uses, one
                             # level below the issue's own.
                             "unresolved": (int(r["count"] or 0)
                                            - int(r.get("recovered") or 0))})
    out = []
    for (tool, family), g in grouped.items():
        # Round 43: the classes of an issue are ordered by what did NOT recover,
        # the same measure as the issues themselves. Measured 2026-11-18:
        # `shell.exec · missing-argument` listed its 10-card fully-recovered class
        # (0 unresolved) above a 1-card class that never recovered, and `REPAIR.md`
        # copied that order as "What fails".
        g["classes"] = sorted(g["classes"],
                              key=lambda c: (-c["unresolved"], -c["count"],
                                             c["error"]))[:3]
        # Round 38: the reach is the union of the classes' sessions; a runs-only
        # issue has no ids and keeps the (zero) count it always had.
        reach = len(g["sids"]) if g["sids"] else g["sessions"]
        action, check = FAMILY_FIX.get(family, FAMILY_FIX["tool-error"])
        out.append({"id": "fail-%s-%s" % (
                        re.sub(r"[^a-z0-9]+", "-", tool.lower()).strip("-") or "tool",
                        family),
                    "tool": tool, "family": family,
                    "severity": severity_for(g["family"], g["count"], reach,
                                             g["repeats"]),
                    "count": g["count"], "sessions": reach,
                    # Round 38: the split, so a mixed row never reads as if all
                    # its failures were session cards.
                    "from_sessions": g["from_sessions"],
                    "from_runs": g["from_runs"],
                    "repeats": g["repeats"],
                    "retry_rate": retry_signal(g["repeats"], g["count"]),
                    "recovered": g["recovered"],
                    # None = no session corpus in this read (runs only).
                    "recovery_rate": (None if not reach else
                                      retry_signal(g["recovered"], g["count"])),
                    # Round 32: one predicate, not a `family in (...)` test at every
                    # consumer — the register and the renderers must agree.
                    "refusal": is_refusal(g["family"]),
                    "runs": g["runs"],
                    "source": ("both" if "both" in g["source"] else
                               "sessions" if "sessions" in g["source"] else "runs"),
                    "classes": g["classes"], "samples": g["samples"],
                    "agents": _top_agents(g["agents"]),
                    # Round 41: the number the ranking uses, stated in the row.
                    # `recovered` is 0 for a runs-only row — the corpus cannot
                    # see recovery, so nothing is credited as if it had.
                    "unresolved": int(g["count"]) - int(g["recovered"]),
                    "action": action, "check": check})
    # Round 41 (AgentDebugX 2607.18754, RECOVER — and round 31's own data):
    # severity first, then what did NOT recover. Measured 2026-11-18 live:
    # `shell.exec · timeout` had 10 of 10 recovered and sat 6th, while
    # `shell.exec · permission` with 7 unresolved sat 4th; unresolved-first moves
    # 33 of 37 positions, all within a severity. A fully recovered class is a
    # stumble (round 31), so it does not outrank a class that keeps failing.
    out.sort(key=lambda i: (_SEV_RANK.get(i["severity"], 3),
                            -int(i.get("unresolved") or 0),
                            -i["count"], i["tool"], i["family"]))
    return out


#: The one ordering of the severity labels (a filter and the sort share it).
_SEV_RANK = {"error": 0, "warning": 1, "info": 2}


def _repair_md(prop):
    """The human/agent-readable body of a repair draft (no invented content)."""
    rows = "\n".join(
        "- `%s` × %s%s" % (c.get("error"), c.get("count"),
                           (" (%s retried in the same shape)" % c["repeats"])
                           if c.get("repeats") else "")
        for c in (prop.get("classes") or []))
    samples = "\n".join("  - %s" % s for s in (prop.get("samples") or []))
    check = prop.get("check")
    # Round 29: a draft says the SCOPE of its evidence — an all-time count and a
    # windowed count are different claims, and a repair written today should
    # target what is still happening.
    window = ("**Window:** sessions and records written since %s.\n\n"
              % time.strftime("%Y-%m-%d %H:%M", time.localtime(float(prop["since"])))
              ) if prop.get("since") else "**Window:** the whole store (all time).\n\n"
    # Round 26: the retry count is the evidence that the hint beside this class
    # was not enough — stated once, in the header, only when it was measured.
    retried = ("**Retried:** %s of %s failures came back in the same shape "
               "(retry rate %s) — the hint beside it did not land.\n\n"
               % (prop.get("repeats"), prop.get("count"),
                  prop.get("retry_rate"))) if prop.get("repeats") else ""
    # Round 31: recovery is measured only where the corpus has ORDER (sessions);
    # a run-record-only row says nothing instead of claiming "never recovered".
    recovery = ""
    if prop.get("recovery_rate") is not None:
        rec, cnt = int(prop.get("recovered") or 0), int(prop.get("count") or 0)
        if prop.get("refusal"):
            # Round 32: the never-recovered residue is refusals. A refusal is not
            # repaired by a later success of the same tool, so the count must not
            # be read as a verdict — the remedy above already names who acts.
            recovery = ("**Recovered:** %d of %d — not the measure for this family: "
                        "the harness answered a POLICY question, so a missing later "
                        "success says the wall still stands, not that a fix failed. "
                        "The remedy above names who acts.\n\n" % (rec, cnt))
        else:
            recovery = ("**Recovered:** %d of %d — %s.\n\n"
                        % (rec, cnt,
                           "a later call of the same tool succeeded in the same stage "
                           "(a stumble, not a break)" if rec else
                           "no later success of the same tool in the same stage"))
    kind = "refusal" if prop.get("refusal") else "failure"
    # Round 38: two corpora, two units. A row that mixes session tool cards with
    # run-record steps names both, so "32 in 1 session" can never read as 32
    # cards seen in one session; a runs-only row says there is no session corpus
    # instead of printing a bare zero.
    _fs, _fr = int(prop.get("from_sessions") or 0), int(prop.get("from_runs") or 0)
    if _fr and not _fs:
        units = ""
        where = "in run records only (no session corpus)"
    else:
        units = (" (%d session card(s) + %d run step(s))" % (_fs, _fr)) if _fr else ""
        where = "in **%s** session(s)" % prop.get("sessions")
    # Round 37 (Who&When Pro): a count with no WHO cannot be routed — the reader
    # had "3 session(s)" and no name. The three strongest agents are named when
    # the store knows them, and the absence is stated when it does not.
    ags = [a for a in (prop.get("agents") or []) if isinstance(a, dict) and a.get("id")]
    who_line = ("**Who:** %s — the agents behind these cards, most failed first%s.\n\n"
                % (", ".join("%s %s (%s)" % (a.get("id"), a.get("name") or "?",
                                             a.get("count"))
                             for a in ags),
                   ", top three shown" if len(ags) >= 3 else "")
                ) if ags else (
        "**Who:** no agent row names these sessions — the org chart has no mapping "
        "for them, and no attribution is invented.\n\n")
    return (
        "# Repair: %s · %s\n\n"
        "**Severity:** %s — **%s** %s(s)%s %s "
        "(source: %s).\n\n"
        "%s"
        "%s"
        "%s"
        "%s"
        "## What fails\n\n%s\n\n"
        "%s"
        "## The remedy the register names\n\n> %s\n\n"
        "## How to prove it\n\n"
        "%s"
        "## Status\n\n"
        "%s"
        % (prop.get("tool"), prop.get("family"),
           prop.get("severity"), prop.get("count"), kind, units, where,
           prop.get("source"), who_line, window, retried, recovery, rows,
           ("```\n%s\n```\n\n" % samples) if samples else "",
           prop.get("action") or "(no remedy recorded)",
           ("Run `%s` after the fix; it is the test that proves this family of "
            "failure is answered.\n\n" % check) if check
           else "No test covers this family yet — write one before calling the "
                "fix done.\n\n",
           _status_text(prop)))


def _status_text(prop):
    """The Status section of a draft — DRAFT until a fix is recorded (round 40).

    Measured 2026-11-18: all 3 fixed drafts still said "Nothing was executed",
    because `repair_mark` wrote `proposal.json` and never touched `REPAIR.md`.
    A record that contradicts its own file is the defect this register exists to
    stop, so the Status section is derived from the record, never left behind.
    """
    fix = prop.get("fix") if isinstance(prop.get("fix"), dict) else None
    if not fix:
        return ("DRAFT — material, not a change. Nothing was executed and no policy "
                "was touched; state the fix, apply it through the normal gate, and "
                "re-read `self.failures` (or run the check) to prove the issue is "
                "gone.\n")
    when = time.strftime("%Y-%m-%d %H:%M",
                         time.localtime(float(fix.get("date") or 0)))
    note = (" — " + str(fix["note"])) if fix.get("note") else ""
    return ("**FIXED** at `%s` on %s%s.\n\n"
            "The window above is counted from that moment: re-read `self.failures` "
            "(or run the check) to see whether the class left. A fix with an empty "
            "window is `unobserved`, not `resolved`.\n"
            % (fix.get("commit") or "?", when, note))


def _stamp_status(md_path, prop):
    """Rewrite a REPAIR.md's Status SECTION from the record, keeping the rest.

    Only the Status block is replaced: an operator's notes elsewhere in the file
    — before or after it — survive. A missing file is rebuilt from the record.
    """
    try:
        with open(md_path, encoding="utf-8") as f:
            txt = f.read()
    except OSError:
        txt = ""
    idx = txt.find("## Status")
    if idx < 0:
        head, tail = txt.rstrip(), ""
    else:
        after = txt[idx + len("## Status"):]
        nxt = after.find("\n## ")
        head = txt[:idx].rstrip()
        tail = after[nxt:].strip("\n") if nxt >= 0 else ""
    if not head:
        head = _repair_md(prop).split("## Status")[0].rstrip()
    body = head + "\n\n## Status\n\n" + _status_text(prop).rstrip("\n") + "\n"
    if tail:
        body += "\n" + tail + "\n"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(body)


#: The evidence a repair draft records. One list so a NEW draft and a REFRESHED
#: one describe the same issue in the same shape — two builders would drift.
_REPAIR_EVIDENCE_KEYS = ("family", "severity", "count", "sessions",
                         "from_sessions", "from_runs", "repeats", "retry_rate",
                         "recovered", "recovery_rate", "refusal", "runs",
                         "source", "classes", "samples", "agents", "action",
                         "check")


def _repair_evidence(name, iss, since):
    """The register's evidence for one issue, as a draft carries it.

    Round 38: the corpus split travels with the count. Round 37: the draft names
    whose sessions hit the class, so a reader can route the fix without opening
    the register. `since` states the window the numbers were read in (round 29).
    """
    ev = {"kind": "repair", "status": "proposed", "name": name, "issue": name,
          "tool": iss.get("tool"), "since": since,
          "origin": "auto",
          "next": "state the fix, apply it through the gate, prove it"}
    for key in _REPAIR_EVIDENCE_KEYS:
        ev[key] = iss.get(key)
    return ev


def issue_drafts(out_dir, limit=5, min_severity="warning", sessions_dir=None,
                 max_sessions=400, since=None):
    """Write one REPAIR draft per failure issue — the register turned into work.

    Round 22. `mine()` drafts a repeated SEQUENCE; the register names a FAILURE
    with its reach, its samples and — when a test covers the family — the check
    that proves a fix. This writes one `kind: "repair"` draft per issue at or
    above `min_severity`, never twice for the same issue id, and executes
    nothing: the draft is material for the optimizer/operator, and every write
    still goes through the normal gate.

    Round 29: `since` scopes the evidence (see `failure_candidates`) and travels
    into the draft — `proposal.json` carries the epoch and `REPAIR.md` states the
    window, so an all-time count can never be mistaken for "still happening".

    Round 61: an existing draft is not simply skipped. An UNFIXED one whose
    evidence changed is REWRITTEN from the current issue (the prior numbers move
    to `previous`, `created` is kept, `refreshed_ts` records the update); a draft
    that carries a `fix` is the record of an applied change and is never touched;
    an unchanged draft is left alone; and a WINDOWED read (`since`) never rewrites
    an all-time draft with a partial count. Refreshes are reported separately and
    do not count against `limit`, which caps NEW drafts.
    """
    floor = _SEV_RANK.get(str(min_severity or "warning"), 1)
    rep = failure_candidates(limit=200, include_sessions=True,
                             sessions_dir=sessions_dir, max_sessions=max_sessions,
                             since=since)
    issues = [i for i in (rep.get("issues") or [])
              if _SEV_RANK.get(i.get("severity"), 3) <= floor]
    written, refreshed, skipped = [], [], []
    try:
        os.makedirs(out_dir, exist_ok=True)
    except OSError:
        return {"ok": False, "error": "cannot create %s" % out_dir}
    for iss in issues:
        name = str(iss.get("id") or "fail-issue")
        d = os.path.join(out_dir, name)
        prop_json = os.path.join(d, "proposal.json")
        ev = _repair_evidence(name, iss, rep.get("since"))
        if os.path.isfile(prop_json):
            prev = _read_json(prop_json)
            # Round 61: the draft is the artifact a reader acts on, so an UNFIXED
            # one must say what the register says NOW. Measured 2026-11-18: 34 of
            # 37 drafts were frozen at their birth numbers — `shell.exec ·
            # nonzero-exit` still claimed 18 failures / 2 sessions while the
            # register (after round 53 re-classified those cards) counts 3.
            if not isinstance(prev, dict):
                skipped.append(name)
                continue
            # A draft that records a fix is the record of an applied change: its
            # numbers are the evidence at fix time and `repair_states` judges what
            # came after. Rewriting it would destroy the before/after pair.
            if prev.get("fix") or prev.get("status") in ("fixed", "resolved"):
                skipped.append(name)
                continue
            # A windowed read is a partial view; it never narrows an all-time draft.
            if rep.get("since") is not None:
                skipped.append(name)
                continue
            if all(prev.get(k) == ev.get(k) for k in _REPAIR_EVIDENCE_KEYS):
                skipped.append(name)
                continue
            before = {k: prev.get(k) for k in ("count", "sessions", "family",
                                               "severity", "repeats", "recovered")}
            merged = dict(prev)
            merged.update(ev)
            merged["refreshed_ts"] = round(time.time(), 3)
            merged["previous"] = before
            try:
                write_json(prop_json, merged)
                with open(os.path.join(d, "REPAIR.md"), "w", encoding="utf-8") as f:
                    f.write(_repair_md(merged))
            except OSError:
                continue
            refreshed.append({"issue": name, "path": d,
                              "count": merged.get("count"),
                              "previous": before.get("count"),
                              "family": merged.get("family"),
                              "severity": merged.get("severity")})
            continue
        # The cap is on NEW drafts; a refresh is maintenance of an existing one.
        if len(written) >= max(1, int(limit or 5)):
            break
        prop = dict(ev)
        prop["created"] = round(time.time(), 3)
        try:
            os.makedirs(d, exist_ok=True)
            write_json(os.path.join(d, "proposal.json"), prop)
            with open(os.path.join(d, "REPAIR.md"), "w", encoding="utf-8") as f:
                f.write(_repair_md(prop))
        except OSError:
            continue
        written.append({"issue": name, "path": d, "severity": prop["severity"],
                        "tool": prop["tool"], "family": prop["family"],
                        "count": prop["count"], "sessions": prop["sessions"],
                        "repeats": prop.get("repeats"),
                        "check": prop["check"]})
    return {"ok": True, "dir": out_dir, "written": written, "refreshed": refreshed,
            "skipped": skipped,
            "issues": len(issues), "severity": str(min_severity),
            "runs": rep.get("runs"), "sessions": rep.get("sessions"),
            "since": rep.get("since")}


def mine_history(out_dir, c=None, path=None, note=""):
    """Mine the recorded history and write the drafts. Returns the paths.

    OCM: the outcome and the purpose travel WITH the sequence they belong to
    (`history_split`), so a candidate can be ranked and refused by evidence
    instead of by frequency.
    """
    seqs, ocs, pps = history_split(path)
    return scan(seqs, out_dir, c, note=note, outcomes=ocs, purposes=pps)


#: The lifecycle of a repair draft. A skill draft has one (`verified` /
#: `rejected` / `archived`, stages 2–3); a repair draft had none — measured
#: 2026-11-18: it was written `proposed` and no code path ever changed it, while
#: its own Status section told the reader to "re-read `self.failures` to prove
#: the issue is gone". Round 34 stores the proof instead of asking for it.
#:
#: Round 35 adds `unobserved`: measured live the same night, a fix dated 23:23:44
#: had ZERO sessions written after it, and "resolved" over an empty window is a
#: claim stronger than its evidence — the exact defect this register exists to
#: stop. A fix with no session in its window has not been observed yet.
REPAIR_STATES = ("proposed", "unobserved", "fixed-open", "resolved")


def repair_mark(out_dir, issue, commit, note="", when=None):
    """Record that a drafted repair was applied — the loop's closing act.

    Writes `fix: {commit, date, note}` into the draft's `proposal.json` and moves
    `status` to `fixed`; `repair_states` then says whether the class left. An
    unknown issue, a missing draft or a name that is not a plain directory all
    answer `ok: False` — nothing is created here.
    """
    name = str(issue or "").strip()
    if not name or os.path.basename(name) != name or name in (".", ".."):
        return {"ok": False, "error": "unknown issue name %r" % (issue,)}
    # A record without a commit is not a record: the point of the close is that a
    # later reader can retrace the fix (ReqToCode, 2603.13999 — traceability as a
    # property of the artifact, not a note beside it).
    commit = str(commit or "").strip()[:64]
    if not commit:
        return {"ok": False,
                "error": "a fix needs the commit that applied it (no commit given)"}
    d = os.path.join(out_dir, name)
    p = os.path.join(d, "proposal.json")
    if not os.path.isfile(p):
        return {"ok": False, "error": "no repair draft at %s" % p}
    prop = _read_json(p)
    if not isinstance(prop, dict) or prop.get("kind") != "repair":
        return {"ok": False, "error": "not a repair draft: %s" % p}
    ts = _since_epoch(when)
    fix = {"commit": commit,
           "date": round(float(ts if ts is not None else time.time()), 3),
           "note": str(note or "")[:300]}
    prop["fix"] = fix
    prop["status"] = "fixed"
    try:
        write_json(p, prop)
    except OSError as e:
        return {"ok": False, "error": "cannot write %s: %s" % (p, e)}
    # Round 40: the record and its readable copy agree. Before this, a fixed
    # draft's REPAIR.md still read "Nothing was executed" (measured: 3 of 3).
    try:
        _stamp_status(os.path.join(d, "REPAIR.md"), prop)
    except OSError:
        pass  # the JSON record is the truth; the markdown is its readable copy
    return {"ok": True, "issue": name, "dir": d, "fix": fix}


def repair_states(out_dir, sessions_dir=None, max_sessions=400, runs_dir=None):
    """Per repair draft: is its class still happening AFTER its own fix date?

    Round 34. One pass over the store, each draft against its own window; the
    family identity is the register's own three functions (`runtree.failed`,
    `error_class`, `failure_family`), never a second rule. `proposed` = no fix
    recorded; `count_since` is `None` there because there is no window to count.

    Round 35: the window has a DENOMINATOR. `sessions_since` is how many session
    files were written after the fix, and a fix with none is `unobserved` — not
    `resolved`, because zero failures out of zero sessions is not evidence.

    Round 39: the window is the WHOLE trace store. Measured 2026-11-18: an issue
    now names its two corpora (`from_sessions`/`from_runs`), and a class that
    also lives in harness run records could read `resolved` from a session-only
    measurement while its run steps still failed. `runs_since` is the second
    denominator, `count_since` is both corpora, and `unobserved` needs BOTH to
    be empty.
    """
    from longrun.util import runtree
    from longrun.harness import record as rec_mod
    states = []
    try:
        names = sorted(n for n in os.listdir(out_dir)
                       if os.path.isfile(os.path.join(out_dir, n, "proposal.json")))
    except OSError:
        return {"ok": True, "states": [], "sessions": 0}
    drafts = []
    for n in names:
        prop = _read_json(os.path.join(out_dir, n, "proposal.json"))
        if not isinstance(prop, dict) or prop.get("kind") != "repair":
            continue
        drafts.append((n, prop))
    if not drafts:
        return {"ok": True, "states": [], "sessions": 0}
    root = sessions_dir or paths.SESSIONS_DIR
    try:
        entries = [e for e in os.scandir(root) if e.name.endswith(".json")]
        entries.sort(key=lambda e: e.stat().st_mtime, reverse=True)
        entries = entries[:max(1, int(max_sessions or 400))]
    except OSError:
        entries = []
    seen = {}          # (tool, family) -> [mtime, …]
    mtimes = []        # every session mtime in the corpus, for the denominator
    for ent in entries:
        try:
            mt = ent.stat().st_mtime
        except OSError:
            continue
        mtimes.append(mt)
        sess = _read_json(ent.path)
        if not isinstance(sess, dict):
            continue
        for c in sess.get("tool_cards") or []:
            if not isinstance(c, dict) or not runtree.failed(c):
                continue
            head = error_class(c.get("error") or c.get("result"))
            fam = failure_family(c.get("tool"), head, c.get("error") or c.get("result"))
            seen.setdefault((str(c.get("tool") or "?"), fam), []).append(mt)
    # Round 39: the second corpus, the same three functions.
    rroot = runs_dir or os.path.join(rec_mod.dir_path(), "runs")
    try:
        rentries = [e for e in os.scandir(rroot) if e.name.endswith(".json")]
        rentries.sort(key=lambda e: e.stat().st_mtime, reverse=True)
        rentries = rentries[:max(1, int(max_sessions or 400))]
    except OSError:
        rentries = []
    in_runs, rmtimes = {}, []
    for ent in rentries:
        try:
            mt = ent.stat().st_mtime
        except OSError:
            continue
        rmtimes.append(mt)
        rec = _read_json(ent.path)
        if not isinstance(rec, dict):
            continue
        for step in rec.get("steps") or []:
            if not isinstance(step, dict) or step.get("ok") is not False:
                continue
            head = error_class(step.get("error"))
            fam = failure_family(step.get("tool"), head, step.get("error"))
            in_runs.setdefault((str(step.get("tool") or "?"), fam), []).append(mt)
    for name, prop in drafts:
        key = (str(prop.get("tool") or ""), str(prop.get("family") or ""))
        fix = prop.get("fix") if isinstance(prop.get("fix"), dict) else None
        state = {"issue": name, "tool": key[0], "family": key[1],
                 "status": "proposed", "fix": fix, "count_since": None,
                 "sessions_since": None, "runs_since": None}
        if fix:
            cutoff = float(fix.get("date") or 0)
            n_sess = sum(1 for mt in mtimes if mt >= cutoff)
            n_runs = sum(1 for mt in rmtimes if mt >= cutoff)
            c_sess = sum(1 for mt in seen.get(key, []) if mt >= cutoff)
            c_runs = sum(1 for mt in in_runs.get(key, []) if mt >= cutoff)
            state["count_since"] = c_sess + c_runs
            state["count_since_sessions"] = c_sess
            state["count_since_runs"] = c_runs
            state["sessions_since"] = n_sess
            state["runs_since"] = n_runs
            state["status"] = ("unobserved" if (n_sess == 0 and n_runs == 0) else
                               "resolved" if (c_sess + c_runs) == 0 else "fixed-open")
        states.append(state)
    states.sort(key=lambda s: (REPAIR_STATES.index(s["status"]),
                               -int(s["count_since"] or 0), s["issue"]))
    return {"ok": True, "states": states, "sessions": len(entries),
            "runs": len(rentries)}


# ------------------------------------------------- stage 2: synth/verify/archive
# Voyager-style write-gate: the skill enters `skills/` ONLY if the generated check
# passes in the sandbox. Nothing but the check is executed (self-contained), so
# the cycle is safe: synthesize -> verify -> archive.

STAGE2_DEFAULTS = {
    # JAG-426: auto-generated skills land under skills/created/ — a dedicated,
    # clearly-labelled box, so the built-in library (skills/core) and the user's
    # own categories stay untouched and auditable.
    "category": "created",  # skills/<category>/<name> during promotion
    # RSI-G-3: retire a machine-created skill never opened for this many days —
    # the same bar as a forged tool nobody called (`retire_unused`).
    "retire_days": 14,
    "verify_timeout": 60,   # timeout of the check in the sandbox
    # F5 (Maka thresholded release): the promotion bar. A proposal is released
    # only after this many CONSECUTIVE green verifies (patience — no release
    # on a single lucky green). 1 preserves the historical single-green
    # behavior; raise it to harden a flaky check.py.
    "min_green_streak": 1,
    # RSI-V (TRUST, 2611.10787): the bar a repeated verify must clear. When a
    # case ran `repeats` times, its pass count must beat a fair coin at this
    # one-sided alpha before the artifact may be promoted — the accepted-set
    # error is bounded by cases x alpha. Cases verified ONCE carry no bound and
    # are named as such; the bound is never invented.
    "promotion_alpha": 0.05,
    # EV-13: evolve's CODE arm. A green pattern already becomes a skill (the
    # declarative procedure); with this on it is ALSO forged into a Matrix tool
    # (`learned_<slug>.run`) that replays the sequence, proven by its own
    # generated test + the sha-bound contract gate and removed when either fails.
    # Bounded per run so one evolve pass cannot flood src/Matrix.
    "forge_on_evolve": True,
    "forge_per_run": 1,
    # THE INSTALL BOUND (measured 2026-11-14). `evolve` runs over EVERY mined
    # pattern, and `pipeline` promotes each green one: on this install that is 91
    # candidates, so the first pass with a working sealed suite would have filled
    # `skills/created/` to its 25-skill cap in one go. The code arm has been
    # bounded per pass since EV-13 (`forge_per_run`); the skill arm had no bound
    # at all. Same shape, same reason: one pass installs at most N verified
    # skills, the rest stay drafts and are mined again next pass.
    "promote_per_run": 1,
    # EV-22: the ABSTRACTION step. A green sequence is not automatically a
    # capability: before it is forged, ONE single-shot model call decides whether
    # the repeat MEANS something and names it (arXiv 2606.02994 ARISE — recurring
    # procedures are induced into subroutines; Agent Workflow Memory — a workflow
    # is a goal + a routine, and the goal is what names it). `compact: false`
    # stops a habit/retry/noise from being written as a tool; `compact: true`
    # makes the module `learned_<meaning>_<hash>` instead of a step slug.
    # Bounded per run (one call, ≤700 tokens) because the pass runs at end of turn.
    "abstract_on_evolve": True,
    "abstract_per_run": 1,
    "abstract_model": "",     # "" = the router's `reviewer` role
    "abstract_timeout": 60,
}

# JAG-426: a hard ceiling on machine-created skills. An unbounded auto-library
# pollutes retrieval and can steer future runs; 25 is plenty for a personal harness.
AUTO_SKILL_CAP = 25


from longrun.util.fswrite import path_under as _under


def _write_json(path, obj):
    try:
        write_json(path, obj)
        return True
    except OSError:
        return False


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _known_tools():
    """Names the harness ACCEPTS now (for the self-contained check).

    v714: `catalog()` lists only the canonical `<namespace>.<subtool>` names, but a
    recorded sequence keeps the name the model actually called (`shell`, `matrix`,
    `memory`, ...). Comparing the two sets made every mined draft unverifiable by
    construction — the live check answered `unknown tools: shell, matrix, shell`
    for a sequence that had just run. The registry is the authority for what a call
    may be: its catalogue PLUS the plain legacy names it still accepts.
    """
    try:
        from longrun.tools import registry
        names = {t["name"] for t in registry.catalog() if t.get("name")}
        names |= set(registry._LEGACY_SCHEMAS)
        return sorted(names)
    except Exception:  # noqa: BLE001
        return []


def _runner_src(name, steps):
    lines = [
        "#!/usr/bin/env python3",
        '"""Runner generated automatically (JAG-135) for the skill %s.' % name,
        "",
        "Not executed by mining: it is the PRIMITIVE that the harness can",
        "invoke. Each step lists the harness tool to call, in order.",
        '"""',
        "import json",
        "import sys",
        "",
        "STEPS = json.loads(%s)" % repr(json.dumps(steps)),
        "",
        "",
        "def run(invoke):",
        '    """Execute the steps in order by calling invoke(tool, args)."""',
        "    out = []",
        "    for st in STEPS:",
        '        out.append(invoke(st["tool"], st.get("args", {})))',
        "    return out",
        "",
        "",
        'if __name__ == "__main__":',
        '    print(json.dumps([s["tool"] for s in STEPS]))',
    ]
    return "\n".join(lines) + "\n"


def _check_src(name, known):
    lines = [
        "#!/usr/bin/env python3",
        '"""Check generated automatically (JAG-135) for the skill %s.' % name,
        "",
        "Validates skill.json: well-formed JSON, at least one step, each step with a",
        "tool known at synthesis time. Green = promotable. Self-contained:",
        "no dependency on the repo, runs in any sandbox.",
        '"""',
        "import json",
        "import os",
        "import sys",
        "",
        'HERE = os.path.dirname(os.path.abspath(__file__))',
        "KNOWN = set(json.loads(%s))" % repr(json.dumps(known)),
        "",
        "",
        "def main():",
        "    try:",
        '        with open(os.path.join(HERE, "skill.json"), encoding="utf-8") as f:',
        "            recipe = json.load(f)",
        "    except (OSError, ValueError) as e:",
        '        print("skill.json unreadable: %s" % e)',
        "        return 1",
        '    steps = recipe.get("steps")',
        "    if not isinstance(steps, list) or not steps:",
        '        print("no steps in the recipe")',
        "        return 1",
        "    bad = [str(s.get(\"tool\")) for s in steps",
        "           if not isinstance(s, dict) or s.get(\"tool\") not in KNOWN]",
        "    if bad:",
        '        print("unknown tools: %s" % ", ".join(bad))',
        "        return 1",
        '    print("ok: %d valid step(s)" % len(steps))',
        "    return 0",
        "",
        "",
        'if __name__ == "__main__":',
        "    sys.exit(main())",
    ]
    return "\n".join(lines) + "\n"


def synth(pattern, out_dir, c=None):
    """Generate the executable artifacts for a pattern (stage 2, codegen).

    Writes, into the proposal folder, `skill.json` (declarative pipeline),
    `runner.py` (invocable primitive) and `check.py` (self-contained verification).
    Returns {"dir","skill","runner","check","steps"} or None if the write fails.
    """
    name = slug(pattern)
    d = os.path.join(out_dir, name)
    steps = [{"tool": str(t)} for t in (pattern or [])]
    recipe = {"name": name, "kind": "pipeline", "steps": steps,
              "note": "generated by selfevolve (JAG-135)"}
    try:
        os.makedirs(d, exist_ok=True)
        if not _write_json(os.path.join(d, "skill.json"), recipe):
            return None
        with open(os.path.join(d, "runner.py"), "w", encoding="utf-8") as f:
            f.write(_runner_src(name, steps))
        with open(os.path.join(d, "check.py"), "w", encoding="utf-8") as f:
            f.write(_check_src(name, _known_tools()))
        return {"dir": d, "skill": os.path.join(d, "skill.json"),
                "runner": os.path.join(d, "runner.py"),
                "check": os.path.join(d, "check.py"), "steps": len(steps)}
    except OSError:
        return None


def ensure_check(proposal_dir):
    """Give a mined draft the code it needs to be verified (ONE owner).

    A mined draft is only a tool pattern: `verify` needs `check.py`, which the
    synth stage writes. The approval path used to do this inline, so the tool
    lane (`improve{action:verify|promote}`) dead-ended on every fresh draft with
    "can't open file …/check.py". Both callers use this instead.

    A check WE generated is regenerated (it embeds the tool names known at synth
    time); a hand-written one is left alone.

    Returns {"ok": True, "synth": bool} or {"ok": False, "error": str}.
    """
    d = str(proposal_dir or "").rstrip("/")
    if not d or not os.path.isdir(d):
        return {"ok": False, "error": "the drafted skill folder is missing (%s)" % d}
    check = os.path.join(d, "check.py")
    if os.path.isfile(check):
        # A check WE generated embeds the tool names known at synth time, so it is
        # refreshed (the registry changes; a stale list is what made drafts fail).
        # A hand-written check is never touched.
        try:
            with open(check, encoding="utf-8") as f:
                head = f.read(400)
        except OSError:
            head = ""
        if AUTOGEN not in head:
            return {"ok": True, "synth": False}
    prop_path = os.path.join(d, "proposal.json")
    if not os.path.isfile(prop_path):
        # EV-14: a folder that is NOT a draft has nothing of ours to verify. The
        # verifier used to run a `check.py` that does not exist and report the
        # raw `python3: can't open file …` as if it were a failed check.
        return {"ok": False,
                "error": "not a mined draft: %s has no proposal.json" % d}
    prop = _read_json(prop_path)
    pattern = prop.get("pattern") if isinstance(prop, dict) else None
    if not isinstance(pattern, list) or not pattern:
        return {"ok": False, "error": "draft has no check.py and no tool pattern — cannot verify it"}
    made = synth([str(x) for x in pattern], os.path.dirname(d))
    if not made:
        return {"ok": False, "error": "could not synthesize the runner/check for this draft"}
    if os.path.realpath(made.get("dir") or "") != os.path.realpath(d):
        return {"ok": False,
                "error": "the synthesized folder (%s) is not the draft (%s)" % (made.get("dir"), d)}
    return {"ok": True, "synth": True}


def _run_check(proposal_dir, command, c):
    """Run the check in the sandbox (cwd = proposal folder). (green, output)."""
    try:
        from longrun.tools import sandbox
        res = sandbox.run(command, timeout=int(c.get("verify_timeout") or 60),
                          workspace=proposal_dir)
    except Exception as e:  # noqa: BLE001
        return False, "sandbox error: %s" % e
    out = (res.get("stdout") or "") + (res.get("stderr") or "")
    return res.get("exit_code") == 0, out


def _case_command(case):
    """The shell command for one case: `default` = the proposal's own check.py."""
    return "python3 check.py" if not case or str(case) == "default" else str(case)


# ------------------------------------------------------- verifier mutations ----
# A check that exits 0 on EVERY input is not evidence. Measured 2026-11-18: 115
# of 134 auto-skill proposals carried one structural boolean
# (`verify.cases == {"default": true}`) as their whole verification, so the
# promotion gate could not tell a real check from a vacuous one. Each mutation
# below breaks ONE assumption of the artifact; the proposal's OWN check.py must
# FAIL on every one of them or the artifact is not promotable. The stored case
# table then says what the verifier can distinguish (`catches:<mutation>`), and
# `promote`'s existing case gate consumes it unchanged.


def _artifact_mutations(proposal_dir):
    """[(case_id, mutated skill dict | None)] — [] when the artifact is not a skill.

    Skills are the artifact kind with a generated `check.py` over `skill.json`;
    other kinds (project/matrix) keep today's single-case verification.
    """
    try:
        art = _read_json(os.path.join(proposal_dir, "skill.json"))
    except Exception:  # noqa: BLE001 — an unreadable artifact is the check's job
        art = None
    if (not isinstance(art, dict)
            or not os.path.isfile(os.path.join(proposal_dir, "check.py"))):
        return []
    out = [("catches:corrupt-json", None)]
    steps = art.get("steps")
    if isinstance(steps, list) and steps:
        out.append(("catches:no-steps", dict(art, steps=[])))
        first = steps[0] if isinstance(steps[0], dict) else {}
        out.append(("catches:unknown-tool",
                    dict(art, steps=[dict(first, tool="no.such.tool")]
                         + list(steps[1:]))))
    return out


def mutation_report(proposal_dir, c=None):
    """Is the artifact's check DISCRIMINATING? (cases, case_runs, applied).

    Each mutation runs in a copy of the proposal folder, so the artifact and its
    digest are untouched. `caught` = the check exited non-zero for that copy. A
    sandbox error is NOT a catch (it would fabricate evidence), so it fails the
    mutation case explicitly.
    """
    c = c or cfg()
    muts = _artifact_mutations(proposal_dir)
    if not muts:
        return {}, {}, []
    import shutil
    import tempfile
    cases, runs, applied = {}, {}, []
    for cid, art in muts:
        tmp = tempfile.mkdtemp(prefix="sev-mut-")
        try:
            for name in os.listdir(proposal_dir):
                src = os.path.join(proposal_dir, name)
                dst = os.path.join(tmp, name)
                if os.path.isdir(src):
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)
            target = os.path.join(tmp, "skill.json")
            if art is None:
                with open(target, "w", encoding="utf-8") as f:
                    f.write("{not json")
            else:
                _write_json(target, art)
            green, msg = _run_check(tmp, "python3 check.py", c)
            caught = (not green) and not str(msg).startswith("sandbox error")
            cases[cid] = caught
            runs[cid] = {"passes": 1 if caught else 0, "runs": 1}
            applied.append(cid)
        except Exception:  # noqa: BLE001 — a mutation is evidence, never a crash
            continue
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return cases, runs, applied


def evaluate_cases(proposal_dir, cases, runner=None, c=None, repeats=1):
    """Run each case `repeats` times and return {case_id: {"passes", "runs"}}.

    A single deterministic check cannot show that nothing else regressed, and a
    single EXECUTION cannot show that the result is stable: ParetoSaddler's
    ablation (2611.02079) reports 81.35% at 3 executions per task against 75.71%
    at 1. `runner(dir, command) -> (green, output)` is injectable so tests never
    touch the sandbox; the default runs the command inside the proposal folder.
    """
    try:
        repeats = max(1, int(repeats or 1))
    except (TypeError, ValueError):
        repeats = 1
    out = {}
    for case in (cases or ["default"]):
        cid = str(case)
        command = _case_command(cid)
        passes = 0
        for _ in range(repeats):
            if runner is not None:
                try:
                    green, msg = runner(proposal_dir, command)
                except Exception as e:  # noqa: BLE001 — a case is data, not a crash
                    green, msg = False, "runner error: %s" % e
            else:
                green, msg = _run_check(proposal_dir, command, c or cfg())
            passes += 1 if green else 0
        out[cid] = {"passes": passes, "runs": repeats}
    return out


def _binomial_tail(passes, runs):
    """P(X >= passes | runs fair coin) — one-sided exact test, stdlib only.

    Under H0 the case passes half the time; a small tail means the observed
    passes are evidence of a real pass, not a lucky run. No SciPy: the counts
    are small (a handful of repeats per case).
    """
    try:
        passes, runs = int(passes), int(runs)
    except (TypeError, ValueError):
        return 1.0
    if runs <= 0:
        return 1.0
    passes = max(0, min(passes, runs))
    return sum(math.comb(runs, k) for k in range(passes, runs + 1)) / float(2 ** runs)


def _promotion_bound(cases, counts, c):
    """How likely is a flaky pass to be released? (RSI-V, TRUST 2611.10787)

    The gate in `promote` is a set of deterministic booleans, so a case that
    passes 2 of 3 runs promotes exactly like one that passes 3 of 3. Where
    `verify` ran repeats, each case now carries an exact one-sided binomial
    p-value against "passes half the time" and must clear `promotion_alpha`; the
    family-wise bound on accepting a case that is truly not better is
    `cases x alpha` (Bonferroni). A case verified ONCE has no bound to compute —
    it is listed under `single_run` and the verdict says so instead of faking a
    number.
    """
    alpha = 0.05
    try:
        alpha = float((c or {}).get("promotion_alpha") or 0.05)
    except (TypeError, ValueError):
        alpha = 0.05
    rows, failed, single = {}, [], []
    for name in sorted(cases or {}):
        got = (counts or {}).get(name) or {}
        try:
            runs, passes = int(got.get("runs") or 0), int(got.get("passes") or 0)
        except (TypeError, ValueError):
            runs, passes = 0, 0
        if runs < 2:
            single.append(name)
            continue
        p = _binomial_tail(passes, runs)
        ok = bool(cases.get(name)) and p <= alpha
        rows[name] = {"passes": passes, "runs": runs, "p": round(p, 6), "ok": ok}
        if not ok:
            failed.append(name)
    verdict = "refused" if failed else ("bounded" if rows else "single-run")
    return {"verdict": verdict, "alpha": alpha,
            "family_alpha": round(len(rows) * alpha, 4),
            "cases": rows, "failed": failed, "single_run": single,
            "basis": "exact binomial, one-sided, H0 p<=0.5"}


def _skill_cost(proposal_dir):
    """Prompt-payload cost of an artifact: markdown bytes / 4 (no model call).

    The skill's own text is what enters the system prompt on every turn, so it
    is the cost a candidate adds. `proposal.json` and logs are EXCLUDED — they
    change between verifies and are not part of the prompt.
    """
    total = 0
    for base, _dirs, files in os.walk(str(proposal_dir or "")):
        for fn in files:
            if not fn.lower().endswith(".md"):
                continue
            try:
                total += os.path.getsize(os.path.join(base, fn))
            except OSError:
                pass
    return {"tokens": max(1, total // 4), "bytes": total}


def _installed_cost_baseline(category="created", skills_dir=None):
    """(median prompt tokens | None, samples) for one category's installed set.

    DR-M: this used to be `_installed_cost_median`, which answered **0** with
    fewer than three samples — and `promote` read 0 as falsy, so a category
    holding one or two artifacts had NO cost gate at all. One or two samples are
    a weak baseline, not the absence of one; `None` means nothing is installed,
    which is the only case where the gate genuinely cannot judge. Returning the
    pair keeps the listing to one pass (no second truth).
    """
    root = os.path.join(skills_dir or os.environ.get("LONGRUN_SKILLS_DIR")
                        or os.path.join(REPO, "skills"), str(category or "created"))
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return None, 0
    costs = []
    for name in names:
        cost = _skill_cost(os.path.join(root, name))
        if cost["bytes"]:
            costs.append(cost["tokens"])
    if not costs:
        return None, 0
    costs.sort()
    return costs[len(costs) // 2], len(costs)


def _artifact_digest(proposal_dir):
    """sha256 over the bytes a promotion would publish.

    `verify` stamps this into the evidence; `promote` recomputes it before
    installing. If the two differ, the draft was EDITED after the check that
    certified it, so the green runs belong to bytes nobody reviewed (AReaL-RSI,
    version-consistent publication). `proposal.json` is excluded because verify
    and promote both rewrite it (it is metadata, not artifact); every other file
    that ships — SKILL.md, runner.py, check.py, skill.json — is covered, keyed by
    sorted relative path so two identical trees hash the same. `""` when the
    folder cannot be walked.
    """
    import hashlib
    h = hashlib.sha256()
    try:
        for base, dirs, files in os.walk(str(proposal_dir or "")):
            dirs[:] = sorted(d for d in dirs if d != "__pycache__")
            for fn in sorted(files):
                if fn == "proposal.json" or fn.endswith((".log", ".pyc")):
                    continue
                rel = os.path.relpath(os.path.join(base, fn), proposal_dir)
                try:
                    with open(os.path.join(base, fn), "rb") as f:
                        data = f.read()
                except OSError:
                    continue
                h.update(rel.encode("utf-8") + b"\0" + data + b"\0")
    except OSError:
        return ""
    return h.hexdigest()


def verify(proposal_dir, runner=None, c=None, cases=None, baseline=None,
           repeats=None):
    """Run the proposal's check(s) and update proposal.json (verified/rejected).

    `cases` is an optional list of commands (the literal `"default"` means
    `python3 check.py`); every case must pass a STRICT MAJORITY of `repeats`
    executions (default from config `verify_repeats`, 1 = today's behaviour).
    `baseline` is the case map of the artifact this one replaces, stored WITH
    the result so `promote()` can refuse a regression instead of averaging it
    away. The report also carries the artifact's prompt cost (`cost_tokens`) and
    the per-case execution counts (`case_runs`).

    `runner(dir, command) -> (green, output)` injectable in tests (pure). An
    injected runner also marks a HARNESS check, not a promotion: the mutation
    cases below need the artifact's own check to run for real, so they are
    skipped there (the case table stays the single injected case).
    """
    c = c or cfg()
    prop = _read_json(os.path.join(proposal_dir, "proposal.json")) or {}
    cases = [str(x) for x in (cases or ["default"])]
    if repeats is None:
        try:
            repeats = int(c.get("verify_repeats") or 1)
        except (TypeError, ValueError):
            repeats = 1
    command = _case_command(cases[0])
    t0 = time.time()
    counts = evaluate_cases(proposal_dir, cases, runner=runner, c=c, repeats=repeats)
    case_map = {k: (v["passes"] * 2 > v["runs"]) for k, v in counts.items()}
    # Is the verifier itself discriminating? A vacuous check passes everything,
    # so it would otherwise promote on its own uselessness.
    mut_applied = []
    if runner is None:
        mut_cases, mut_runs, mut_applied = mutation_report(proposal_dir, c)
        if mut_cases:
            case_map.update(mut_cases)
            counts.update(mut_runs)
    green = all(case_map.values())
    out = ", ".join("%s=%d/%d" % (k, v["passes"], v["runs"]) for k, v in counts.items())
    report = {"ran": True, "green": bool(green), "command": command,
              "cases": case_map, "case_runs": counts,
              "mutations": mut_applied,
              "baseline": {str(k): bool(v) for k, v in (baseline or {}).items()},
              "cost_tokens": _skill_cost(proposal_dir),
              # AA: the bytes this verdict is ABOUT. Stamped so `promote` can
              # refuse to publish a draft that changed after the check ran.
              "artifact_sha256": _artifact_digest(proposal_dir),
              "duration_ms": int((time.time() - t0) * 1000),
              "output": str(out)[-1200:]}
    prop["status"] = "verified" if green else "rejected"
    # F5 (Maka patience): the consecutive-green streak. A red verify resets it;
    # promote() releases only when the streak reaches the bar.
    try:
        _prev = int(prop.get("green_streak") or 0)
    except (TypeError, ValueError):
        _prev = 0
    prop["green_streak"] = (_prev + 1) if green else 0
    prop["verify"] = report
    _write_json(os.path.join(proposal_dir, "proposal.json"), prop)
    return report


def attribute(proposal_dir, runner=None, c=None):
    """Per-case delta of a promotion (Harness-Delta, 2610.22466).

    Built from the maps already stored by `verify`: which case the artifact
    FIXED, which it BROKE, and its prompt cost. With a runner, the installed
    copy is re-checked once (`installed_confirmed`) so an install that rewrote
    the artifact cannot pass silently.
    """
    prop = _read_json(os.path.join(proposal_dir, "proposal.json")) or {}
    v = prop.get("verify") if isinstance(prop.get("verify"), dict) else {}
    cases = v.get("cases") if isinstance(v.get("cases"), dict) else {}
    base = v.get("baseline") if isinstance(v.get("baseline"), dict) else {}
    flips = {}
    for key in sorted(set(cases) | set(base)):
        if key not in cases or key not in base:
            continue
        if bool(base[key]) != bool(cases[key]):
            flips[key] = "pass->fail" if base[key] else "fail->pass"
    out = {"case_flips": flips,
           "gained": len([1 for v2 in flips.values() if v2 == "fail->pass"]),
           "lost": len([1 for v2 in flips.values() if v2 == "pass->fail"]),
           "cost_tokens": v.get("cost_tokens")}
    if runner is not None and cases:
        counts = evaluate_cases(proposal_dir, sorted(cases), runner=runner, c=c)
        out["installed_confirmed"] = all(
            (counts[k]["passes"] * 2 > counts[k]["runs"]) == bool(cases[k])
            for k in counts)
    prop["attribution"] = out
    _write_json(os.path.join(proposal_dir, "proposal.json"), prop)
    return out


def smoke_installed(skills_dir=None, runner=None, c=None, category="created",
                    limit=50):
    """Re-check every installed auto artifact against its OWN case table.

    Compositional Safety (2609.33123): edits that are safe alone can compose
    into unsafe behaviour, so the set is what needs a smoke test. Only artifacts
    that stored a case table are checked; a red entry blocks a promotion.
    """
    root = os.path.join(skills_dir or os.environ.get("LONGRUN_SKILLS_DIR")
                        or os.path.join(REPO, "skills"), str(category or "created"))
    try:
        names = sorted(os.listdir(root))[:max(1, int(limit or 50))]
    except OSError:
        return {}
    out = {}
    for name in names:
        d = os.path.join(root, name)
        prop = _read_json(os.path.join(d, "proposal.json")) or {}
        v = prop.get("verify") if isinstance(prop.get("verify"), dict) else {}
        cases = sorted((v.get("cases") or {}).keys())
        if not cases:
            continue
        counts = evaluate_cases(d, cases, runner=runner, c=c)
        out[name] = {k: (v2["passes"] * 2 > v2["runs"]) for k, v2 in counts.items()}
    return out


def _pattern_of(prop):
    """The tool sequence a proposal was mined from, [] when it has none."""
    pat = (prop or {}).get("pattern")
    return [str(x) for x in pat] if isinstance(pat, list) else []


def _archived_skill_md(name, pattern, purpose, rel, origin, evidence=None):
    """The SKILL.md an INSTALLED skill carries (one owner of the archived text).

    v717: promotion copied the DRAFT verbatim, so the installed skill still said
    "DRAFT — not verified, not archived" and told the agent to verify/promote the
    folder it was already living in — while the purpose the operator wrote was
    dropped. The archived text says what the skill is for, the sequence, and its
    real state.
    """
    text = str(purpose or "").strip()
    lines = ["# %s" % name, ""]
    lines += [text or "A repeated tool sequence the harness observed (no stated purpose).", ""]
    if pattern:
        lines += ["## Sequence", ""]
        lines += ["%d. `%s`" % (i + 1, t) for i, t in enumerate(pattern)]
        lines += [""]
    lines += ["## Status", "",
              "ARCHIVED — verified green and installed at `%s` (origin: %s%s)."
              % (rel, origin or "auto",
                 ", evidence: %s" % evidence if evidence else ""), ""]
    return "\n".join(lines)


def _retired_root(root):
    """Where a superseded skill goes: `<skills>/_retired`.

    Deliberately two directory levels ABOVE the `skills/<category>/<name>/SKILL.md`
    shape `list_skills` scans, so a retired folder is preserved for audit and a
    manual restore but never surfaces as an active skill again (`_retired/<cat>`
    holds no `SKILL.md`, so the loader skips it).
    """
    return os.path.join(root, "_retired")


def _retire_skill(target, root, category, name, by="", reason=""):
    """Move an installed skill ASIDE so a promotion can take its name (v823).

    Never deletes: the folder keeps its `SKILL.md` and `proposal.json` under
    `<root>/_retired/<category>/<name>-<stamp>/`, and one append-only line in
    `<root>/_retired/ledger.jsonl` records who replaced what, when, at which
    content digest (`prev_sha256`) and why. Returns {ok, retired_to, prev_sha256}.
    """
    import hashlib
    import shutil
    dest_dir = os.path.join(_retired_root(root), category)
    try:
        os.makedirs(dest_dir, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
        dest = os.path.join(dest_dir, "%s-%s" % (name, stamp))
        n = 1
        while os.path.exists(dest):
            dest = os.path.join(dest_dir, "%s-%s-%d" % (name, stamp, n))
            n += 1
        prev_sha = ""
        try:
            with open(os.path.join(target, "SKILL.md"), "rb") as f:
                prev_sha = hashlib.sha256(f.read()).hexdigest()
        except OSError:
            pass
        shutil.move(target, dest)
        rel = os.path.relpath(dest, root)
        line = {"ts": round(time.time(), 3),
                "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "name": name, "category": category, "retired_to": rel,
                "by": by or "?", "reason": (reason or "")[:300],
                "prev_sha256": prev_sha}
        with open(os.path.join(_retired_root(root), "ledger.jsonl"), "a",
                  encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
        return {"ok": True, "retired_to": rel, "prev_sha256": prev_sha}
    except OSError as e:
        return {"ok": False, "error": str(e)}


def promote(proposal_dir, skills_dir=None, c=None, human=False, purpose="",
            reason="", runner=None, supersede=False):
    """Archive a VERIFIED proposal into skills/<category>/<name>/ (write-gate).

    Rejects if the status is not `verified`. Does not overwrite — UNLESS
    `supersede` is set, in which case an installed skill of the same name is
    RETIRED (moved to `<skills>/_retired/`, recorded in the ledger and on the new
    proposal) and the promotion takes its place. Returns {"ok",...} or
    {"ok": False, "error": ...}.

    `human=True` is the OPERATOR path (an approved proposal in the WebUI): the
    sandbox check still has to be green, but the sealed held-out suite is not
    required — a person looking at the draft IS the independent judge, which is
    what the RDD gate protects against (the machine certifying itself). The
    release is stamped on the proposal (who, when, why, which evidence) so a
    later audit can identify it; a release with no reason at all is refused.

    `runner` (optional) re-checks the installed copy once (`attribute`), so an
    install that rewrote the artifact cannot pass silently.
    """
    c = c or cfg()
    _rel_reason = str(reason or purpose or "").strip()
    if human and not _rel_reason:
        return {"ok": False,
                "error": "operator release needs a reason — pass `reason` (or the "
                         "proposal's purpose) so the release is attributable"}
    prop_path = os.path.join(proposal_dir, "proposal.json")
    prop = _read_json(prop_path) or {}
    if prop.get("status") != "verified":
        return {"ok": False, "error": "proposal not verified (status=%s)"
                % prop.get("status", "?")}
    # F5 (Maka thresholded release): the bar. A single lucky green does not
    # release — the streak must reach min_green_streak. A legacy `verified`
    # proposal without a streak key counts as 1: the verify that set the
    # status WAS a green, it just was not counted yet. Invalid bar configs
    # fail closed (rate_limit precedent).
    try:
        _bar = int((c.get("min_green_streak") if c else None) or 1)
    except (TypeError, ValueError):
        return {"ok": False,
                "error": "invalid min_green_streak config %r (expected a positive int)"
                % ((c.get("min_green_streak") if c else None),)}
    _bar = max(1, _bar)
    _streak = prop.get("green_streak")
    if _streak is None:
        _streak = 1
    try:
        _streak = int(_streak)
    except (TypeError, ValueError):
        _streak = 0
    if _streak < _bar:
        return {"ok": False, "streak": _streak, "bar": _bar,
                "error": "patience: proposal needs %d consecutive green verifies "
                         "(streak=%d) — run verify again" % (_bar, _streak)}
    # CASE-TABLE GATE (SAGE direction): one green check is not evidence that the
    # artifact did not break something that used to work. With a baseline, refuse
    # any dropped case and require at least one gained; without one, say so
    # instead of dressing a single case up as a statistical result.
    _verify = prop.get("verify") if isinstance(prop.get("verify"), dict) else {}
    _cases = _verify.get("cases") if isinstance(_verify.get("cases"), dict) else {}
    _base = _verify.get("baseline") if isinstance(_verify.get("baseline"), dict) else {}
    # CONSISTENCY GATE (AReaL-RSI eq.11 — version-consistent publication): every
    # gate below reads the STORED numbers, not the current files, so a draft
    # EDITED between `verify` and this promote would publish an artifact whose
    # green runs describe a version that no longer exists. `verify` stamped the
    # digest of the bytes it ran; recompute it here and refuse on a mismatch. A
    # legacy proposal that never stamped one (predates the gate) passes, exactly
    # as the case gate treats a missing baseline.
    _stamp = _verify.get("artifact_sha256")
    if _stamp:
        _now = _artifact_digest(proposal_dir)
        if _now != str(_stamp):
            return {"ok": False, "verified_sha256": _stamp, "current_sha256": _now,
                    "error": "consistency gate: the artifact changed after it was "
                             "verified (%s -> %s) — the evidence describes the earlier "
                             "bytes; run verify again before promoting"
                             % (str(_stamp)[:12], str(_now)[:12])}
    if _base:
        _regressed = sorted(k for k, ok in _base.items() if ok and not _cases.get(k))
        if _regressed:
            return {"ok": False, "regressions": _regressed,
                    "error": "case gate: %s regressed — a promotion may not break a "
                             "case that used to pass" % ", ".join(_regressed)}
        if sum(1 for v in _cases.values() if v) <= sum(1 for v in _base.values() if v):
            return {"ok": False,
                    "error": "case gate: no case improved over the baseline"}
        evidence = "cases"
    elif os.environ.get("LONGRUN_EVOLVE_CASES") == "1" and len(_cases) < 2:
        return {"ok": False,
                "error": "case gate: %d case(s) verified — at least 2 are required "
                         "while LONGRUN_EVOLVE_CASES=1" % len(_cases)}
    else:
        evidence = "single-case" if len(_cases) < 2 else "cases-no-baseline"
    # EVIDENCE GATE (RSI-V, TRUST 2611.10787): the case table above is a set of
    # booleans, so a case that passes 2 of 3 repeats promotes exactly like 3 of 3.
    # Where `verify` ran repeats, each case must beat a fair coin at
    # `promotion_alpha`; a case verified once is named `single_run` and carries no
    # bound rather than a fabricated one. The greedy gate the paper measured
    # accepted an inferior update in 45.59% of rounds — this is the quantity that
    # number is about.
    _bound = _promotion_bound(_cases, _verify.get("case_runs") or {}, c)
    if _bound["verdict"] == "refused":
        return {"ok": False, "bound": _bound,
                "error": "evidence gate: %s did not clear alpha=%.3f over its "
                         "repeats — verify again with more repeats before promoting"
                         % (", ".join(_bound["failed"]), _bound["alpha"])}
    name = prop.get("name") or os.path.basename(proposal_dir)
    # The skills root is a PATH, not a constant: a test (or a different install)
    # points it elsewhere with LONGRUN_SKILLS_DIR instead of writing into the
    # checkout. Default stays the repo's skills/ library.
    root = (skills_dir or os.environ.get("LONGRUN_SKILLS_DIR")
            or os.path.join(REPO, "skills"))
    category = str(c.get("category") or "created")
    target = os.path.join(root, category, name)
    # JAG-426 safety boundary 1: the built-in library is IMMUTABLE — an auto skill
    # may never land in (or overwrite) skills/core/**.
    if _under(target, os.path.join(root, "core")):
        return {"ok": False, "error": "refusing to write into skills/core (built-in skills are immutable)"}
    # JAG-426 safety boundary 2: a machine-generated skill may ONLY live under
    # skills/created/, and only within the quota. DR-M: the QUOTA is a hard cap, so
    # it is answered BEFORE the cost heuristic — at the cap nothing can be released
    # whatever its price, and the old order reported "cost gate" for an artifact
    # that was never going to fit (v416).
    if prop.get("origin") == "auto":
        box = os.path.join(root, "created")
        if not _under(target, box):
            return {"ok": False,
                    "error": "an auto-generated skill must be promoted under skills/created (got category %r)" % category}
        existing = [d for d in os.listdir(box)] if os.path.isdir(box) else []
        if len(existing) >= AUTO_SKILL_CAP:
            return {"ok": False,
                    "error": "skills/created quota reached (%d) — prune before promoting" % AUTO_SKILL_CAP}
    # COST GATE (HarnessPro 2610.26770, Harmony 2610.15150): quality and cost are
    # one objective. The skill's own markdown is what enters the prompt on every
    # turn, so a candidate that is an OUTLIER against the installed set may not
    # be promoted automatically — the operator can still release it.
    _cost = int((_verify.get("cost_tokens") or {}).get("tokens") or 0)
    _median, _samples = _installed_cost_baseline(str(c.get("category") or "created"),
                                                 skills_dir)
    # DR-M: the basis is WRITTEN on the artifact, so a promotion never hides which
    # of these three happened. `None` is not "cheap": it is "nothing installed to
    # compare against", and refusing it would make the first install — the one
    # that CREATES the baseline — impossible.
    _cost_basis = ("no-baseline" if _median is None
                   else ("weak-median(n=%d)" % _samples if _samples < 3
                         else "median(n=%d)" % _samples))
    try:
        _ratio = float(c.get("max_cost_ratio") or 2.0)
    except (TypeError, ValueError):
        _ratio = 2.0
    _skipped = []
    # DR-M: a median from fewer than three samples is a weak baseline in BOTH
    # directions — it used to fail OPEN (no gate at all). It must not fail CLOSED
    # on a stub corpus either: v598 archives two 55-token stubs and a real 209-token
    # skill (3.8x) was refused. A weak median therefore needs TWICE the normal
    # deviation before it refuses; the gate still fires on a true outlier (v919 A/B
    # are 33-40x).
    _eff_ratio = _ratio if _samples >= 3 else _ratio * 2.0
    if _median is not None and _cost > _median * _eff_ratio:
        if human:
            _skipped.append("cost")
        else:
            return {"ok": False, "cost_tokens": _cost, "median_tokens": _median,
                    "cost_basis": _cost_basis,
                    "error": "cost gate: %d prompt tokens against a %d-token median "
                             "across installed artifacts (> x%.1f) — release it as the "
                             "operator if it is worth the prompt budget"
                             % (_cost, _median, _eff_ratio)}
    # RDD point 2: sealed held-out gate (fail-closed). The local verifier
    # (check.py) is NOT enough: promotion requires the external judge suite.
    from longrun.plan import heldout
    _heldout_required = heldout.require_enabled()
    if _heldout_required and human:
        _skipped.append("heldout")
    if _heldout_required and not human:
        g = heldout.gate(proposal_dir, c=c)
        if not g.get("green"):
            why = str(g.get("reason") or "")
            if why == "canary_tripped":
                # PROCTOR §5.5 (S-2026-11-18-007): a canary is a held-out case no
                # honest candidate can pass, so a PASS on it is evidence of label or
                # sandbox leakage, not of quality — refuse, and name the canary.
                return {"ok": False, "canary": g.get("canary"), "gate": g,
                        "error": "canary integrity: an unpassable case passed — "
                                 "refusing promotion (suspected label/sandbox leakage)"}
            # v645: "no_manifest" is not a defect of the draft — it means the
            # sealed judge suite was never installed, so NOTHING can be promoted
            # (the automatic path fails the same way). Say that instead of
            # leaving the operator with a dead accept button.
            hint = (" — the sealed judge suite is not installed (data/heldout/manifest.json); "
                    "run the admin step once: "
                    "python3 -c \"from longrun.plan import heldout; print(heldout.install())\""
                    ) if why == "no_manifest" else ""
            return {"ok": False, "gate": g,
                    "error": "held-out gate not green (%s)%s" % (why, hint)}
    superseded = None
    _collides = os.path.exists(target)
    if _collides and not supersede:
        return {"ok": False, "error": "target already exists: %s" % target}
    # COMPOSED-SET SMOKE (Compositional Safety 2609.33123): `verify` checks the
    # candidate ALONE; this re-checks the artifacts already installed, because
    # edits that are safe alone can compose into unsafe behaviour. Opt-in
    # (`smoke_set`) or automatic when a runner is injected — it runs every stored
    # case of every artifact, so it is not free.
    if c.get("smoke_set") or runner is not None:
        try:
            suite = smoke_installed(root, runner=runner, c=c, category=category)
        except Exception:  # noqa: BLE001 — a smoke must never break a release
            suite = {}
        _red = {n: [k for k, ok in rows.items() if not ok]
                for n, rows in suite.items() if not all(rows.values())}
        if _red:
            return {"ok": False, "smoke": _red,
                    "error": "composed-set smoke red: %s — fix or retire the named "
                             "artifact before promoting" % ", ".join(sorted(_red))}
    # The video's lifecycle (v823): an improvement that collides with the installed
    # name RETIRES the version it replaces instead of being refused. Staged OUTSIDE
    # the library and swapped in, so no failure after the retire can leave the
    # installed skill missing. Never deleted: the folder and one ledger line record
    # the replacement, and the default stays a refusal (nothing is clobbered
    # silently).
    import shutil
    import tempfile
    from longrun.memory import skills as skills_mod
    _stage = tempfile.mkdtemp(prefix="promote-stage-")
    try:
        _staged = os.path.join(_stage, name)
        got = skills_mod.install_skill_dir(proposal_dir, _staged)
        if not got.get("ok"):
            return got
        if _collides:
            superseded = _retire_skill(target, root, category, name,
                                       by=("operator" if human else "auto"),
                                       reason=_rel_reason or purpose)
            if not superseded.get("ok"):
                return {"ok": False, "error": "cannot retire the existing skill: %s"
                        % superseded.get("error")}
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.move(_staged, target)
        except OSError as e:
            # The swap failed: put the retired skill back — nothing is lost.
            if superseded:
                try:
                    shutil.move(os.path.join(root, superseded["retired_to"]), target)
                except OSError:
                    pass
            return {"ok": False, "error": "install failed: %s" % e}
    finally:
        shutil.rmtree(_stage, ignore_errors=True)
    prop["status"] = "archived"
    prop["evidence"] = evidence
    prop["promotion_bound"] = _bound
    prop["cost_tokens"] = _cost
    # DR-M: which bar judged the cost, and which bars an operator release skipped.
    prop["cost_basis"] = _cost_basis
    if human:
        prop["released_by"] = "operator"
        prop["released_ts"] = round(time.time(), 3)
        prop["released_reason"] = _rel_reason[:300]
        prop["release_skipped"] = list(_skipped)
    _under_repo = os.path.abspath(target).startswith(os.path.abspath(REPO) + os.sep)
    prop["archived_to"] = (os.path.relpath(target, REPO) if _under_repo else target)
    if superseded:
        # One record on the NEW proposal, so the artifact names what it replaced.
        prop["supersedes"] = {"name": name, "retired_to": superseded["retired_to"],
                              "prev_sha256": superseded["prev_sha256"],
                              "by": "operator" if human else "auto"}
    _write_json(prop_path, prop)
    _write_json(os.path.join(target, "proposal.json"), prop)
    # v717: the archived SKILL.md states the purpose and the REAL state (the draft
    # text said "not archived" inside the installed skill).
    try:
        with open(os.path.join(target, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write(_archived_skill_md(name, _pattern_of(prop), purpose,
                                       prop["archived_to"], prop.get("origin"),
                                       evidence=evidence))
        skills_mod.list_skills(reload=True)
    except OSError:
        pass
    # ATTRIBUTION (Harness-Delta 2610.22466): store which case this artifact
    # fixed/broke, at what prompt cost; with a runner, confirm the INSTALLED copy
    # behaves like the verified draft.
    attr = attribute(target, runner=runner, c=c)
    out = {"ok": True, "name": name, "path": target,
           "rel": prop["archived_to"], "evidence": evidence,
           "cost_tokens": _cost, "cost_basis": _cost_basis, "attribution": attr}
    if superseded:
        out["superseded"] = superseded
    # THE CHANGELOG HOLE (measured 2026-11-14): `improve.decide` recorded the
    # operator's DECISION in the improvement ledger, but the install itself — the
    # bytes that landed in skills/<category>/<name>/ — was recorded nowhere, so the
    # automatic path (evolve → pipeline → promote) could change the skill set with
    # no audit line at all. One row per install, whichever path produced it; the
    # `decide` row stays the decision, this one is the artifact.
    try:
        from longrun.util import improve as _imp
        _imp.ledger_add("promote", origin=("operator" if human else str(prop.get("origin") or "auto")),
                        artifact_kind="skill", name=name, path=prop["archived_to"],
                        evidence=evidence, cost_tokens=_cost,
                        superseded=(superseded or {}).get("retired_to") or "",
                        reason=_rel_reason[:300])
    except Exception:  # noqa: BLE001 — the audit must never break a release
        pass
    return out


MATRIX_FORGE_NS = "learned"


def _forge_slug(pattern):
    """Filesystem-safe, stable name for one mined sequence (same pattern, same name)."""
    import hashlib
    joined = "|".join(str(t) for t in pattern)
    digest = hashlib.sha1(joined.encode("utf-8")).hexdigest()[:8]
    base = re.sub(r"[^a-z0-9]+", "_", joined.lower()).strip("_")[:40].strip("_")
    return "%s_%s" % (base or "seq", digest)


ABSTRACT_SYSTEM = (
    "You name CAPABILITIES, not steps. You are given a tool sequence that one "
    "agent harness executed in the same order across several independent runs, "
    "plus one line per tool taken from the harness's own catalogue. Decide "
    "whether the repetition MEANS something: a compact, reusable capability the "
    "harness was missing. A retry, a habit, a single-tool loop, or a sequence "
    "that only restates one existing tool is NOT a capability. Answer with ONE "
    "JSON object and nothing else: "
    '{"compact": true|false, "name": "<2-4 words, snake_case>", '
    '"goal": "<one sentence: what the caller gets>", '
    '"why": "<one sentence: the evidence in the sequence>", '
    '"confidence": <0.0-1.0>}.'
)


def _tool_brief(names):
    """One line per tool, from the registry's own description (nothing invented)."""
    try:
        from longrun.tools import registry
        cat = {str(r.get("name")): str(r.get("description") or "")
               for r in registry.catalog()}
    except Exception:  # noqa: BLE001 — a prompt must never fail on the catalogue
        cat = {}
    return {str(n): (cat.get(str(n)) or "")[:240] for n in (names or [])}


def semantic_namespace(pattern, name):
    """The Matrix namespace of a SEMANTICALLY named pattern (readable + unique).

    EV-22: the meaning names the tool (`learned_<name>_<hash8>`), and the short
    hash of the sequence keeps two different procedures that were named alike
    from colliding, so "already forged" stays a truthful answer.
    """
    base = re.sub(r"[^a-z0-9]+", "_", str(name or "").lower()).strip("_")[:40].strip("_")
    if not base:
        return ""
    return "%s_%s_%s" % (MATRIX_FORGE_NS, base, _forge_slug(pattern).rsplit("_", 1)[-1])


def _abstract_prompt(pattern, support, briefs):
    payload = {"sequence": list(pattern), "repeated_across_runs": int(support),
               "tools": briefs}
    return [{"role": "system", "content": ABSTRACT_SYSTEM},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]


def _norm_abstract(data, pattern):
    """Normalise a model answer into the record a draft stores (no trust in it)."""
    try:
        conf = max(0.0, min(1.0, float(data.get("confidence"))))
    except (TypeError, ValueError):
        conf = 0.0
    compact = bool(data.get("compact"))
    raw = str(data.get("name") or "")
    name = re.sub(r"[^a-z0-9]+", "_", raw.lower()).strip("_")[:40].strip("_")
    goal = " ".join(str(data.get("goal") or "").split())[:240]
    why = " ".join(str(data.get("why") or "").split())[:240]
    return {"compact": compact, "name": name if compact else "",
            "namespace": semantic_namespace(pattern, name) if compact and name else "",
            "goal": goal, "why": why, "confidence": round(conf, 3)}


def abstract(pattern, support=0, draft="", model=None, call=None, timeout=None,
             write=True):
    """Name the capability a repeated sequence IS — the ring ③ that was missing.

    EV-22 (arXiv 2606.02994 ARISE, Agent Workflow Memory): a repeat becomes a
    subroutine only after something reads it as a PROCEDURE and states its goal.
    Until now a forge replayed the steps and named itself after them.

    One single-shot model call, injectable as `call(msgs, model, timeout) ->
    (answer, model_used)` so a test is deterministic. Failure is fail-OPEN on
    naming (`ok: False`, `compact: True`) because an unreachable model must not
    stop the lane — the forge is still tested and verified — and fail-CLOSED on
    code, which the forge gate already owns. Never raises.
    """
    steps = [str(t).strip() for t in (pattern or []) if str(t).strip()]
    if len(steps) < 2:
        return {"ok": False, "compact": False, "confidence": 0.0,
                "error": "abstraction needs at least 2 steps (got %d)" % len(steps),
                "steps": steps}
    c = cfg()
    try:
        tmo = float(timeout if timeout is not None else (c.get("abstract_timeout") or 60))
    except (TypeError, ValueError):
        tmo = 60.0
    msgs = _abstract_prompt(steps, support, _tool_brief(steps))
    try:
        if call is not None:
            answer, used = call(msgs, model, tmo)
        else:
            from longrun.util import improve as _imp
            answer, used = _imp.single_shot(msgs, model=model, role="reviewer",
                                            timeout=tmo, max_tokens=700)
    except Exception as e:  # noqa: BLE001 — the lane must survive a dead model
        return {"ok": False, "compact": True, "confidence": 0.0, "name": "",
                "namespace": "", "goal": "", "why": "", "model": "",
                "error": "abstraction unavailable: %s" % e, "steps": steps}
    from longrun.util.textkit import _iter_json_objects
    data = {}
    for obj in _iter_json_objects(str(answer or "")):
        if isinstance(obj, dict) and ("compact" in obj or "name" in obj):
            data = obj
            break
    if not data:
        return {"ok": False, "compact": True, "confidence": 0.0, "name": "",
                "namespace": "", "goal": "", "why": "", "model": str(used or ""),
                "error": "the model's answer carried no JSON verdict",
                "steps": steps}
    rec = _norm_abstract(data, steps)
    rec.update({"ok": True, "model": str(used or ""), "steps": steps,
                "raw": " ".join(str(answer or "").split())[:400]})
    if write and draft:
        prop_path = os.path.join(str(draft), "proposal.json")
        prop = _read_json(prop_path) or {}
        if prop:
            rec["ts"] = round(time.time(), 3)
            prop["abstract"] = dict(rec, ts=rec["ts"])
            # One truth: the purpose the forge/promote path already reads is the
            # goal the model stated, so the draft says what it is for.
            if rec.get("compact") and rec.get("goal") and \
                    not str(prop.get("purpose") or "").strip():
                prop["purpose"] = rec["goal"]
            try:
                _write_json(prop_path, prop)
            except OSError:
                pass
    try:
        from longrun.util import improve as _imp
        _imp.ledger_add("abstract", origin="mining",
                        draft=os.path.basename(str(draft or "")) or "",
                        pattern=steps, name=rec.get("name"),
                        compact=rec.get("compact"),
                        confidence=rec.get("confidence"), ok=bool(rec.get("ok")),
                        error=rec.get("error"))
    except Exception:  # noqa: BLE001 — the ledger must never break the lane
        pass
    return rec


def draft_abstract(proposal_dir):
    """The abstraction recorded on a draft (or `{}`) — one owner of the read."""
    prop = _read_json(os.path.join(str(proposal_dir), "proposal.json")) or {}
    ab = prop.get("abstract")
    return dict(ab) if isinstance(ab, dict) else {}


def _forge_body(ns, full, steps, description, support, origin):
    """The REAL module a forged tool ships (the scaffold stub is a placeholder).

    One owner of the generated code, so the file and the test that proves it can
    never disagree: the test imports THIS module and pins the refusal paths.
    Three literal chunks, formatted only where a value must be inserted — a single
    big format string made the generated `%d` of the runtime report ambiguous.
    """
    head = (
        '"""Matrix tool forged from a mined tool sequence (Longrun self-evolve).\n'
        "\n"
        "Sequence: %s\n"
        "Support: %d run(s). Origin: %s.\n"
        "\n"
        "Each step runs through `longrun.tools.tools.execute`, so the harness's own\n"
        "approval policy still applies to every single step: this module never bypasses\n"
        "a gate, it only removes the need to retype the sequence.\n"
        '"""\n'
        "\n"
        "STEPS = %r\n"
        "\n"
    ) % (" \u2192 ".join(steps), int(support or 0), origin or "mined draft", list(steps))
    schema = (
        "TOOL_SCHEMAS = {\n"
        "    %r: {\n"
        '        "description": %r,\n'
        '        "type": "object",\n'
        '        "properties": {\n'
        '            "inputs": {\n'
        '                "type": "array",\n'
        '                "description": "one argument object per step, in STEP order",\n'
        "            },\n"
        "        },\n"
        '        "required": ["inputs"],\n'
        '        "approval": "auto",\n'
        "    },\n"
        "}\n"
        "TOOL_SCHEMA = dict(TOOL_SCHEMAS[%r])\n"
        "\n"
        "\n"
    ) % (full, description, full)
    body = (
        "def execute(args, run_id=None, subtool=None):\n"
        '    """Run the mined sequence with the caller\'s arguments, in order."""\n'
        "    args = args or {}\n"
        '    inputs = args.get("inputs")\n'
        "    if not isinstance(inputs, list) or len(inputs) != len(STEPS):\n"
        '        return {"ok": False, "exit_code": 64,\n'
        '                "error": "`inputs` must be a list of %d argument objects "\n'
        '                         "(one per step)" % len(STEPS),\n'
        '                "steps": list(STEPS)}\n'
        "    from longrun.tools import tools as _tools\n"
        "    out = []\n"
        "    for name, step_args in zip(STEPS, inputs):\n"
        "        if not isinstance(step_args, dict):\n"
        '            out.append({"tool": name, "ok": False,\n'
        '                        "error": "step arguments must be an object"})\n'
        "            break\n"
        "        try:\n"
        "            res = _tools.execute(name, step_args, run_id=run_id) or {}\n"
        "        except Exception as e:  # noqa: BLE001 — one broken step must not hide the rest\n"
        '            out.append({"tool": name, "ok": False, "error": str(e)})\n'
        "            break\n"
        '        ok = bool(res.get("ok", res.get("exit_code") == 0))\n'
        '        out.append({"tool": name, "ok": ok})\n'
        "        if not ok:\n"
        "            break\n"
        "    done = sum(1 for s in out if s[\"ok\"])\n"
        '    return {"ok": len(out) == len(STEPS) and done == len(STEPS),\n'
        '            "steps": out, "ok_count": done, "step_count": len(STEPS),\n'
        '            "stdout": "%d/%d step(s) executed" % (done, len(STEPS))}\n'
    )
    return head + schema + body


def _forge_test(ns, full, steps):
    """A deterministic proof of the forged tool's BEHAVIOUR, not just its refusals.

    arXiv 2610.15964 ("Small but Mighty"): a refusal-only check is too sparse to
    catch a behaviour-changing rewrite — the repository's own tests rejected only
    25.3% of them. So this proof pins, with the dispatcher stubbed (no side
    effects, nothing executed for real):

        order of the steps · the arguments passed to each step · a failing step
        stops the run · the ok-count · the three refusals

    Every assertion is about the bytes that were just written, so a forged tool
    that drifts from its sequence can never pass its own gate.
    """
    head = (
        '"""Generated proof for the forged tool %s (behaviour, dispatcher stubbed)."""\n'
        "import sys\n"
        "import types\n"
        "\n"
        "from Matrix.tools import %s as M\n"
        "\n"
        'assert callable(getattr(M, "execute", None)), "execute is not callable"\n'
        "assert M.STEPS == %r, M.STEPS\n"
        "SEEN = []\n"
        "\n"
        "\n"
        "def _record_ok(name, args, run_id=None):\n"
        "    SEEN.append((name, dict(args or {})))\n"
        '    return {"ok": True}\n'
        "\n"
        "\n"
        "def _fail_second(name, args, run_id=None):\n"
        "    SEEN.append((name, dict(args or {})))\n"
        '    return {"ok": len(SEEN) < 2}\n'
        "\n"
        "\n"
        "# The dispatcher is stubbed through sys.modules, so the proof needs neither\n"
        "# the harness installed nor a config: nothing real can run from here.\n"
        "def _stub(fn):\n"
        '    pkg = types.ModuleType("longrun")\n'
        "    pkg.__path__ = []\n"
        '    sub = types.ModuleType("longrun.tools")\n'
        "    sub.__path__ = []\n"
        '    mod = types.ModuleType("longrun.tools.tools")\n'
        "    mod.execute = fn\n"
        "    sub.tools = mod\n"
        '    sys.modules["longrun"] = pkg\n'
        '    sys.modules["longrun.tools"] = sub\n'
        '    sys.modules["longrun.tools.tools"] = mod\n'
        "\n"
    ) % (full, ns, list(steps))
    body = (
        "# 1) the whole sequence runs, in order, with the caller's arguments\n"
        "_stub(_record_ok)\n"
        "ARGS = [{\"i\": i} for i in range(len(M.STEPS))]\n"
        'r = M.execute({"inputs": ARGS}, run_id="forge-test")\n'
        'assert r.get("ok") is True, r\n'
        "assert [s[0] for s in SEEN] == list(M.STEPS), SEEN\n"
        "assert [s[1] for s in SEEN] == ARGS, SEEN\n"
        'assert r.get("ok_count") == len(M.STEPS), r\n'
        "# 2) a failing step stops the run (no silent continuation)\n"
        "SEEN.clear()\n"
        "_stub(_fail_second)\n"
        'r = M.execute({"inputs": ARGS}, run_id="forge-test")\n'
        'assert r.get("ok") is False, r\n'
        "assert len(SEEN) == 2, SEEN\n"
        'assert r.get("ok_count") == 1, r\n'
        "# 3) the refusals still hold\n"
        'r = M.execute({}, run_id="forge-test")\n'
        'assert r.get("ok") is False and "inputs" in str(r.get("error")), r\n'
        'r = M.execute({"inputs": []}, run_id="forge-test")\n'
        'assert r.get("ok") is False, r\n'
        'r = M.execute({"inputs": [{}] * (len(M.STEPS) + 1)}, run_id="forge-test")\n'
        'assert r.get("ok") is False, r\n'
        'print("ok: behaviour pinned for", len(M.STEPS), "steps")\n'
    )
    return head + body


def forge_target(pattern, name="", repo_root=None):
    """The module a forge of THIS pattern writes, and its namespace.

    One owner of the naming rule: `forge_matrix` writes there, and `evolve` asks
    here whether a pattern was already forged (so "already done" is not reported
    as a clobber refusal).
    """
    from longrun.core import matrix as mtx
    steps = [str(t).strip() for t in (pattern or []) if str(t).strip()]
    ns = str(name or "").strip() or (MATRIX_FORGE_NS + "_" + _forge_slug(steps))
    ns = re.sub(r"[^a-zA-Z0-9_]", "_", ns).strip("_")
    _root, msrc, _mdot = mtx._roots(repo_root)
    return os.path.join(msrc, "tools", ns + ".py"), ns


def forge_bundle(pattern, support=0, draft="", name="", description="",
                 repo_root=None):
    """The artifact bundle a forge WOULD write, built and validated (no write).

    One owner of the generated module: `forge_matrix` writes exactly these bytes
    and `evolve` can put them in front of the operator as a pending `matrix`
    proposal instead of landing code on its own. Same validation on both paths,
    so a proposal can never carry a bundle a forge would have refused.
    """
    import hashlib
    steps = [str(t).strip() for t in (pattern or []) if str(t).strip()]
    if len(steps) < 2:
        return {"ok": False, "error": "a forged tool needs at least 2 steps (got %d)"
                                      " — a single-tool repeat is a loop" % len(steps)}
    known = set(_known_tools())
    bad = [t for t in steps if not _dispatchable(t, known)]
    if bad:
        return {"ok": False, "error": "not replayable: %s" % ", ".join(bad)}
    fpath, ns = forge_target(steps, name, repo_root)
    full = "%s.run" % ns
    desc = str(description or "").strip() or (
        "Replay the mined tool sequence %s in order: `inputs` carries one argument "
        "object per step, the run stops at the first failure, and every step keeps "
        "its own approval policy." % " \u2192 ".join(steps))
    origin = os.path.basename(str(draft or "")) or "mined draft"
    body = _forge_body(ns, full, steps, desc, support, origin)
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return {"ok": True, "matrix_tool": full, "namespace": ns, "path": fpath,
            "steps": steps, "sha256": digest, "description": desc,
            # `matrix_tool` is the kind the learned-artifact owner accepts
            # (`_LEARNING_KINDS`); the hash is what the approval binds.
            "artifacts": [{"kind": "matrix_tool", "name": ns, "content": body,
                           "sha256": digest}]}


def forge_matrix(pattern, support=0, draft="", name="", description="",
                 repo_root=None):
    """Turn a REPLAYABLE mined sequence into a tested Matrix tool (EV-11).

    The mining lane ended at `ledger.jsonl`: a green recurring pattern became a
    skill or nothing. This is its executive arm — Matrix is the live, revisable
    code zone, so the artifact is a real tool that replays the sequence and
    carries its own proof:

        scaffold (compliant skeleton)
          -> overwrite with the REAL body (a placeholder is refused at load)
          -> matrix.run_test with a generated, side-effect free test
          -> matrix.verify_target (the sha-bound contract gate)
          -> kept only when green; removed otherwise

    It never invents arguments: the caller supplies one argument object per step,
    and every step still passes the harness's own approval policy. Nucleous is
    untouched (`promote_to_nucleous` keeps its own checkbox).
    """
    from longrun.core import matrix as mtx
    bnd = forge_bundle(pattern, support=support, draft=draft, name=name,
                       description=description, repo_root=repo_root)
    if not bnd.get("ok"):
        return bnd
    steps, ns, full = bnd["steps"], bnd["namespace"], bnd["matrix_tool"]
    fpath, body = bnd["path"], bnd["artifacts"][0]["content"]
    if not mtx.is_enabled():
        return {"ok": False, "error": "Matrix is disabled — enable it before forging"}
    if os.path.exists(fpath):
        return {"ok": False, "error": "refusing to clobber %s (matrix.remove it first)"
                                      % fpath}
    sc = mtx.scaffold("tool", full, description=bnd["description"], repo_root=repo_root)
    if not sc.get("ok"):
        return {"ok": False, "error": "scaffold refused: %s" % sc.get("error"), "scaffold": sc}
    try:
        with open(fpath, "w", encoding="utf-8", newline="\n") as f:
            f.write(body)
    except OSError as e:
        return {"ok": False, "error": "write failed: %s" % e, "path": fpath}
    hl = mtx.hotload(repo_root)
    test = mtx.run_test("forge_%s.py" % ns, code=_forge_test(ns, full, steps),
                        target="tool:%s" % ns, timeout_secs=60, repo_root=repo_root)
    ver = mtx.verify_target("tool", ns, repo_root=repo_root) if test.get("ok") else {}
    ok = bool(test.get("ok")) and bool(ver.get("ok"))
    # EV-14: the field is `matrix_tool`, not `tool` — the dispatch envelope owns
    # `tool` (it is the executed tool's canonical name) and overwrites it, which
    # made every caller read "improve.forge" instead of the tool that was created.
    result = {"ok": ok, "matrix_tool": full, "namespace": ns, "path": fpath,
              "steps": steps, "sha256": bnd["sha256"],
              "load": {"ok": hl.get("ok"), "errors": hl.get("errors") or []},
              "test": {k: test.get(k) for k in ("ok", "exit_code", "stdout",
                                                "stderr", "path", "duration_ms")},
              "verify": {k: ver.get(k) for k in ("ok", "error", "sha256")}}
    if not ok:
        # Fail closed: a tool that cannot prove itself does not stay loaded.
        rem = mtx.remove("tool", ns, repo_root=repo_root)
        result["removed"] = bool(rem.get("ok"))
        result["error"] = (test.get("stderr") or test.get("error")
                           or ver.get("error") or "the forged tool did not verify")
        return result
    result["stdout"] = "forged %s (%d steps), tested and verified" % (full, len(steps))
    return result


def forge_from_draft(proposal_dir, name="", description=""):
    """Forge the Matrix tool of ONE mined draft, and record the outcome on it.

    The draft is the input (it already owns a replayable pattern); the ledger and
    the draft's own `matrix_tool` field are the output, so `improve{forge}` and
    any future caller share one implementation.
    """
    prop_path = os.path.join(proposal_dir, "proposal.json")
    prop = _read_json(prop_path) or {}
    if not prop:
        return {"ok": False, "error": "no proposal.json in %s" % proposal_dir}
    pattern = _pattern_of(prop)
    ab = prop.get("abstract") if isinstance(prop.get("abstract"), dict) else {}
    # EV-22: the name the abstraction step recorded wins, so the module is called
    # after its MEANING; an explicit caller still overrides it.
    ns = str(ab.get("namespace") or "") if ab.get("compact") else ""
    res = forge_matrix(pattern, support=int(prop.get("support") or 0), draft=proposal_dir,
                       name=name or ns,
                       description=(description or str(ab.get("goal") or "")
                                    or str(prop.get("purpose") or "")))
    prop["matrix_tool"] = ({"matrix_tool": res.get("matrix_tool"),
                            "namespace": res.get("namespace"),
                            "path": res.get("path"), "ok": bool(res.get("ok")),
                            "steps": res.get("steps") or pattern,
                            "error": res.get("error")} if res.get("ok")
                           else {"ok": False, "error": res.get("error")})
    try:
        _write_json(prop_path, prop)
    except OSError:
        pass
    try:
        from longrun.util import improve as _imp
        _imp.ledger_add("forge", origin="mining", draft=os.path.basename(proposal_dir),
                        pattern=pattern, matrix_tool=res.get("matrix_tool"),
                        ok=bool(res.get("ok")), error=res.get("error"))
    except Exception:  # noqa: BLE001 — the ledger must never break a forge
        pass
    return res


def pipeline(pattern, out_dir, support=0, runner=None, promote_if_green=True,
             skills_dir=None, c=None, purpose=""):
    """Full stage 2 cycle: draft -> synth -> verify -> (promote if green AND
    the green streak reaches the bar).

    `purpose` is the one sentence that turns material into a skill; an empty one
    means the automatic cycle stops at a VERIFIED DRAFT (the purpose gate in
    `promote` refuses the install), which is the designed behaviour: a mined
    sequence is evidence of a repeat, not a statement of what it is for.
    """
    c = c or cfg()
    d = draft(pattern, support, out_dir, purpose=purpose)
    if not d:
        return {"ok": False, "error": "draft failed"}
    s = synth(pattern, out_dir, c)
    if not s:
        return {"ok": False, "error": "synth failed", "dir": d}
    report = verify(d, runner=runner, c=c)
    arch = None
    if report.get("green") and promote_if_green:
        arch = promote(d, skills_dir=skills_dir, c=c, purpose=purpose)
    return {"ok": bool(report.get("green")), "dir": d, "verify": report,
            "archived": arch}


