#!/usr/bin/env python3
"""v1168 — a 403 with a quota BODY is not an authentication failure.

A54 P1: a valid key whose credit is exhausted answers 403 with a JSON body
("Key limit exceeded"). `str(HTTPError)` is only "HTTP Error 403: Forbidden", so
classifying on `str(error)` alone still reports `provider.auth_rejected` — the
operator is sent to re-enter a key that was never wrong.

Pinned here:
  * 403 + quota body -> provider.quota_exhausted, action keys;
  * 403 without quota markers -> provider.request_forbidden, never auth;
  * 401 stays provider.auth_rejected;
  * 402 stays provider.quota_exhausted;
  * the body/URL are never echoed.

Run: python3 tests/acceptance/v1168_provider_quota_body.py
"""
import io
import os
import sys
import tempfile
import urllib.error

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1168-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import diagnostics as D  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail else ""))


QUOTA_BODY = (b'{"error":{"message":"Key limit exceeded (total limit), '
              b'$10.00 of $10.00 used; does not reset.",'
              b'"code":403,"metadata":{"limit_source":"openrouter_key_limit"}}}')
SECRET = "NEVER-ECHO-THIS"


def http_error(code, body=b"", reason="Error"):
    fp = io.BytesIO(body) if body else None
    return urllib.error.HTTPError(
        "https://provider.invalid/v1/chat?token=" + SECRET,
        code, reason, {}, fp)


# A1/A2: the real production shape — HTTPError whose body carries the quota.
err = http_error(403, QUOTA_BODY, "Forbidden")
issue = D.classify_model_error(err, "openrouter:z-ai/glm-5.3-flash", "v1168")
check("A1 a 403 with a quota body maps to provider.quota_exhausted",
      issue.get("code") == "provider.quota_exhausted"
      and issue.get("action") == "keys", issue)
check("A2 the operator message names credit/limit, never 'rejected its API key'",
      ("credit" in issue.get("message", "").lower()
       or "limit" in issue.get("message", "").lower())
      and "rejected its api key" not in issue.get("message", "").lower(),
      issue.get("message"))

# A3: a 403 with no quota marker is still NOT an auth failure.
plain = D.classify_model_error(http_error(403, b"", "Forbidden"),
                               "openrouter:x", "v1168")
check("A3 a plain 403 maps to provider.request_forbidden, not auth",
      plain.get("code") == "provider.request_forbidden"
      and plain.get("code") != "provider.auth_rejected", plain)

# A4/A5: the existing branches must not regress.
auth = D.classify_model_error(http_error(401, b"invalid api key"),
                              "openrouter:x", "v1168")
check("A4 a 401 stays provider.auth_rejected",
      auth.get("code") == "provider.auth_rejected", auth)
auth_quota = D.classify_model_error(http_error(401, QUOTA_BODY),
                                    "openrouter:x", "v1168")
check("A4b a 401 stays auth even when its body mentions a limit",
      auth_quota.get("code") == "provider.auth_rejected", auth_quota)
pay = D.classify_model_error(http_error(402, b"Payment Required"),
                             "openrouter:x", "v1168")
check("A5 a 402 stays provider.quota_exhausted",
      pay.get("code") == "provider.quota_exhausted", pay)

# A6: the body and the URL are never rendered.
check("A6 neither the body nor the URL reaches the issue",
      SECRET not in repr(issue) and "provider.invalid" not in repr(issue)
      and "Key limit exceeded" not in repr(issue), repr(issue)[:200])

# A7: reading the body once must not make a second classification raise.
err2 = http_error(403, QUOTA_BODY, "Forbidden")
first = D.classify_model_error(err2, "openrouter:x", "v1168")
second = D.classify_model_error(err2, "openrouter:x", "v1168")
check("A7 a consumed body does not raise on a second classification",
      isinstance(second, dict)
      and second.get("code") in ("provider.quota_exhausted",
                                 "provider.request_forbidden"),
      (first.get("code"), second.get("code")))

print("---")
ok = sum(results)
print("\nv1168: %d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
