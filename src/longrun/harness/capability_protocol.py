#!/usr/bin/env python3
"""A capability protocol: an evolve/held-out split, a noise band, a verdict.

Source: RRSI (arXiv:2609.24972 §4.1, Tables 2–3) and Hierarchical
Self-Improvement (arXiv:2608.08466 §4.1, Setup B). Both papers separate the tasks
a harness is evolved on from the tasks it is scored on, and both report an A/A
noise band before trusting a delta. Longrun had benchmark runners but no protocol
tying them together, so "is it better?" had no like-for-like answer.

This module is that protocol and only that: it never runs an agent, never calls a
model and never reads a benchmark. It decides which task ids form the evolve and
held-out sides (deterministically, from a seed), what a run record must carry,
the empirical noise band from repeated unchanged runs, and whether a before/after
difference clears that band at the same n on the same suite.

The SEAL is a contract, not a mechanism here: the caller must give the proposer
only the `evolve` ids and keep `heldout` for the final scoring run.
"""
import hashlib
import json
import random
import time

DEFAULT_FRACTION = 0.3


def split(tasks, heldout_fraction=DEFAULT_FRACTION, seed=0):
    """Deterministic evolve/held-out split of task ids.

    Refuses fewer than two tasks, duplicate ids, and a fraction outside (0, 1);
    both sides are always non-empty. The same (tasks, fraction, seed) always
    produces the same two lists, so a rerun scores the same held-out set.
    """
    ids = [str(t).strip() for t in (tasks or [])]
    if any(not t for t in ids):
        return {"ok": False, "error": "task ids must be non-empty strings"}
    if len(ids) < 2:
        return {"ok": False, "error": "a split needs at least two tasks"}
    if len(set(ids)) != len(ids):
        return {"ok": False, "error": "task ids must be unique"}
    try:
        frac = float(heldout_fraction)
    except (TypeError, ValueError):
        return {"ok": False, "error": "heldout_fraction must be a number in (0, 1)"}
    if not (0.0 < frac < 1.0):
        return {"ok": False, "error": "heldout_fraction must be in (0, 1)"}
    k = int(round(len(ids) * frac))
    k = max(1, min(len(ids) - 1, k))
    shuffled = sorted(ids)
    random.Random(int(seed)).shuffle(shuffled)
    held = shuffled[:k]
    evolve = shuffled[k:]
    return {"ok": True, "seed": int(seed), "fraction": round(frac, 4),
            "n": len(ids), "evolve": evolve, "heldout": held}


