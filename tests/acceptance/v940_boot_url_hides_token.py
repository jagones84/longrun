#!/usr/bin/env python3
"""v940: the boot banner never writes the bearer to the journal, and auth
comparisons are constant-time.

`systemctl --user restart longrun` captures stdout into the systemd journal, so
the tokenized phone/voice URL that `main()` printed put the bearer in a file any
local `journalctl` reader can open, on every restart. `boot_url()` keeps the URL
printable without the secret (token only on an interactive terminal, where the
service manager cannot capture it), and `check_auth` compares with
`hmac.compare_digest` so a wrong token costs the same time as a right one.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server  # noqa: E402,F401 — server first (circular import)
from longrun.core import httpapi  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


TOKEN = "lr-test-5ecret"
_prev = httpapi.AUTH_TOKEN
httpapi.AUTH_TOKEN = TOKEN
try:
    check("1a the bearer header is accepted",
          httpapi.check_auth({"Authorization": "Bearer " + TOKEN}) is True)
    check("1b a wrong bearer is rejected",
          httpapi.check_auth({"Authorization": "Bearer nope"}) is False)
    check("1c a prefix of the token is rejected",
          httpapi.check_auth({"Authorization": "Bearer " + TOKEN[:-1]}) is False)
    check("1d an empty authorization header is rejected",
          httpapi.check_auth({}) is False)
    check("2a ?token= is accepted (EventSource fallback)",
          httpapi.check_auth({}, {"token": TOKEN}) is True)
    check("2b a wrong ?token= is rejected",
          httpapi.check_auth({}, {"token": "lr-test"}) is False)
    check("2c a query without a token is rejected",
          httpapi.check_auth({}, {"session": "abc"}) is False)
    check("2d a non-ASCII header is rejected, not raised",
          httpapi.check_auth({"Authorization": "Bearer tökén"}) is False)
    check("2e a non-ASCII ?token= is rejected, not raised",
          httpapi.check_auth({}, {"token": "tökén"}) is False)
finally:
    httpapi.AUTH_TOKEN = _prev

try:
    httpapi.AUTH_TOKEN = None
    check("3a no token configured still means open (local first run)",
          httpapi.check_auth({}) is True)
finally:
    httpapi.AUTH_TOKEN = _prev

src = open(os.path.join(REPO, "src/longrun/core/httpapi.py"), encoding="utf-8").read()

check("4a the comparison goes through hmac.compare_digest",
      "hmac.compare_digest" in src and "def _same_secret" in src)
check("4b no direct secret comparison is left in check_auth",
      '== "Bearer " + AUTH_TOKEN' not in src and "qs.get(\"token\") == AUTH_TOKEN" not in src)

# --- the boot URL -------------------------------------------------------------
_real_isatty = sys.stdout.isatty


class _NotTty:
    def isatty(self):
        return False


class _Tty:
    def isatty(self):
        return True


_saved = sys.stdout
try:
    sys.stdout = _NotTty()
    plain = httpapi.boot_url("192.168.1.37", 8790, TOKEN)
    plain_https = httpapi.boot_url("192.168.1.37", 8790, TOKEN, scheme="https")
finally:
    sys.stdout = _saved
check("5a a piped stdout (systemd) gets the URL with NO token", "token=" not in plain, plain)
check("5b the piped URL is still usable", plain == "http://192.168.1.37:8790/", plain)
check("5c the HTTPS banner hides the token too", "token=" not in plain_https, plain_https)

try:
    sys.stdout = _Tty()
    tty = httpapi.boot_url("192.168.1.37", 8790, TOKEN)
    tty_none = httpapi.boot_url("192.168.1.37", 8790, "")
    tty_special = httpapi.boot_url("10.0.0.2", 8790, "a b&c")
finally:
    sys.stdout = _saved
check("6a an interactive terminal keeps the convenient tokenized URL",
      tty == "http://192.168.1.37:8790/?token=" + TOKEN, tty)
check("6b a terminal without a token prints the plain URL",
      tty_none == "http://192.168.1.37:8790/", tty_none)
check("6c the token is URL-quoted in the terminal URL",
      tty_special.endswith("?token=a%20b%26c"), tty_special)

check("7a main() no longer interpolates the token into a print",
      "quote(args.token)" not in src)
check("7b both boot banners go through boot_url",
      src.count("boot_url(") >= 2 and "Open on your phone: %s" in src)

print("TOTAL %d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
