#!/usr/bin/env python3
"""`forge.py paperclip-bot` — the child process Paperclip's adapter spawns.

Paperclip's TypeScript adapter starts ``python forge.py paperclip-bot``, writes
ONE invocation envelope (``longrun.paperclip.invocation.v1``) to stdin, and
reads versioned NDJSON protocol frames from stdout. Diagnostics go to stderr.

Contract:

  * the operator's Longrun URL and bearer token come from ``LONGRUN_URL`` and
    ``LONGRUN_TOKEN`` only — never from the envelope, argv, or stdout;
  * an invalid envelope is rejected before any network call;
  * exit ``0`` only for a corroborated ``completed`` run, ``1`` for anything
    else (incomplete, failed, indeterminate, or rejected input), and ``130``
    after SIGINT/SIGTERM, which aborts the known Longrun run id first.

The protocol work itself lives in ``longrun.integrations.paperclip_adapter``.
"""

from __future__ import annotations

import json
import os
import signal
import sys
from typing import Any, Dict, Optional

from longrun.integrations.paperclip_adapter import (
    InvocationError,
    LongrunApiClient,
    PaperclipInvocation,
    TERMINATION_COMPLETED,
)

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_CANCELLED = 130

DEFAULT_URL = "http://127.0.0.1:8790"
# A task envelope is small; a huge stdin payload is a protocol error, not a goal.
STDIN_MAX_BYTES = 262144
LABEL = "paperclip-bot"


def _diagnostic(message: str) -> None:
    """Human diagnostics go to stderr; stdout carries protocol frames only."""
    print("%s: %s" % (LABEL, message), file=sys.stderr, flush=True)


def read_stdin(stream: Any = None) -> str:
    """Read the one invocation envelope; raise ``InvocationError`` if unusable."""
    source = stream if stream is not None else sys.stdin
    raw = source.read(STDIN_MAX_BYTES + 1)
    if len(raw) > STDIN_MAX_BYTES:
        raise InvocationError("stdin exceeds %d bytes" % STDIN_MAX_BYTES)
    text = raw.strip()
    if not text:
        raise InvocationError("empty invocation on stdin")
    return text


def parse_invocation(text: str) -> PaperclipInvocation:
    """Decode and validate the envelope (schema, required ids, bounds)."""
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise InvocationError("stdin is not valid JSON: %s" % exc)
    return PaperclipInvocation.from_dict(data)


class FrameWriter:
    """Writes protocol frames as NDJSON and remembers the Longrun run id.

    The run id is what a cancellation signal must abort; it is learned from the
    streamed frames, not from the invocation.
    """

    def __init__(self, stream: Any = None) -> None:
        self._stream = stream if stream is not None else sys.stdout
        self.run_id: Optional[str] = None

    def __call__(self, frame: Dict[str, Any]) -> None:
        if frame.get("run_id"):
            self.run_id = frame["run_id"]
        self._stream.write(json.dumps(frame, ensure_ascii=False) + "\n")
        self._stream.flush()


def install_cancellation_handlers(client: LongrunApiClient, writer: FrameWriter) -> None:
    """Abort the known run and exit 130 on SIGINT/SIGTERM.

    The handler must not raise: a signal can arrive inside any read, and
    ``os._exit`` is the only exit that cannot be swallowed by the streaming
    loop. Nothing sensitive is printed.
    """

    def _handler(_signum: int, _frame: Any) -> None:
        run_id = writer.run_id
        _diagnostic("cancellation signal received; aborting %s" % (run_id or "unknown run"))
        if run_id:
            try:
                client.abort_run(run_id)
            except BaseException:  # bounded cleanup: never block the exit
                pass
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except BaseException:
            pass
        os._exit(EXIT_CANCELLED)

    for name in ("SIGTERM", "SIGINT"):
        number = getattr(signal, name, None)
        if number is None:
            continue
        try:
            signal.signal(number, _handler)
        except (ValueError, OSError):  # not the main thread / unsupported platform
            pass


def main(argv: Optional[list] = None) -> int:
    """Run one Paperclip-issued task. Returns the process exit code."""
    try:
        invocation = parse_invocation(read_stdin())
    except InvocationError as exc:
        _diagnostic("invalid invocation: %s" % exc)
        return EXIT_FAILED

    client = LongrunApiClient(os.environ.get("LONGRUN_URL", DEFAULT_URL),
                              os.environ.get("LONGRUN_TOKEN"))
    writer = FrameWriter()
    install_cancellation_handlers(client, writer)

    try:
        outcome = client.stream_run(invocation).run(writer)
    except Exception as exc:  # the adapter returns outcomes; this is a last resort
        _diagnostic("adapter failure: %s: %s" % (type(exc).__name__, exc))
        return EXIT_FAILED

    _diagnostic("run %s -> %s" % (outcome.run_id or "unidentified", outcome.termination))
    return EXIT_OK if outcome.termination == TERMINATION_COMPLETED else EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
