#!/usr/bin/env python3
"""v1167 — a VALID key with no credit must not be reported as a rejected key.

Measured on the live service: OpenRouter answered 200 on `/api/v1/key` (the key is
fine) while every turn failed with "provider rejected its API key", because the
key's own spending limit was reached (limit 10, usage 10.00). The operator was sent
to re-enter a key that was never wrong.
"""
import os
import sys
import unittest
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src"))

from longrun.core import diagnostics  # noqa: E402


def http_error(code, body=""):
    return urllib.error.HTTPError("https://openrouter.ai/api/v1/chat/completions",
                                  code, body, {}, None)


class QuotaDiagnosis(unittest.TestCase):
    def test_402_is_a_quota_problem(self):
        issue = diagnostics.classify_model_error(
            http_error(402, "Payment Required"), model="openrouter:z-ai/glm-5.3-flash")
        self.assertEqual(issue["code"], "provider.quota_exhausted")
        self.assertIn("credit", issue["message"].lower())
        self.assertNotIn("rejected its api key", issue["message"].lower())

    def test_403_with_a_key_limit_body_is_quota(self):
        issue = diagnostics.classify_model_error(
            Exception("HTTP 403: Key limit exceeded (total limit)"), model="openrouter:x")
        self.assertEqual(issue["code"], "provider.quota_exhausted")

    def test_a_real_auth_failure_is_still_auth(self):
        issue = diagnostics.classify_model_error(
            http_error(401, "invalid api key"), model="openrouter:x")
        self.assertEqual(issue["code"], "provider.auth_rejected")


if __name__ == "__main__":
    unittest.main()
