#!/usr/bin/env python3
"""Paperclip adapter library — drive one Longrun agent run over REST/SSE.

This is the Python half of the Paperclip external adapter (the TypeScript
package under ``integrations/paperclip`` is the other half). It owns four
things:

  * ``PaperclipInvocation`` — the validated, immutable stdin envelope
    (``longrun.paperclip.invocation.v1``);
  * ``SSEDecoder`` — an incremental, spec-faithful ``text/event-stream`` parser
    (comments, multiline ``data``, arbitrary chunk boundaries);
  * ``map_longrun_event`` — the SAFE event allowlist. Model reasoning
    (``agent.think``), raw observations, tool arguments/results and unknown
    events are never forwarded: they can carry private task data or
    credentials;
  * ``LongrunApiClient`` — bearer-authenticated POST-SSE dispatch, terminal
    corroboration against the run record, and abort by known run id.

Rules this module enforces (design spec, "Cancellation and Failure Handling"):

  * A dispatch is never retried and the SSE request is never reconnected. A
    disconnect before Longrun reports its run id leaves remote work under an id
    we cannot name, so the outcome is ``indeterminate`` — never a success, and
    never a silent second run.
  * Success requires BOTH the streamed terminal classification and the fetched
    run record to say ``completed``. A missing or contradictory record is
    ``indeterminate`` (fail-closed: no false success).
  * The bearer token travels only in the ``Authorization`` header. It is never
    placed in the URL, the body, or an emitted frame payload.

Stdlib only (``urllib.request``): no Python dependency, no LLM, no network in
tests (the opener is injectable).
"""

from __future__ import annotations

import dataclasses
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Tuple

# --------------------------------------------------------------- schema -----
SCHEMA_INVOCATION = "longrun.paperclip.invocation.v1"
SCHEMA_EVENT = "longrun.paperclip.event.v1"

# The five allowlisted Paperclip runtime events.
EVENT_STARTED = "longrun.run.started"
EVENT_PROGRESS = "longrun.run.progress"
EVENT_COMPLETED = "longrun.run.completed"
EVENT_FAILED = "longrun.run.failed"
EVENT_CANCELLED = "longrun.run.cancelled"

# Terminal classifications reported by Longrun (spec: "Completion semantics").
TERMINATION_COMPLETED = "completed"
TERMINATION_MAX_STEPS = "max_steps"
TERMINATION_NO_PROGRESS = "no_progress"
TERMINATION_ABORTED = "aborted"
TERMINATION_ERROR = "error"
# Adapter-local: we could not establish the real outcome. Never a success.
TERMINATION_INDETERMINATE = "indeterminate"

DEFAULT_MAX_STEPS = 6
DEFAULT_TIMEOUT_SEC = 300.0

MAX_SUMMARY_CHARS = 2000
MAX_ERROR_CHARS = 400

# Bound on one `read1` call while draining the SSE stream.
_READ_CHUNK = 65536


class InvocationError(ValueError):
    """The Paperclip stdin envelope is missing or malformed."""


def _require_text(data: Dict[str, Any], key: str) -> str:
    """Return a non-empty string field, or raise ``InvocationError``."""
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise InvocationError("%s must be a non-empty string" % key)
    return value.strip()


def _optional_text(data: Dict[str, Any], key: str) -> Optional[str]:
    """Return an optional string field, or raise ``InvocationError``."""
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise InvocationError("%s must be a non-empty string when present" % key)
    return value.strip()


