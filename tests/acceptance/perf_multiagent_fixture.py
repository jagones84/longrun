#!/usr/bin/env python3
"""Isolated deterministic server for multi-session browser profiling."""
import argparse
import os
import sys
import tempfile
import time
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=18794)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="longrun-perf-") as home:
        path = os.environ.get("PATH", "")
        os.environ.clear()
        os.environ.update(PATH=path, HOME=home, LONGRUN_OFFLINE="1", LONGRUN_OPTIMIZER="0")
        for key, name in {
            "DATA_HOME": "home", "DATA_DIR": "data", "CONFIG_DIR": "config",
            "SESSIONS_DIR": "sessions", "GRAPH_DIR": "graphs", "EDITS_DIR": "edits",
            "RUNS_DIR": "runs", "ROLES_DIR": "roles", "COSTS_DIR": "costs",
            "THREADS_DIR": "threads", "MATRIX_SRC": "matrix_src", "MATRIX_DOT": "matrix_dot",
            "SKILLS_DIR": "skills",
        }.items():
            directory = os.path.join(home, name)
            os.makedirs(directory, exist_ok=True)
            os.environ["LONGRUN_" + key] = directory
        os.environ["LONGRUN_DB"] = os.path.join(home, "events.db")
        os.environ["LONGRUN_PRICES_FILE"] = os.path.join(home, "prices.json")
        os.chdir(home)

        from longrun.model import keys, providers
        providers.load_env = lambda *a, **k: None
        keys.ENV_FILE = os.path.join(home, "no-env")
        from longrun.interop import mcp_client
        mcp_client.load_doc = lambda: {"env_files": [], "clients": {}}
        mcp_client._load_env_files = lambda paths: None
        mcp_client.MCPClientManager.start_all = lambda self: None
        from longrun.core import server  # initializes the server/httpapi import cycle
        from longrun.core import httpapi
        from longrun.memory import stores

        httpapi.AUTH_TOKEN = "isolated-perf-token"
        httpapi._sf_server.AUTH_TOKEN = httpapi.AUTH_TOKEN
        httpapi.prepare_session_for_turn = lambda session, model: session
        httpapi._local_ref = lambda model: False

        def fake_chat(session, message, model, on_delta, trace=None, on_event=None, **kwargs):
            sid = session["id"]
            if message == "fixture-dupe":
                httpapi.publish("tool.call", session=sid, tool="fixture", args={"message": message})
            on_event("tool.call", session=sid, tool="fixture", args={"message": message})
            on_event("approval.request", session=sid, tool="fixture", approval="fixture")
            for index in range(1 if message in ("fixture-fast", "fixture-dupe",
                                                "fixture-no-reply", "fixture-error") else 80):
                on_delta("answer", "%s:%s " % (sid, index))
                if index == 10:
                    on_event("tool.output", session=sid, tool="fixture", text="running")
                    on_event("approval.resolved", session=sid, approval="fixture")
                time.sleep(0.1)
            if message == "fixture-error":
                raise RuntimeError("fixture error")
            on_event("tool.result", session=sid, tool="fixture", result="complete")
            if message == "fixture-no-reply":
                return
            stores.append_message(session, "assistant", "fixture complete")
            on_event("chat.final", session=sid, text="fixture complete")
            httpapi.publish("chat.done", session=sid)

        httpapi.chat_once = fake_chat
        original_start = httpapi._start_chat_worker

        def delayed_fast_start(*args, **kwargs):
            result = original_start(*args, **kwargs)
            if len(args) > 1 and args[1] == "fixture-fast":
                time.sleep(0.5)
            return result

        httpapi._start_chat_worker = delayed_fast_start
        httpapi._ensure_dirs()
        srv = ThreadingHTTPServer(("127.0.0.1", args.port), httpapi.Handler)
        srv.host, srv.port = srv.server_address
        print("fixture ready at http://127.0.0.1:%d/" % srv.port, flush=True)
        try:
            srv.serve_forever()
        finally:
            srv.server_close()


if __name__ == "__main__":
    main()
