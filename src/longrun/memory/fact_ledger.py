#!/usr/bin/env python3
"""Fact ledger — current value, validity interval, provenance, deletion state.

Source: arXiv:2611.20927, "LEDGER: Auditable Agent Memory Under Change" (round
115). Memory that returns an old value next to the current one, trusts a guess
over the user, or brings back a deleted value is wrong even when the final answer
happens to be right. LEDGER keeps, for every fact, its source and the period it
held, and applies five invariants:

  I1 deletion      — a forgotten fact is never returned again;
  I2 supersession  — after an accepted update, only the current value is served;
  I3 temporal      — "as of t" returns the value that held at t;
  I4 deduplication — a replayed event id is ignored;
  I5 contamination — a less trusted source cannot replace a more trusted value.

This module is that ledger, deterministic and cheap: claims are applied in event
order, intervals are half-open `[from, to)`, deletion is a tombstone that closes
the interval, and `verify()` re-checks the five invariants over the stored state.

Pure: claims in, values out; nothing is fetched and nothing is invented.
"""
from __future__ import annotations

FORMAT = "longrun-fact-ledger/1"


def _key(k):
    return " ".join(str(k or "").strip().lower().split())


class Ledger:
    def __init__(self):
        self.entries = []       # {key, value, source, trust, from, to, deleted, event}
        self._events = set()
        self.applied = []

    # -- writes -----------------------------------------------------------
    def apply(self, claim):
        c = claim or {}
        event = str(c.get("id") or "")
        key = _key(c.get("key") or c.get("subject"))
        value = str(c.get("value") or c.get("object") or "").strip()
        source = str(c.get("source") or "").strip()
        # R160 bug hunt: a non-numeric trust label used to abort the whole
        # ingest with ValueError. An unreadable trust is the LEAST trusted value,
        # which is the fail-closed direction for replacement.
        try:
            trust = int(c.get("trust") or 0)
        except (TypeError, ValueError):
            trust = 0
        ts = c.get("ts") or c.get("from")
        if not key or not value:
            return self._note("invalid", key, value, "key and value are required")
        if event and event in self._events:
            return self._note("duplicate-ignored", key, value, "event already ingested (I4)")
        if event:
            self._events.add(event)
        current = self._open(key)
        if current is not None and current["value"] == value:
            return self._note("unchanged", key, value, "same value (I4)")
        if current is not None and trust < current["trust"]:
            # I5 is unconditional: it used to fire only for a new value below
            # trust 2, so a trust-0 claim replaced a trust-1 incumbent.
            return self._note("held-untrusted", key, value,
                              "less trusted source cannot replace the current value (I5)")
        if current is not None:
            current["to"] = ts
            # An untimestamped supersede cannot express a closed interval
            # (`to=None` is "still open"), which used to leave BOTH values open
            # and made verify() report a false I2 violation. The flag is the
            # explicit "this entry is no longer current".
            current["superseded"] = True
        self.entries.append({"key": key, "value": value, "source": source,
                             "trust": trust, "from": ts, "to": None,
                             "deleted": False, "event": event})
        return self._note("superseded" if current else "opened", key, value, "")

    def forget(self, key, ts=None):
        """I1: a tombstone, not a removal — history stays auditable, evidence stops."""
        key = _key(key)
        hit = 0
        for e in self.entries:
            if e["key"] == key and e["to"] is None:
                e["to"] = ts
                e["deleted"] = True
                hit += 1
        return self._note("deleted" if hit else "not-found", key, "", "")

    def _note(self, status, key, value, why):
        row = {"status": status, "key": key, "value": value, "why": why}
        self.applied.append(row)
        return row

    # -- reads ------------------------------------------------------------
    def _open(self, key):
        for e in reversed(self.entries):
            if (e["key"] == key and e["to"] is None and not e["deleted"]
                    and not e.get("superseded")):
                return e
        return None

    def resolve(self, key, as_of=None):
        """I2/I3: the value that held at `as_of` (default: now), never a deleted one."""
        key = _key(key)
        rows = [e for e in self.entries if e["key"] == key]
        if any(e["deleted"] for e in rows):
            # I1 is about the user's request: a forgotten fact is not served, not
            # even as a past value (the paper's probe checks past values too).
            return {"value": None, "status": "deleted"}
        if as_of is None:
            current = self._open(key)
            if current is None:
                return {"value": None, "status": "deleted-or-unknown"}
            return {"value": current["value"], "source": current["source"],
                    "status": "current"}
        for e in rows:
            start = e["from"]
            end = e["to"]
            if e.get("superseded") and end is None:
                # Superseded without a timestamp: the interval has no known end,
                # so no "as of t" answer can be derived from it.
                continue
            if start is not None and start <= as_of and (end is None or as_of < end):
                if e["deleted"]:
                    return {"value": None, "status": "deleted-at-that-time"}
                return {"value": e["value"], "source": e["source"],
                        "status": "historical"}
        return {"value": None, "status": "no-value-at-that-time"}

    def evidence(self, keys, as_of=None):
        """What may be sent to the model: current values, no tombstoned fact (I1)."""
        rows = []
        for k in keys or ():
            got = self.resolve(k, as_of)
            if got.get("value") is not None:
                rows.append({"key": _key(k), "value": got["value"],
                             "source": got.get("source"), "status": got["status"]})
        return rows

    # -- invariants -------------------------------------------------------
    def verify(self):
        problems = []
        opens = {}
        for e in self.entries:
            if (e["to"] is None and not e["deleted"]
                    and not e.get("superseded")):
                opens[e["key"]] = opens.get(e["key"], 0) + 1
            if e["deleted"] and e["to"] is None:
                problems.append({"invariant": "I1", "key": e["key"],
                                 "why": "a tombstone is still open"})
        for k, n in opens.items():
            if n > 1:
                problems.append({"invariant": "I2", "key": k,
                                 "why": "%d open values for one key" % n})
        for k in opens:
            if any(e["key"] == k and e["deleted"] for e in self.entries):
                if self.resolve(k).get("value") is not None:
                    problems.append({"invariant": "I1", "key": k,
                                     "why": "a deleted fact still resolves"})
        # I5: the accepted lineage of a key must be non-decreasing in trust. A
        # deletion starts a new lineage (a tombstone is not a superseded value).
        for k in {e["key"] for e in self.entries}:
            trusts = []
            for e in self.entries:
                if e["key"] != k:
                    continue
                if e["deleted"]:
                    trusts = []
                    continue
                trusts.append(e["trust"])
            if any(trusts[i] > trusts[i + 1] for i in range(len(trusts) - 1)):
                problems.append({"invariant": "I5", "key": k,
                                 "why": "a less trusted value replaced a more trusted one"})
        ids = [e["event"] for e in self.entries if e["event"]]
        if len(ids) != len(set(ids)):
            problems.append({"invariant": "I4", "why": "duplicate event ids"})
        return {"format": FORMAT, "entries": len(self.entries),
                "problems": problems, "verdict": "holds" if not problems else "violated"}
