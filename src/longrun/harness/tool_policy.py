#!/usr/bin/env python3
"""One schema-derived tool classifier, shared by the harness checkers.

`intent_audit.policy()` and `write_integrity.policy()` answer the same question
from the same schema record: what class is this tool, and what role does each
argument play? They used to carry independent verb lists, which had already
drifted (`download` and `invite` in one, `pay` listed twice in the other), so
the same tool could be classified two different ways. The verb lists and the
role rules live here once; both modules delegate.

The record shape is the one `tools.registry.tool_record()` builds from a live
spec::

    {"name": str, "description": str,
     "args": [{"name", "type", "enum", "description"}],
     "required": [str]}

Pure: a record in, a class and argument roles out.
"""
from __future__ import annotations

import re

FORMAT = "longrun-tool-policy/1"

READ_VERBS = ("get", "search", "list", "read", "fetch", "find", "query",
              "lookup", "view", "retrieve", "download", "recall")
EFFECT_VERBS = ("send", "create", "pay", "update", "delete", "remove", "add",
                "set", "write", "post", "put", "upload", "move", "edit",
                "modify", "rename", "publish", "submit", "purchase", "order",
                "grant", "revoke", "transfer", "cancel", "schedule", "invite",
                "store", "run", "exec", "execute", "plan")
PAYLOAD_NAMES = ("body", "content", "subject", "title", "description",
                 "message", "text", "note", "notes", "comment", "comments")
DESTINATION_HINTS = ("url", "uri", "link", "webpage", "website", "endpoint")
NETWORK_HINTS = ("url", "uri", "http", "https", "web", "network", "remote")
TEMPORAL_HINTS = ("date", "time", "day")


def classify(record):
    """A tool's granular class and its argument roles, from the schema alone.

    Kind is `write`, `local-read`, `external-read` or `unclassified`. A caller
    that only needs read/write folds the two read kinds together; one that
    grants the local-read bypass keys on `local-read` alone. The tool name is
    split on BOTH `.` and `_`, because the live catalog is dotted (`fs.read`)
    while MCP names are underscored (`get_channels`).
    """
    r = record or {}
    name = str(r.get("name") or "").lower()
    docs = str(r.get("description") or "").lower()
    parts = {t for t in re.split(r"[._]+", name) if t}
    first_doc = docs.split()[0] if docs else ""
    if parts & set(EFFECT_VERBS) or first_doc in EFFECT_VERBS:
        kind = "write"
    elif parts & set(READ_VERBS):
        # An external MCP tool is ALWAYS an external read: `client__tool` crosses
        # a server boundary, so a `github__search_code` reads the network even
        # though neither its name nor its description says "url"/"web". The
        # harness's own audit calls extending the local-read bypass to an
        # external read the `read_bypass_extended_to_external` misreading.
        external = ("__" in name
                    or any(h in name or h in docs for h in NETWORK_HINTS))
        kind = "external-read" if external else "local-read"
    else:
        kind = "unclassified"
    roles = {}
    enum = {}
    for arg in r.get("args") or []:
        a = arg if isinstance(arg, dict) else {}
        aname = str(a.get("name") or "")
        low = aname.lower()
        atype = str(a.get("type") or "").lower()
        if a.get("payload") is True or low in PAYLOAD_NAMES:
            role = "payload"
        elif any(h in low for h in DESTINATION_HINTS):
            role = "authority"
        elif any(h in low for h in TEMPORAL_HINTS) or \
                "yyyy-mm-dd" in str(a.get("description") or "").lower():
            role = "temporal"
        elif atype in ("boolean", "enum") or a.get("enum"):
            role = "control"
        else:
            role = "authority"
        roles[aname] = role
        if a.get("enum"):
            enum[aname] = list(a.get("enum") or [])
    return {"format": FORMAT, "kind": kind, "roles": roles, "enum": enum,
            "verdict": "classified" if kind != "unclassified" else "unclassified"}
