#!/usr/bin/env python3
"""Longrun context engineering — v0.3 compaction / token budget / retrieval.

Builds the LLM message list for chat from a session transcript under a token
budget:

  1. the system prompt always stays (uncompacted);
  2. the most recent `keep_recent` messages stay verbatim;
  3. older messages are *compacted* (extractive merge: role + truncated first
     line) into a single synthetic `system` summary block;
  4. relevant memories are *retrieved* (semantic or keyword via memory.search)
     and injected as a separate system block, so answers can use knowledge from
     previous sessions.

`preview()` runs the same pipeline without calling the model — it is what
`POST /api/context/preview` and the `longrun_context` MCP tool expose as
evidence (message counts, estimated tokens in/out, retrieved memory hits).
"""

import os

# JAG-261: fallback budget when NOTHING is known about the model (no alias, no
# live window). The fleet runs 256k-window models, so assuming 256k avoids the
# old 32768 fallback that compacted far too early. A real window (JAG-259) still
# wins whenever it is available.
DEFAULT_BUDGET = int(os.environ.get("LONGRUN_CONTEXT_BUDGET", "262144"))
DEFAULT_KEEP_RECENT = int(os.environ.get("LONGRUN_CONTEXT_KEEP_RECENT", "8"))
RETRIEVAL_TOP_K = int(os.environ.get("LONGRUN_CONTEXT_RETRIEVAL_K", "3"))

# M7: stable summary-block labels. The LLM path stamps SUMMARY_PREFIX; the local
# extractive fallback keeps its legacy EXTRACTIVE_PREFIX (older transcripts and
# `httpapi.compact_session` already emit that form). Both are recognised when
# splitting a previous summary off the next compaction window, so summaries are
# carried forward instead of re-summarized (no summary-of-summary drift).
SUMMARY_PREFIX = "Earlier conversation (summary):\n"
EXTRACTIVE_PREFIX = "Earlier conversation (compacted):\n"
_SUMMARY_PREFIXES = (SUMMARY_PREFIX, EXTRACTIVE_PREFIX)
# M7: cap on the COMBINED (carried + fresh) summary body, mirroring
# `config/compaction.yaml` output_max_chars. Pruned from the front (most-recent
# bullets win — same policy as the summarizer instruction).
COMBINED_SUMMARY_MAX_CHARS = 6000


def _summary_body(content):
    """Return the body after a known summary prefix, or None."""
    if not isinstance(content, str):
        return None
    for prefix in _SUMMARY_PREFIXES:
        if content.startswith(prefix):
            return content[len(prefix):]
    return None


def _is_summary_block(msg):
    return (isinstance(msg, dict) and msg.get("role") == "system"
            and _summary_body(msg.get("content") or "") is not None)


def _is_effective_turn(msg):
    """A turn worth sending to the summarizer (skips scaffolding/noise)."""
    if not isinstance(msg, dict):
        return False
    role = msg.get("role", "?")
    if role == "system":
        return False
    content = msg.get("content") or ""
    if not isinstance(content, str):
        content = str(content)
    content = content.strip()
    return bool(content) and not content.startswith("[harness]")


