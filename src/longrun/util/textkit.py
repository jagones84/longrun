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


#: JSON string escapes for the control characters a model writes RAW (a literal
#: newline/tab instead of `\n`), which makes an otherwise-valid object unparseable.
_JSON_CTRL_ESCAPES = {"\n": "\\n", "\r": "\\r", "\t": "\\t", "\b": "\\b", "\f": "\\f"}


def _escape_control_chars(blob):
    """Escape RAW control characters that sit INSIDE JSON string literals.

    A model that writes a multi-line value emits technically-INVALID JSON —
    `"code": "line1<newline>line2"` with a REAL newline — so `json.loads` rejects
    the whole object ("Invalid control character"). The intent is unambiguous: the
    control character is a literal character of the string, so escape it (and only
    inside string literals) and let the parser read the model's call. Measured
    2026-11-21 (session 5033e643711a): `{"action":"tool","tool":"python.run", …}`
    carried raw newlines, so the call never ran and 2 KB of raw JSON was painted in
    the chat as the turn's answer.
    """
    out, in_str, esc = [], False, False
    for ch in blob:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            elif ch in _JSON_CTRL_ESCAPES:
                out.append(_JSON_CTRL_ESCAPES[ch])
                continue
            elif ord(ch) < 0x20:
                out.append("\\u%04x" % ord(ch))
                continue
        elif ch == '"':
            in_str = True
        out.append(ch)
    return "".join(out)


def inline_code_ranges(text):
    """(start, end) of every INLINE code span in `text` (CommonMark backtick runs).

    2026-11-21 (bug hunt, session b7329cccf94c): a verification report wrote
    `POST /api/tools/call {"tool":"fs.read"}` — a QUOTATION inside an inline code
    span. `extract_action_json` read it as the turn's action, the call ran with no
    arguments and failed, and the same sentence in each of the next five reports
    re-fired the "repeat" guard: seven harness rows in one close-out. A call inside
    backticks is prose, never an emission.

    A FENCED block (```…```) is deliberately NOT a span here: models habitually wrap
    a REAL call in ```json, and those must keep running.
    """
    out, i, n = [], 0, len(text or "")
    while i < n:
        if text[i] != "`":
            i += 1
            continue
        j = i
        while j < n and text[j] == "`":
            j += 1
        ticks = j - i
        k = j
        close = None
        while k < n:
            if text[k] != "`":
                k += 1
                continue
            m = k
            while m < n and text[m] == "`":
                m += 1
            if m - k >= ticks:
                close = m
                break
            k = m
        if close is None:      # an unclosed run is literal text, not a span
            i = j
            continue
        if ticks < 3:          # a fence, not an inline span — never masked
            out.append((i, close))
        i = close
    return out


def _single_quote_is_bracket(text, i, closing):
    """Is the `'` at `i` an OPENING quote and the one at `closing` its CLOSING quote?

    A real quotation is bounded by whitespace (` 'a phrase' `); an APOSTROPHE is not
    (`don't`, `agents'`). Without this test, pairing quotes at random would let a
    stray apostrophe pair with another one 1000 chars later and mask a REAL call in
    between — the mask must never hide an emission.
    """
    before = text[i - 1] if i > 0 else " "
    after_open = text[i + 1] if i + 1 < len(text) else ""
    before_close = text[closing - 1] if closing > 0 else ""
    after = text[closing + 1] if closing + 1 < len(text) else " "
    return ((i == 0 or before.isspace() or before in "([{—-")
            and after_open not in ("", " ")
            and before_close not in ("", " ")
            and (after.isspace() or after in ".,;:!?)]}'\"—-"))


def single_quote_ranges(text):
    """(start, end) of every well-formed SINGLE-quoted span in `text`.

    2026-11-21 (round 165, session b7329cccf94c): the model's explicit finish summary
    read *"the exact sentence **'**The harness once executed the quotation
    POST /api/tools/call {"tool":"fs.read"} and it was denied.**'** was quoted…"*. The
    JSON sat inside SINGLE quotes, so `_looks_like_json_action` still called the whole
    summary machine text and the harness replaced a real answer with "The turn ended
    before a final answer" — the operator's *"I don't want agents stopping
    unexpectedly"*. Prose quotes a sentence with `'…'`; that is a quotation too.

    Measured before shipping: of 2148 assistant messages in the live store, extending
    the mask to these spans changes the SELECTED action in 2 messages and both are
    phantom picks (a shell `-d '{…}'` argument, a payload dump) — no real emission is
    hidden.
    """
    out, i, n = [], 0, len(text or "")
    while i < n:
        if text[i] != "'":
            i += 1
            continue
        j, close = i + 1, None
        while j < n:
            if text[j] == "'" and _single_quote_is_bracket(text, i, j):
                close = j
                break
            j += 1
        if close is None:      # an apostrophe (or an unclosed quote) is literal text
            i += 1
            continue
        out.append((i, close + 1))
        i = close + 1
    return out


