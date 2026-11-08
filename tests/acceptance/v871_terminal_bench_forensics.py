#!/usr/bin/env python3
"""v871 — Terminal-Bench forensic artifacts are useful and secret-safe."""

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

try:
    from benchmarks import terminal_bench_forensics as forensic
except ImportError:
    forensic = None

try:
    from benchmarks import terminal_bench_agent as longrun_adapter
except ImportError:
    longrun_adapter = None

try:
    from benchmarks import terminal_bench_openclaw as openclaw_adapter
except ImportError:
    openclaw_adapter = None

RESULTS: list[bool] = []


def check(name: str, ok: bool, detail: Any = "") -> None:
    """Record and print one deterministic acceptance result."""
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail and not ok else ""))


class _LongrunBox:
    """In-memory container facade for Longrun trace-capture tests."""

    def __init__(self) -> None:
        self.session = {
            "id": "probe-session",
            "messages": [
                {"role": "system", "content": "private system prompt"},
                {"role": "user", "content": "do the task"},
            ],
            "tool_cards": [{"tool": "fs.edit", "result": "patched"}],
            "injects": [],
        }

    def sh(self, command: str) -> tuple[int, str]:
        """Return the fake session record for the adapter's expected read."""
        if command == "cat /tmp/lr/sessions/probe-session.json":
            return 0, json.dumps(self.session)
        return 1, "not found"

    def api(self, method: str, path: str) -> tuple[int, dict[str, Any]]:
        """Return a small graph result for the adapter's read-only request."""
        return 200, {"nodes": [], "method": method, "path": path}


class _OpenClawBox:
    """Container facade for OpenClaw SQLite session lookup and bundle export."""

    def sh(self, command: str) -> tuple[int, str]:
        """Return deterministic session rows and redacted trajectory files."""
        if command == "cat /tmp/oc/err.log":
            return 0, "safe diagnostic"
        if "sessions --json" in command:
            return 0, json.dumps({"sessions": [{
                "key": "agent:main:probe",
                "sessionId": "session-uuid",
            }]})
        if "sessions export-trajectory" in command:
            if "openclaw.mjs' sessions" in command:
                return 127, "OpenClaw executable arguments were merged"
            return 0, '{"ok":true}'
        if command == (
            "find /tmp/oc/.openclaw/trajectory-exports/terminal-bench-session -type f"
        ):
            root = "/tmp/oc/.openclaw/trajectory-exports/terminal-bench-session"
            return 0, "\n".join(
                root + "/" + name for name in (
                    "manifest.json",
                    "events.jsonl",
                    "artifacts.json",
                    "system-prompt.txt",
                )
            )
        if command.endswith("/events.jsonl"):
            return 0, (
                '{"traceSchema":"openclaw-trajectory","schemaVersion":1}\n'
                '{"type":"prompt.submitted","prompt":"private system prompt"}\n'
                '{"type":"tool.call","tool":"fs.edit","args":{"path":"src/x.py"}}\n'
                '{"type":"tool.result","tool":"fs.edit","success":true}\n'
            )
        if command.endswith("/manifest.json"):
            return 0, '{"runtimeEventCount":2}'
        if command.endswith("/artifacts.json"):
            return 0, '{"toolSummary":{"calls":1}}'
        return 1, "not found"


class _OpenClawExportFailureBox(_OpenClawBox):
    """Expose CLI failure details without returning any prompt or transcript data."""

    def sh(self, command: str) -> tuple[int, str]:
        """Return a bounded diagnostic for a failed trajectory export."""
        if "export-trajectory" in command:
            return 17, "fixture exporter rejected export openrouter-secret-value"
        return super().sh(command)


