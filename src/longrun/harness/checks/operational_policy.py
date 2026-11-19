#!/usr/bin/env python3
"""Harness as Operational Policy — realization, grounding, model affinity.

Source: arXiv:2611.15006, "EvoX: Rethinking the Agent Harness as a Runtime
Policy" (round 124). The harness is not a wrapper around the model: it is an
Operational Policy `H = (Γ, Δ)` complementing the model's Semantic Policy. Γ is
model-facing guidance; Δ is deterministic runtime control. A turn's output
becomes either an executable action or a **disposition** (execute / diagnose /
terminate), never a silent reinterpretation (§3.2-3.3).

The paper's own table is the reason this module refuses to rank harnesses
without the model in the key: EvoX beats the mean of five harnesses by 3.0
points overall, by 10.7 on GLM-5.3 and 7.9 on Kimi K3, and is slightly NEGATIVE
on Sonnet 5 and DeepSeek V4 Flash (§5.3). One global "best harness" is a claim
the evidence contradicts.

  * `realize(output, tools, guidance)` — Δ: schema validation, BOUNDED
    normalization (only a type-coercible argument), a text-leaked call recovered
    only when exactly one tool is named and the caller enabled it. Everything
    else is `diagnose` with the reason, never an inventive repair.
  * `ground(claim, observations)` — Outcome Grounding: a completion claim is
    `supported` only when it cites observations that exist and succeeded, and
    every required operation is among them.
  * `affinity(rows)` — per (model, harness) success over the tasks the harness
    and the baseline BOTH ran, with the discordant pairs and an exact two-sided
    sign test.
  * `route(models, learned)` — propose a harness for a model only with a
    significant, non-tied paired difference; otherwise keep the default and say
    `unmeasured`, because an untested routing decision is a guess.

Pure: records in, decisions out.
"""
from __future__ import annotations

import json
import math

FORMAT = "longrun-operational-policy/1"
_TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool,
          "object": dict, "array": list}


def _disposed(decision, findings, action=None, why=""):
    return {"format": FORMAT, "decision": decision, "action": action,
            "findings": findings, "why": why}


def _coerce(value, declared):
    """The only normalization allowed: a value of the DECLARED type."""
    kind = _TYPES.get(str(declared or ""))
    if kind is None:
        return False, value
    if isinstance(value, bool) and kind is not bool:
        return False, value          # a bool is an int in Python; never assume it was meant
    if isinstance(value, kind):
        return True, value
    if kind is str and isinstance(value, (int, float)):
        return True, str(value)
    if kind in (int, float) and isinstance(value, str):
        try:
            return True, kind(value) if kind is int else float(value)
        except ValueError:
            return False, value
    if kind is bool and isinstance(value, str) and value.lower() in ("true", "false"):
        return True, value.lower() == "true"
    return False, value


def realize(output, tools, guidance=None):
    """Turn a model output into an executable action or an explicit disposition."""
    guidance = guidance or {}
    catalog = {str(t.get("name")): t for t in (tools or []) if isinstance(t, dict)}
    out = output if isinstance(output, dict) else {}
    name = str(out.get("tool") or "")
    if not name:
        return _realize_leak(out, catalog, guidance)
    spec = catalog.get(name)
    if spec is None:
        return _disposed("diagnose", [{"kind": "unknown-tool", "tool": name,
                                       "why": "not a registered interface"}],
                         why="the harness returns the name to the model; it does not invent a tool")
    schema = spec.get("args") or {}
    given = out.get("args") if isinstance(out.get("args"), dict) else {}
    args, normalized, findings = {}, [], []
    for key, value in given.items():
        declared = schema.get(key) or {}
        ok, fixed = _coerce(value, declared.get("type") if isinstance(declared, dict) else None)
        if not ok:
            findings.append({"kind": "schema-mismatch", "tool": name, "argument": key,
                             "declared": declared.get("type") if isinstance(declared, dict) else None,
                             "why": "not coercible to the declared type"})
            continue
        if not (type(fixed) is type(value) and fixed == value):
            normalized.append({"argument": key, "from": value, "to": fixed})
        args[key] = fixed
    for key, declared in schema.items():
        if isinstance(declared, dict) and declared.get("required") and key not in args:
            findings.append({"kind": "missing-argument", "tool": name, "argument": key})
    if findings:
        if not guidance.get("diagnose"):
            findings.append({"kind": "guidance-missing",
                             "why": "Γ has no diagnostic text; Δ alone leaves the model blind"})
        return _disposed("diagnose", findings,
                         why="the call cannot be realized; the model must correct it")
    return _disposed("execute", [{"kind": "normalized", **row} for row in normalized],
                     action={"tool": name, "args": args},
                     why="schema-valid; every change is a coercion of the declared type")