def quotation_ranges(text):
    """Every QUOTED span in `text`: inline code spans + well-formed `'…'` spans.

    The ONE reader both the extractor and the reply judgement use, so a JSON object
    that is quoted in prose can never be an emission in one place and an action in
    another.
    """
    return sorted(inline_code_ranges(text) + single_quote_ranges(text))


def mask_quotations(text):
    """`text` with every QUOTED span's body blanked (same length, offsets kept).

    The ONE helper the machine-text judgement uses: anything inside backticks or
    single quotes is a quotation, so a JSON object there can never be the message's
    action.
    """
    text = text or ""
    spans = quotation_ranges(text)
    if not spans:
        return text
    parts, last = [], 0
    for a, b in spans:
        if a < last:
            continue
        parts.append(text[last:a])
        parts.append(" " * (b - a))
        last = b
    parts.append(text[last:])
    return "".join(parts)


def _iter_json_objects(text):
    """Every balanced top-level JSON object/array found in `text`, in order.

    Models frequently wrap their action JSON in prose ("Here is the plan. {..} Now
    I proceed. {..}") or emit SEVERAL actions in one message. The old
    first-`{`..last-`}` slice swallowed the prose between the objects and failed
    to parse, so the turn fell through to "announce and stop". This scanner walks
    the text with a brace/quote-aware cursor and yields each complete value
    independently.
    """
    return [obj for _start, _end, obj in _iter_json_spans(text)]


def _scan_json_value(text, i):
    """`(end_offset, value)` of the balanced JSON value starting at `text[i]`.

    `(None, None)` when the value never closes (a truncated call). End offsets are
    what tells a real action apart from a quoted example: the action is the
    message's CONCLUSION, so only a value that ENDS the message may be executed.
    """
    n, depth, instr, esc, j = len(text), 0, False, False, i
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
                    blob = text[i:j + 1]
                    try:
                        return j + 1, json.loads(blob)
                    except Exception:  # noqa: BLE001
                        # A model's multi-line string value makes the object invalid
                        # for the strict parser (raw control chars): escape them and
                        # retry before dropping the model's call on the floor.
                        try:
                            return j + 1, json.loads(_escape_control_chars(blob))
                        except Exception:  # noqa: BLE001 — unparseable blob
                            return j + 1, None
        j += 1
    return None, None


def _iter_json_spans(text):
    """`(start, end, value)` for every balanced top-level JSON value in `text`."""
    out, i, n = [], 0, len(text)
    while i < n:
        if text[i] in "{[":
            end, val = _scan_json_value(text, i)
            if end is not None:
                if val is not None:
                    out.append((i, end, val))
                i = end
                continue
        i += 1
    return out


#: What may follow a JSON value that still counts as the message's CONCLUSION:
#: whitespace, a closing ``` fence, a closing `<json>` tag, or closing punctuation.
#: Anything else is prose.
#:
#: 2026-11-27 (session architect): the model wrapped its action as
#: `<json>\n{"action":"tool",…}\n</json>`. The `</json>` footer is not in
#: `_TAIL_ONLY`, so `tail_json_spans` saw no call, `extract_action_json` returned
#: None and the harness persisted/streamed the raw envelope as the turn's final
#: answer (three todo.update calls were swallowed the same way, so the harness
#: kept rejecting an answer it thought had never closed its steps).
_TAIL_ONLY = re.compile(
    r"^\s*(?:</\s*json\s*>\s*)?(?:```[ \t]*)?[.,;:!?]*\s*$", re.I)


def tail_json_spans(text):
    """`(start, end, value)` for balanced JSON values that END the message."""
    return [(s, e, v) for s, e, v in _iter_json_spans(text) if _TAIL_ONLY.match(text[e:])]


