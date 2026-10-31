#!/usr/bin/env python3
"""JobBench: measure Longrun and Harness² on the SAME official tasks and judge.

    python3 -m benchmarks.jobbench_compare \\
        --profession biostatisticians --tasks 2 \\
        --arms longrun,harness2 \\
        --model openrouter:z-ai/glm-5.3-flash \\
        --judge-model z-ai/glm-5.3-flash \\
        --judge-base https://openrouter.ai/api/v1 \\
        --out .agent/BENCHMARKS/runs/2026-10-30_jobbench_glm53flash

Parity is the point, so it is explicit in the report:

* the same task corpus (`benchmarks.jobbench`), the same instruction text, the same
  `output/` convention;
* the same solver weights — Longrun takes `provider:model`, Harness²/OpenCode takes
  `provider/model`, the judge takes the bare id: one model, three spellings;
* the same judge process (`benchmarks.jobbench_judge`, the upstream `eval/judge.py`)
  with the same judge model, whichever arm produced the files.

Two honest asymmetries, recorded in every report: Longrun is driven over HTTP
(`POST /api/chat`), Harness² has no task endpoint and is driven through its own CLI
sweep; and Harness² runs its substrate (OpenCode) as the agent loop, which is the
thing being measured, not a setup detail.
"""
import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

from . import jobbench
from . import jobbench_judge as JJ
from .bare_adapter import _env_file_key, _key

DEFAULT_HARNESS2 = Path(os.environ.get("HARNESS2_REPO",
                                       "/home/jagones/Repositories/Harness2")).expanduser()

SUITE = "jobbench"
#: Where runs live by default. The repo ships no results; `.agent/` is local only.
RUNS_ROOT = Path(os.environ.get("BENCH_RUNS_DIR")
                 or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 ".agent", "BENCHMARKS", "runs")).expanduser()


def _slug(task_id):
    return re.sub(r"[^A-Za-z0-9_.-]+", "__", task_id)


def _model_slug(model):
    return re.sub(r"[^A-Za-z0-9.]+", "-", str(model or "model")).strip("-")


def key_budget(key, base):
    """Remaining credit on the solver key (OpenRouter), or None when unknown.

    Measured 2026-10-31: a full four-arm sweep finished in 106 s with every arm at
    `0.0` — not because a harness is bad, but because the key had $0.00 left
    ("Key limit exceeded (total limit)"). A benchmark that cannot call the model
    must REFUSE to spend, not produce a table of zeros that looks like a result.
    """
    base = str(base or "")
    if "openrouter.ai" not in base:
        return None          # another provider: no portable budget endpoint
    import urllib.request
    url = base.rstrip("/") + "/key"
    req = urllib.request.Request(url, headers={"Authorization": "Bearer %s" % key})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            d = (json.load(resp) or {}).get("data") or {}
        rem = d.get("limit_remaining")
        return None if rem is None else float(rem)
    except Exception:  # noqa: BLE001 — an inspection must never block a run
        return None


def default_out(arms, model, n_tasks, scope=""):
    """The canonical folder for a run — one naming rule, collision-safe.

    `<date>_<suite>_<model-slug>_<arms>_<scope>_n<N>`, with `-2`, `-3` appended when
    the same combination is run twice, so a run folder is always self-describing
    (what, with what, on which tasks) and never silently overwrites another one.
    """
    slug = "%s_%s_%s_%s%s_n%d" % (time.strftime("%Y-%m-%d"), SUITE, _model_slug(model),
                                  "-".join(arms),
                                  ("_" + _model_slug(scope)) if scope else "",
                                  int(n_tasks))
    path, i = RUNS_ROOT / slug, 2
    while path.exists():
        path = RUNS_ROOT / ("%s-%d" % (slug, i))
        i += 1
    return path


def select_tasks(all_tasks, only=None, limit=None):
    """The tasks a run actually uses — a re-run is named, never positional.

    `only` is a list of task ids or their bare suffixes (`task2`); a re-run must
    target the task that failed, not "the first N" again. `limit` keeps its
    meaning only when nothing is named (`--tasks 3`).
    """
    tasks = list(all_tasks or [])
    only = [o for o in (only or []) if o]
    if only:
        return [t for t in tasks
                if t.get("id") in only
                or any(str(t.get("id", "")).endswith("/" + o) for o in only)]
    return tasks if limit is None else tasks[:max(0, int(limit))]


def write_manifest(out, **fields):
    """Merge `fields` into `<out>/run.json` (one manifest per run, never a guess)."""
    path = Path(out) / "run.json"
    data = {}
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            data = {}
    data.update(fields)
    _write(path, data)
    return data


def rebuild_index(root=None):
    """`runs/INDEX.md`, derived from every `run.json` (the manifest is the truth)."""
    root = Path(root or RUNS_ROOT)
    rows = []
    if root.is_dir():
        for d in sorted((p for p in root.iterdir() if p.is_dir()), reverse=True):
            f = d / "run.json"
            if not f.is_file():
                continue
            try:
                rows.append(json.loads(f.read_text(encoding="utf-8")))
            except ValueError:
                continue
    # Newest first by the manifest's own `started`: the folder name is not
    # chronological (`_n3` sorts before `_n1-2` lexically), and an index whose
    # first row is not the latest run is a misleading index.
    rows.sort(key=lambda r: str(r.get("started") or ""), reverse=True)
    lines = ["# Benchmark runs", "",
             "Derived from each run's `run.json` — do not edit by hand.", "",
             "| run | started | suite | arms | solver | judge | n | status | mean ratio |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        means = r.get("arms_summary") or {}
        mr = ", ".join("%s %s" % (k, v.get("mean_ratio"))
                       for k, v in sorted(means.items())) or "-"
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s |"
                     % (r.get("run_id", "?"), str(r.get("started", ""))[:16],
                        r.get("suite", ""), ",".join(r.get("arms") or []),
                        r.get("model", ""), r.get("judge_model", ""),
                        r.get("n_tasks", ""), r.get("status", ""), mr))
    text = "\n".join(lines) + "\n"
    root.mkdir(parents=True, exist_ok=True)
    (root / "INDEX.md").write_text(text, encoding="utf-8")
    return text