def count_tokens(text):
    """Same ~4 chars/token proxy the harness uses for accounting.

    JAG-238: a stored message may carry a non-string `content` (a client POSTed
    `{"message": 123}` — `/api/chat` used to persist any truthy value). `len()` on
    an int raised TypeError inside `/api/context`, which dropped the connection
    (the UI then kept showing the PREVIOUS session's meter). Coerce to str here so
    every caller is safe.
    """
    if not text:
        return 0
    if not isinstance(text, str):
        text = str(text)
    return max(1, len(text) // 4)


def _msgs_tokens(msgs):
    return sum(count_tokens(m.get("content", "")) for m in msgs)


def compact(messages, budget_tokens, keep_recent=DEFAULT_KEEP_RECENT, summarizer=None,
            force=False):
    """Compact a transcript under a token budget.

    Returns (msgs, stats). Keeps the newest `keep_recent` messages verbatim;
    older ones are merged into one summary message. If even that is over budget,
    more of the "kept" window is summarized (never silently dropped).

    JAG-103: when `summarizer(old_messages) -> str|None` is given, the older turns
    are summarized BY THE MODEL (a faithful prose summary) instead of the local
    extractive merge. A None/empty return (router down, timeout) falls back to
    the extractive path, so compaction can never stall a turn.

    JAG-110: `force=True` skips the "already under budget" early return, so the
    MANUAL "compact now" action always merges the older turns even on a short
    transcript (previously it silently did nothing and never touched the model).

    JAG-214: when the whole transcript is `keep_recent` messages or fewer (e.g. a
    single huge paste), the verbatim window used to swallow EVERYTHING: `old` was
    empty, so (a) the LLM summarizer was never called (manual "compact" looked
    instant and did nothing) and (b) the over-budget shrink DROPPED turns from the
    front — silent data loss. Now we always leave at least the last message
    verbatim and SUMMARIZE the rest, and a retained turn that alone exceeds the
    budget is TRUNCATED (kept with a head) rather than dropped.
    """
    stats = {"input_messages": len(messages),
             "input_tokens": _msgs_tokens(messages),
             "compacted": 0, "kept": 0, "dropped": 0, "truncated": 0, "summary": None}
    if not messages:
        return [], stats
    if not force and stats["input_tokens"] <= budget_tokens:
        stats["kept"] = len(messages)
        return list(messages), stats
    # Never keep the WHOLE transcript verbatim when we must shrink: leave at least
    # one message to summarize (the newest stays verbatim when there is room).
    if len(messages) > keep_recent:
        keep = keep_recent
    else:
        keep = max(0, len(messages) - 1)
    old = list(messages[:len(messages) - keep])
    recent = list(messages[len(messages) - keep:])
    # If the verbatim window ALONE is over budget, summarize more of it (never
    # drop it): move the oldest "recent" turns into the summarized set.
    while len(recent) > 1 and _msgs_tokens(recent) > budget_tokens:
        old.append(recent.pop(0))
    if old:
        # M7: split the window — a previous summary block is carried forward
        # untouched, ONLY the fresh turns go to the summarizer. No fresh turns
        # means no model call: the previous block is returned byte-identical
        # (content cooldown, fully deterministic).
        prev_bodies = [_summary_body(m.get("content") or "")
                       for m in old if _is_summary_block(m)]
        prev_bodies = [b for b in prev_bodies if b is not None]
        fresh = [m for m in old if not _is_summary_block(m)]
        if prev_bodies and not any(_is_effective_turn(m) for m in fresh):
            summary = old[next(i for i, m in enumerate(old)
                               if _is_summary_block(m))].get("content")
            stats["summary"] = "carried"
            stats["summary_carried"] = True
        else:
            stats["summary_carried"] = False
            new_body = None
            new_from_llm = False
            if summarizer is not None and any(_is_effective_turn(m) for m in fresh):
                try:
                    raw = summarizer(fresh)
                except Exception:  # noqa: BLE001 — fall back to the local merge
                    raw = None
                if raw:
                    raw = str(raw)
                    stripped = _summary_body(raw)
                    new_body = stripped if stripped is not None else raw
                    new_from_llm = True
            if new_body is None:
                # Extractive fallback on the FRESH turns only (legacy path: no
                # previous summary to carry, keep the legacy prefix verbatim).
                summary_lines = []
                for m in fresh:
                    role = m.get("role", "?")
                    # JAG-238: content may be a non-str (see count_tokens).
                    content = m.get("content") or ""
                    if not isinstance(content, str):
                        content = str(content)
                    content = content.strip().replace("\n", " ")
                    # JAG-461: never fold harness scaffolding into the user-facing summary
                    # block — a raw "[harness] Observation for tool …" dump is noise, not
                    # memory (that was the "junk repeated in context" the operator saw when
                    # the LLM summarizer was unavailable). A previous system summary is
                    # skipped too, so summaries never nest.
                    if role == "system" or content.startswith("[harness]"):
                        continue
                    if content:
                        summary_lines.append("%s: %s" % (role, content[:160]))
                extractive_body = "\n".join(summary_lines[-40:])
                if prev_bodies:
                    new_body = extractive_body
                    new_from_llm = False
                else:
                    summary = EXTRACTIVE_PREFIX + extractive_body
                    stats["summary"] = "extractive"
                    new_body = None  # legacy path already stored; skip combine
            if new_body is not None:
                if prev_bodies:
                    combined = "\n".join([b for b in prev_bodies if b] +
                                         ([new_body] if new_body else []))
                    if len(combined) > COMBINED_SUMMARY_MAX_CHARS:
                        combined = combined[-COMBINED_SUMMARY_MAX_CHARS:]
                    summary = SUMMARY_PREFIX + combined
                else:
                    summary = SUMMARY_PREFIX + new_body
                stats["summary"] = "llm" if new_from_llm else "extractive"
        stats["compacted"] = len(old)
        msgs = [{"role": "system", "content": summary}]
    else:
        msgs = []
    for m in recent:
        msgs.append(m)
        stats["kept"] += 1
    out_tokens = _msgs_tokens(msgs)
    # JAG-214: a retained turn that ALONE exceeds the budget is truncated (kept
    # with a head) rather than dropped — losing a turn is worse than shortening it.
    marker = " …[truncated]"
    guard = 0
    while recent and out_tokens > budget_tokens and guard < 4096:
        guard += 1
        head = dict(recent[0])
        rest = _msgs_tokens(([{"role": "system", "content": msgs[0]["content"]}] if old else [])
                            + recent[1:])
        room_chars = max(0, (budget_tokens - rest) * 4)
        content = str(head.get("content", ""))
        if room_chars >= 80 and len(content) > room_chars:
            head["content"] = content[:max(0, room_chars - len(marker))] + marker
            recent[0] = head
            stats["truncated"] += 1
        else:
            recent.pop(0)          # nothing sensible to keep of it
            stats["dropped"] += 1
            stats["kept"] -= 1
        msgs = ([{"role": "system", "content": msgs[0]["content"]}] if old else []) + recent
        out_tokens = _msgs_tokens(msgs)
    stats["output_tokens"] = out_tokens
    return msgs, stats


def retrieve(query_text, top_k=RETRIEVAL_TOP_K, semantic=True):
    """Pull relevant memories for context injection (score >= 0.15)."""
    try:
        from longrun.memory import memory
        if not query_text:
            return []
        hits = memory.search(query_text, None, top_k, semantic)
        out = [{"score": round(s, 3), "kind": r.get("kind"),
                "ts": r.get("ts"), "content": (r.get("content") or "")[:300]}
               for s, r in hits]
        # The vector index is rebuilt periodically; records written since the
        # last rebuild are invisible to it, so merge a keyword pass too.
        if semantic:
            seen = {(h["kind"], h["ts"]) for h in out}
            for s, r in memory.search(query_text, None, top_k, False):
                key = (r.get("kind"), r.get("ts"))
                if key not in seen:
                    out.append({"score": round(s, 3), "kind": r.get("kind"),
                                "ts": r.get("ts"), "content": (r.get("content") or "")[:300]})
        out.sort(key=lambda h: h["score"], reverse=True)
        return out[:top_k]
    except Exception:
        return []


def build(system_prompt, messages, message=None, budget_tokens=DEFAULT_BUDGET,
          keep_recent=DEFAULT_KEEP_RECENT, retrieve_memory=True):
    """Full pipeline: compaction + retrieval. Returns (msgs, stats).

    `msgs` is ready to send: [system(s)...] + compacted transcript + [user message].
    """
    query = message or (messages[-1].get("content") if messages else "")
    stats = {"budget_tokens": budget_tokens, "keep_recent": keep_recent,
             "retrieval_query": (query or "")[:120]}
    # JAG-99: the system prompt is sent uncompacted and dominates small budgets;
    # compact the transcript against what is LEFT for it, so the TOTAL prompt
    # (system + transcript) stays within `budget_tokens`.
    room = max(1024, budget_tokens - count_tokens(system_prompt))
    msgs, cstats = compact(messages, room, keep_recent)
    stats.update({"compaction": cstats})
    if retrieve_memory and query:
        hits = retrieve(query)
        stats["retrieved_memories"] = len(hits)
        if hits:
            mem_block = "Relevant memories from previous sessions:\n" + "\n".join(
                "- (%s, score %.2f) %s" % (h["kind"], h["score"], h["content"])
                for h in hits)
            msgs = [{"role": "system", "content": mem_block}] + msgs
    msgs = [{"role": "system", "content": system_prompt}] + msgs
    if message:
        msgs.append({"role": "user", "content": message})
    stats["final_messages"] = len(msgs)
    stats["final_tokens"] = _msgs_tokens(msgs)
    return msgs, stats


def preview(session, message=None, budget_tokens=DEFAULT_BUDGET, keep_recent=DEFAULT_KEEP_RECENT):
    """Dry-run against a harness session dict (no LLM call). Evidence-shaped."""
    from longrun.core import server  # lazy: server imports this module's consumers, not us
    sess = server.load_session(session) if session else None
    if not sess:
        return {"error": "session not found: %s" % session}
    # JAG-366: use the REAL section-registry prompt (what `assemble_turn` sends),
    # not the legacy monolithic constant — otherwise the budget/compaction maths
    # ran against a ~64-token prompt and the preview LIED about what would be sent.
    try:
        sysp = server._system_prompt(sess)
    except Exception:  # noqa: BLE001 — a dry-run must never raise
        sysp = server.SYSTEM_PROMPT
    msgs, stats = build(sysp, sess.get("messages", []), message,
                        budget_tokens, keep_recent, retrieve_memory=False)
    stats["system_prompt_tokens"] = count_tokens(sysp)
    # retrieval is reported separately so the check can observe memory hits
    hits = retrieve(message or (sess["messages"][-1]["content"] if sess["messages"] else ""))
    stats["retrieval_hits"] = len(hits)
    stats["retrieval_samples"] = [h["content"][:120] for h in hits[:3]]
    stats["session_id"] = sess["id"]
    stats["transcript_messages"] = len(sess.get("messages", []))
    return stats
