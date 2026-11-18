#!/usr/bin/env python3
"""Memory surfacing — retrieve less, and put the rule where the reader acts on it.

Source: arXiv:2611.22179, "RAG in a Trenchcoat: When Minimal Memory Is Enough for
Agentic Systems, and When It Isn't" (round 113). Two findings drive this module:

  * a deliberately minimal memory (per-block observation notes, hybrid retrieval,
    chronological rendering) reaches parity with the prior SOTA at ~5-7K reader
    tokens per query — none of the extraction/supersession/reflection layers earned
    their cost on the tested benchmarks;
  * what separates designs is not what they RETRIEVE but what they ENABLE: atomic
    fact extractors lose the form a demonstrated pattern takes, and a block-summary
    memory retrieves the rule while the reader still does not act on it — a gap that
    "presenting the rule more prominently largely closes" (p. 1).

So the renderer has three tiers and a fixed order:

  1. RULES      — imperative/procedural memories, first, in full, with provenance;
  2. PATTERNS   — demonstrated forms (code/step templates) with their example;
  3. FACTS      — everything else, chronological (stable, no invented ordering).

Under a token budget the renderer drops FACTS first and never drops a RULE: the
paper's point is that the rule's position decides whether it is used.

Pure: hits in, text out; nothing is invented and nothing is stored.
"""
from __future__ import annotations

import re

FORMAT = "longrun-rule-surface/1"
_RULE = re.compile(r"\b(always|never|must|must not|do not|only|required?|"
                   r"when .{1,60} (?:then|do)|before .{1,60} (?:do|run))\b", re.I)
_PATTERN = re.compile(r"```|^\s*\d+[.)]\s|^\s*[-*]\s+\S.*\n\s*[-*]\s", re.M)


def estimate_tokens(text):
    return (len(text or "") + 3) // 4


def classify(hit):
    """A hit is a rule, a pattern, or a fact — from its own text, not a label."""
    text = str((hit or {}).get("text") or "")
    if _PATTERN.search(text):
        return "pattern"
    if _RULE.search(text):
        return "rule"
    return "fact"


def _source(hit):
    src = (hit or {}).get("source") or (hit or {}).get("id") or ""
    return str(src)


def _block(title, rows):
    if not rows:
        return ""
    body = "\n".join("- %s%s" % (r["text"].strip(),
                                 ("  [%s]" % r["source"] if r["source"] else ""))
                     for r in rows)
    return "%s\n%s" % (title, body)


def render(hits, budget_tokens=None):
    """Rules first, patterns second, facts chronological; never invent."""
    rows = []
    for hit in hits or ():
        if not isinstance(hit, dict):
            continue
        text = str(hit.get("text") or "").strip()
        if not text:
            continue
        rows.append({"kind": classify(hit), "text": text,
                     "source": _source(hit), "ts": hit.get("ts") or hit.get("time") or ""})
    rules = [r for r in rows if r["kind"] == "rule"]
    patterns = [r for r in rows if r["kind"] == "pattern"]
    facts = [r for r in rows if r["kind"] == "fact"]
    facts.sort(key=lambda r: str(r["ts"]))          # chronological, stable
    dropped = []
    if budget_tokens:
        keep_facts = list(facts)
        # Drop facts first; if the rules alone exceed the budget, keep the rules
        # and report the overflow instead of hiding the rule.
        while keep_facts and estimate_tokens(
                "\n".join(x for x in (_block("RULES (apply these):", rules),
                                      _block("PATTERNS (form to reuse):", patterns),
                                      _block("FACTS (chronological):", keep_facts)) if x)
        ) > int(budget_tokens):
            dropped.append(keep_facts.pop())
        facts = keep_facts
    text = "\n\n".join(x for x in (_block("RULES (apply these):", rules),
                                   _block("PATTERNS (form to reuse):", patterns),
                                   _block("FACTS (chronological):", facts)) if x)
    return {"format": FORMAT, "text": text,
            "counts": {"rules": len(rules), "patterns": len(patterns),
                       "facts": len(facts), "dropped": len(dropped)},
            "prominent": [r["source"] for r in rules],
            "tokens": estimate_tokens(text),
            "over_budget": bool(budget_tokens and estimate_tokens(text) > int(budget_tokens))}
