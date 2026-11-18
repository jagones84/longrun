#!/usr/bin/env python3
"""Black-box tests for connection-independent, idempotent chat starts."""
import concurrent.futures
import json
import os
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN = "isolated-perf-token"


class ChatStart(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.proc = subprocess.Popen(
            [sys.executable, "-B", os.path.join(HERE, "perf_multiagent_fixture.py"),
             "--port", "0"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        line = cls.proc.stdout.readline().strip()
        if not line.startswith("fixture ready at "):
            raise RuntimeError("isolated fixture failed to start: " + line)
        cls.base = line.removeprefix("fixture ready at ").rstrip("/")

    @classmethod
    def tearDownClass(cls):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                if not cls.request("GET", "/api/chat/live")[1].get("active"):
                    break
            except Exception:
                pass
            time.sleep(0.2)
        else:
            raise RuntimeError("fixture still has active turns; refusing to stop it")
        cls.proc.terminate()
        cls.proc.wait(timeout=10)
        cls.proc.stdout.close()

    @classmethod
    def request(cls, method, path, body=None, authenticated=True):
        headers = {"Authorization": "Bearer " + TOKEN} if authenticated else {}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(cls.base + path, data=data, headers=headers, method=method)
        try:
            response = urllib.request.urlopen(req, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)

    def test_authentication_and_validation(self):
        self.assertEqual(self.request("POST", "/api/chat/start", {}, False)[0], 401)
        self.assertEqual(self.request("POST", "/api/chat/start", {})[0], 400)
        valid = {"message": "fixture-fast", "idempotency_key": "invalid-fields"}
        for name, value in (("session", []), ("model", {}),
                            ("headless", "false"), ("max_steps", True),
                            ("max_steps", -1), ("mode", [])):
            with self.subTest(name=name, value=value):
                self.assertEqual(self.request("POST", "/api/chat/start",
                                              dict(valid, **{name: value}))[0], 400)

    def test_turn_frames_reach_the_shared_feed_with_a_terminal(self):
        """v1165: the WebUI follows a turn on the ONE feed, so the feed itself must
        carry the turn's frames and an explicit terminal (no private stream)."""
        _, session = self.request("GET", "/api/sessions/new")
        body = {"session": session["id"], "message": "fixture-fast",
                "model": "fixture", "idempotency_key": "fixture-feed-turn"}
        code, started = self.request("POST", "/api/chat/start", body)
        self.assertEqual(code, 202)
        turn = started["turn_id"]
        req = urllib.request.Request(
            self.base + "/api/feed?protocol=2&since=0",
            headers={"Authorization": "Bearer " + TOKEN})
        kinds, ended = [], False
        deadline = time.monotonic() + 10
        with urllib.request.urlopen(req, timeout=10) as stream:
            while time.monotonic() < deadline and not ended:
                frame = {}
                while True:
                    line = stream.readline().decode().rstrip("\r\n")
                    if time.monotonic() > deadline:
                        break
                    if not line:
                        if frame:
                            break
                        continue
                    if ": " in line:
                        key, value = line.split(": ", 1)
                        frame[key] = value
                if not frame:
                    break
                event = json.loads(frame.get("data") or "{}")
                if event.get("session") != session["id"]:
                    continue
                if event.get("turn_id") not in (None, turn):
                    continue
                kinds.append(frame.get("event"))
                ended = frame.get("event") == "chat.stream.end"
        self.assertTrue(ended, kinds)
        self.assertIn("chat.run", kinds)
        self.assertIn("chat.delta", kinds)

    def test_fixture_uses_an_empty_private_skill_catalog(self):
        code, catalog = self.request("GET", "/api/skills")
        self.assertEqual(code, 200)
        self.assertEqual(catalog.get("skills"), [])

    def test_concurrent_retry_accepts_one_turn_and_rejects_other_payload(self):
        status, session = self.request("GET", "/api/sessions/new")
        self.assertEqual(status, 200)
        body = {"session": session["id"], "message": "benchmark",
                "model": "fixture", "idempotency_key": "fixture-idempotency"}
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: self.request("POST", "/api/chat/start", body),
                                        range(2)))
        self.assertTrue(all(code in (200, 202) for code, _ in results), results)
        self.assertEqual(results[0][1]["turn_id"], results[1][1]["turn_id"])
        self.assertEqual(results[0][1]["session"], session["id"])
        conflict = dict(body, message="different")
        self.assertEqual(self.request("POST", "/api/chat/start", conflict)[0], 409)
        code, live = self.request("GET", "/api/chat/live")
        self.assertEqual(code, 200)
        self.assertEqual(live["active"].count(session["id"]), 1)

    def test_fast_turn_is_reported_finished_on_retry(self):
        _, session = self.request("GET", "/api/sessions/new")
        body = {"session": session["id"], "message": "fixture-fast",
                "model": "fixture", "idempotency_key": "fixture-fast"}
        status, started = self.request("POST", "/api/chat/start", body)
        self.assertEqual(status, 202)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            code, result = self.request("POST", "/api/chat/start", body)
            if code == 200 and result["status"] == "finished":
                self.assertEqual(result["turn_id"], started["turn_id"])
                return
            time.sleep(0.05)
        self.fail("completed turn was not reported as finished")

    def test_missing_reply_is_persisted_as_failure(self):
        _, session = self.request("GET", "/api/sessions/new")
        body = {"session": session["id"], "message": "fixture-no-reply",
                "model": "fixture", "idempotency_key": "fixture-no-reply"}
        self.assertEqual(self.request("POST", "/api/chat/start", body)[0], 202)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            code, result = self.request("POST", "/api/chat/start", body)
            if code == 200 and result["status"] in ("finished", "failed"):
                break
            time.sleep(0.05)
        else:
            self.fail("turn did not finish")
        self.assertEqual(result["status"], "failed")
        _, history = self.request("GET", "/api/history?session=" + session["id"])
        self.assertEqual(history["messages"][-1]["role"], "assistant")
        self.assertIn("stream ended without a reply", history["messages"][-1]["content"])

    def test_worker_error_is_visible_and_terminal(self):
        _, session = self.request("GET", "/api/sessions/new")
        body = {"session": session["id"], "message": "fixture-error",
                "model": "fixture", "idempotency_key": "fixture-error"}
        code, started = self.request("POST", "/api/chat/start", body)
        self.assertEqual(code, 202)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            code, result = self.request("POST", "/api/chat/start", body)
            if code == 200 and result["status"] == "failed":
                break
            time.sleep(0.05)
        else:
            self.fail("failed worker was not recorded")
        _, history = self.request("GET", "/api/history?session=" + session["id"])
        self.assertEqual(history["messages"][-1]["role"], "assistant")
        _, errors = self.request("GET", "/api/events?kind=chat.error&session=" + session["id"])
        _, terminal = self.request("GET", "/api/events?kind=chat.stream.end&session=" + session["id"])
        self.assertEqual(len(errors["events"]), 1, errors)
        self.assertEqual(len(terminal["events"]), 1)
        self.assertEqual(terminal["events"][0]["data"]["turn_id"], started["turn_id"])

    def test_tool_event_published_twice_is_deduplicated_with_turn_id(self):
        _, session = self.request("GET", "/api/sessions/new")
        body = {"session": session["id"], "message": "fixture-dupe",
                "model": "fixture", "idempotency_key": "fixture-dupe"}
        code, started = self.request("POST", "/api/chat/start", body)
        self.assertEqual(code, 202)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            code, result = self.request("POST", "/api/chat/start", body)
            if code == 200 and result["status"] == "finished":
                break
            time.sleep(0.05)
        else:
            self.fail("turn did not finish")
        _, reply = self.request("GET", "/api/events?kind=tool.call&session=" + session["id"])
        self.assertEqual(len(reply["events"]), 1)
        self.assertEqual(reply["events"][0]["data"]["turn_id"], started["turn_id"])

    def test_retry_of_first_queued_session_turn_remains_identifiable(self):
        _, session = self.request("GET", "/api/sessions/new")
        first = {"session": session["id"], "message": "first", "model": "fixture",
                 "idempotency_key": "fixture-first"}
        second = dict(first, message="second", idempotency_key="fixture-second")
        code, started = self.request("POST", "/api/chat/start", first)
        self.assertEqual(code, 202)
        self.assertEqual(self.request("POST", "/api/chat/start", second)[0], 202)
        code, retry = self.request("POST", "/api/chat/start", first)
        self.assertEqual(code, 200)
        self.assertEqual(retry["turn_id"], started["turn_id"])

    def test_replay_pages_are_ordered_and_bound_to_high_water_mark(self):
        for _ in range(5):
            self.assertEqual(self.request("GET", "/api/sessions/new")[0], 200)
        code, page = self.request("GET", "/api/feed/replay?after=0&limit=2")
        self.assertEqual(code, 200)
        upper = page["until"]
        rows = page["events"]
        self.assertTrue(page["has_more"])
        self.assertEqual(self.request("GET", "/api/sessions/new")[0], 200)
        while page["has_more"]:
            path = "/api/feed/replay?after=%s&until=%s&limit=2" % (page["next"], upper)
            code, page = self.request("GET", path)
            self.assertEqual(code, 200)
            rows.extend(page["events"])
        ids = [row["id"] for row in rows]
        self.assertEqual(ids, sorted(set(ids)))
        self.assertTrue(ids)
        self.assertTrue(all(event_id <= upper for event_id in ids))
        self.assertFalse(page["gap"])

    def test_shared_feed_replays_and_then_delivers_live_events_once(self):
        _, first = self.request("GET", "/api/sessions/new")
        req = urllib.request.Request(
            self.base + "/api/feed?protocol=2&since=0",
            headers={"Authorization": "Bearer " + TOKEN})
        with urllib.request.urlopen(req, timeout=5) as stream:
            deadline = time.monotonic() + 3
            def read_event():
                frame = {}
                while True:
                    if time.monotonic() > deadline:
                        self.fail("shared feed did not deliver the expected event")
                    line = stream.readline().decode().rstrip("\r\n")
                    if not line:
                        if frame:
                            return frame
                    elif ": " in line:
                        key, value = line.split(": ", 1)
                        frame[key] = value
            seen = []
            while True:
                frame = read_event()
                if frame.get("event") == "feed.ready":
                    break
                if frame.get("id"):
                    seen.append(int(frame["id"]))
            self.assertTrue(seen)
            self.assertEqual(seen, sorted(set(seen)))
            _, second = self.request("GET", "/api/sessions/new")
            while True:
                frame = read_event()
                if frame.get("event") == "session.created":
                    event = json.loads(frame["data"])
                    if event.get("session") == second["id"]:
                        self.assertGreater(int(frame["id"]), seen[-1])
                        break

    def test_z_ten_distinct_turns_overlap_and_finish(self):
        sessions = [self.request("GET", "/api/sessions/new")[1]["id"] for _ in range(10)]
        bodies = [{"session": sid, "message": "fixture-stress", "model": "fixture",
                   "idempotency_key": "stress-" + sid} for sid in sessions]
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            starts = list(executor.map(
                lambda body: self.request("POST", "/api/chat/start", body), bodies))
        self.assertTrue(all(code == 202 for code, _ in starts), starts)
        self.assertEqual(len({result["turn_id"] for _, result in starts}), 10)
        _, live = self.request("GET", "/api/chat/live")
        self.assertTrue(set(sessions).issubset(live["active"]), live)
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            _, live = self.request("GET", "/api/chat/live")
            if not set(sessions).intersection(live["active"]):
                break
            time.sleep(0.1)
        else:
            self.fail("not all fixture turns completed")
        for body, (_, started) in zip(bodies, starts):
            code, result = self.request("POST", "/api/chat/start", body)
            self.assertEqual((code, result["status"]), (200, "finished"))
            self.assertEqual(result["turn_id"], started["turn_id"])
            _, history = self.request("GET", "/api/history?session=" + body["session"])
            self.assertEqual(history["messages"][-1]["content"], "fixture complete")


if __name__ == "__main__":
    unittest.main()
