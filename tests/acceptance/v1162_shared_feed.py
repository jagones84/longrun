#!/usr/bin/env python3
"""The shared feed must report overflow instead of silently dropping events."""
import os
import json
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.TemporaryDirectory(prefix="longrun-shared-feed-")
os.environ["HOME"] = TMP.name
os.environ["LONGRUN_DATA_HOME"] = TMP.name
os.environ["LONGRUN_DATA_DIR"] = TMP.name
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP.name, "config")
os.environ["LONGRUN_DB"] = os.path.join(TMP.name, "events.db")
os.environ["LONGRUN_OFFLINE"] = "1"
sys.path.insert(0, os.path.join(ROOT, "src"))

from longrun.core import server  # noqa: E402,F401
from longrun.core import events, httpapi  # noqa: E402


class SharedFeed(unittest.TestCase):
    def test_events_published_during_multipage_replay_arrive_once_in_order(self):
        start = events.feed_seq()
        historical = [events.publish("test.replay", value=i)["id"] for i in range(250)]
        gen = httpapi.feed_gen_v2(start, queue_size=32)
        self.assertIn("feed open", next(gen))
        received = []
        try:
            for _ in range(5):
                frame = next(gen)
                received.append(int(frame.splitlines()[0].split(": ")[1]))
            live = [events.publish("test.live", value=i)["id"] for i in range(3)]
            while True:
                frame = next(gen)
                if "event: feed.ready" in frame:
                    break
                received.append(int(frame.splitlines()[0].split(": ")[1]))
            for _ in live:
                frame = next(gen)
                received.append(int(frame.splitlines()[0].split(": ")[1]))
            self.assertEqual(received, historical + live)
        finally:
            gen.close()

    def test_prune_during_replay_never_silently_skips_events(self):
        start = events.feed_seq()
        ids = [events.publish("test.prune-race", value=i)["id"] for i in range(5)]
        gen = httpapi.feed_gen_v2(start)
        self.assertIn("feed open", next(gen))
        original_lock = events._db_lock

        class PruneAfterRead:
            triggered = False

            def __enter__(self):
                return original_lock.__enter__()

            def __exit__(self, *args):
                result = original_lock.__exit__(*args)
                if not self.triggered:
                    self.triggered = True
                    events.prune_events(keep=1)
                return result

        events._db_lock = PruneAfterRead()
        seen, gap = [], False
        try:
            while True:
                frame = next(gen)
                if "event: feed.ready" in frame:
                    break
                if "event: feed.gap" in frame:
                    gap = True
                if "event: test.prune-race" in frame:
                    data = next(line[6:] for line in frame.splitlines() if line.startswith("data: "))
                    seen.append(json.loads(data)["id"])
            self.assertTrue(gap or seen == ids, (seen, ids))
        finally:
            gen.close()
            events._db_lock = original_lock

    def test_overflow_is_signalled_before_ready(self):
        gen = httpapi.feed_gen_v2(events.feed_seq(), queue_size=1)
        self.assertIn("feed open", next(gen))
        events.publish("test.one")
        events.publish("test.two")
        try:
            self.assertIn("event: feed.overflow", next(gen))
            self.assertRaises(StopIteration, next, gen)
        finally:
            gen.close()


if __name__ == "__main__":
    unittest.main()
