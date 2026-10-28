#!/usr/bin/env python3
"""Allowlisted inference gateway for confined Harness2 probes.

A probe container runs with `--network none`, so it cannot reach the operator's
router directly. The only channel is a Unix socket the launcher mounts read-only;
this module serves an OpenAI-compatible endpoint on that socket and forwards to
ONE fixed upstream path, for ONE fixed model, under request/body/token bounds.

Design rules:

* The candidate never chooses the destination, the model or the budget. A
  request for another model is refused before any upstream call.
* Only the wire fields the real chat loop emits are forwarded
  (`rllm._completion_body`); anything else is dropped, not relayed.
* Streaming bytes are relayed unchanged; usage is parsed for accounting without
  rewriting the stream.
* Quotas are enforced here, in the trusted host process, not in the container.

Sources: https://docs.python.org/3.12/library/http.server.html and
https://docs.python.org/3.12/library/socketserver.html (Unix stream server).
"""
import http.client
import json
import os
import socketserver
import threading
import time
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlsplit

CHAT_PATH = "/v1/chat/completions"
MODELS_PATH = "/v1/models"
DEFAULT_MAX_BODY = 512 * 1024
DEFAULT_MAX_RESPONSE = 8 * 1024 * 1024
DEFAULT_MAX_REQUESTS = 24
DEFAULT_MAX_TOKENS = 4096
DEFAULT_MAX_SECONDS = 900

# Exactly the fields `rllm._completion_body` builds. A candidate-supplied field
# outside this set is dropped so the gateway never relays arbitrary provider
# options (tools parsing, logprobs, n>1, provider routing) by accident.
ALLOWED_FIELDS = ("model", "messages", "stream", "stream_options", "temperature",
                  "max_tokens", "reasoning_effort")


class _UnixHTTPServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    allow_reuse_address = False


class Gateway:
    """One fixed model, one fixed upstream path, bounded requests."""

    def __init__(self, model, upstream, max_requests=DEFAULT_MAX_REQUESTS,
                 max_body=DEFAULT_MAX_BODY, max_response=DEFAULT_MAX_RESPONSE,
                 max_tokens=DEFAULT_MAX_TOKENS, max_seconds=DEFAULT_MAX_SECONDS,
                 timeout=300):
        self.model = str(model or "").strip()
        self.upstream = str(upstream or "").strip()
        self.max_requests = int(max_requests)
        self.max_body = int(max_body)
        self.max_response = int(max_response)
        self.max_tokens = int(max_tokens)
        self.max_seconds = float(max_seconds)
        self.timeout = float(timeout)
        self._lock = threading.Lock()
        self._server = None
        self._thread = None
        self.socket_path = ""
        self._started = 0.0
        self._stats = self._empty_stats()

    @staticmethod
    def _empty_stats():
        return {"requests": 0, "forwarded": 0, "refused": 0,
                "prompt_tokens": 0, "completion_tokens": 0, "dropped_fields": 0}

    def usable(self):
        """True when the fixed destination is well formed."""
        u = urlsplit(self.upstream)
        return bool(self.model and u.scheme == "http" and u.hostname
                    and u.path.endswith("/chat/completions")
                    and self.max_requests > 0 and self.max_body > 0
                    and self.max_tokens > 0 and self.max_seconds > 0)

    def start(self, socket_path):
        """Serve on `socket_path`; refuses an existing path instead of reusing it."""
        if not self.usable():
            return {"ok": False, "error": "gateway profile is invalid"}
        path = str(socket_path or "")
        if not path or os.path.exists(path):
            return {"ok": False, "error": "gateway socket path is not free"}
        self.socket_path = path
        self._started = time.monotonic()
        try:
            self._server = _UnixHTTPServer(path, _handler(self))
        except OSError as exc:
            return {"ok": False, "error": "cannot bind gateway socket: %s" % exc}
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        kwargs={"poll_interval": 0.1},
                                        name="h2-gateway", daemon=True)
        self._thread.start()
        return {"ok": True, "path": path}

    def stop(self):
        """Stop serving and remove the socket; never raises."""
        server, thread = self._server, self._thread
        self._server = self._thread = None
        if server is not None:
            try:
                server.shutdown()
            except Exception:  # noqa: BLE001
                pass
            try:
                server.server_close()
            except Exception:  # noqa: BLE001
                pass
        if thread is not None:
            try:
                thread.join(timeout=3)
            except Exception:  # noqa: BLE001
                pass
        if self.socket_path:
            try:
                os.unlink(self.socket_path)
            except OSError:
                pass
        return self.stats()

    def stats(self):
        with self._lock:
            out = dict(self._stats)
        out["model"] = self.model
        return out

    # -- policy -----------------------------------------------------------
    def admit(self):
        """Count a request and decide whether it may be forwarded."""
        with self._lock:
            self._stats["requests"] += 1
            if time.monotonic() - self._started > self.max_seconds:
                self._stats["refused"] += 1
                return False, "gateway time budget exhausted"
            if self._stats["forwarded"] >= self.max_requests:
                self._stats["refused"] += 1
                return False, "gateway request budget exhausted"
            return True, ""

    def commit(self):
        with self._lock:
            self._stats["forwarded"] += 1

    def drop(self, count):
        with self._lock:
            self._stats["dropped_fields"] += int(count)

    def usage(self, prompt, completion):
        try:
            prompt, completion = int(prompt or 0), int(completion or 0)
        except (TypeError, ValueError):
            return
        with self._lock:
            self._stats["prompt_tokens"] += max(0, prompt)
            self._stats["completion_tokens"] += max(0, completion)


