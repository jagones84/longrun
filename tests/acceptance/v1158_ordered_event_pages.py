#!/usr/bin/env python3
"""Ordered replay pages preserve the existing newest-first limit contract."""
import os
import queue
import sys
import tempfile
import threading
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.TemporaryDirectory(prefix="longrun-event-pages-")
os.environ["LONGRUN_DATA_DIR"] = TMP.name
os.environ["LONGRUN_DB"] = os.path.join(TMP.name, "events.db")
sys.path.insert(0, os.path.join(ROOT, "src"))

from longrun.core import events  # noqa: E402


class OrderedEventPages(unittest.TestCase):
    def test_pages_are_oldest_first_with_a_stable_upper_bound(self):
        self.assertTrue(hasattr(events, "events_page"), "ordered replay is missing")
        ids = [events.publish("test.page", value=i)["id"] for i in range(7)]
        upper = ids[-2]
        first = events.events_page(ids[0], limit=2, until=upper)
        second = events.events_page(first[-1]["id"], limit=2, until=upper)
        third = events.events_page(second[-1]["id"], limit=2, until=upper)
        self.assertEqual([e["id"] for e in first + second + third], ids[1:-1])
        self.assertEqual(events.events_since(ids[0], limit=2)[-1]["id"], ids[-1])
        with events._feed_lock:
            events._feed.clear()
        self.assertEqual([e["id"] for e in events.events_page(ids[0], 2, upper)],
                         ids[1:3])

    def test_concurrent_publishers_deliver_in_durable_order(self):
        arrived = threading.Event()
        release = threading.Event()
        original_lock = events._sse_lock
        subscriber = queue.Queue()

        class DelayedFirstLock:
            def __enter__(self):
                if threading.current_thread().name == "first-publisher":
                    arrived.set()
                    if not release.wait(3):
                        raise RuntimeError("test timed out")
                return original_lock.__enter__()

            def __exit__(self, *args):
                return original_lock.__exit__(*args)

        events._sse_lock = DelayedFirstLock()
        events._sse_queues.add(subscriber)
        first = threading.Thread(name="first-publisher",
                                 target=events.publish, args=("test.first",))
        second = threading.Thread(name="second-publisher",
                                  target=events.publish, args=("test.second",))
        try:
            first.start()
            self.assertTrue(arrived.wait(3))
            second.start()
            second.join(0.2)
            release.set()
            first.join(3)
            second.join(3)
            self.assertFalse(first.is_alive() or second.is_alive())
            frames = [subscriber.get_nowait(), subscriber.get_nowait()]
            ids = [int(frame.splitlines()[0].split(": ")[1]) for frame in frames]
            self.assertEqual(ids, sorted(ids))
        finally:
            release.set()
            first.join(3)
            if second.ident:
                second.join(3)
            events._sse_queues.discard(subscriber)
            events._sse_lock = original_lock

    def test_retention_floor_tracks_pruning_not_rewind_holes(self):
        self.assertTrue(hasattr(events, "retention_floor"), "retention watermark is missing")
        start = events.retention_floor()
        rows = [events.publish("test.retention", session="fixture", value=i)
                for i in range(5)]
        events.truncate("fixture", rows[1]["id"])
        self.assertEqual(events.retention_floor(), start)
        later = [events.publish("test.retention", value=i) for i in range(5)]
        self.assertGreater(events.prune_events(keep=2), 0)
        self.assertGreaterEqual(events.retention_floor(), rows[1]["id"])
        self.assertLess(events.retention_floor(), later[-2]["id"])


if __name__ == "__main__":
    unittest.main()
