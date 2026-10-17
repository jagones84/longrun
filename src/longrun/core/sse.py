"""Server-Sent Events plumbing + chain-of-thought delta coalescing.

Terminal SSE streams (a chat turn, an agent run) must end — and the socket must
close — shortly after their terminal ``done`` event; they must never outlive it.
The heartbeat + idle guards keep a mobile/proxy channel alive during a silent
gap. ``ThinkCoalescer`` (JAG-265) bounds how fast per-token ``think`` deltas
reach the SSE stream and the durable feed.

Extracted from ``server.py`` (JAG-370). Stdlib only.
"""
import json
import os
import queue
import socket
import time

# JAG-265: chain-of-thought (`think`) deltas stream per-token. On a fast model that
# is dozens of `chat.delta` events/s going to BOTH the SSE stream AND the durable
# feed — the WebUI render queue falls behind and the page LOOKS frozen while the
# server is perfectly healthy. Coalesce consecutive think chunks into one delta
# emitted at most every CHAT_THINK_FLUSH_S, and cap the LIVE think text so a runaway
# monologue cannot flood the client. The full text is still kept on the tool card.
CHAT_THINK_FLUSH_S = float(os.environ.get("LONGRUN_THINK_FLUSH_S", "0.08"))
CHAT_THINK_LIVE_CAP = int(os.environ.get("LONGRUN_THINK_LIVE_CAP", "20000"))


def sse_close(handler):
    """v0.6.1 (JAG-48): end an SSE response for good.

    The HTTP/1.0 shutdown was not enough: the generator (and with it the
    socket) stayed open whenever the upstream model call stalled, so clients
    that wait for EOF (`curl -N`, the mobile app's HttpURLConnection with
    readTimeout=0) froze on `busy` and could not send the next message.
    Flush, mark the connection non-reusable and send the EOF explicitly.
    """
    try:
        handler.wfile.flush()
    except Exception:  # noqa: BLE001 — client already gone
        pass
    handler.close_connection = True
    try:
        handler.connection.shutdown(socket.SHUT_WR)  # FIN → client sees EOF now
    except Exception:  # noqa: BLE001
        pass


def sse_response(handler, gen, keepalive=False):
    """Write an SSE stream and close it when the generator ends.

    `keepalive=True` is reserved for `/api/feed` (and the blackboard watcher):
    those streams are loopback tails that stay open on purpose, so the socket
    gets SO_KEEPALIVE. Every other stream (`/api/chat/stream`,
    `/api/agent/run`) is terminal: after its `done` event the generator is
    exhausted and the connection is closed immediately.
    """
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Connection", "close")
    handler.end_headers()
    if keepalive:
        try:
            handler.connection.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        except Exception:  # noqa: BLE001
            pass
    try:
        for chunk in gen:
            handler.wfile.write(chunk.encode("utf-8"))
            handler.wfile.flush()
    except (BrokenPipeError, ConnectionResetError):
        pass
    finally:
        sse_close(handler)


def sse_pump(q, worker, open_comment=": stream open\n\n", terminal="done",
             idle_timeout=None):
    """Drain a producer queue into SSE frames, then stop for good.

    v0.6.1 (JAG-48): the stream is *terminal* — it ends with exactly one
    terminal `done` and the caller closes the socket.
    Two guards make that unconditional, so the connection can never linger:
      * the producer thread dying without its sentinel ends the stream, and
      * `idle_timeout` seconds without a single event ends the stream with an
        `error` + `done` instead of waiting on a stalled upstream forever.
    v1.6.9 (JAG-60): while the producer is silent (blocked on the approval
    gate, or a slow first token) we emit an SSE comment `: ping` every ~10s so
    mobile networks/proxies don't idle-abort the channel ("connection abort").
    """
    yield open_comment  # first bytes out immediately → the client sees 200
    deadline = time.time() + idle_timeout if idle_timeout else None
    idle_s = 0.0
    while True:
        try:
            item = q.get(timeout=1.0)
        except queue.Empty:
            if deadline is not None and time.time() > deadline:
                yield "event: error\ndata: %s\n\n" % json.dumps(
                    {"error": "chat stream timed out after %.0fs of silence" % idle_timeout})
                break
            if not worker.is_alive():
                break  # producer gone without a sentinel: never hang the client
            idle_s += 1.0
            # JAG-79: shorter heartbeat (5s) so mobile NAT/proxies don't idle-abort
            # a chat stream during a silent gap (a tool call, an MCP recovery).
            if idle_s >= 5.0:
                idle_s = 0.0
                yield ": ping\n\n"  # heartbeat: keeps the SSE channel alive
            continue
        if item is None:
            break
        idle_s = 0.0
        if deadline is not None:
            deadline = time.time() + idle_timeout
        yield item
    yield "event: %s\ndata: {}\n\n" % terminal


def sse_tail(q, backlog=None, open_comment=": tail open\n\n", idle_limit=600):
    """Drain a LOOPBACK tail queue into SSE frames, then stop (JAG-483).

    The durable feed (``/api/feed``) and the blackboard watcher are the two
    streams that stay open on purpose: replay their backlog once, then forward
    whatever the producer pushes, emitting a ``: ping`` comment on every silent
    second and giving up after ``idle_limit`` consecutive silent ones.

    Only the tail skeleton is shared — each caller keeps its own backlog source,
    registration set and open comment.
    """
    if backlog:
        yield "event: backlog\ndata: %s\n\n" % json.dumps(backlog, ensure_ascii=False)
    yield open_comment
    idle = 0
    while idle < idle_limit:
        try:
            yield q.get(timeout=1)
            idle = 0
        except queue.Empty:
            idle += 1
            yield ": ping\n\n"


class ThinkCoalescer:
    """JAG-265: coalesce per-token chain-of-thought deltas into bounded flushes.

    `feed(channel, text)` accumulates consecutive `think` chunks and emits them as
    ONE delta at most every `flush_s` seconds (and once the live text hits `cap`),
    so a fast reasoning model cannot flood the SSE stream / durable feed with
    dozens of events per second. Any non-think channel flushes the pending CoT
    first, preserving ordering. `flush()` is called at turn end for the tail.
    """

    def __init__(self, emit, flush_s=None, cap=None, clock=time.time):
        self._emit = emit
        self._flush_s = CHAT_THINK_FLUSH_S if flush_s is None else flush_s
        self._cap = CHAT_THINK_LIVE_CAP if cap is None else cap
        self._clock = clock
        self._buf = ""
        self._t0 = clock()
        self._total = 0
        self._capped = False

    def feed(self, channel, text):
        if channel != "think":
            self.flush()
            self._emit(channel, text)
            return
        if self._capped:
            return
        self._total += len(text)
        self._buf += text
        if self._total >= self._cap:
            self._capped = True
            self._buf += "\n… (live thinking truncated)"
        if self._capped or (self._clock() - self._t0) >= self._flush_s:
            self.flush()

    def flush(self):
        if not self._buf:
            return
        text = self._buf
        self._buf = ""
        self._t0 = self._clock()
        self._emit("think", text)