def _realize_leak(out, catalog, guidance):
    text = str(out.get("text") or "")
    named = sorted(n for n in catalog if n and n in text)
    if not named:
        return _disposed("diagnose", [{"kind": "no-action",
                                       "why": "no tool call and no registered tool named"}],
                         why="nothing to execute")
    if len(named) > 1:
        return _disposed("diagnose", [{"kind": "ambiguous-leak", "tools": named,
                                       "why": "more than one tool named in prose"}],
                         why="choosing one would be an invented decision")
    if not guidance.get("recover_leaked"):
        return _disposed("diagnose", [{"kind": "text-leaked-call", "tool": named[0],
                                       "why": "recovery is disabled for this model"}],
                         why="the caller decides whether a prose call may be recovered")
    tail = text.split(named[0], 1)[1]
    if "{" in tail:
        try:
            args, _end = json.JSONDecoder().raw_decode(tail[tail.find("{"):])
        except ValueError:
            args = None
        if isinstance(args, dict):
            return _disposed("execute", [{"kind": "text-leaked-call", "tool": named[0]}],
                             action={"tool": named[0], "args": args},
                             why="one tool, parseable arguments, recovery enabled")
    return _disposed("diagnose", [{"kind": "unparseable-leak", "tool": named[0],
                                   "why": "arguments are not a JSON object"}],
                     why="a guessed argument list is not a repair")


def ground(claim, observations, required=()):
    """A completion claim is supported only by the observations that exist and passed."""
    claim = claim if isinstance(claim, dict) else {"text": str(claim or "")}
    seen = {str(o.get("id")): o for o in (observations or []) if isinstance(o, dict)}
    cited = [str(c) for c in (claim.get("cites") or [])]
    findings = []
    if not cited:
        findings.append({"kind": "ungrounded-claim",
                         "why": "the claim cites no observation"})
    ok_ids = set()
    for cid in cited:
        row = seen.get(cid)
        if row is None:
            findings.append({"kind": "unknown-evidence", "evidence": cid})
        elif row.get("ok"):
            ok_ids.add(cid)
        else:
            findings.append({"kind": "claimed-on-failure", "evidence": cid})
    missing = [name for name in (required or ())
               if not any(o.get("ok") and o.get("operation") == name
                          for o in seen.values())]
    for name in missing:
        findings.append({"kind": "missing-operation", "operation": name})
    blocked = any(f["kind"] in ("ungrounded-claim", "unknown-evidence",
                                "claimed-on-failure", "missing-operation")
                  for f in findings)
    return {"format": FORMAT, "supported": not blocked, "cited": cited,
            "findings": findings,
            "why": ("every cited observation exists and passed"
                    if not blocked else "a report is not proof of execution")}


def _sig(wins, losses):
    """Exact two-sided sign test (the paired comparison the pairs actually support)."""
    n = wins + losses
    if n == 0:
        return 1.0
    k = min(wins, losses)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / (2 ** n)
    return round(min(1.0, 2 * tail), 4)


def affinity(rows, baseline="default"):
    """Per-model harness advantage on the common task set; no shared task, no estimate."""
    by_model = {}
    for row in rows or ():
        if not isinstance(row, dict):
            continue
        model, harness, task = (str(row.get("model") or ""), str(row.get("harness") or ""),
                                str(row.get("task") or ""))
        if not model or not harness or not task:
            continue
        by_model.setdefault(model, {}).setdefault(harness, {})[task] = bool(row.get("ok"))
    out = {}
    for model, harnesses in by_model.items():
        base = harnesses.get(baseline) or {}
        est = {}
        for harness, result in harnesses.items():
            if harness == baseline:
                continue
            shared = sorted(set(base) & set(result))
            if not shared:
                est[harness] = {"unmeasured": True, "pairs": 0,
                                "why": "no task ran under both this harness and the baseline"}
                continue
            wins = sum(1 for t in shared if result[t] and not base[t])
            losses = sum(1 for t in shared if base[t] and not result[t])
            rate = sum(1 for t in shared if result[t]) / len(shared)
            base_rate = sum(1 for t in shared if base[t]) / len(shared)
            est[harness] = {"pairs": len(shared), "wins": wins, "losses": losses,
                            "ties": len(shared) - wins - losses,
                            "rate": round(rate, 4), "baseline_rate": round(base_rate, 4),
                            "delta": round(rate - base_rate, 4), "p": _sig(wins, losses)}
        out[model] = {"baseline_tasks": len(base), "harnesses": est}
    return {"format": FORMAT, "baseline": baseline, "models": out,
            "why": "the model is the key: the same harness wins on one model and loses on another"}


def route(models, learned, p_max=0.05, min_discordant=2):
    """Propose a per-model harness only from a significant paired difference."""
    learned = learned or {}
    decided = {}
    for model in models or ():
        model = str(model)
        candidates = ((learned.get("models") or {}).get(model) or {}).get("harnesses") or {}
        best, findings = None, []
        for harness, row in candidates.items():
            if row.get("unmeasured") or row.get("pairs", 0) < 2:
                findings.append({"kind": "unmeasured", "harness": harness,
                                 "why": "fewer than two shared tasks"})
                continue
            if row.get("wins", 0) + row.get("losses", 0) < min_discordant:
                findings.append({"kind": "no-discordant-pairs", "harness": harness})
                continue
            if row.get("delta", 0) <= 0 or row.get("p", 1.0) > p_max:
                findings.append({"kind": "not-significant", "harness": harness,
                                 "delta": row.get("delta"), "p": row.get("p")})
                continue
            if best is None or row["delta"] > candidates[best]["delta"]:
                best = harness
        if best is None:
            decided[model] = {"harness": learned.get("baseline", "default"),
                              "why": "no measured advantage on this model",
                              "findings": findings}
        else:
            decided[model] = {"harness": best, "why": "measured on shared tasks",
                              "delta": candidates[best]["delta"],
                              "p": candidates[best]["p"], "findings": findings}
    return {"format": FORMAT, "routes": decided,
            "why": "a routing decision without the model's own pairs is a guess"}