def split_digest(split_result):
    """sha256 of the held-out ids, so a run record can name its split without
    carrying the ids (the seal is a contract; the digest is the audit)."""
    held = (split_result or {}).get("heldout") or []
    body = json.dumps({"heldout": list(held)}, sort_keys=True,
                      separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def noise_band(runs):
    """The empirical A/A band: the worst gap between two runs of the UNCHANGED
    harness. A verdict that does not clear this is `flat`, not `improved`.

    `runs` are the same suite's scores across repeated unchanged runs (rates in
    [0, 1] or pass counts). Two runs are the minimum; a single run cannot
    establish a band and is refused instead of guessed.
    """
    vals = []
    for value in runs or []:
        try:
            vals.append(float(value))
        except (TypeError, ValueError):
            return {"ok": False, "error": "A/A scores must be numbers"}
    if len(vals) < 2:
        return {"ok": False,
                "error": "an A/A band needs at least two runs of the unchanged harness"}
    if any(v < 0.0 for v in vals):
        return {"ok": False, "error": "A/A scores cannot be negative"}
    band = max(abs(a - b) for i, a in enumerate(vals) for b in vals[i + 1:])
    return {"ok": True, "band": round(band, 4), "runs": len(vals),
            "min": round(min(vals), 4), "max": round(max(vals), 4)}


def _side(scores):
    """(passed, n, rate) for one side; None when the side is unusable."""
    vals = []
    for value in scores if isinstance(scores, (list, tuple)) else []:
        try:
            v = float(value)
        except (TypeError, ValueError):
            return None
        if v not in (0.0, 1.0):
            return None
        vals.append(int(v))
    if not vals:
        return None
    return {"passed": sum(vals), "n": len(vals),
            "rate": round(sum(vals) / float(len(vals)), 4)}


def record(arm, model, suite, split_result, evolve_scores, heldout_scores,
           tokens=None, date=None):
    """One auditable capability record: who ran what, on which split, at what cost.

    `arm` names the change (or `baseline`), `model` the provider:model, `suite`
    the benchmark. `split_result` is `split()`'s output; the held-out ids are
    replaced by their digest so the record can be shared without breaking the
    seal. Scores are per-task 0/1 outcomes, not an average pasted from a log.
    """
    for name, value in (("arm", arm), ("model", model), ("suite", suite)):
        if not str(value or "").strip():
            return {"ok": False, "error": "%s is required" % name}
    if not isinstance(split_result, dict) or not split_result.get("ok"):
        return {"ok": False, "error": "a recorded run needs a valid split()"}
    ev, ho = _side(evolve_scores), _side(heldout_scores)
    if ev is None or ho is None:
        return {"ok": False,
                "error": "evolve and held-out scores must be non-empty lists of 0/1"}
    if ev["n"] != len(split_result.get("evolve") or []):
        return {"ok": False, "error": "evolve scores do not match the split (%d vs %d)"
                % (ev["n"], len(split_result.get("evolve") or []))}
    if ho["n"] != len(split_result.get("heldout") or []):
        return {"ok": False, "error": "held-out scores do not match the split (%d vs %d)"
                % (ho["n"], len(split_result.get("heldout") or []))}
    try:
        cost = int(tokens) if tokens is not None else None
    except (TypeError, ValueError):
        return {"ok": False, "error": "tokens must be an integer when given"}
    return {"ok": True, "arm": str(arm).strip(), "model": str(model).strip(),
            "suite": str(suite).strip(),
            "date": str(date or time.strftime("%Y-%m-%d")),
            "seed": split_result.get("seed"),
            "fraction": split_result.get("fraction"),
            "split_sha256": split_digest(split_result),
            "evolve": ev, "heldout": ho, "tokens": cost}


def compare(before, after, noise=None, side="heldout"):
    """Did the change clear the A/A band, like for like?

    Requires the same suite and the same n on the compared side; a different n is
    `not-comparable`, not a win. A difference inside the band is `flat`; only a
    difference larger than the band is `improved` or `worse`. Without a band the
    answer is `no-noise-band` — the honest result, not a guess.
    """
    if side not in ("evolve", "heldout"):
        return {"ok": False, "error": "side must be evolve|heldout"}
    if not (isinstance(before, dict) and before.get("ok")
            and isinstance(after, dict) and after.get("ok")):
        return {"ok": False, "error": "compare needs two successful records"}
    if before.get("suite") != after.get("suite"):
        return {"ok": False, "error": "different suites are not comparable"}
    b, a = before.get(side), after.get(side)
    if not (isinstance(b, dict) and isinstance(a, dict)):
        return {"ok": False, "error": "record has no %s side" % side}
    if b.get("n") != a.get("n"):
        return {"ok": False, "error": "not-comparable: n changed (%s vs %s)"
                % (b.get("n"), a.get("n"))}
    try:
        band = float((noise or {}).get("band")) if isinstance(noise, dict) else (
            float(noise) if noise is not None else None)
    except (TypeError, ValueError):
        band = None
    if band is None:
        return {"ok": False, "error": "no-noise-band: run the unchanged harness at "
                "least twice and pass noise_band()"}
    delta = round(float(a["rate"]) - float(b["rate"]), 4)
    if delta > band:
        verdict = "improved"
    elif delta < -band:
        verdict = "worse"
    else:
        verdict = "flat"
    return {"ok": True, "side": side, "suite": before.get("suite"),
            "n": b.get("n"), "before": b["rate"], "after": a["rate"],
            "delta": delta, "band": band, "verdict": verdict,
            "arms": [before.get("arm"), after.get("arm")]}