def json_value_end(text, start):
    """End offset of the balanced JSON value at `start`; None when it never closes.

    Used by the reply judgement: a call cut off mid-emission (no closing brace) is
    still a call attempt; a COMPLETE object quoted mid-sentence is a report.
    """
    return _scan_json_value(str(text or ""), int(start))[0]


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

    2026-11-21: the same hazard with NO later action — a report that QUOTES a call
    inside inline backticks (`` `POST /api/tools/call {"tool":"fs.read"}` ``) had the
    quotation executed as the turn's action, then re-blocked on every retry. A JSON
    value that starts inside a QUOTED span (backticks, or a well-formed `'…'`) is prose
    and is never an action; a fenced block still counts (models wrap real calls in
    ```json).

    2026-11-22 (live session 4dc73d4ef973): a report wrote its dispatch back in plain
    prose — ``chiamata nativa {"action":"dispatch","agent":"A60","goal":"...","wait":true}``
    — with NO quotation marks. The extractor executed that EXAMPLE: two ghost
    dispatches with the placeholder goal, plus a third at 07:50:37 that failed with
    "goal required" (the quoted call had no `goal` key). Only a JSON value that ENDS
    the message (whitespace / a closing fence / punctuation after it) is an action; a
    value embedded mid-sentence is a report ABOUT a call.
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
    quotes = quotation_ranges(text)
    objs = [o for s, _e, o in tail_json_spans(text) if isinstance(o, dict)
            and not any(a <= s < b for a, b in quotes)]
    if not objs:
        return None
    for obj in reversed(objs):
        if any(k in obj for k in _ACTION_KEYS):
            return obj
    return objs[-1]


#: The marker a model's NATIVE tool-call dialect wraps its tags in — full-width
#: bars on DeepSeek V4 (`<｜｜DSML｜｜ invoke ...>`), one bar or none on drifting
#: builds (JAG-534), CORNER BRACKETS on the 2026-11-15 build
#: (`<「DSML」 invoke ...>`, session fd98ee64e89f). It lives here, in the pure text
#: layer, because TWO readers must agree on it: the agent loop (is this message a
#: call?) and reply selection (is this message an ANSWER?) —
#: `memory.stores.turn_reply`, 2026-11-08.
#:
#: 2026-11-15: `「」` was not in the class, so `is_dsml` was False for a message
#: that WAS a call. The turn ended with 2 KB of raw markup stored as the final
#: answer and painted in the chat (the operator's screenshot), instead of the two
#: shell calls being executed. Only `|`/`｜` were known; the drift is the same
#: event JAG-534 described, one alphabet further.
DSML_MARK = r"[|｜「」『』【】]{1,3}\s*DSML\s*[|｜「」『』【】]{1,3}"


def is_dsml(text):
    """True when `text` carries the model's native (DSML) tool-call markup."""
    return bool(re.search(r"<\s*" + DSML_MARK, str(text or ""), re.I))


def is_tool_markup(text):
    """True for any NATIVE tool-call envelope a model emits instead of JSON.

    Three dialects, all machine text: the DSML/Hermes wrapper (`<｜｜DSML｜｜
    invoke name="X">`, `<tool_call><function=…>`), the `<arg_key>K</arg_key>
    <arg_value>V</arg_value>` template (JAG-… 2026-10-31), and the bare
    `<parameter name="x">…` fragment a truncated call leaves behind. Never a
    reply: it is a call the harness already parsed and executed.
    """
    t = str(text or "")
    if not t or "<" not in t:
        return False
    if is_dsml(t):
        return True
    # 2026-11-15: marker drift is a recurring event (bars → one bar → corner
    # brackets). A message that STARTS as a tag envelope and names both `invoke`
    # and `parameter` is a call whatever glyph wraps the marker — and reply
    # selection must prefer a rejected retry over 2 KB of markup shown as the
    # answer. The window keeps a long prose answer that merely QUOTES the tags
    # out of this rule.
    head = t.lstrip()
    if head.startswith("<"):
        window = head[:2000]
        if (re.search(r"\binvoke\b", window, re.I)
                and re.search(r"\bparameter\b", window, re.I)):
            return True
    if re.search(r"<tool_call\b", t, re.I) and re.search(r"<function\s*=", t, re.I):
        return True
    if "<arg_value>" in t and "</arg_key>" in t:
        return True
    return bool(re.search(r"<parameter\s+name\s*=", t, re.I)
                and re.search(r"</?invoke\b", t, re.I))


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


#: The argument names a call uses for the text a HUMAN will read. A write carries
#: the file body in `content`; a message/send in `text`/`body`/`message`.
_WRITTEN_KEYS = ("content", "text", "body", "message", "summary")


def markup_text(text):
    """The WRITTEN text a native tool call carried, or "" when it carried none.

    Measured on job J30 (2026-11-08): the coordinator's per-agent plan and A88's
    report were stored as `<｜｜DSML｜｜ invoke name="fs.write"><｜｜DSML｜｜ parameter
    name="args" …>{"path": …, "content": "# Assignment brief …"}`. The prose
    existed — INSIDE the call — so a panel can show the real brief instead of
    reporting an empty row. A call with no written payload (a shell command, a
    read) honestly returns "".
    """
    t = str(text or "")
    if not t or not is_tool_markup(t):
        return ""
    for obj in _iter_json_objects(t):
        if not isinstance(obj, dict):
            continue
        found = _written_in(obj)
        if found:
            return found
        args = obj.get("args")
        if isinstance(args, dict):
            found = _written_in(args)
            if found:
                return found
    return ""


def _written_in(obj):
    for k in _WRITTEN_KEYS:
        v = obj.get(k)
        if isinstance(v, str) and len(v.strip()) >= 40:
            return v.strip()
    return ""

