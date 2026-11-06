#!/usr/bin/env python3
"""Turn-1 contract: SCHEMA_VERSION is still 3."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _load import load  # noqa: E402


class Version(unittest.TestCase):
    def test_version(self):
        self.assertEqual(load().SCHEMA_VERSION, 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
