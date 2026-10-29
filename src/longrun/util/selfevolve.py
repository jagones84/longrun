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
import json
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


def mine(sequences, c=None):
    """Find contiguous tool sequences repeated across different runs.

    Args:
        sequences: list of runs; each run is the list of NAMES of the tools used,
            in execution order.
    Returns:
        list of {"pattern": [tool,...], "length": k, "support": n, "runs": [idx]}
        sorted by (length*support) descending; the longer patterns with the
        same support win over their sub-patterns.
    """
    c = c or cfg()
    mn = max(1, int(c.get("min_len") or 3))
    mc = max(2, int(c.get("min_count") or 3))
    mx = max(mn, int(c.get("max_len") or 6))
    seqs = [[str(x) for x in (s or [])] for s in (sequences or [])]
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
        out.append(d)
    out.sort(key=lambda d: (d["length"] * d["support"], d["support"]), reverse=True)
    return out


def slug(pattern):
    """Filesystem-safe slug for a tool pattern."""
    raw = "-".join(pattern)
    s = re.sub(r"[^a-zA-Z0-9._-]+", "-", raw).strip("-").lower()
    return (s or "skill")[:64]


def draft(pattern, support, out_dir, note=""):
    """Write a skill DRAFT (proposal.json + SKILL.md). Executes nothing.

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
                    # JAG-426: provenance — a machine-mined proposal is 'auto', so
                    # promote() can enforce the skills/created/ box on it only.
                    "origin": "auto",
                    "next": "verify in sandbox, then archive to skills/created/"}
        write_json(os.path.join(d, "proposal.json"), proposal)
        steps = "\n".join("%d. `%s`" % (i + 1, t) for i, t in enumerate(pattern))
        # v656: the draft must be readable by the operator who finds it in the
        # file tree — what was observed, why it matters, and the exact commands
        # that turn it into a real skill — instead of a two-line stub.
        md = ("# Proposed skill: %s\n\n"
              "The harness observed this tool sequence **%d times** across "
              "distinct runs (JAG-133). A repeated sequence is a skill "
              "CANDIDATE.\n\n"
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
              % (name, support, steps, " → ".join(pattern), name))
        with open(os.path.join(d, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write(md)
        return d
    except OSError:
        return None


def scan(sequences, out_dir, c=None, note=""):
    """Mine the sequences and write a draft per pattern. Returns the paths."""
    c = c or cfg()
    paths = []
    for cand in mine(sequences, c):
        # Self-maintenance: skip drafts that already exist — a re-mine
        # must not re-emit (and re-flood the chat with) the same patterns.
        name = slug(cand["pattern"])
        if os.path.isfile(os.path.join(out_dir, name, "proposal.json")):
            continue
        p = draft(cand["pattern"], cand["support"], out_dir, note=note)
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


def record(key, tools, path=None):
    """Record the tool sequence of a run (for later mining).

    Keeps the latest 500 runs. Never blocking: a write error is ignored.
    """
    seq = [str(t) for t in (tools or []) if str(t).strip()]
    if not seq or not key:
        return False
    p = path or _history_path()
    try:
        data = {}
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                data = json.load(f) or {}
        if not isinstance(data, dict):
            data = {}
        data[str(key)] = {"tools": seq, "ts": round(time.time(), 3)}
        if len(data) > 500:
            for k in sorted(data, key=lambda x: data[x].get("ts", 0))[:len(data) - 500]:
                data.pop(k, None)
        write_json(p, data)
        return True
    except OSError:
        return False


def history(path=None):
    """The recorded sequences, as a list of lists of tool names."""
    p = path or _history_path()
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f) or {}
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    return [e.get("tools", []) for e in data.values() if isinstance(e, dict)]


def mine_history(out_dir, c=None, path=None, note=""):
    """Mine the recorded history and write the drafts. Returns the paths."""
    return scan(history(path), out_dir, c, note=note)


# ------------------------------------------------- stage 2: synth/verify/archive
# Voyager-style write-gate: the skill enters `skills/` ONLY if the generated check
# passes in the sandbox. Nothing but the check is executed (self-contained), so
# the cycle is safe: synthesize -> verify -> archive.

STAGE2_DEFAULTS = {
    # JAG-426: auto-generated skills land under skills/created/ — a dedicated,
    # clearly-labelled box, so the built-in library (skills/core) and the user's
    # own categories stay untouched and auditable.
    "category": "created",  # skills/<category>/<name> during promotion
    "verify_timeout": 60,   # timeout of the check in the sandbox
    # F5 (Maka thresholded release): the promotion bar. A proposal is released
    # only after this many CONSECUTIVE green verifies (patience — no release
    # on a single lucky green). 1 preserves the historical single-green
    # behavior; raise it to harden a flaky check.py.
    "min_green_streak": 1,
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
        # Not a draft folder: there is nothing of OURS to synthesize, and the
        # verifier is the one that decides what a non-draft path means.
        return {"ok": True, "synth": False}
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


def verify(proposal_dir, runner=None, c=None):
    """Run `check.py` in the sandbox and update proposal.json (verified/rejected).

    `runner(dir, command) -> (green, output)` injectable in tests (pure).
    Returns the report {"ran","green","command","duration_ms","output"}.
    """
    c = c or cfg()
    prop = _read_json(os.path.join(proposal_dir, "proposal.json")) or {}
    command = "python3 check.py"
    t0 = time.time()
    if runner is not None:
        try:
            green, out = runner(proposal_dir, command)
        except Exception as e:  # noqa: BLE001
            green, out = False, "runner error: %s" % e
    else:
        green, out = _run_check(proposal_dir, command, c)
    report = {"ran": True, "green": bool(green), "command": command,
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


def promote(proposal_dir, skills_dir=None, c=None, human=False):
    """Archive a VERIFIED proposal into skills/<category>/<name>/ (write-gate).

    Rejects if the status is not `verified`. Does not overwrite. Returns
    {"ok",...} or {"ok": False, "error": ...}.

    `human=True` is the OPERATOR path (an approved proposal in the WebUI): the
    sandbox check still has to be green, but the sealed held-out suite is not
    required — a person looking at the draft IS the independent judge, which is
    what the RDD gate protects against (the machine certifying itself). The
    release is stamped on the proposal so the provenance stays visible.
    """
    c = c or cfg()
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
    # RDD point 2: sealed held-out gate (fail-closed). The local verifier
    # (check.py) is NOT enough: promotion requires the external judge suite.
    from longrun.plan import heldout
    if heldout.require_enabled() and not human:
        g = heldout.gate(proposal_dir, c=c)
        if not g.get("green"):
            why = str(g.get("reason") or "")
            # v645: "no_manifest" is not a defect of the draft — it means the
            # sealed judge suite was never installed, so NOTHING can be promoted
            # (the automatic path fails the same way). Say that instead of
            # leaving the operator with a dead accept button.
            hint = (" — the sealed judge suite is not installed (data/heldout/manifest.json); "
                    "pin it before promoting a skill") if why == "no_manifest" else ""
            return {"ok": False, "gate": g,
                    "error": "held-out gate not green (%s)%s" % (why, hint)}
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
    # skills/created/, and only within the quota.
    if prop.get("origin") == "auto":
        box = os.path.join(root, "created")
        if not _under(target, box):
            return {"ok": False,
                    "error": "an auto-generated skill must be promoted under skills/created (got category %r)" % category}
        existing = [d for d in os.listdir(box)] if os.path.isdir(box) else []
        if len(existing) >= AUTO_SKILL_CAP:
            return {"ok": False,
                    "error": "skills/created quota reached (%d) — prune before promoting" % AUTO_SKILL_CAP}
    if os.path.exists(target):
        return {"ok": False, "error": "target already exists: %s" % target}
    from longrun.memory import skills as skills_mod
    got = skills_mod.install_skill_dir(proposal_dir, target)
    if not got.get("ok"):
        return got
    prop["status"] = "archived"
    if human:
        prop["released_by"] = "operator"
    _under_repo = os.path.abspath(target).startswith(os.path.abspath(REPO) + os.sep)
    prop["archived_to"] = (os.path.relpath(target, REPO) if _under_repo else target)
    _write_json(prop_path, prop)
    _write_json(os.path.join(target, "proposal.json"), prop)
    return {"ok": True, "name": name, "path": target,
            "rel": prop["archived_to"]}


def pipeline(pattern, out_dir, support=0, runner=None, promote_if_green=True,
             skills_dir=None, c=None):
    """Full stage 2 cycle: draft -> synth -> verify -> (promote if green AND
    the green streak reaches the bar)."""
    c = c or cfg()
    d = draft(pattern, support, out_dir)
    if not d:
        return {"ok": False, "error": "draft failed"}
    s = synth(pattern, out_dir, c)
    if not s:
        return {"ok": False, "error": "synth failed", "dir": d}
    report = verify(d, runner=runner, c=c)
    arch = None
    if report.get("green") and promote_if_green:
        arch = promote(d, skills_dir=skills_dir, c=c)
    return {"ok": bool(report.get("green")), "dir": d, "verify": report,
            "archived": arch}


