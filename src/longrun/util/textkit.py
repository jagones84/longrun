"""Prose-tolerant text helpers: split `<think>` blocks, recover JSON from prose.

Models frequently wrap their action JSON in prose and emit SEVERAL values in one
message; these scanners recover each complete value without dropping the turn.

Extracted from ``server.py`` (JAG-370). Pure functions, stdlib only.
"""
import json
import re


#: Every reasoning-wrapper a model has been seen to emit. The LITERAL `<think>` was
#: the only one matched before 2026-11-01, so `<think signature="reasoning-details://…">`
#: — what the routed model actually sends — went straight through to the answer surface
#: (measured on GAIA: the graded answer became the whole thinking block).
_THINK_BLOCK = re.compile(
    r"<(think|thinking|reasoning|analysis|thought)(?:\s[^>]*)?>(.*?)</\1\s*>",
    re.S | re.I)
#: An opening tag that was never closed. Dropping only the tag keeps whatever text
#: follows, which is the honest choice: the reasoning and the answer are then
#: indistinguishable, and cutting at the tag would throw the answer away.
_THINK_OPEN = re.compile(r"<(think|thinking|reasoning|analysis|thought)(?:\s[^>]*)?>", re.I)


def strip_think(text):
    """Split every `<think …>…</think>` block out of content.

    Tolerates attributes (`<think signature="…">`), any case, the
    `thinking`/`reasoning`/`analysis`/`thought` spellings, and SEVERAL blocks. An
    unclosed opening tag is dropped as a token (the body is kept), because a turn
    that never closed the block still has to answer.
    """
    if not text or "<" not in text:
        return text, None
    found = []

    def _take(m):
        found.append(m.group(2))
        return ""

    clean = _THINK_BLOCK.sub(_take, text)
    if not found:
        return _THINK_OPEN.sub("", text), None
    clean = _THINK_OPEN.sub("", clean)
    return clean, "\n\n".join(found).strip() or None


def _iter_json_objects(text):
    """Every balanced top-level JSON object/array found in `text`, in order.

    Models frequently wrap their action JSON in prose ("Here is the plan. {..} Now
    I proceed. {..}") or emit SEVERAL actions in one message. The old
    first-`{`..last-`}` slice swallowed the prose between the objects and failed
    to parse, so the turn fell through to "announce and stop". This scanner walks
    the text with a brace/quote-aware cursor and yields each complete value
    independently.
    """
    objs, i, n = [], 0, len(text)
    while i < n:
        if text[i] in "{[":
            depth, instr, esc, start = 0, False, False, i
            j = i
            while j < n:
                c = text[j]
                if instr:
                    if esc:
                        esc = False
                    elif c == "\\":
                        esc = True
                    elif c == '"':
                        instr = False
                else:
                    if c == '"':
                        instr = True
                    elif c in "{[":
                        depth += 1
                    elif c in "}]":
                        depth -= 1
                        if depth == 0:
                            break
                j += 1
            if depth == 0 and j < n:
                try:
                    objs.append(json.loads(text[start:j + 1]))
                except Exception:  # noqa: BLE001 — skip an unparseable blob
                    pass
                i = j + 1
                continue
        i += 1
    return objs


#: The keys that make a JSON object an ACTION rather than a data artifact.
_ACTION_KEYS = ("action", "tool", "tool_name", "todos", "steps", "calls", "tool_calls")


def extract_action_json(text):
    """The JSON object the model MEANT as its action: the LAST action-shaped one.

    Measured 2026-11-01 (GAIA `5d0080cb`): the model's prose/scratchpad QUOTED an
    earlier action ("… not {"tool":"todo.update"} …") before the real action at the
    end of the message. `extract_json` returns the FIRST object, so the harness
    rejected a call the model had not made — and the model, seeing its correct JSON
    refused, re-emitted the identical thing four times. An action is the message's
    CONCLUSION, not the first JSON that happens to appear in it.
    """
    text = (text or "").strip()
    if not text:
        return None
    try:
        whole = json.loads(text)
        if isinstance(whole, dict):
            return whole
    except Exception:  # noqa: BLE001 — prose around the object is the normal case
        pass
    objs = [o for o in _iter_json_objects(text) if isinstance(o, dict)]
    if not objs:
        return None
    for obj in reversed(objs):
        if any(k in obj for k in _ACTION_KEYS):
            return obj
    return objs[-1]


def extract_json(text):
    """First JSON value in `text` (prose-tolerant, multi-object safe).

    Tolerates prose around and BETWEEN objects: returns the FIRST complete
    {"action": ...} the model emitted, so the chat/agent loop acts on it instead
    of dropping the whole turn.
    """
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    objs = _iter_json_objects(text)
    return objs[0] if objs else None

