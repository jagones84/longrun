#!/usr/bin/env python3
"""Allowlisted inference gateway and loopback shim (loopback only, no model)."""
import http.client
import http.server
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="longrun-v697-")
for key in ("CONFIG_DIR", "DATA_HOME", "DATA_DIR", "SESSIONS_DIR"):
    os.environ["LONGRUN_" + key] = os.path.join(TMP, key)
sys.path.insert(0, os.path.join(REPO, "src"))
from longrun.harness import gateway as gateway_mod
from longrun.harness import unixshim

MODEL = "fixture-model"


class Upstream(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    calls = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        type(self).calls.append(body)
        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Connection", "close")
            self.end_headers()
            for piece in (b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n',
                          b'data: {"choices":[],"usage":{"prompt_tokens":11,'
                          b'"completion_tokens":2}}\n\n',
                          b"data: [DONE]\n\n"):
                self.wfile.write(piece)
                self.wfile.flush()
            return
        data = json.dumps({"choices": [{"message": {"content": "ok"}}],
                           "usage": {"prompt_tokens": 5, "completion_tokens": 3}
                           }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_args):
        return


class GatewayFixture(unittest.TestCase):
    def setUp(self):
        Upstream.calls = []
        self.upstream = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        self.upstream_thread = threading.Thread(target=self.upstream.serve_forever,
                                                kwargs={"poll_interval": 0.05},
                                                daemon=True)
        self.upstream_thread.start()
        self.dir = tempfile.mkdtemp(dir=TMP)
        self.socket = os.path.join(self.dir, "gateway.sock")
        port = self.upstream.server_address[1]
        self.gateway = gateway_mod.Gateway(
            model=MODEL,
            upstream="http://127.0.0.1:%d/v1/chat/completions" % port,
            max_requests=3, max_body=2048, max_response=65536,
            max_tokens=64, max_seconds=30, timeout=10)
        self.assertTrue(self.gateway.start(self.socket)["ok"])
        self.shim = unixshim.Shim(self.socket)
        started = self.shim.start()
        self.assertTrue(started["ok"], started)
        self.port = started["port"]

    def tearDown(self):
        self.shim.stop()
        self.gateway.stop()
        self.upstream.shutdown()
        self.upstream.server_close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def call(self, method, path, payload=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"} if body else {}
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        data = response.read()
        conn.close()
        return response.status, data

    def chat(self, **extra):
        payload = {"model": MODEL, "messages": [{"role": "user", "content": "hi"}],
                   "temperature": 0.7, "max_tokens": 999}
        payload.update(extra)
        return self.call("POST", "/v1/chat/completions", payload)


class GatewayPolicy(GatewayFixture):
    def test_forwards_only_allowed_fields_and_clamps_tokens(self):
        status, data = self.chat(evil="drop-me")
        self.assertEqual(status, 200, data)
        self.assertEqual(len(Upstream.calls), 1)
        sent = Upstream.calls[0]
        self.assertNotIn("evil", sent)
        self.assertEqual(sent["max_tokens"], 64)
        self.assertEqual(sent["model"], MODEL)
        stats = self.gateway.stats()
        self.assertEqual((stats["prompt_tokens"], stats["completion_tokens"]), (5, 3))
        self.assertEqual(stats["dropped_fields"], 1)

    def test_other_model_is_refused_before_upstream(self):
        status, _data = self.chat(model="another-model")
        self.assertEqual(status, 403)
        self.assertEqual(Upstream.calls, [])

    def test_only_chat_path_is_available(self):
        status, _data = self.call("POST", "/v1/models/load", {"model": MODEL})
        self.assertEqual(status, 404)
        self.assertEqual(Upstream.calls, [])

    def test_models_endpoint_lists_only_the_fixed_model(self):
        status, data = self.call("GET", "/v1/models")
        self.assertEqual(status, 200)
        self.assertEqual([row["id"] for row in json.loads(data)["data"]], [MODEL])

    def test_oversized_body_is_refused(self):
        status, _data = self.chat(messages=[{"role": "user", "content": "x" * 4000}])
        self.assertEqual(status, 413)
        self.assertEqual(Upstream.calls, [])

    def test_request_budget_is_enforced(self):
        for _ in range(3):
            self.assertEqual(self.chat()[0], 200)
        status, _data = self.chat()
        self.assertEqual(status, 429)
        self.assertEqual(len(Upstream.calls), 3)

    def test_stream_is_relayed_unchanged_and_usage_recorded(self):
        status, data = self.chat(stream=True)
        self.assertEqual(status, 200)
        self.assertIn(b'"content":"hi"', data)
        self.assertIn(b"[DONE]", data)
        stats = self.gateway.stats()
        self.assertEqual((stats["prompt_tokens"], stats["completion_tokens"]), (11, 2))

    def test_shim_refuses_without_a_gateway_socket(self):
        result = unixshim.Shim(os.path.join(self.dir, "missing.sock")).start()
        self.assertFalse(result["ok"])


if __name__ == "__main__":
    try:
        unittest.main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
