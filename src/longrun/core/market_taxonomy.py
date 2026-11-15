"""Deterministic macro-area classifier for marketplace items.

The official MCP Registry publishes no category, and ClawHub's topics are
inconsistent (and often non-English), so without a curated vocabulary every
registry row landed in one bucket and a chip like "Research & Analysis" filtered
to nothing.

The vocabulary and its keywords live in ``config/market_taxonomy.yaml``; this
module only applies them. Same input → same area: no model call, no network, no
randomness. Matching is case-insensitive on word boundaries over the title, name,
description and the publisher's own topic; the area with the most DISTINCT keyword
hits wins, ties follow the file's order, and a miss is the file's ``fallback``.
"""
from __future__ import annotations

import os
import re

import yaml

from longrun.util import paths

TAXONOMY_PATH = os.path.join(paths.REPO_ROOT, "config", "market_taxonomy.yaml")
FALLBACK = "Other"
_cache = {"sig": None, "doc": None}


def _pattern(keyword):
    return re.compile(r"(?<![a-z0-9])" + re.escape(keyword) + r"(?![a-z0-9])")


def _load():
    """`(names, patterns, fallback)` memoised on (path, mtime, size)."""
    path = TAXONOMY_PATH
    try:
        st = os.stat(path)
        sig = (path, st.st_mtime, st.st_size)
    except OSError:
        sig = (path, None, None)
    if _cache["sig"] == sig and _cache["doc"] is not None:
        return _cache["doc"]
    names, pats, fallback = [], {}, FALLBACK
    if sig[1] is not None:
        try:
            with open(path, encoding="utf-8") as f:
                doc = yaml.safe_load(f) or {}
        except (OSError, yaml.YAMLError):
            doc = {}
        if isinstance(doc, dict):
            fallback = str(doc.get("fallback") or FALLBACK)
            for row in (doc.get("areas") or []):
                if not isinstance(row, dict) or not str(row.get("name") or "").strip():
                    continue
                name = str(row["name"]).strip()
                kws = [str(k).strip().lower() for k in (row.get("keywords") or [])
                       if str(k).strip()]
                if not kws:
                    continue
                names.append(name)
                pats[name] = [_pattern(k) for k in kws]
    if not names:                      # a missing/broken file must not crash a sync
        names, pats = [FALLBACK], {FALLBACK: []}
    out = (names, pats, fallback)
    _cache.update(sig=sig, doc=out)
    return out


def areas():
    """The macro-areas, in their declared order (chips use this order)."""
    return list(_load()[0])


def fallback():
    return _load()[2]


def is_known(name):
    return str(name or "").strip().lower() in {n.lower() for n in _load()[0]}


def classify(text, upstream=""):
    """The macro-area of one item.

    `text` is what the item says about itself (title, name, description).
    `upstream` is the publisher's own category, when there is one: an exact match
    to a curated area wins outright, otherwise it is just more text to match.
    """
    names, pats, fb = _load()
    up = str(upstream or "").strip()
    if up:
        low = up.lower()
        for name in names:
            if name.lower() == low:
                return name
    hay = (str(text or "") + " " + up).lower()
    best, hits = "", 0
    for name in names:
        seen = {m.group(0) for p in pats.get(name) or [] for m in p.finditer(hay)}
        if len(seen) > hits:
            best, hits = name, len(seen)
    return best or fb