def _write(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def _openrouter_key():
    """The judge/solver key: process env first, then the DGX dotenv files."""
    return (_key(["OPENROUTER_API_KEY"])
            or _env_file_key(["OPENROUTER_API_KEY"], "~/.hermes/.env")
            or _env_file_key(["OPENROUTER_API_KEY"], ".env"))


# --------------------------------------------------------------- longrun arm
def run_longrun(tasks, out, *, model, judge_model, judge_base, key, timeout,
                judge_timeout, keep_sessions=False, max_steps=None, adapter=None):
    """Drive the LIVE Longrun over REST, one session per task, then judge."""
    from .longrun_adapter import LongrunAdapter
    arm = Path(out) / "longrun"
    arm.mkdir(parents=True, exist_ok=True)
    ad = adapter or LongrunAdapter(model=model, timeout=timeout,
                                   keep_sessions=keep_sessions,
                                   tag="jobbench", max_steps=max_steps)
    rows, prov = [], {}
    try:
        prov = ad.provenance()
        ad.setup()
        for task in tasks:
            slug = _slug(task["id"])
            ws = arm / slug / "workspace"
            jobbench.stage(task, ws)
            t0 = time.time()
            ref = ad.create_agent({"id": task["id"], "workspace": str(ws)})
            res = ad.send_task(ref, jobbench.prompt_for(task, ws), timeout=timeout)
            files = jobbench.deliverables(ws)
            # The session's cost ledger lives under `~/.longrun/data/costs/<sid>.json`
            # and `delete_agent` takes it away with the session. Measured 2026-10-30:
            # a finished task reported score+files and NO tokens, so Longrun looked
            # free next to Harness² (which logs per-step token cost in its
            # trajectory). Read it while the session still exists.
            usage = {}
            try:
                usage = ad.usage(ref.session) or {}
            except Exception as exc:  # noqa: BLE001 — accounting never fails a task
                usage = {"error": str(exc)[:200]}
            sc = JJ.score_run(task, ws, arm / slug / "judge.json", judge_model,
                              judge_base, key, evaluated_model="longrun-%s" % slug,
                              timeout=judge_timeout)
            row = {"task": task["id"], "arm": "longrun", "ok": bool(res.ok),
                   "error": res.error or "", "delivered": len(files),
                   "files": files[:40], "duration_s": round(time.time() - t0, 1),
                   "model": model, "score": sc, "usage": usage,
                   # The reply is the only evidence of WHY a turn delivered nothing:
                   # keep its head and length, and the ids needed to open the session.
                   "reply": (res.output or "")[:1200],
                   "reply_len": len(res.output or ""),
                   "run_id": res.run_id, "session": ref.session,
                   "max_steps": max_steps,
                   "workspace_error": (ref.meta or {}).get("error", "")}
            _write(arm / slug / "result.json", row)
            if usage:
                _write(arm / slug / "costs.json", usage)
            rows.append(row)
            ad.delete_agent(ref)
            print("  longrun %-42s delivered=%d score=%s"
                  % (task["id"], len(files),
                     "%s/%s" % (sc.get("score"), sc.get("max")) if sc.get("ok") else sc.get("error")),
                  flush=True)
    finally:
        try:
            ad.teardown()
        except Exception:  # noqa: BLE001 — never leave the server half-configured
            pass
    return rows, prov


# ------------------------------------------------------------------- raw arm
def bare_model_id(model):
    """`openrouter:z-ai/glm-5.3-flash` -> `z-ai/glm-5.3-flash` (a raw endpoint's id)."""
    text = str(model or "")
    return text.split(":", 1)[1] if ":" in text else text


def run_raw(tasks, out, *, model, judge_model, judge_base, key, timeout,
            judge_timeout, adapter=None):
    """The NO-HARNESS control: one plain chat call per task, judged like the others.

    Same corpus, same verbatim instruction, same weights, **no tools, no system
    prompt, no memory** — the honest floor a harness must beat. A raw model cannot
    create the files a rubric asks for, so its only artefact is its own text: the
    reply is persisted as `output/answer.md` (the same `output/` convention every
    arm is graded through). Without that the control would always score 0 and
    would compare nothing.
    """
    from .bare_adapter import BareAdapter
    arm = Path(out) / "raw"
    arm.mkdir(parents=True, exist_ok=True)
    ad = adapter or BareAdapter(base=judge_base, api_key=key, model=bare_model_id(model),
                                timeout=timeout)
    rows = []
    for task in tasks:
        slug = _slug(task["id"])
        ws = arm / slug / "workspace"
        jobbench.stage(task, ws)
        t0 = time.time()
        res = ad.send_task(None, jobbench.prompt_for(task, ws), timeout=timeout)
        if res.ok and (res.output or "").strip():
            (ws / "output" / "answer.md").write_text(res.output, encoding="utf-8")
        files = jobbench.deliverables(ws)
        sc = JJ.score_run(task, ws, arm / slug / "judge.json", judge_model,
                          judge_base, key, evaluated_model="raw-%s" % slug,
                          timeout=judge_timeout)
        row = {"task": task["id"], "arm": "raw", "ok": bool(res.ok),
               "error": res.error or "", "delivered": len(files), "files": files[:40],
               "duration_s": round(time.time() - t0, 1), "model": bare_model_id(model),
               "score": sc, "reply": (res.output or "")[:1200],
               "reply_len": len(res.output or "")}
        _write(arm / slug / "result.json", row)
        rows.append(row)
        print("  raw     %-42s delivered=%d score=%s"
              % (task["id"], len(files),
                 "%s/%s" % (sc.get("score"), sc.get("max")) if sc.get("ok") else sc.get("error")),
              flush=True)
    return rows, ad.provenance()


# -------------------------------------------------------------- opencode arm
def opencode_command(workspace, model, prompt):
    """The bare AGENT LOOP: OpenCode alone, same prompt, no Harness² evolution.

    Harness² is a meta-harness that proposes and evolves a harness spec and then
    runs it on a substrate; `--substrate oc` means OpenCode executes the rollouts.
    Measuring the substrate ON ITS OWN is what separates "this agent loop is good"
    from "the search around it is good" — without it a Harness² score cannot say
    which half earned the points.
    """
    root = DEFAULT_HARNESS2
    bun = root / "dependencies" / "tools" / "node_modules" / ".bin" / "bun"
    oc = root / "dependencies" / "opencode" / "packages" / "opencode"
    # `--dangerously-skip-permissions` is a PARITY flag, not a shortcut. A
    # non-interactive `opencode run` auto-rejects EVERY permission ask ("permission
    # requested: …; auto-rejecting"), so on 2026-10-30 the bare arm died after 4
    # steps / 11.6 s with 0 files delivered on a task needing one scratch write —
    # 0/88 that measures its permission gate, not its loop. Longrun runs with
    # `approvals.mode=full` (see `setup()`), so parity requires this.
    return [str(bun), "run", "--cwd", str(oc), "--conditions=browser", "src/index.ts",
            "run", prompt, "--dir", str(workspace), "--model", model, "--format", "json",
            "--dangerously-skip-permissions"]


#: OpenClaw's own CLI (a complete third-party harness: gateway + agent loop).
#: `agent exec` is its ONE isolated headless turn — no chat channel, no session
#: reuse — which is exactly the shape a benchmark needs. It requires Node
#: >= 24.22 (the CLI refuses older: `node:sqlite is unavailable`) and the nvm copy
#: is on no default PATH, so both are pinned here instead of assumed.
OPENCLAW_BIN = "/home/jagones/.local/bin/openclaw"
OPENCLAW_NODE_BIN = "/home/jagones/.nvm/versions/node/v24.22.1/bin"


def openclaw_command(workspace, model, prompt, timeout):
    """The OpenClaw arm's command line: one headless embedded agent turn."""
    return [OPENCLAW_BIN, "agent", "exec", prompt, "--cwd", str(workspace),
            "--model", model, "--json", "--timeout", str(int(max(30, timeout)))]


def _openclaw_env(key):
    """Env for OpenClaw: its node, the provider key, and its own `.env`.

    OpenClaw resolves providers from its gateway config, which reads several
    `*_API_KEY` variables; a missing one aborts the run BEFORE the model is chosen
    ("Environment variable VLLM_API_KEY is missing"). The operator's real values
    live in `~/.hermes/.env`, so they are merged here (never overriding what the
    caller already set) instead of being guessed.
    """
    env = dict(os.environ)
    env["PATH"] = OPENCLAW_NODE_BIN + os.pathsep + env.get("PATH", "")
    env["OPENROUTER_API_KEY"] = key
    dot = Path(os.path.expanduser("~/.hermes/.env"))
    try:
        body = dot.read_text(encoding="utf-8")
    except OSError:
        return env
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return env


def _openclaw_usage(stdout):
    """Steps/tokens/cost + the reply from OpenClaw's `--json` envelope.

    One object (not a JSONL stream): `usage.input/output`, `usage.cost.total`,
    `assistantTurns`, `toolSummary.calls` and `final`. Anything missing stays 0
    rather than inventing a number.
    """
    try:
        obj = json.loads((stdout or "").strip() or "{}")
    except ValueError:
        return ({"steps": 0, "tokens_in": 0, "tokens_out": 0, "total_usd": 0.0,
                 "source": "openclaw agent exec --json"}, "")
    u = obj.get("usage") or {}
    cost = u.get("cost") if isinstance(u.get("cost"), dict) else {}
    tools = (obj.get("toolSummary") or {}).get("calls") or 0
    usage = {
        "steps": int(obj.get("assistantTurns") or tools or 0),
        "tokens_in": int(u.get("input") or 0),
        "tokens_out": int(u.get("output") or 0) + int(u.get("reasoningTokens") or 0),
        "total_usd": round(float(cost.get("total") or obj.get("costUsd") or 0), 6),
        "source": "openclaw agent exec --json",
        "tool_calls": int(tools or 0),
        "tool_failures": int((obj.get("toolSummary") or {}).get("failures") or 0),
    }
    return usage, str(obj.get("final") or "")


def run_openclaw(tasks, out, *, solver_model, judge_model, judge_base, key, timeout,
                 judge_timeout):
    """Run OpenClaw's own headless turn per task, then grade its `output/`.

    Same staging, same prompt, same judge as every other arm: the only thing that
    changes is who runs the loop.
    """
    arm = Path(out) / "openclaw"
    arm.mkdir(parents=True, exist_ok=True)
    rows = []
    for task in tasks:
        slug = _slug(task["id"])
        ws = arm / slug / "workspace"
        jobbench.stage(task, ws)
        prompt = jobbench.prompt_for(task, ws)
        cmd = openclaw_command(ws, solver_model, prompt, timeout)
        meta = {"command": ["<prompt>" if i == 3 else c for i, c in enumerate(cmd)],
                "model": solver_model, "workspace": str(ws),
                "cwd": str(ws), "transport": "openclaw agent exec --json"}
        t0 = time.time()
        timed_out = False
        proc = None
        try:
            proc = subprocess.Popen(cmd, cwd=str(ws), env=_openclaw_env(key),
                                    text=True, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    start_new_session=True)
            out_s, err_s = proc.communicate(timeout=timeout + 60)
            rc = proc.returncode
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            timed_out, out_s, err_s, rc = True, "", "", -1
        except (OSError, subprocess.SubprocessError) as exc:
            meta["error"] = str(exc)
            _write(arm / slug / "command.json", meta)
            print("  openclaw FAILED to start: %s" % exc, flush=True)
            rows.append({"task": task["id"], "arm": "openclaw", "ok": False,
                         "error": str(exc), "delivered": 0, "files": [],
                         "duration_s": round(time.time() - t0, 1),
                         "model": solver_model, "score": None, "timed_out": False})
            continue
        meta.update({"returncode": rc, "status": "timeout" if timed_out else
                     ("ok" if rc == 0 else "failed"),
                     "duration_s": round(time.time() - t0, 1),
                     "stderr_tail": (err_s or "")[-1200:]})
        _write(arm / slug / "command.json", meta)
        usage, reply = _openclaw_usage(out_s)
        files = jobbench.deliverables(ws)
        sc = JJ.score_run(task, ws, arm / slug / "judge.json", judge_model,
                          judge_base, key, evaluated_model="openclaw-%s" % slug,
                          timeout=judge_timeout)
        row = {"task": task["id"], "arm": "openclaw", "ok": bool(sc.get("ok")),
               "error": sc.get("error") or "", "delivered": len(files),
               "files": files[:40], "duration_s": meta["duration_s"],
               "model": solver_model, "score": sc, "usage": usage,
               "steps": usage.get("steps"), "timed_out": timed_out,
               "reply": (reply or "")[:1200], "reply_len": len(reply or "")}
        _write(arm / slug / "result.json", row)
        print("  openclaw %-50s delivered=%s steps=%s score=%s"
              % (task["id"], len(files), usage.get("steps"),
                 "%s/%s" % (sc.get("score"), sc.get("max")) if sc.get("ok")
                 else sc.get("error")), flush=True)
        rows.append(row)
    return rows, {"model": solver_model, "transport": "openclaw agent exec --json",
                  "cli": OPENCLAW_BIN, "node": OPENCLAW_NODE_BIN}


def _h2_env(key):
    """Harness²'s own runtime env (isolated XDG dirs) + the solver key.

    OpenCode reads its provider config from `XDG_CONFIG_HOME`, and Harness² keeps a
    dedicated one so a sweep never collides with the operator's desktop OpenCode.
    Reusing the same dirs keeps the substrate arm on the same provider/model wiring
    instead of inventing a second config.
    """
    env = dict(os.environ)
    env["OPENROUTER_API_KEY"] = key
    dot = DEFAULT_HARNESS2 / ".env"
    try:
        text = dot.read_text(encoding="utf-8")
    except OSError:
        return env
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env.setdefault(k.strip(), v.strip())
    return env


def _oc_usage(stdout):
    """Steps, tokens and dollars from `opencode run --format json` (a JSONL stream).

    Each `step_finish` part carries the step's own `tokens` and `cost`; the last
    `text` part is the agent's final answer. Summing the steps is the only honest
    cost for this arm — the process prints nothing else.
    """
    steps = tin = tout = 0
    usd = 0.0
    reply = ""
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        part = obj.get("part") or {}
        if obj.get("type") == "step_finish":
            steps += 1
            t = part.get("tokens") or {}
            tin += int(t.get("input") or 0)
            tout += int(t.get("output") or 0) + int(t.get("reasoning") or 0)
            usd += float(part.get("cost") or 0)
        elif obj.get("type") == "text" and isinstance(part.get("text"), str):
            reply = part["text"]
    return ({"steps": steps, "tokens_in": tin, "tokens_out": tout,
             "total_usd": round(usd, 6), "source": "opencode step_finish"}, reply)


def run_opencode(tasks, out, *, solver_model, judge_model, judge_base, key, timeout,
                 judge_timeout):
    """Run the bare agent loop per task, then grade its `output/` with the same judge."""
    arm = Path(out) / "opencode"
    arm.mkdir(parents=True, exist_ok=True)
    rows = []
    for task in tasks:
        slug = _slug(task["id"])
        ws = arm / slug / "workspace"
        jobbench.stage(task, ws)
        prompt = jobbench.prompt_for(task, ws)
        cmd = opencode_command(ws, solver_model, prompt)
        # Mask the PROMPT only (index 7: bun run --cwd <oc> --conditions=browser
        # src/index.ts run <PROMPT> --dir …). It used to mask index 8, which is
        # `--dir`, so command.json showed a workspace as a bare positional and hid
        # the flag — and reading that file suggested the arm was invoked wrong when
        # it was not (2026-10-31). The record must show every real flag.
        meta = {"command": ["<prompt>" if i == 7 else c for i, c in enumerate(cmd)],
                "model": solver_model, "workspace": str(ws),
                "cwd": str(DEFAULT_HARNESS2)}
        t0 = time.time()
        timed_out = False
        proc = None
        try:
            proc = subprocess.Popen(cmd, cwd=str(DEFAULT_HARNESS2), env=_h2_env(key),
                                    text=True, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    start_new_session=True)
            out_s, err_s = proc.communicate(timeout=timeout)
            rc = proc.returncode
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            timed_out, out_s, err_s, rc = True, "", "", -1
        except (OSError, subprocess.SubprocessError) as exc:
            meta["error"] = str(exc)
            _write(arm / slug / "command.json", meta)
            print("  opencode FAILED to start: %s" % exc, flush=True)
            rows.append({"task": task["id"], "arm": "opencode", "ok": False,
                         "error": str(exc), "delivered": 0, "files": [],
                         "duration_s": round(time.time() - t0, 1), "model": solver_model,
                         "score": None, "timed_out": False})
            continue
        meta.update({"returncode": rc, "status": "timeout" if timed_out else
                     ("ok" if rc == 0 else "failed"),
                     "duration_s": round(time.time() - t0, 1),
                     "stderr_tail": (err_s or "")[-1200:]})
        _write(arm / slug / "command.json", meta)
        usage, reply = _oc_usage(out_s)
        files = jobbench.deliverables(ws)
        sc = JJ.score_run(task, ws, arm / slug / "judge.json", judge_model,
                          judge_base, key, evaluated_model="opencode-%s" % slug,
                          timeout=judge_timeout)
        row = {"task": task["id"], "arm": "opencode", "ok": bool(sc.get("ok")),
               "error": sc.get("error") or "", "delivered": len(files),
               "files": files[:40], "duration_s": meta["duration_s"],
               "model": solver_model, "score": sc, "usage": usage,
               "steps": usage.get("steps"), "timed_out": timed_out,
               "reply": (reply or "")[:1200], "reply_len": len(reply or "")}
        _write(arm / slug / "result.json", row)
        if usage.get("steps"):
            _write(arm / slug / "costs.json", usage)
        rows.append(row)
        print("  opencode %-40s delivered=%d steps=%s score=%s"
              % (task["id"], len(files), usage.get("steps"),
                 "%s/%s" % (sc.get("score"), sc.get("max")) if sc.get("ok") else sc.get("error")),
              flush=True)
    return rows, {"model": solver_model, "transport": "opencode run --format json",
                  "cwd": str(DEFAULT_HARNESS2)}


# -------------------------------------------------------------- harness2 arm
def harness2_command(tasks, solver_model, extra=""):
    """The official sweep command for the same tasks (Harness² has no HTTP API)."""
    prof = tasks[0]["profession"] if tasks else ""
    py = DEFAULT_HARNESS2 / ".venv" / "bin" / "python"
    cmd = [str(py), "-m", "harness2.cli.run_sweep", "--bench", "jb", "--substrate", "oc",
           "--k", "1", "--split", "all", "--modes", "parallel",
           "--only-domains", prof, "--max-tasks", str(len(tasks))]
    return cmd + ([extra] if extra else [])


def _kill_tree(proc, grace=5.0):
    """Stop a sweep AND everything it spawned — a budget that leaks agents is not one.

    The sweep is started in its own session (`start_new_session=True`), so its pid
    is also its process-group id: SIGTERM the group, then SIGKILL whatever ignored
    it. Measured 2026-10-30: killing only the sweep's pid left an OpenCode/bun
    rollout alive and still calling the model after the budget had expired.
    """
    if proc is None or proc.poll() is not None:
        return
    try:
        pgid = os.getpgid(proc.pid)
    except OSError:
        pgid = None
    for sig in (signal.SIGTERM, signal.SIGKILL):
        if pgid is None:
            proc.kill()
            return
        try:
            os.killpg(pgid, sig)
        except OSError:
            return
        try:
            proc.wait(timeout=grace)
            return
        except subprocess.TimeoutExpired:
            continue


def run_harness2(tasks, out, *, solver_model, judge_model, judge_base, key,
                 timeout, judge_timeout, dry_run=False, reuse=None):
    """Run Harness²'s own sweep, then grade ITS `model_output/` with the same judge.

    `reuse` names an EARLIER run folder: its sweep is not spent a second time, the
    model_output already under it is graded again. A Harness² sweep costs ~12 min
    per task (4 rollouts + 3 improver sessions), so adding the other two arms to a
    finished sweep must not pay for it twice.
    """
    arm = Path(out) / "harness2"
    arm.mkdir(parents=True, exist_ok=True)
    # Each sweep gets its OWN run store: Harness² refuses a directory that already
    # belongs to different models/tasks ("Choose a new HARNESS2_RUNS_DIR"), and a
    # shared store would also mix this run's model_output with an older one.
    h2_runs = (Path(reuse) / "harness2" / "_h2runs") if reuse else (arm / "_h2runs")
    h2_runs.mkdir(parents=True, exist_ok=True)
    cmd = harness2_command(tasks, solver_model)
    env = dict(os.environ)
    env.update({"HARNESS2_SOLVER_MODEL": solver_model,
                "HARNESS2_IMPROVER_MODEL": solver_model,
                "HARNESS2_JUDGE_MODEL": judge_model,
                "HARNESS2_JUDGE_BASE_URL": judge_base,
                "HARNESS2_JUDGE_API_KEY": key,
                "HARNESS2_RUNS_DIR": str(h2_runs),
                # The task-executor substrate (OpenCode) authenticates to the
                # solver provider from its OWN env, not from our driver: without
                # this the sweep starts and every rollout dies as unauthorized.
                "OPENROUTER_API_KEY": key})
    meta = {"command": cmd, "env_model": solver_model, "cwd": str(DEFAULT_HARNESS2),
            "runs_dir": str(h2_runs), "status": "dry-run" if dry_run else ""}
    if reuse:
        # A reused sweep still has a COST IN TIME, and that is half the comparison:
        # carry the earlier sweep's own wall clock and budget verdict forward
        # instead of printing "-" for the arm that took the longest.
        earlier = {}
        try:
            earlier = json.loads((Path(reuse) / "harness2" / "command.json")
                                 .read_text(encoding="utf-8")) or {}
        except (OSError, ValueError):
            earlier = {}
        meta.update({"status": "reused", "reused_from": str(reuse), "command": [],
                     "duration_s": earlier.get("duration_s"),
                     "reused_budget_status": earlier.get("status", "")})
        _write(arm / "command.json", meta)
        print("  harness2 (reused from %s)" % reuse, flush=True)
        return _grade_harness2(tasks, arm, h2_runs, judge_model, judge_base, key,
                               judge_timeout, elapsed=meta.get("duration_s"),
                               timed_out=earlier.get("status") == "timeout"), meta
    if dry_run:
        _write(arm / "command.json", meta)
        print("  harness2 (dry-run): %s" % " ".join(cmd), flush=True)
        return [], meta
    t0 = time.time()
    # A Popen, not `run(timeout=)`: Harness² fans out into a process TREE (a sweep
    # python -> OpenCode/bun -> the model calls). Killing only the sweep's own pid
    # leaves those grandchildren alive and still spending, so the budget must be
    # enforced on the whole process GROUP and nothing may outlive it.
    proc = None
    try:
        # `stdin=DEVNULL` is LOAD-BEARING, not hygiene: Harness²'s proposer step
        # launches the OpenCode CLI without `stdin=` of its own, so the child would
        # INHERIT this process's stdin all the way down. An open stdin with no EOF
        # (an ssh session, a parent pipeline) makes `opencode run` block forever —
        # measured: inherit -> hung at 45 s, DEVNULL -> answers in 5 s, a closed
        # pipe -> answers in 22 s. Without this the sweep's rollouts finish and its
        # three improver sessions hang until the timeout kills the sweep.
        proc = subprocess.Popen(cmd, cwd=str(DEFAULT_HARNESS2), env=env, text=True,
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, start_new_session=True)
        out_s, err_s = proc.communicate(timeout=timeout)
        meta.update({"returncode": proc.returncode, "stderr_tail": (err_s or "")[-1200:],
                     "stdout_tail": (out_s or "")[-1200:],
                     "duration_s": round(time.time() - t0, 1)})
        meta["status"] = "ok" if proc.returncode == 0 else "failed"
    except subprocess.TimeoutExpired as e:
        # A BUDGET is not a failure. Harness² writes each label's files under
        # `model_output/` as that rollout finishes, so a sweep cut at the wall-clock
        # budget has still delivered whatever it completed — and that is exactly
        # what a time-budgeted comparison wants to measure. Throwing the labels
        # away (the old behaviour) turned a slow arm into "no data" instead of
        # "this much quality in this much time". Measured 2026-10-30: one task is
        # 7 opencode sessions of 40-100 steps, ~55 min end to end.
        _kill_tree(proc)
        meta.update({"status": "timeout", "duration_s": round(time.time() - t0, 1),
                     "error": "sweep exceeded the %.0fs budget" % timeout,
                     "stdout_tail": str(getattr(e, "output", "") or "")[-1200:],
                     "stderr_tail": str(getattr(e, "stderr", "") or "")[-1200:]})
        _write(arm / "command.json", meta)
        print("  harness2 hit the %.0fs budget: grading what it delivered" % timeout,
              flush=True)
        return _grade_harness2(tasks, arm, h2_runs, judge_model, judge_base, key,
                               judge_timeout, elapsed=meta["duration_s"],
                               timed_out=True), meta
    except (OSError, subprocess.SubprocessError) as e:
        _kill_tree(proc)
        meta.update({"error": str(e), "duration_s": round(time.time() - t0, 1)})
        _write(arm / "command.json", meta)
        print("  harness2 FAILED to start: %s" % e, flush=True)
        return [], meta
    _write(arm / "command.json", meta)
    return _grade_harness2(tasks, arm, h2_runs, judge_model, judge_base, key,
                           judge_timeout, elapsed=meta.get("duration_s"),
                           timed_out=meta["status"] != "ok"), meta


def _h2_deliverables(label_dir):
    """What a Harness² label DELIVERED: its files sit flat in the label folder.

    Measured 2026-10-30: `model_output/<label>/Baseline_Subgroup_Analysis.xlsx`
    (three workbooks at the root, no `output/`). The judge was always pointed at
    that folder and scored 62/72, while the report — reading `<label>/output` like
    the other arms — printed "delivered 0". An arm that delivered three files must
    never be reported as having delivered none. `output/` is still honoured when a
    label happens to use it.
    """
    p = Path(label_dir)
    nested = p / "output"
    root = nested if nested.is_dir() else p
    return sorted(str(f.relative_to(root)) for f in root.rglob("*")
                  if f.is_file() and not f.name.startswith("."))


def _grade_harness2(tasks, arm, h2_runs, judge_model, judge_base, key, judge_timeout,
                    elapsed=None, timed_out=False):
    """Grade ITS `model_output/`: `<runs>/jb/dataset/<prof>/<task>/model_output/<label>`.

    Harness² is a SELF-IMPROVING harness: one sweep writes several labels (the
    `base1` baseline, then the improved attempts). The newest label is the arm's
    result, and `base1` is graded too — "what did the improvement buy" is the whole
    point of that harness, and a single number would hide it.

    `elapsed`/`timed_out` carry the sweep's wall clock and whether it was cut at
    the budget: a graded label is not the same claim as "the sweep finished", so
    both travel with every row instead of being inferred later.
    """
    rows = []
    for task in tasks:
        prof, name = task["id"].split("/", 1)
        base = Path(h2_runs) / "jb" / "dataset" / prof / name / "model_output"
        labels = sorted((p for p in base.iterdir() if p.is_dir()),
                        key=lambda p: p.stat().st_mtime) if base.is_dir() else []
        if not labels:
            rows.append({"task": task["id"], "arm": "harness2", "ok": False,
                         "error": "no model_output under %s" % base, "score": None,
                         "duration_s": elapsed, "timed_out": bool(timed_out)})
            continue
        slug = _slug(task["id"])

        def _scored(run_dir, tag):
            sc = JJ.judge(run_dir, task["rubrics"], Path(arm) / slug / ("judge-%s.json" % tag),
                          judge_model, judge_base, key,
                          evaluated_model="harness2-%s" % run_dir.name, timeout=judge_timeout)
            return sc, _h2_deliverables(run_dir)

        run_dir = labels[-1]                        # the improved attempt
        sc, files = _scored(run_dir, "final")
        row = {"task": task["id"], "arm": "harness2", "ok": bool(sc.get("ok")),
               "error": sc.get("error") or "", "delivered": len(files),
               "files": files[:40], "label": run_dir.name, "score": sc,
               "labels": [p.name for p in labels],
               "duration_s": elapsed, "timed_out": bool(timed_out)}
        baseline = next((p for p in labels if p.name.endswith("base1")), None)
        if baseline is not None and baseline != run_dir:
            b_sc, b_files = _scored(baseline, "baseline")
            row["baseline"] = {"label": baseline.name, "score": b_sc,
                               "delivered": len(b_files)}
        _write(Path(arm) / slug / "result.json", row)
        rows.append(row)
        b = row.get("baseline") or {}
        print("  harness2 %-41s delivered=%d score=%s%s"
              % (task["id"], len(files),
                 "%s/%s" % (sc.get("score"), sc.get("max")) if sc.get("ok") else sc.get("error"),
                 ("  (baseline %s/%s)" % ((b.get("score") or {}).get("score"),
                                          (b.get("score") or {}).get("max"))
                  if b.get("score") and b["score"].get("ok") else "")),
              flush=True)
    return rows


# ------------------------------------------------------------------- report
#: The order every report uses: the no-harness floor, the bare agent loop, this
#: harness, the evolving one. It is a LADDER, so each step answers one question:
#: does a tool loop beat a single call (raw -> opencode), does this harness beat a
#: bare loop (opencode -> longrun), does search beat both (-> harness2).
ARM_ORDER = ("raw", "opencode", "openclaw", "longrun", "harness2")


def _arm_rank(name):
    """Position of an arm in the canonical order (an unknown arm sorts last)."""
    return ARM_ORDER.index(name) if name in ARM_ORDER else len(ARM_ORDER)


def _secs(value):
    """A duration for the report: seconds under a minute, minutes above, `-` when absent."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "-"
    return ("%.1fs" % v) if v < 60 else ("%.1fmin" % (v / 60.0))


def report(out, rows, parity):
    """`compare.json` + `compare.md`: per-task numbers and the parity block."""
    def _ratio(r):
        sc = r.get("score") or {}
        try:
            return float(sc["score"]) / float(sc["max"]) if sc.get("max") else None
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            return None

    def _cut(r):
        """The run was CUT at the wall clock — it has no score, only a duration."""
        if r.get("timed_out"):
            return True
        err = str(r.get("error") or "").lower()
        return "timed out" in err or "timeout" in err

    def _empty(r):
        """Finished, but produced no deliverable at all (no_output from the judge)."""
        return not _cut(r) and (r.get("score") or {}).get("no_output") is True

    arms = {}
    for r in rows:
        a = arms.setdefault(r["arm"], {"tasks": 0, "delivered": 0, "scored": 0,
                                       "timeouts": 0, "empty": 0,
                                       "ratio_sum": 0.0, "ratio_n": 0,
                                       "tokens": None, "usd": None, "time_s": 0.0})
        a["tasks"] += 1
        a["delivered"] += 1 if r.get("delivered") else 0
        if r.get("duration_s") is not None:
            a["time_s"] += float(r["duration_s"])
        # A CUT TASK IS NOT A SCORE (2026-10-30). A row killed at the wall clock
        # carries score 0 and max 94, so folding it into the mean made an arm look
        # eight times worse than it was: the two longrun re-runs that timed out on
        # endpoint latency (p50 19.5 s vs 2.4 s) dragged a 0.57 mean down to 0.19.
        # A timeout is counted as a timeout, never as a 0.000 result — and neither
        # is a run that finished with nothing to grade.
        if _cut(r):
            a["timeouts"] += 1
        elif _empty(r):
            a["empty"] += 1
        rt = _ratio(r)
        if rt is not None and not _cut(r) and not _empty(r):
            a["scored"] += 1
            a["ratio_sum"] += rt
            a["ratio_n"] += 1
        u = r.get("usage") or {}
        if u:
            # An arm that reports no ledger stays `None` ("not recorded"), which is
            # not the same claim as "$0".
            a["tokens"] = (a["tokens"] or 0) + int(u.get("tokens_in") or 0) \
                + int(u.get("tokens_out") or 0)
            if u.get("total_usd") is not None:
                a["usd"] = (a["usd"] or 0.0) + float(u["total_usd"])
    summary = {}
    for name, a in arms.items():
        summary[name] = {"tasks": a["tasks"], "delivered": a["delivered"],
                         "scored": a["scored"], "timeouts": a["timeouts"],
                         "no_output": a["empty"],
                         "time_s": round(a["time_s"], 1),
                         "tokens": a["tokens"], "usd": (round(a["usd"], 6)
                                                        if a["usd"] is not None else None),
                         # None when EVERY task of this arm was cut at the budget:
                         # an arm with no completed task has no mean, and printing
                         # 0.000 would state the opposite.
                         "mean_ratio": round(a["ratio_sum"] / a["ratio_n"], 4)
                         if a["ratio_n"] else None}
    payload = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "parity": parity,
               "arms": summary, "rows": rows}
    _write(Path(out) / "compare.json", payload)

    lines = ["# JobBench — raw vs bare agent loop vs Longrun vs Harness²", "",
             "Arms in a fixed ladder: `raw` (no harness, one call) → `opencode` (the "
             "bare agent loop Harness² itself runs on) → `longrun` (this harness) → "
             "`harness2` (Google's evolving meta-harness). One model, one instruction, "
             "one judge.", "",
             "| parity | value |", "|---|---|"]
    for k, v in sorted(parity.items()):
        lines.append("| %s | `%s` |" % (k, v))
    lines += ["", "| task | arm | delivered | score | max | ratio | time | note |",
              "|---|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda x: (x["task"], _arm_rank(x["arm"]))):
        sc = r.get("score") or {}
        rt = _ratio(r)
        note = sc.get("error") or r.get("error") or ""
        if r.get("timed_out"):
            # "graded at the budget" is a different claim from "finished": saying
            # it in the row is what keeps a truncated sweep from reading as a
            # complete one.
            note = ("cut at the budget; " + note) if note else "cut at the budget"
        _score_cell = ("TIMEOUT" if _cut(r) else
                       ("NO OUTPUT" if _empty(r) else sc.get("score", "-")))
        _ratio_cell = ("-" if (_cut(r) or _empty(r)) else (
            ("%.3f" % rt) if rt is not None else "-"))
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s |"
                     % (r["task"], r["arm"], r.get("delivered", 0),
                        _score_cell, sc.get("max", "-"), _ratio_cell,
                        _secs(r.get("duration_s")),
                        str(note)[:60].replace("|", "/")))
    lines += ["", "| arm | tasks | delivered | scored | timeouts | no output | mean ratio | time | tokens | usd |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for name in sorted(summary, key=_arm_rank):
        s = summary[name]
        _mean = ("%.4f" % s["mean_ratio"]) if s["mean_ratio"] is not None else "n/a"
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |"
                     % (name, s["tasks"], s["delivered"], s["scored"],
                        s.get("timeouts") or 0, s.get("no_output") or 0, _mean,
                        _secs(s["time_s"]),
                        s["tokens"] if s["tokens"] is not None else "-",
                        ("$%.4f" % s["usd"]) if s["usd"] is not None else "-"))
    ranked = [(n, s["mean_ratio"]) for n, s in summary.items() if s["mean_ratio"] is not None]
    if ranked:
        ranked.sort(key=lambda kv: kv[1], reverse=True)
        best, best_v = ranked[0]
        tied = len(ranked) > 1 and ranked[0][1] == ranked[1][1]
        if best_v <= 0:
            # A run where every arm scores 0 has no winner: naming the floor
            # "better" would read as a result when nothing was produced. Measured
            # 2026-10-30: a single-arm raw run printed "Better on this run: raw at
            # 0.000", which is the opposite of what the number says.
            lines += ["", "**No arm beat the floor on this run:** best is `%s` at "
                      "%.3f. A raw model with no tools is the floor: an arm that "
                      "does not beat it is not paying for itself." % (best, best_v)]
        elif tied:
            # A TIE with a real score is a RESULT, not an absence of one: two arms
            # reached the same quality, so the decision falls to what they cost.
            # Measured 2026-10-30: `opencode` and `harness2` both scored 48/58 while
            # one took 5 min and the other 20 — printing "no arm beat the floor"
            # hid the only actionable fact.
            _tops = [n for n, v in ranked if v == best_v]
            _cost = ", ".join("%s %s" % (n, _secs(summary[n].get("time_s")))
                              for n in _tops)
            lines += ["", "**Tied at the top:** %s at %.3f — same result, different "
                      "cost (%s). Read the time/cost columns before calling one of "
                      "them better." % (", ".join("`%s`" % n for n in _tops), best_v,
                                        _cost)]
        else:
            tail = ("" if len(ranked) == 1 else
                    " (next: %s)" % ", ".join("%s %.3f" % (n, v) for n, v in ranked[1:]))
            lines += ["", "**Better on this run:** `%s` at %.3f%s. A raw model with no "
                      "tools is the floor: an arm that does not beat it is not paying "
                      "for itself." % (best, best_v, tail)]
    text = "\n".join(lines) + "\n"
    (Path(out) / "compare.md").write_text(text, encoding="utf-8")
    return payload, text


def main(argv=None):
    ap = argparse.ArgumentParser(prog="benchmarks.jobbench_compare")
    ap.add_argument("--profession", default="", help="JobBench profession folder")
    ap.add_argument("--tasks", type=int, default=1, help="task cap")
    ap.add_argument("--arms", default="longrun",
                    help="comma list: raw (no harness), opencode (bare agent loop), "
                         "longrun, harness2")
    ap.add_argument("--model", default="openrouter:z-ai/glm-5.3-flash",
                    help="solver model, Longrun spelling (provider:model)")
    ap.add_argument("--harness2-model", default="",
                    help="solver model, OpenCode spelling (provider/model); "
                         "derived from --model when empty")
    ap.add_argument("--judge-model", default="z-ai/glm-5.3-flash")
    ap.add_argument("--judge-base", default="https://openrouter.ai/api/v1")
    ap.add_argument("--judge-key-env", default="OPENROUTER_API_KEY")
    ap.add_argument("--out", default=None,
                    help="run folder; default: <runs>/<date>_jobbench_<model>_<arms>_n<N>")
    ap.add_argument("--rebuild-index", action="store_true",
                    help="only rebuild <runs>/INDEX.md from the existing run.json files")
    ap.add_argument("--timeout", type=float, default=2400.0, help="per-task solver timeout")
    ap.add_argument("--harness2-timeout", type=float, default=0.0,
                    help="wall-clock budget for the whole Harness² sweep (0 = "
                         "--timeout x tasks). Harness² is a multi-session pipeline "
                         "(base + INV/DOM + AGG), so this is a budget: whatever it "
                         "delivered when it runs out is graded and flagged")
    ap.add_argument("--judge-timeout", type=float, default=3600.0)
    ap.add_argument("--keep-sessions", action="store_true")
    ap.add_argument("--max-steps", type=int, default=40,
                    help="real-tool steps per turn for the Longrun arm (server clamps "
                         "it to its iteration cap); the chat default is 8")
    ap.add_argument("--only-task", default="",
                    help="comma list of task ids or suffixes to re-run (e.g. task2); "
                         "the Longrun arm only — Harness² sweeps by domain")
    ap.add_argument("--harness2-dry-run", action="store_true",
                    help="print Harness²'s command without spending anything")
    ap.add_argument("--harness2-from", default=None,
                    help="grade an EARLIER run folder's Harness² sweep instead of "
                         "spending a second one (adding the other arms is free)")
    args = ap.parse_args(argv)

    if args.rebuild_index:
        print(rebuild_index())
        return 0

    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    only = [t.strip() for t in args.only_task.split(",") if t.strip()]
    if only and "harness2" in arms:
        print("--only-task is the Longrun arm only: Harness² sweeps a whole domain")
        return 2
    tasks = jobbench.tasks(args.profession, None if only else args.tasks)
    tasks = select_tasks(tasks, only, None if only else args.tasks)
    if not tasks:
        print("no JobBench task matched profession=%r" % args.profession)
        return 2
    out = (Path(args.out) if args.out else default_out(arms, args.model, len(tasks),
                                                       scope=args.profession or "all")).resolve()
    # ABSOLUTE, always: the run folder is handed to the Harness² child in
    # `HARNESS2_RUNS_DIR`, and that child resolves it against ITS cwd (the Harness²
    # checkout). Measured 2026-10-30: a relative --out put the whole sweep — and its
    # model_output — inside the upstream repo, where grading never looked.
    os.makedirs(out, exist_ok=True)
    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    write_manifest(out, run_id=out.name, suite=SUITE, started=started,
                   status="running", arms=arms, model=args.model,
                   judge_model=args.judge_model, judge_base=args.judge_base,
                   n_tasks=len(tasks), tasks=[t["id"] for t in tasks],
                   corpus=str(jobbench.repo()), argv=sys.argv[1:])
    print("run: %s" % out, flush=True)
    key = (_key([args.judge_key_env]) or _env_file_key([args.judge_key_env], "~/.hermes/.env")
           or _env_file_key([args.judge_key_env], ".env"))
    if not key:
        write_manifest(out, status="failed", error="no %s" % args.judge_key_env,
                       finished=time.strftime("%Y-%m-%dT%H:%M:%S"))
        print("no %s found (env, ~/.hermes/.env, ./.env)" % args.judge_key_env)
        return 2
    # Refuse to spend on a key that cannot answer: without this, a dead key
    # produced a full table of zeros in 106 s (2026-10-31) and every row looked
    # like a harness verdict.
    remaining = key_budget(key, args.judge_base)
    if remaining is not None and remaining <= 0:
        write_manifest(out, status="failed", finished=time.strftime("%Y-%m-%dT%H:%M:%S"),
                       error="key budget exhausted: %.4f USD left" % remaining)
        print("REFUSED: the solver key has %.4f USD left on %s — top it up, or run "
              "with another provider. No arm was started." % (remaining, args.judge_base))
        return 3
    if remaining is not None:
        print("key budget: %.4f USD left" % remaining, flush=True)
    h2_model = args.harness2_model or args.model.replace(":", "/", 1)
    parity = {"corpus": str(jobbench.repo()), "tasks": ",".join(t["id"] for t in tasks),
              "solver_longrun": args.model, "solver_harness2": h2_model,
              "solver_raw": bare_model_id(args.model),
              "judge_model": args.judge_model, "judge_base": args.judge_base,
              "prompt": "upstream Harness2 PROMPT (verbatim)",
              "longrun_transport": "HTTP POST /api/chat",
              "longrun_max_steps": args.max_steps,
              "raw_transport": "one plain chat/completions call, no tools, no system prompt",
              "harness2_transport": "CLI sweep (harness2 run_sweep --bench jb)"}
    if remaining is not None:
        # The budget at the moment the run started: a reader can tell whether the
        # run was affordable without guessing.
        parity["key_remaining_usd"] = "%.4f" % remaining

    rows = []
    for arm in arms:
        if arm == "longrun":
            got, prov = run_longrun(tasks, out, model=args.model,
                                    judge_model=args.judge_model, judge_base=args.judge_base,
                                    key=key, timeout=args.timeout,
                                    judge_timeout=args.judge_timeout,
                                    keep_sessions=args.keep_sessions,
                                    max_steps=args.max_steps)
            parity.update({"longrun_git": prov.get("git_sha", ""),
                           "longrun_version": prov.get("version", ""),
                           "longrun_token_source": prov.get("token_source", "")})
            rows += got
        elif arm == "raw":
            got, prov_raw = run_raw(tasks, out, model=args.model,
                                    judge_model=args.judge_model, judge_base=args.judge_base,
                                    key=key, timeout=args.timeout,
                                    judge_timeout=args.judge_timeout)
            parity.update({"raw_base_url": prov_raw.get("base_url", ""),
                           "raw_model": prov_raw.get("model", ""),
                           "raw_tools": prov_raw.get("tools", 0)})
            rows += got
        elif arm == "opencode":
            got, prov_oc = run_opencode(tasks, out, solver_model=h2_model,
                                        judge_model=args.judge_model,
                                        judge_base=args.judge_base, key=key,
                                        timeout=args.timeout,
                                        judge_timeout=args.judge_timeout)
            parity.update({"opencode_model": prov_oc.get("model", ""),
                           "opencode_transport": prov_oc.get("transport", "")})
            rows += got
        elif arm == "openclaw":
            got, prov_ocw = run_openclaw(tasks, out, solver_model=h2_model,
                                         judge_model=args.judge_model,
                                         judge_base=args.judge_base, key=key,
                                         timeout=args.timeout,
                                         judge_timeout=args.judge_timeout)
            parity.update({"openclaw_model": prov_ocw.get("model", ""),
                           "openclaw_transport": prov_ocw.get("transport", ""),
                           "openclaw_cli": prov_ocw.get("cli", "")})
            rows += got
        elif arm == "harness2":
            got, meta = run_harness2(tasks, out, solver_model=h2_model,
                                     judge_model=args.judge_model,
                                     judge_base=args.judge_base, key=key,
                                     timeout=(args.harness2_timeout
                                              or args.timeout * len(tasks)),
                                     judge_timeout=args.judge_timeout,
                                     dry_run=args.harness2_dry_run,
                                     reuse=args.harness2_from)
            parity.update({"harness2_status": meta.get("status", ""),
                           "harness2_cmd": " ".join(meta.get("command") or [])})
            rows += got
        else:
            write_manifest(out, status="failed", error="unknown arm %r" % arm,
                           finished=time.strftime("%Y-%m-%dT%H:%M:%S"))
            print("unknown arm %r" % arm)
            return 2

    payload, text = report(out, rows, parity)
    ok = all((r.get("score") or {}).get("ok") for r in rows) and bool(rows)
    write_manifest(out, status=("ok" if ok else "incomplete"),
                   finished=time.strftime("%Y-%m-%dT%H:%M:%S"),
                   arms_summary=payload.get("arms") or {},
                   results=[{"task": r["task"], "arm": r["arm"],
                             "score": (r.get("score") or {}).get("score"),
                             "max": (r.get("score") or {}).get("max"),
                             "delivered": r.get("delivered", 0),
                             "note": (r.get("score") or {}).get("error") or r.get("error") or ""}
                            for r in rows],
                   compare_md="compare.md")
    rebuild_index()
    print("\n" + text)
    print("-> %s/compare.md" % out)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
