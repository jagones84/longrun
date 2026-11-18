#!/usr/bin/env python3
"""v1170 — a redirect / soft-404 must not be reported as a clean success.

A54 P3: `web.fetch` on a URL that does not exist under a live host returned the
site's real content with `exit=0`. The current `_web_fetch` follows redirects and
never compares the FINAL url with the requested one, so the caller cannot tell a
wrong deep link from the page it asked for.

Pinned here (local loopback fixture, no external network):
  * `/missing` -> 302 `/known` is flagged and is not a clean exit 0;
  * a query-only redirect is NOT flagged (no false positive);
  * a reader answer carrying `URL Source:` is compared too;
  * the public `http.fetch` route propagates the flag.

Run: python3 tests/acceptance/v1170_fetch_redirect_truth.py
"""
import http.server
import os
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1170-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_OFFLINE"] = "1"
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry  # noqa: E402
from longrun.tools import tools as T  # noqa: E402

registry._external_tools = lambda: {}
registry._matrix_tools = lambda: {}

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail else ""))


KNOWN = b"<html><body>KNOWN-A54-PAGE</body></html>"
PAGE_OK = b"<html><body>PAGE-OK</body></html>"


class _Fixture(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 — stdlib handler name
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/known":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(KNOWN)))
            self.end_headers()
            self.wfile.write(KNOWN)
            return
        if parsed.path == "/missing":
            self.send_response(302)
            self.send_header("Location", "/known")
            self.end_headers()
            return
        if parsed.path == "/page" and parsed.query == "x=2":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(PAGE_OK)))
            self.end_headers()
            self.wfile.write(PAGE_OK)
            return
        if parsed.path == "/page":
            self.send_response(302)
            self.send_header("Location", "/page?x=2")
            self.end_headers()
            return
        self.send_error(404)

    def log_message(self, *args):  # keep the test output clean
        pass


_srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Fixture)
_port = _srv.server_address[1]
threading.Thread(target=_srv.serve_forever, daemon=True).start()
_local = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class _Rewritten:
    """A real fixture response whose `geturl()` names the ORIGINAL host.

    The fixture lives on loopback, but the code under test must see the final
    URL the way it would in production: same host, different path.
    """

    def __init__(self, resp, requested):
        self._resp = resp
        self._requested = requested

    def read(self, n=-1):
        return self._resp.read(n)

    def geturl(self):
        got = urllib.parse.urlparse(self._resp.geturl())
        req = urllib.parse.urlparse(self._requested)
        return urllib.parse.urlunsplit((req.scheme, req.netloc, got.path,
                                        got.query, got.fragment))

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self._resp.close()
        return False


class _ToFixture:
    """The tool opener, redirected to the loopback fixture; reader is refused."""

    def open(self, req, timeout=None):
        full = getattr(req, "full_url", req)
        if "r.jina.ai" in full:
            raise urllib.error.HTTPError(full, 403, "reader blocked", {}, None)
        parsed = urllib.parse.urlparse(full)
        target = "http://127.0.0.1:%d%s" % (_port, parsed.path)
        if parsed.query:
            target += "?" + parsed.query
        return _Rewritten(_local.open(target, timeout=timeout), full)


class _ReaderResp:
    def __init__(self, body, url):
        self._body = body
        self._url = url

    def read(self, _n=-1):
        return self._body

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _ReaderFixture:
    """A reader answer that honestly names the page it served."""

    def open(self, req, timeout=None):
        full = getattr(req, "full_url", req)
        body = (b"URL Source: https://fixture.invalid/known\n\nKNOWN-A54-PAGE")
        return _ReaderResp(body, full)


_orig_opener, _orig_guard = T._opener, T._public_host
_orig_spec = registry.tool_spec
T._opener = lambda check: _ToFixture()
T._public_host = lambda url: (True, urllib.parse.urlparse(url).hostname or "fixture")
try:
    # ---- A1: a 302 to another path is a soft-404 --------------------------
    data, err = T._web_fetch("https://fixture.invalid/missing", 4096)
    check("A1 a redirect to another path is flagged as soft-404",
          data is not None and data.get("soft_404") is True
          and str(data.get("redirected_to") or "").endswith("/known")
          and "KNOWN-A54-PAGE" in str(data.get("text") or ""),
          (data or {}).get("final_url"))

    # ---- A2: the tool result is not a clean success ----------------------
    res = T._web_open({"url": "https://fixture.invalid/missing"}, time.time())
    check("A2 a single soft-404 page returns ok=False and exit 1",
          res.get("ok") is False and res.get("exit_code") == 1
          and "soft-404" in str(res.get("error") or "").lower()
          and "KNOWN-A54-PAGE" in str(res.get("stdout") or ""),
          (res.get("exit_code"), res.get("error")))

    # ---- A3: a query-only redirect is benign -----------------------------
    benign, _ = T._web_fetch("https://fixture.invalid/page", 4096)
    benign_res = T._web_open({"url": "https://fixture.invalid/page"}, time.time())
    check("A3 a query-only redirect is not flagged",
          benign is not None and not benign.get("soft_404")
          and benign_res.get("exit_code") == 0,
          (benign or {}).get("final_url"))

    # ---- A4: the reader's own URL Source is compared ---------------------
    T._opener = lambda check: _ReaderFixture()
    reader, _ = T._web_fetch("https://fixture.invalid/missing", 4096)
    check("A4 a reader answer naming another page is flagged",
          reader is not None and reader.get("soft_404") is True,
          (reader or {}).get("final_url"))

    # ---- A5: the public http.fetch route propagates the flag -------------
    T._opener = lambda check: _ToFixture()
    registry.tool_spec = lambda name, *a, **k: (
        {"allow_hosts": [], "enabled": True}
        if name == "http" else _orig_spec(name, *a, **k))
    http_res = T._http({"url": "https://fixture.invalid/missing"}, None)
    check("A5 the public http.fetch route does not claim a clean success",
          http_res.get("soft_404") is True
          and http_res.get("ok") is False
          and "soft-404" in str(http_res.get("error") or "").lower(),
          (http_res.get("exit_code"), http_res.get("error")))

    registry.tool_spec = lambda name, *a, **k: (
        {"allow_hosts": [], "enabled": True}
        if name == "browser" else _orig_spec(name, *a, **k))
    browser_res = T._browser({"url": "https://fixture.invalid/missing"}, None)
    check("A5b the public browser.fetch route does not claim a clean success",
          browser_res.get("soft_404") is True and browser_res.get("ok") is False,
          (browser_res.get("exit_code"), browser_res.get("error")))
finally:
    T._opener, T._public_host = _orig_opener, _orig_guard
    registry.tool_spec = _orig_spec
    _srv.shutdown()
    _srv.server_close()

print("---")
ok = sum(results)
print("\nv1170: %d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