def main() -> int:
    """Verify redaction, trace normalization, state filtering, and file output."""
    if forensic is None:
        check("forensic helper exists", False, "module not found")
    else:
        secret = "openrouter-secret-value"
        clean = forensic.sanitize_payload(
            {
                "api_key": secret,
                "authorization": "Bearer bearer-secret-value",
                "nested": {
                    "tool": "fs.edit",
                    "args": {"path": "src/app.py", "replace": secret},
                },
                "log": "OPENROUTER_API_KEY=" + secret,
            },
            secrets=(secret,),
        )
        encoded = json.dumps(clean, sort_keys=True)
        check("A1 nested credentials and bearer strings are redacted",
              secret not in encoded
              and "bearer-secret-value" not in encoded
              and "<REDACTED>" in encoded, encoded)
        pattern_text = forensic.sanitize_payload(
            "authorization: bearer case-insensitive-token\n"
            "openrouter_api_key=case-insensitive-secret"
        )
        check("A1b free-text credential patterns are case-insensitive",
              "case-insensitive-token" not in pattern_text
              and "case-insensitive-secret" not in pattern_text)
        password_text = forensic.sanitize_payload(
            "PASSWORD=synthetic-task-secret"
        )
        check("A1d password assignments in free text are redacted",
              "synthetic-task-secret" not in password_text
              and "<REDACTED>" in password_text)
        truncated = forensic.sanitize_payload("abcdefghij", max_chars=4)
        check("A1c truncated text carries an explicit marker",
              truncated.startswith("abcd") and "TRUNCATED" in truncated)

        session = {
            "id": "session-test",
            "messages": [
                {"role": "system", "content": "private system prompt"},
                {"role": "user", "content": "complete the task"},
                {"role": "assistant", "content": "I will inspect the file."},
            ],
            "tool_cards": [
                {
                    "tool": "fs.edit",
                    "args": {"path": "src/app.py"},
                    "result": "patched one block",
                    "exit_code": 0,
                }
            ],
            "injects": [{"kind": "review", "text": "check the result"}],
        }
        trace = forensic.longrun_trace(
            session,
            costs={"calls": 2, "tokens_in": 120, "tokens_out": 40},
            secrets=(),
        )
        check("A2 Longrun trace omits system messages",
              all(message["role"] != "system" for message in trace["messages"])
              and "private system prompt" not in json.dumps(trace))
        check("A3 Longrun trace retains tool calls, results, injects, and costs",
              trace["tool_cards"][0]["tool"] == "fs.edit"
              and trace["tool_cards"][0]["result"] == "patched one block"
              and trace["injects"][0]["kind"] == "review"
              and trace["costs"]["calls"] == 2)
        oversized_session = {
            "messages": [{"role": "user", "content": "task"}]
            * (forensic.MAX_TRACE_ITEMS + 1),
            "tool_cards": [],
            "injects": [],
        }
        oversized_trace = forensic.longrun_trace(oversized_session)
        check("A4 capped Longrun collections carry truncation metadata",
              (oversized_trace.get("truncated") or {}).get("messages") is True)

        trajectory_path = getattr(forensic, "is_openclaw_trajectory_path", None)
        session_key_for_id = getattr(forensic, "session_key_for_id", None)
        check("B1 trajectory filter accepts event bundles and rejects system prompts",
              bool(trajectory_path)
              and trajectory_path(
                  "/tmp/oc/.openclaw/trajectory-exports/run/events.jsonl")
              and trajectory_path(
                  "/tmp/oc/.openclaw/trajectory-exports/run/artifacts.json")
              and not trajectory_path(
                  "/tmp/oc/.openclaw/trajectory-exports/run/system-prompt.txt")
              and not trajectory_path(
                  "/tmp/oc/.openclaw/trajectory-exports/../../etc/events.jsonl"))
        check("B2 session ID resolves only to one exact session key",
              bool(session_key_for_id)
              and session_key_for_id(
                  {"sessions": [{"key": "agent:main:probe",
                                 "sessionId": "session-uuid"}]},
                  "session-uuid",
              ) == "agent:main:probe"
              and session_key_for_id(
                  {"sessions": [
                      {"key": "agent:main:a", "sessionId": "session-uuid"},
                      {"key": "agent:main:b", "sessionId": "session-uuid"},
                  ]},
                  "session-uuid",
              ) is None)

        events = (
            '{"traceSchema":"openclaw-trajectory","schemaVersion":1}\n'
            '{"traceSchema":"openclaw-trajectory","type":"prompt.submitted",'
            '"prompt":"private submitted prompt"}\n'
            '{"traceSchema":"openclaw-trajectory","type":"context.compiled",'
            '"data":{"systemPrompt":"private system prompt"}}\n'
            '{"traceSchema":"openclaw-trajectory","type":"user.message",'
            '"data":{"content":"private task prompt"}}\n'
            '{"traceSchema":"openclaw-trajectory","type":"tool.call",'
            '"tool":"fs.edit","args":{"path":"src/x.py"}}\n'
            '{"traceSchema":"openclaw-trajectory","type":"tool.result",'
            '"tool":"fs.edit","success":true}\n'
        )
        try:
            oc = forensic.openclaw_trace(
                envelope={"final": "done", "usage": {"input": 18, "output": 4}},
                stderr="Authorization: Bearer bearer-secret-value",
                trajectory_files={
                    "events.jsonl": events,
                    "manifest.json": '{"runtimeEventCount":2}',
                    "system-prompt.txt": "private system prompt",
                    "prompts.json": "private submitted prompts",
                },
                secrets=("bearer-secret-value",),
                trajectory_files_truncated=False,
            )
        except TypeError:
            check("B3 OpenClaw trace accepts trajectory bundle files", False)
            oc = {}
        else:
            check("B3 OpenClaw trace accepts trajectory bundle files", True)
        event_text = (oc.get("trajectory_files") or {}).get("events.jsonl", "")
        check("B4 trace retains tool calls/results and omits submitted prompts",
              "tool.call" in event_text and "tool.result" in event_text
              and "prompt.submitted" not in event_text
              and "user.message" not in event_text
              and "context.compiled" not in event_text
              and "private submitted prompt" not in event_text
              and "private system prompt" not in event_text
              and "private task prompt" not in event_text
              and oc.get("filtered_event_count") == 3
              and "private system prompt" not in json.dumps(oc)
              and "private submitted prompts" not in json.dumps(oc))
        check("B5 OpenClaw trace redacts the provider bearer value",
              "bearer-secret-value" not in json.dumps(oc))
        long_stderr = "x" * (forensic.MAX_TEXT_CHARS + 1)
        try:
            oc_truncated = forensic.openclaw_trace(
                envelope={},
                stderr=long_stderr,
                trajectory_files={},
                trajectory_files_truncated=True,
            )
        except TypeError:
            oc_truncated = forensic.openclaw_trace(
                envelope={}, stderr=long_stderr
            )
        check("B6 capped OpenClaw stderr carries truncation metadata",
              (oc_truncated.get("truncated") or {}).get("stderr") is True
              and "TRUNCATED" in oc_truncated["stderr_tail"])

        with tempfile.TemporaryDirectory(prefix="v871-forensic-") as temp:
            target = forensic.write_forensic(temp, "longrun-forensic.json", trace)
            saved = json.loads(Path(target).read_text(encoding="utf-8"))
            check("C1 forensic artifact is written as readable JSON",
                  Path(target).name == "longrun-forensic.json"
                  and saved["tool_cards"][0]["tool"] == "fs.edit")

    longrun_source = Path(REPO, "benchmarks", "terminal_bench_agent.py").read_text(
        encoding="utf-8"
    )
    openclaw_source = Path(REPO, "benchmarks", "terminal_bench_openclaw.py").read_text(
        encoding="utf-8"
    )
    longrun_body = longrun_source.split("def perform_task", 1)[-1]
    openclaw_body = openclaw_source.split("def perform_task", 1)[-1]
    check("D1 Longrun captures forensic session data before stopping its server",
          "_capture_longrun_forensic(" in longrun_body
          and longrun_body.index("_capture_longrun_forensic(")
          < longrun_body.index('box.sh("kill'))
    check("D2 OpenClaw exports the official redacted trajectory bundle",
          '"--state-dir"' in openclaw_source
          and '"/tmp/oc/state"' in openclaw_source
          and "_capture_openclaw_forensic(" in openclaw_body
          and "openclaw-forensic.json" in openclaw_source
          and '"sessions"' in openclaw_source
          and '"export-trajectory"' in openclaw_source
          and '"--session-key"' in openclaw_source
          and '"--workspace"' in openclaw_source
          and '"--output"' in openclaw_source
          and "session_key_for_id(" in openclaw_source)
    if forensic is not None and longrun_adapter is not None:
        with tempfile.TemporaryDirectory(prefix="v871-adapter-") as temp:
            longrun_adapter._capture_longrun_forensic(
                _LongrunBox(),
                "probe-session",
                {"calls": 1, "recent": []},
                temp,
                "openrouter-secret-value",
            )
            saved = json.loads(
                Path(temp, "longrun-forensic.json").read_text(encoding="utf-8")
            )
            check("E1 Longrun adapter writes a redacted session and tool trace",
                  saved["tool_cards"][0]["tool"] == "fs.edit"
                  and "private system prompt" not in json.dumps(saved)
                  and "openrouter-secret-value" not in json.dumps(saved))
    else:
        check("E1 Longrun adapter trace fixture imports", False)

    if forensic is not None and openclaw_adapter is not None:
        with tempfile.TemporaryDirectory(prefix="v871-adapter-") as temp:
            openclaw_adapter._capture_openclaw_forensic(
                _OpenClawBox(),
                {"final": "done", "sessionId": "session-uuid"},
                '{"final":"done","sessionId":"session-uuid"}',
                temp,
                "openrouter-secret-value",
            )
            saved = json.loads(
                Path(temp, "openclaw-forensic.json").read_text(encoding="utf-8")
            )
            check("E2 OpenClaw adapter exports redacted tool-call trajectory",
                  "tool.call" in json.dumps(saved)
                  and "tool.result" in json.dumps(saved)
                  and "private system prompt" not in json.dumps(saved)
                  and not saved.get("capture_error"))

        with tempfile.TemporaryDirectory(prefix="v871-export-failure-") as temp:
            openclaw_adapter._capture_openclaw_forensic(
                _OpenClawExportFailureBox(),
                {"final": "done", "sessionId": "session-uuid"},
                '{"final":"done","sessionId":"session-uuid"}',
                temp,
                "openrouter-secret-value",
            )
            saved = json.loads(
                Path(temp, "openclaw-forensic.json").read_text(encoding="utf-8")
            )
            check("E3 OpenClaw export failure keeps a bounded, sanitized diagnostic",
                  "trajectory-export" in saved.get("capture_error", "")
                  and "fixture exporter rejected export" in saved["capture_error"]
                  and "<REDACTED>" in saved["capture_error"]
                  and "openrouter-secret-value" not in json.dumps(saved))
    else:
        check("E2 OpenClaw adapter trace fixture imports", False)

    passed = sum(RESULTS)
    print(f"v871: {passed}/{len(RESULTS)} checks")
    return 0 if RESULTS and all(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
