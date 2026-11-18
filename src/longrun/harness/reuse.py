#!/usr/bin/env python3
"""Safe reuse — one execution per identical deterministic tool call.

Source: arXiv:2611.09254, "TwinHash: Two-Sided Object Identity Management for
Time- and Energy-Efficient Agentic Workflows" (round 110). Its rule is the one a
naive tool cache gets wrong: an input-side key alone is UNSAFE. A hit is only
served when (a) the tool is on the allowlist of read-only tools, (b) the key
includes the versions of the resources the call reads, and (c) the stored output
still matches its content fingerprint.

This module is the harness-side half of that idea, with no serving stack:

  * `classify`  — is this call reusable at all? writes and execs never are;
  * `key`       — canonical descriptor (tool, version, regularized args,
                  resource epochs) digested to a short hash;
  * `Epochs`    — per-resource version counter; a write advances it, so every
                  later read gets a NEW key (no stale reuse);
  * `Store`     — put/get with content fingerprints and a per-key serve cap
                  (the paper's guard against replaying a search algorithm's
                  sampled diversity away);
  * `audit`     — over a session's stored cards: how many identical
                  deterministic reads repeated, how many were safely reusable,
                  and which keys produced DIFFERENT outputs (unsafe, excluded).

Pure: nothing is executed and nothing is written.
"""
from __future__ import annotations

import hashlib
import json
import os

FORMAT = "longrun-safe-reuse/1"

# Argument fields that must NOT take part in identity: they change per request
# while the work the call does stays the same.
_TRANSIENT = ("timeout", "request_id", "trace", "trace_id", "ts", "timestamp",
              "nonce", "seed", "call_id", "run_id")
_PATH_KEYS = ("path", "file", "target", "cwd", "workspace", "dir", "filename")
_OUTPUT_KEYS = ("result", "observation", "output", "stdout")

_WRITE_WORDS = ("write", "edit", "append", "delete", "remove", "move", "rename",
                "apply", "commit", "push", "mkdir", "touch", "chmod")
_EXEC_WORDS = ("shell", "exec", "run", "terminal", "bash", "python", "sandbox")
_READ_WORDS = ("read", "grep", "glob", "search", "list", "ls", "find", "tree",
               "cat", "stat", "head", "tail")


def _args(card_or_args):
    raw = card_or_args.get("args") if isinstance(card_or_args, dict) and "args" in card_or_args \
        else card_or_args
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {}


def _has_word(tool, words):
    low = str(tool or "").lower()
    return any(w in low for w in words)


def classify(tool, args=None, allow=None):
    """Decide the stream of a call and whether its result may be reused.

    `allow` is the allowlist of read-only tool names (the paper's SafeTools).
    Without it the tool NAME decides, conservatively: a write/exec word always
    wins over a read word, and an unknown tool is not reusable.
    """
    tool = str(tool or "")
    if not tool:
        return {"tool": tool, "stream": "unknown", "reusable": False,
                "why": "no tool name"}
    if _has_word(tool, _WRITE_WORDS):
        return {"tool": tool, "stream": "write", "reusable": False,
                "why": "a write changes state; its result is never reused"}
    if _has_word(tool, _EXEC_WORDS):
        return {"tool": tool, "stream": "exec", "reusable": False,
                "why": "an exec can have side effects; never reused"}
    if allow is not None:
        ok = tool in allow
        return {"tool": tool, "stream": "read", "reusable": ok,
                "why": "on the allowlist" if ok else "not on the read-only allowlist"}
    if _has_word(tool, _READ_WORDS):
        return {"tool": tool, "stream": "read", "reusable": True,
                "why": "read-shaped tool name"}
    return {"tool": tool, "stream": "unknown", "reusable": False,
            "why": "unknown tool; not admitted without an allowlist"}


def _regular(args):
    """The descriptor of the call: args minus the fields that vary per request."""
    out = {}
    for k, v in (args or {}).items():
        if str(k).lower() in _TRANSIENT:
            continue
        if isinstance(v, str):
            out[str(k)] = v.strip()
        else:
            out[str(k)] = v
    return out


def resources(args):
    """The resources a call declares it reads (its path-shaped arguments)."""
    args = _regular(args)
    out = []
    for k in _PATH_KEYS:
        v = args.get(k)
        if isinstance(v, str) and v.strip():
            out.append(os.path.normpath(os.path.expanduser(v.strip())))
    return sorted(set(out))


