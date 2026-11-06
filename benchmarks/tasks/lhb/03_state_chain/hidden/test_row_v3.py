#!/usr/bin/env python3
"""Turn-2 contract: to_row emits a,b,c."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _load import load  # noqa: E402


class RowV3(unittest.TestCase):
    def test_order(self):
        m = load()
        self.assertEqual(m.to_row({"c": "3", "a": "1", "b": "2"}), "1,2,3")
        self.assertEqual(m.to_row({"a": "1", "b": "2"}), "1,2,")
        self.assertEqual(m.to_row({"a": "1", "b": "2", "c": "3", "z": "9"}), "1,2,3")


if __name__ == "__main__":
    unittest.main(verbosity=2)
