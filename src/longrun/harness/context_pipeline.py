#!/usr/bin/env python3
"""Context attrition — measure what a tool result loses before the model reads it.

Source: arXiv:2610.36114, "Context Is a Pipeline, Not a Window: Information
Attrition in LLM Agent Harnesses" (round 121). An agent never reads its context
window; it reads whatever the harness put there. The paper models five
boundaries and measures a failure at each — and shows the destructive one is
mechanical: slicing a serialized payload at a fixed character count deletes
whatever sits past the cut, so a late field disappears WHOLE while an early one
always survives (§II, §III).

  * `deliver(payload, budget, mode)` — the S1 boundary. "prefix" reproduces the
    shipped defect (a text slice that usually breaks the JSON); "rows" is the
    safe rule: drop whole fields from the end and say which ones, so the payload
    always parses and no field is half-delivered.
  * `profile(runs)` — per-boundary counts and one yield number (findings ÷
    computations), the paper's narrow proxy for work that reached the decision.
  * `boundaries()` — the five stages, with the unit each one loses.

Pure: payloads and run records in, measurements out; nothing is sent anywhere.
"""
from __future__ import annotations

import json

FORMAT = "longrun-context-pipeline/1"
BOUNDARIES = (
    ("S1", "produce->deliver", "top-level field of a tool result"),
    ("S2", "deliver->act", "worker turn before its step budget"),
    ("S3", "act->retain", "history kept after compaction"),
    ("S4", "retain->transfer", "finding handed to the deciding phase"),
    ("S5", "transfer->persist", "nothing survives the run, by design"),
)
MODES = ("prefix", "rows")


def boundaries():
    """The five boundaries and the unit each one loses."""
    return {"format": FORMAT,
            "boundaries": [{"id": b, "stage": s, "unit": u} for b, s, u in BOUNDARIES]}


def _text(payload):
    return json.dumps(payload, ensure_ascii=False)


def deliver(payload, budget, mode="prefix"):
    """Cut one result to a character budget; report what survived and whether it parses."""
    payload = payload if isinstance(payload, dict) else {"value": payload}
    budget = max(0, int(budget or 0))
    if mode not in MODES:
        return {"format": FORMAT, "ok": False, "mode": mode,
                "why": "unknown delivery mode"}
    full = _text(payload)
    fields = [str(k) for k in payload]
    if len(full) <= budget:
        return {"format": FORMAT, "ok": True, "mode": mode, "budget": budget,
                "chars": len(full), "delivered": fields, "dropped": [],
                "broken": False, "parsed": True}
    if mode == "prefix":
        text = full[:budget]
        try:
            parsed = json.loads(text)
            ok_json = True
        except ValueError:
            parsed, ok_json = None, False
        delivered = ([str(k) for k in parsed] if isinstance(parsed, dict) else
                     [f for f in fields if '"%s"' % f in text])
        return {"format": FORMAT, "ok": ok_json, "mode": mode, "budget": budget,
                "chars": budget, "delivered": delivered,
                "dropped": [f for f in fields if f not in delivered],
                "broken": not ok_json, "parsed": ok_json,
                "why": ("the slice broke the payload" if not ok_json else
                        "the slice happened to stay parseable")}
    kept, dropped = [], []
    for name in fields:
        candidate = {**{k: payload[k] for k in kept}, name: payload[name]}
        if len(_text(candidate)) <= budget:
            kept.append(name)
        else:
            dropped.append(name)
    return {"format": FORMAT, "ok": True, "mode": mode, "budget": budget,
            "chars": len(_text({k: payload[k] for k in kept})),
            "delivered": kept, "dropped": dropped, "broken": False, "parsed": True,
            "why": "whole fields only; every drop is named"}


def profile(runs):
    """Per-boundary loss counts and the yield of one campaign (§II)."""
    rows = [r for r in (runs or []) if isinstance(r, dict)]
    stages = {}
    for r in rows:
        stage = str(r.get("boundary") or "").upper()
        if not stage:
            continue
        bucket = stages.setdefault(stage, {"produced": 0, "survived": 0})
        bucket["produced"] += int(r.get("produced") or 0)
        bucket["survived"] += int(r.get("survived") or 0)
    out = {}
    for stage, b in stages.items():
        lost = max(0, b["produced"] - b["survived"])
        out[stage] = {"produced": b["produced"], "survived": b["survived"],
                      "lost": lost,
                      "loss_rate": round(lost / b["produced"], 4) if b["produced"] else None}
    computations = sum(int(r.get("computations") or 0) for r in rows)
    findings = sum(int(r.get("findings") or 0) for r in rows)
    return {"format": FORMAT, "boundaries": out,
            "yield": round(findings / computations, 4) if computations else None,
            "why": "yield is findings over computations, not relevance"}
