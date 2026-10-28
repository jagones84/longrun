#!/usr/bin/env python3
"""Localhost TCP → Unix-socket relay for a confined probe container.

The chat loop speaks plain HTTP to a `base_url`. Inside the container the only
reachable host channel is the gateway socket mounted read-only, so this module
listens on loopback and relays bytes to that socket. It parses nothing: the
gateway remains the policy owner (model, path, budget).

Source: https://docs.python.org/3.12/library/select.html (socket readiness).
"""
import os
import select
import socket
import socketserver
import threading


def _relay(client, socket_path, timeout=300):
    """Copy bytes both ways until either side closes."""
    upstream = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        upstream.settimeout(timeout)
        upstream.connect(socket_path)
        client.settimeout(timeout)
        peers = {client: upstream, upstream: client}
        while True:
            ready, _, _ = select.select(list(peers), [], [], timeout)
            if not ready:
                return
            for source in ready:
                data = source.recv(65536)
                if not data:
                    return
                peers[source].sendall(data)
    finally:
        try:
            upstream.close()
        except OSError:
            pass


def _handler(socket_path):
    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            try:
                _relay(self.request, socket_path)
            except OSError:
                return

        def log_message(self, *_args):  # socketserver has no logger
            return

    return Handler


class Shim:
    """A loopback listener bound to one gateway socket."""

    def __init__(self, socket_path):
        self.socket_path = str(socket_path or "")
        self._server = None
        self._thread = None

    def start(self, port=0, host="127.0.0.1"):
        if not self.socket_path or not os.path.exists(self.socket_path):
            return {"ok": False, "error": "gateway socket is unavailable"}
        try:
            self._server = socketserver.ThreadingTCPServer(
                (host, int(port)), _handler(self.socket_path))
        except OSError as exc:
            return {"ok": False, "error": "cannot bind loopback relay: %s" % exc}
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        kwargs={"poll_interval": 0.1},
                                        name="h2-unix-shim", daemon=True)
        self._thread.start()
        return {"ok": True, "port": self._server.server_address[1]}

    def stop(self):
        server, thread = self._server, self._thread
        self._server = self._thread = None
        if server is not None:
            try:
                server.shutdown()
                server.server_close()
            except Exception:  # noqa: BLE001
                pass
        if thread is not None:
            try:
                thread.join(timeout=3)
            except Exception:  # noqa: BLE001
                pass