def key(tool, args=None, version="", epochs=None):
    """The input-side key: tool + version + regularized args + resource epochs.

    A tool that declares no resource depends on the GLOBAL epoch, so any write
    anywhere invalidates it — the paper's conservative fallback.
    """
    args = _regular(args)
    desc = {"tool": str(tool or ""), "version": str(version or ""), "args": args}
    if epochs is not None:
        res = resources(args)
        desc["epochs"] = {r: epochs.get(r) for r in res} if res \
            else {"*": epochs.global_epoch()}
    blob = json.dumps(desc, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


class Epochs:
    """Per-resource version counters. A write advances the resource it touched."""

    def __init__(self, initial=None):
        self._epochs = dict(initial or {})
        self._global = 0

    def get(self, resource):
        return int(self._epochs.get(str(resource), 0))

    def global_epoch(self):
        return self._global

    def advance(self, resource):
        r = str(resource)
        self._epochs[r] = self.get(r) + 1
        self._global += 1
        return self._epochs[r]

    def advance_all(self, items):
        for r in items or ():
            self.advance(r)
        return self.snapshot()

    def snapshot(self):
        return {"global": self._global,
                "resources": dict(sorted(self._epochs.items()))}


def fingerprint(output):
    """Output-side content fingerprint (short sha256 over the normalized text)."""
    if output is None:
        return None
    if not isinstance(output, str):
        output = json.dumps(output, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(output.encode("utf-8")).hexdigest()[:16]


class Store:
    """Committed outputs by input-side key, validated by fingerprint.

    `cap` is the per-key serve cap: after that many hits the entry is no longer
    served, so a search loop's sampled diversity is not replayed away.
    """

    def __init__(self, cap=4):
        self.cap = int(cap)
        self._rows = {}
        self.hits = 0
        self.misses = 0

    def put(self, key_, output, fingerprint_=None):
        fp = fingerprint_ or fingerprint(output)
        self._rows[key_] = {"output": output, "fingerprint": fp, "served": 0}
        return fp

    def get(self, key_, expect=None):
        row = self._rows.get(key_)
        if not row:
            self.misses += 1
            return {"hit": False, "reason": "unknown-key"}
        if row["served"] >= self.cap:
            self.misses += 1
            return {"hit": False, "reason": "serve-cap"}
        if expect is not None and row["fingerprint"] != expect:
            self.misses += 1
            return {"hit": False, "reason": "fingerprint-mismatch"}
        if row["fingerprint"] != fingerprint(row["output"]):
            # The stored bytes were mutated after commit: never serve them.
            self.misses += 1
            return {"hit": False, "reason": "content-changed"}
        row["served"] += 1
        self.hits += 1
        return {"hit": True, "output": row["output"], "fingerprint": row["fingerprint"],
                "served": row["served"]}

    def stats(self):
        return {"entries": len(self._rows), "hits": self.hits, "misses": self.misses,
                "cap": self.cap}


def _output(card):
    for k in _OUTPUT_KEYS:
        v = card.get(k)
        if isinstance(v, str):
            return v
        if v is not None and not isinstance(v, (dict, list)):
            return str(v)
    return None


def audit(cards, allow=None, version=""):
    """How much repeated deterministic work did this session do?

    Reads the stored cards in order. A write/exec advances the epochs of the
    resources it names, so a read AFTER it is a different key by construction.
    Returns reusable repeats, unsafe keys (same key, different output) and the
    calls that could have been served instead of recomputed.
    """
    cards = [c for c in (cards or []) if isinstance(c, dict)]
    epochs = Epochs()
    seen = {}
    candidates = 0
    reusable_hits = 0
    unsafe = []
    skipped = 0
    for i, card in enumerate(cards):
        tool = str(card.get("tool") or "")
        args = _args(card)
        cls = classify(tool, args, allow)
        if cls["stream"] in ("write", "exec"):
            epochs.advance_all(resources(args))
            continue
        if not cls["reusable"]:
            skipped += 1
            continue
        candidates += 1
        k = key(tool, args, version, epochs)
        out = _output(card)
        fp = fingerprint(out) if out is not None else None
        rec = seen.get(k)
        if rec is None:
            seen[k] = {"tool": tool, "fingerprint": fp, "count": 1, "seq": i,
                       "args": _regular(args)}
            continue
        rec["count"] += 1
        if fp and rec["fingerprint"] and fp != rec["fingerprint"]:
            if k not in unsafe:
                unsafe.append(k)
        elif fp and fp == rec["fingerprint"]:
            reusable_hits += 1
    repeats = sum(r["count"] - 1 for r in seen.values())
    top = sorted(
        ({"key": k, "tool": r["tool"], "count": r["count"], "seq": r["seq"],
          "args": r["args"]} for k, r in seen.items() if r["count"] > 1),
        key=lambda r: (-r["count"], r["seq"]))[:10]
    return {
        "format": FORMAT,
        "cards": len(cards),
        "candidates": candidates,
        "distinct": len(seen),
        "repeats": repeats,
        "reusable_hits": reusable_hits,
        "unsafe": unsafe,
        "skipped_not_reusable": skipped,
        "saved_calls": reusable_hits,
        "top": top,
        "verdict": ("no-repetition" if not repeats else
                    "reusable" if reusable_hits else "unsafe-only"),
    }
