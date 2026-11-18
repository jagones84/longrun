#!/usr/bin/env python3
"""v693: real chat tool cards retain structured errors with blank stderr.

Scripted provider and tool gate, real chat_once and session persistence.
All state is temporary. No live model, network, or server.
"""
import atexit
import json
import os
import shutil
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v693-")
atexit.register(lambda: shutil.rmtree(TMP, ignore_errors=True))
for key in ("CONFIG_DIR", "DATA_DIR", "DATA_HOME", "SESSIONS_DIR", "GRAPH_DIR",
            "EDITS_DIR", "RUNS_DIR", "THREADS_DIR", "COSTS_DIR", "PROJECTS_DIR",
            "ROLES_DIR", "MATRIX_SRC", "MATRIX_DOT", "SKILLS_DIR", "HARNESS_DIR"):
    os.environ["LONGRUN_" + key] = os.path.join(TMP, key)
    os.makedirs(os.environ["LONGRUN_" + key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_HOOKS"] = os.path.join(TMP, "hooks.yaml")
os.environ["LONGRUN_PRICES_FILE"] = os.path.join(TMP, "prices.json")
# The post-turn proposer is a LIVE model call (round 90): a deterministic test
# that drives `chat_once` must never reach the network. The battery exports this
# too; set here so running the file alone is deterministic as well.
os.environ["LONGRUN_OPTIMIZER"] = "0"
# The context backfill's meter asks the router for the model's window
# (`rllm.router_models`); in this process there is no router to ask.
os.environ["LONGRUN_OFFLINE"] = "1"
sys.path.insert(0, os.path.join(REPO, "src"))

# Match the service import order: server breaks the agent/server cycle.
from longrun.core import server  # noqa: E402
from longrun.agent import agent as A  # noqa: E402
from longrun.harness import record  # noqa: E402
from longrun.memory import stores  # noqa: E402
from longrun.tools import registry  # noqa: E402


class ChatDiagnostics(unittest.TestCase):
    def test_persisted_tool_error_fallback(self):
        cases = (
            ("blank", {"stderr": "", "error": "candidate validation failed"},
             "candidate validation failed", False, None),
            ("none", {"stderr": None, "error": "candidate not found"},
             "candidate not found", False, None),
            ("missing", {"error": "probe refused"},
             "probe refused", False, None),
            ("stderr", {"stderr": "process stderr", "error": "structured error"},
             "process stderr", False, 7),
            ("success", {"stderr": ""}, "", True, 0),
        )
        for name, diagnostic, expected, ok, exit_code in cases:
            with self.subTest(name=name):
                sid = "v693-" + name
                message = "Read the candidate diagnostics."
                sess = {"id": sid, "workspace": TMP, "messages": [],
                        "tool_cards": [], "injects": []}
                stores.save_session(sess)
                stores.append_message(sess, "user", message)
                args = {"path": "candidate.json"}
                action = json.dumps({"action": "tool", "tool": "fs.read", "args": args})
                answers = iter((action, "Candidate diagnostics recorded.",
                                "Candidate diagnostics recorded."))
                events = []

                def provider(msgs, model, role, on_delta, **kwargs):
                    text = next(answers)
                    on_delta("answer", text)
                    return text, "", model

                result = dict(diagnostic, ok=ok, exit_code=exit_code,
                              stdout="", backend="fixture")
                response = {"status": "executed", "result": result,
                            "observation": "candidate inspection completed"}
                with patch.object(server, "_tool_context", return_value="fs.read"), \
                        patch.object(A, "assemble_turn", return_value=(
                            [{"role": "system", "content": "Fixture tool context."},
                             {"role": "user", "content": message}], {})), \
                        patch.object(server, "stream_with_fallback",
                                     side_effect=provider) as model_calls, \
                        patch.object(A.api_v02, "gated_call",
                                     return_value=response) as tool_calls, \
                        patch.object(registry, "_external_tools", return_value={}), \
                        patch.object(A, "_improvement_pass"), \
                        patch.object(socket.socket, "connect",
                                     side_effect=AssertionError("network forbidden")) as network:
                    reply, model = A.chat_once(
                        sess, message, model="fixture",
                        on_delta=lambda channel, text: None,
                        on_event=lambda kind, **data: events.append((kind, data)))
                    network.assert_not_called()

                # EV-41: a FAILED tool call earns ONE bounded failure verdict
                # before the turn may close, so a failing case costs 3 model
                # calls; a successful one still costs 2 (pin kept meaningful).
                self.assertEqual(model_calls.call_count, 2 if ok else 3)
                tool_calls.assert_called_once()
                self.assertEqual(tool_calls.call_args.args, ("fs.read", args))
                self.assertEqual(model, "fixture")
                self.assertEqual(reply["content"], "Candidate diagnostics recorded.")
                self.assertEqual(sum(kind == "tool.result" for kind, _ in events), 1)
                persisted = stores.load_session(sid)
                self.assertEqual(len(persisted["tool_cards"]), 1)
                card = persisted["tool_cards"][0]
                self.assertEqual(card["ok"], ok)
                self.assertEqual(card["exit_code"], exit_code)
                self.assertEqual(card["backend"], "fixture")
                self.assertEqual(card["result"], response["observation"])
                self.assertEqual(card["error"], expected)
                # The harness record consumes the same persisted card, not a
                # second diagnostic derived from observation text.
                evidence = record.build(sid, session=persisted)
                self.assertEqual(len(evidence["steps"]), 1)
                self.assertEqual(evidence["steps"][0]["error"], expected)
                self.assertEqual(evidence["steps"][0]["ok"], ok)


class OfflineHermeticity(unittest.TestCase):
    """A54 round 105 (2026-11-18): the battery's offline promise must be total.

    `LONGRUN_OFFLINE=1` was honoured only by `model/rllm.local_models`; the MCP
    client still opened sockets (2 of 10 runs reached the github server, HTTP 429)
    and the tests stayed green only because that client fails OPEN.
    """

    def test_offline_skips_a_network_client(self):
        from unittest import mock
        from longrun.interop import mcp_client as MC

        def boom(*a, **k):
            raise AssertionError("offline must not open a network transport")

        cfg = {"net": {"url": "http://127.0.0.1:1/mcp", "enabled": True}}
        with mock.patch.object(MC, "_load_config", return_value=cfg), \
             mock.patch.object(MC.MCPClientManager, "_ensure_config", lambda self: None), \
             mock.patch.object(MC.MCPSession, "_connect_http", boom):
            mgr = MC.MCPClientManager()
            mgr.start_all()
        self.assertNotIn("net", mgr.sessions)
        self.assertIn("offline", mgr._errors.get("net", ""), mgr._errors)

    def test_offline_still_allows_a_stdio_client(self):
        """A stdio client is a local subprocess (the plugin tests start a fake one)."""
        from unittest import mock
        from longrun.interop import mcp_client as MC

        cfg = {"local": {"command": "true", "args": [], "enabled": True}}
        seen = mock.Mock(return_value=False)
        with mock.patch.object(MC, "_load_config", return_value=cfg), \
             mock.patch.object(MC.MCPClientManager, "_ensure_config", lambda self: None), \
             mock.patch.object(MC.MCPSession, "_connect_stdio", seen):
            mgr = MC.MCPClientManager()
            mgr.start_all()
        self.assertEqual(seen.call_count, 1)
        self.assertNotIn("offline", (mgr._errors.get("local") or ""), mgr._errors)


if __name__ == "__main__":
    unittest.main(verbosity=2)