@dataclasses.dataclass(frozen=True)
class PaperclipInvocation:
    """One Paperclip-orchestrated task, validated and immutable.

    Paperclip identity here is invocation-scoped provenance, not a persistent
    Longrun identity: the same Paperclip agent may drive many runs.
    """

    paperclip_run_id: str
    agent_id: str
    company_id: str
    goal: str
    task_id: Optional[str] = None
    model: Optional[str] = None
    max_steps: int = DEFAULT_MAX_STEPS
    session_id: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Any) -> "PaperclipInvocation":
        """Validate a decoded stdin envelope.

        Unknown keys are ignored so a newer Paperclip can add metadata without
        breaking an older adapter. Every known key is type-checked.
        """
        if not isinstance(data, dict):
            raise InvocationError("invocation must be a JSON object")
        schema = data.get("schema", SCHEMA_INVOCATION)
        if schema != SCHEMA_INVOCATION:
            raise InvocationError("unsupported invocation schema: %r" % (schema,))
        max_steps = data.get("max_steps", DEFAULT_MAX_STEPS)
        if isinstance(max_steps, bool) or not isinstance(max_steps, int) or max_steps < 1:
            raise InvocationError("max_steps must be a positive integer")
        return cls(
            paperclip_run_id=_require_text(data, "paperclip_run_id"),
            agent_id=_require_text(data, "agent_id"),
            company_id=_require_text(data, "company_id"),
            goal=_require_text(data, "goal"),
            task_id=_optional_text(data, "task_id"),
            model=_optional_text(data, "model"),
            max_steps=max_steps,
            session_id=_optional_text(data, "session_id"),
        )

    def longrun_body(self) -> Dict[str, Any]:
        """Return the JSON body for ``POST /api/agent/run/stream``.

        Only the run inputs Longrun understands are forwarded; optional keys are
        omitted rather than sent as ``null`` so the server applies its defaults.
        """
        body: Dict[str, Any] = {"goal": self.goal, "max_steps": self.max_steps}
        if self.model is not None:
            body["model"] = self.model
        if self.session_id is not None:
            body["session"] = self.session_id
        return body


# ------------------------------------------------------------ SSE parser ----
class SSEDecoder:
    """Incremental ``text/event-stream`` decoder.

    ``push`` accepts a ``str`` or ``bytes`` chunk of any size — including chunks
    that split a line, a field, or a frame — and returns the complete
    ``(event, data)`` tuples that became available. ``data:`` lines of one frame
    are joined with ``\\n`` (spec), comments and unknown fields are dropped, and
    an incomplete tail stays buffered until the next push.
    """

    def __init__(self) -> None:
        self._buffer = ""
        self._event: Optional[str] = None
        self._data: List[str] = []

    def push(self, chunk: Any) -> List[Tuple[str, str]]:
        """Feed raw bytes/text; return the events completed by this chunk."""
        if isinstance(chunk, (bytes, bytearray)):
            chunk = bytes(chunk).decode("utf-8", "replace")
        self._buffer += chunk
        out: List[Tuple[str, str]] = []
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            out.extend(self._consume(line.rstrip("\r")))
        return out

    def _consume(self, line: str) -> List[Tuple[str, str]]:
        """Process one complete line; dispatch on the blank separator."""
        if line == "":
            if self._event is None and not self._data:
                return []
            event = self._event or "message"
            data = "\n".join(self._data)
            self._event, self._data = None, []
            return [(event, data)]
        if line.startswith(":"):
            return []  # comment / keepalive
        field, _, value = line.partition(":")
        if value.startswith(" "):
            value = value[1:]
        if field == "event":
            self._event = value
        elif field == "data":
            self._data.append(value)
        return []


# -------------------------------------------------------- event allowlist ---
def map_longrun_event(name: str, payload: Any) -> Optional[str]:
    """Map a Longrun SSE event to a Paperclip runtime event, or ``None``.

    ``None`` means "do not forward": reasoning, observations, tool traffic,
    lifecycle chatter and anything unknown. A ``agent.finish`` without a
    recognised terminal classification is also dropped — an unclassified finish
    must not become a success.
    """
    payload = payload if isinstance(payload, dict) else {}
    if name == "run":
        return EVENT_STARTED
    if name == "agent.iteration":
        return EVENT_PROGRESS
    if name == "agent.finish":
        termination = payload.get("termination")
        if termination == TERMINATION_COMPLETED:
            return EVENT_COMPLETED
        if termination == TERMINATION_ABORTED:
            return EVENT_CANCELLED
        if termination in (TERMINATION_MAX_STEPS, TERMINATION_NO_PROGRESS,
                           TERMINATION_ERROR):
            return EVENT_FAILED
        return None
    if name in ("agent.error", "error"):
        return EVENT_FAILED
    if name == "agent.aborted":
        return EVENT_CANCELLED
    return None


def _classification(name: str, payload: Dict[str, Any]) -> str:
    """Terminal classification carried by a terminal SSE event."""
    termination = payload.get("termination")
    if isinstance(termination, str) and termination:
        return termination
    if name == "agent.aborted":
        return TERMINATION_ABORTED
    return TERMINATION_ERROR


