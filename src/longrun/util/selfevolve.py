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
    # v716: a pattern is a skill candidate, and a skill can only replay a real
    # tool. Loop pseudo-actions (`batch`, `subagent`, `dispatch`) are dropped here
    # so neither old history nor a direct caller can mint an unverifiable draft.
    known = set(_known_tools())
    seqs = [[str(x) for x in (s or []) if _dispatchable(x, known)]
            for s in (sequences or [])]
    seqs = [s for s in seqs if len(s) >= mn]
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


def record(key, tools, path=None):
    """Record the tool sequence of a run (for later mining).

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
    # EV-13: evolve's CODE arm. A green pattern already becomes a skill (the
    # declarative procedure); with this on it is ALSO forged into a Matrix tool
    # (`learned_<slug>.run`) that replays the sequence, proven by its own
    # generated test + the sha-bound contract gate and removed when either fails.
    # Bounded per run so one evolve pass cannot flood src/Matrix.
    "forge_on_evolve": True,
    "forge_per_run": 1,
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


def _pattern_of(prop):
    """The tool sequence a proposal was mined from, [] when it has none."""
    pat = (prop or {}).get("pattern")
    return [str(x) for x in pat] if isinstance(pat, list) else []


def _archived_skill_md(name, pattern, purpose, rel, origin):
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
              "ARCHIVED — verified green and installed at `%s` (origin: %s)."
              % (rel, origin or "auto"), ""]
    return "\n".join(lines)


def promote(proposal_dir, skills_dir=None, c=None, human=False, purpose=""):
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
    # v717: the archived SKILL.md states the purpose and the REAL state (the draft
    # text said "not archived" inside the installed skill).
    try:
        with open(os.path.join(target, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write(_archived_skill_md(name, _pattern_of(prop), purpose,
                                       prop["archived_to"], prop.get("origin")))
        skills_mod.list_skills(reload=True)
    except OSError:
        pass
    return {"ok": True, "name": name, "path": target,
            "rel": prop["archived_to"]}


MATRIX_FORGE_NS = "learned"


def _forge_slug(pattern):
    """Filesystem-safe, stable name for one mined sequence (same pattern, same name)."""
    import hashlib
    joined = "|".join(str(t) for t in pattern)
    digest = hashlib.sha1(joined.encode("utf-8")).hexdigest()[:8]
    base = re.sub(r"[^a-z0-9]+", "_", joined.lower()).strip("_")[:40].strip("_")
    return "%s_%s" % (base or "seq", digest)


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
    """A deterministic, side-effect free test: it only pins the REFUSALS."""
    head = (
        '"""Generated proof for the forged tool %s (no side effects: refusals only)."""\n'
        "from Matrix.tools import %s as M\n"
        "\n"
        'assert callable(getattr(M, "execute", None)), "execute is not callable"\n'
        "assert M.STEPS == %r, M.STEPS\n"
    ) % (full, ns, list(steps))
    body = (
        'r = M.execute({}, run_id="forge-test")\n'
        'assert r.get("ok") is False and "inputs" in str(r.get("error")), r\n'
        'r = M.execute({"inputs": []}, run_id="forge-test")\n'
        'assert r.get("ok") is False, r\n'
        'r = M.execute({"inputs": [{}] * (len(M.STEPS) + 1)}, run_id="forge-test")\n'
        'assert r.get("ok") is False, r\n'
        'print("ok: refusals pinned for", len(M.STEPS), "steps")\n'
    )
    return head + body


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
    and every step still passes the harness's own approval policy. Nucleus is
    untouched (`promote_to_nucleus` keeps its own checkbox).
    """
    import hashlib
    from longrun.core import matrix as mtx
    steps = [str(t).strip() for t in (pattern or []) if str(t).strip()]
    if len(steps) < 2:
        return {"ok": False, "error": "a forged tool needs at least 2 steps (got %d)"
                                      " — a single-tool repeat is a loop" % len(steps)}
    known = set(_known_tools())
    bad = [t for t in steps if not _dispatchable(t, known)]
    if bad:
        return {"ok": False, "error": "not replayable: %s" % ", ".join(bad)}
    if not mtx.is_enabled():
        return {"ok": False, "error": "Matrix is disabled — enable it before forging"}
    ns = str(name or "").strip() or (MATRIX_FORGE_NS + "_" + _forge_slug(steps))
    ns = re.sub(r"[^a-zA-Z0-9_]", "_", ns).strip("_")
    sub = "run"
    full = "%s.%s" % (ns, sub)
    _root, msrc, _mdot = mtx._roots(repo_root)
    fpath = os.path.join(msrc, "tools", ns + ".py")
    if os.path.exists(fpath):
        return {"ok": False, "error": "refusing to clobber %s (matrix.remove it first)"
                                      % fpath}
    desc = str(description or "").strip() or (
        "Replay the mined tool sequence %s in order: `inputs` carries one argument "
        "object per step, the run stops at the first failure, and every step keeps "
        "its own approval policy." % " \u2192 ".join(steps))
    origin = os.path.basename(str(draft or "")) or "mined draft"
    sc = mtx.scaffold("tool", full, description=desc, repo_root=repo_root)
    if not sc.get("ok"):
        return {"ok": False, "error": "scaffold refused: %s" % sc.get("error"), "scaffold": sc}
    body = _forge_body(ns, full, steps, desc, support, origin)
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
    result = {"ok": ok, "tool": full, "kind": "tool", "name": ns, "path": fpath,
              "steps": steps,
              "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
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
    res = forge_matrix(pattern, support=int(prop.get("support") or 0), draft=proposal_dir,
                       name=name, description=description or str(prop.get("purpose") or ""))
    prop["matrix_tool"] = ({"tool": res.get("tool"), "name": res.get("name"),
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
                        pattern=pattern, tool=res.get("tool"), ok=bool(res.get("ok")),
                        error=res.get("error"))
    except Exception:  # noqa: BLE001 — the ledger must never break a forge
        pass
    return res


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