def _handler(gw):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "longrun-h2-gateway"

        def address_string(self):  # Unix sockets have no peer address tuple.
            return "unix"

        def log_message(self, *_args):  # keep the operator log clean
            return

        def _send(self, code, payload):
            body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

        def _deny(self, code, message):
            self._send(code, {"error": {"code": code, "message": message}})

        def do_GET(self):
            if self.path != MODELS_PATH:
                return self._deny(404, "only %s is available" % MODELS_PATH)
            self._send(200, {"object": "list",
                             "data": [{"id": gw.model, "object": "model"}]})

        def do_POST(self):
            if self.path != CHAT_PATH:
                return self._deny(404, "only %s is available" % CHAT_PATH)
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return self._deny(400, "invalid content length")
            if length <= 0 or length > gw.max_body:
                return self._deny(413, "request body exceeds gateway bound")
            raw = self.rfile.read(length)
            try:
                body = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                return self._deny(400, "request body is not JSON")
            if not isinstance(body, dict):
                return self._deny(400, "request body must be an object")
            if str(body.get("model") or "") != gw.model:
                return self._deny(403, "model is not allowlisted")
            messages = body.get("messages")
            if not isinstance(messages, list) or not messages:
                return self._deny(400, "messages must be a non-empty list")
            allowed, why = gw.admit()
            if not allowed:
                return self._deny(429, why)
            forwarded = {}
            for key in ALLOWED_FIELDS:
                if key in body:
                    forwarded[key] = body[key]
            gw.drop(len(body) - len(forwarded))
            if forwarded.get("max_tokens"):
                try:
                    forwarded["max_tokens"] = min(int(forwarded["max_tokens"]),
                                                  gw.max_tokens)
                except (TypeError, ValueError):
                    return self._deny(400, "max_tokens must be an integer")
            upstream = urlsplit(gw.upstream)
            conn = http.client.HTTPConnection(upstream.hostname, upstream.port,
                                              timeout=gw.timeout)
            try:
                conn.request("POST", upstream.path,
                             json.dumps(forwarded, ensure_ascii=True).encode("utf-8"),
                             {"Content-Type": "application/json"})
                gw.commit()
                resp = conn.getresponse()
                if forwarded.get("stream") and resp.status == 200:
                    return self._relay_stream(resp)
                data = resp.read(gw.max_response + 1)
                if len(data) > gw.max_response:
                    return self._deny(502, "upstream response exceeds gateway bound")
                self._record_usage(data)
                self.send_response(resp.status)
                self.send_header("Content-Type",
                                 resp.getheader("Content-Type") or "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(data)
            except (OSError, http.client.HTTPException):
                self._deny(502, "upstream request failed")
            finally:
                try:
                    conn.close()
                except Exception:  # noqa: BLE001
                    pass

        def _relay_stream(self, resp):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            seen = 0
            pending = b""
            try:
                while True:
                    piece = resp.read1(8192)
                    if not piece:
                        break
                    seen += len(piece)
                    if seen > gw.max_response:
                        break
                    self.wfile.write(piece)
                    self.wfile.flush()
                    pending = self._scan_usage(pending + piece)
            except (OSError, http.client.HTTPException):
                return
            finally:
                try:
                    resp.close()
                except Exception:  # noqa: BLE001
                    pass

        def _scan_usage(self, buffer):
            """Record `usage` from complete SSE lines; keep the unfinished tail."""
            lines = buffer.split(b"\n")
            for line in lines[:-1]:
                if not line.startswith(b"data: "):
                    continue
                try:
                    obj = json.loads(line[6:].decode("utf-8"))
                except (UnicodeDecodeError, ValueError):
                    continue
                if isinstance(obj, dict) and isinstance(obj.get("usage"), dict):
                    use = obj["usage"]
                    gw.usage(use.get("prompt_tokens"), use.get("completion_tokens"))
            return lines[-1][-65536:]

        def _record_usage(self, data):
            try:
                obj = json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                return
            if isinstance(obj, dict) and isinstance(obj.get("usage"), dict):
                use = obj["usage"]
                gw.usage(use.get("prompt_tokens"), use.get("completion_tokens"))

    return Handler