def _progress_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Bounded "current / maximum step" payload; never raw event data."""
    out: Dict[str, Any] = {}
    for key, source in (("iteration", ("i", "iteration")),
                        ("total", ("of", "total"))):
        for candidate in source:
            value = payload.get(candidate)
            if isinstance(value, int) and not isinstance(value, bool):
                out[key] = value
                break
    return out


def _decode(data: str) -> Optional[Dict[str, Any]]:
    """Decode one SSE frame payload; ``None`` when it is not a JSON object."""
    try:
        payload = json.loads(data)
    except (ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _bounded_error(exc: BaseException) -> str:
    """Sanitised, bounded transport error message (no headers, no token)."""
    message = " ".join(str(exc).split())
    name = type(exc).__name__
    return ("%s: %s" % (name, message))[:MAX_ERROR_CHARS] if message else name


class RunOutcome:
    """The adapter's verdict for one dispatched run.

    ``ok`` is the ONLY success signal, and it is true only for a corroborated
    ``completed`` run. ``exit_code`` mirrors that for a CLI shim.
    """

    def __init__(self, termination: str, run_id: Optional[str], exit_code: int) -> None:
        self.termination = termination
        self.run_id = run_id
        self.exit_code = exit_code

    @property
    def ok(self) -> bool:
        return self.termination == TERMINATION_COMPLETED

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "RunOutcome(termination=%r, run_id=%r, exit_code=%d)" % (
            self.termination, self.run_id, self.exit_code)


class _StreamRun:
    """Handle returned by ``stream_run``; ``run(emit)`` actually dispatches."""

    def __init__(self, client: "LongrunApiClient", invocation: PaperclipInvocation) -> None:
        self._client = client
        self._invocation = invocation

    def run(self, emit: Callable[[Dict[str, Any]], None]) -> RunOutcome:
        """Dispatch the run and stream allowlisted frames to ``emit``."""
        return self._client._execute(self._invocation, emit)


class LongrunApiClient:
    """Bearer-authenticated REST/SSE client for one Longrun server.

    ``opener`` is injected (defaults to ``urllib.request.urlopen``) and called as
    ``opener(request, timeout=...)``; tests pass a fake so the suite stays
    offline and deterministic.
    """

    def __init__(self, base_url: str, token: Optional[str], opener: Any = None,
                 timeout_sec: float = DEFAULT_TIMEOUT_SEC) -> None:
        self.base_url = str(base_url).rstrip("/")
        self.token = token
        self.timeout_sec = timeout_sec
        self._opener = opener or urllib.request.urlopen

    # ------------------------------------------------------------ requests --
    def _request(self, method: str, path: str, body: Optional[Dict[str, Any]] = None,
                 stream: bool = False) -> urllib.request.Request:
        """Build a request. The token lives in the header and nowhere else."""
        headers = {"Authorization": "Bearer %s" % (self.token or "")}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if stream:
            headers["Accept"] = "text/event-stream"
        return urllib.request.Request(self.base_url + path, data=data,
                                      headers=headers, method=method)

    def _read_json(self, request: urllib.request.Request) -> Dict[str, Any]:
        """Perform a request and decode a JSON object body (``{}`` on junk)."""
        response = self._opener(request, timeout=self.timeout_sec)
        try:
            raw = response.read()
        finally:
            _close(response)
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, AttributeError):
            return {}
        return decoded if isinstance(decoded, dict) else {}

    def get_run(self, run_id: str) -> Dict[str, Any]:
        """Fetch the authoritative run record (terminal corroboration)."""
        path = "/api/agent/runs/" + urllib.parse.quote(run_id, safe="")
        return self._read_json(self._request("GET", path))

    def abort_run(self, run_id: str) -> Dict[str, Any]:
        """Ask Longrun to abort a KNOWN run id; returns the control response."""
        request = self._request("POST", "/api/agent/control",
                                {"action": "abort", "runId": run_id})
        return self._read_json(request)

    # ------------------------------------------------------------ dispatch --
    def stream_run(self, invocation: PaperclipInvocation) -> _StreamRun:
        """Prepare one run. Nothing is sent until ``.run(emit)`` is called."""
        return _StreamRun(self, invocation)

    def _execute(self, invocation: PaperclipInvocation,
                 emit: Optional[Callable[[Dict[str, Any]], None]] = None) -> RunOutcome:
        """POST the run, stream allowlisted frames, corroborate the outcome."""
        sink = emit if callable(emit) else (lambda frame: None)
        counter = {"seq": 0}

        def send(event: str, run_id: Optional[str], payload: Dict[str, Any]) -> None:
            counter["seq"] += 1
            sink({"schema": SCHEMA_EVENT, "seq": counter["seq"], "event": event,
                  "run_id": run_id, "payload": payload})

        request = self._request("POST", "/api/agent/run/stream",
                                invocation.longrun_body(), stream=True)
        try:
            response = self._opener(request, timeout=self.timeout_sec)
        except BaseException as exc:  # dispatch never happened: safe to report
            send(EVENT_FAILED, None, {"termination": TERMINATION_INDETERMINATE,
                                      "error": _bounded_error(exc)})
            return RunOutcome(TERMINATION_INDETERMINATE, None, 1)

        run_id: Optional[str] = None
        pending: Optional[Tuple[str, str, Dict[str, Any]]] = None
        decoder = SSEDecoder()
        try:
            while True:
                try:
                    chunk = _read(response, _READ_CHUNK)
                except BaseException:
                    # Transport dropped mid-run. Never reconnect, never start a
                    # replacement run: the remote work keeps its own life.
                    break
                if not chunk:
                    break
                for name, data in decoder.push(chunk):
                    payload = _decode(data)
                    if payload is None:
                        continue  # fail-closed: an unparsed frame is dropped
                    if name == "run":
                        run_id = payload.get("run_id") or payload.get("run") or run_id
                    event = map_longrun_event(name, payload)
                    if event is None:
                        continue
                    if event == EVENT_STARTED:
                        send(EVENT_STARTED, run_id, {})
                    elif event == EVENT_PROGRESS:
                        send(EVENT_PROGRESS, run_id, _progress_payload(payload))
                    else:
                        # Terminal frames are held back: they are only emitted
                        # once the run record corroborates them, so exactly one
                        # terminal frame ever reaches Paperclip.
                        pending = (event, _classification(name, payload), payload)
        finally:
            _close(response)

        if pending is None:
            send(EVENT_FAILED, run_id, {"termination": TERMINATION_INDETERMINATE,
                                        "error": "stream ended without a terminal event"})
            return RunOutcome(TERMINATION_INDETERMINATE, run_id, 1)

        event, stream_termination, payload = pending
        if run_id is None:
            send(EVENT_FAILED, None, {"termination": TERMINATION_INDETERMINATE,
                                      "error": "run id was never reported"})
            return RunOutcome(TERMINATION_INDETERMINATE, None, 1)

        try:
            record = self.get_run(run_id)
        except BaseException as exc:
            send(EVENT_FAILED, run_id, {"termination": TERMINATION_INDETERMINATE,
                                        "error": _bounded_error(exc)})
            return RunOutcome(TERMINATION_INDETERMINATE, run_id, 1)
        if record.get("termination") != stream_termination:
            send(EVENT_FAILED, run_id, {"termination": TERMINATION_INDETERMINATE,
                                        "error": "run record contradicts the stream"})
            return RunOutcome(TERMINATION_INDETERMINATE, run_id, 1)

        send(event, run_id, _terminal_payload(stream_termination, payload))
        exit_code = 0 if stream_termination == TERMINATION_COMPLETED else 1
        return RunOutcome(stream_termination, run_id, exit_code)


def _terminal_payload(termination: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Bounded terminal payload: classification, optional summary, error text."""
    out: Dict[str, Any] = {"termination": termination}
    summary = payload.get("summary")
    if isinstance(summary, str) and summary.strip():
        out["summary"] = summary.strip()[:MAX_SUMMARY_CHARS]
    error = payload.get("error") or payload.get("message")
    if isinstance(error, str) and error.strip():
        out["error"] = " ".join(error.split())[:MAX_ERROR_CHARS]
    return out


def _read(response: Any, size: int) -> bytes:
    """One incremental read; prefers ``read1`` so frames arrive as they happen."""
    reader = getattr(response, "read1", None) or response.read
    return reader(size)


def _close(response: Any) -> None:
    """Best-effort close; a broken socket must not mask the real outcome."""
    try:
        response.close()
    except BaseException:
        pass
