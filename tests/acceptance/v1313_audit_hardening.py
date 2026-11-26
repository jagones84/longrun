#!/usr/bin/env python3
"""v1313 — audit hardening: three contained fixes from the 2026-11-27 security audit.

The audit (audit-context DOSSIER → trailmark graph → semgrep + CodeQL → fp-check)
found the core's write/exec perimeter already guarded (realpath roots, one hard-deny
judge, argv-not-shell, `hmac.compare_digest`), so the exploitable-looking
`py/path-injection` / `py/command-line-injection` / timing findings were false
positives. Three items were worth fixing:

  A  `_RX_PATH` — the context-panel path regex was ambiguous and unbounded, so a
     `/`-heavy transcript hung the derivation on the request thread (codeql
     py/redos). Pinned: it still finds real paths, and a 60k-segment adversarial
     input resolves in well under a second.
  B  `_tls_context()` — the HTTPS-for-voice server now states its TLS floor
     explicitly (codeql py/insecure-protocol).
  C  `setup_blocks._Store.restore` — a checkpoint tar is extracted member by
     member, refusing absolute / `..` / escaping members (codeql py/tarslip,
     semgrep tarfile-extractall-traversal), the same guard shape the zip paths use.

Deterministic: no model, no network, no server. Run:
    python3 tests/acceptance/v1313_audit_hardening.py
"""
import io
import json
import os
import ssl
import sys
import tarfile
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(REPO, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from longrun.core import server as _server  # noqa: E402,F401 — populates imports first
from longrun.core import httpapi  # noqa: E402
from longrun.harness.checks import setup_blocks  # noqa: E402

FAILED = []
CHECKS = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ((" — %s" % (detail,)) if detail else ""))
    CHECKS.append(name)
    if not ok:
        FAILED.append(name)


# ── A · the path regex: still useful, now bounded ───────────────────────────
_RX = httpapi._RX_PATH
check("A1 a normal path is still found",
      _RX.findall("see /src/longrun/core/httpapi.py now") == ["/src/longrun/core/httpapi.py"])
check("A2 a deep path is still found",
      _RX.findall("/a/b/c/d/e/f.py") == ["/a/b/c/d/e/f.py"])
check("A3 a path without a known extension is not a match",
      _RX.findall("/foo/bar") == [])
_t0 = time.time()
_RX.search("/" + "!/" * 60000 + ".py")
_elapsed = time.time() - _t0
check("A4 a 60k-segment adversarial input is linear (<2s)",
      _elapsed < 2.0, "%.3fs" % _elapsed)

# ── B · the TLS floor is explicit ───────────────────────────────────────────
check("B1 the server context pins TLS >= 1.2",
      httpapi._tls_context().minimum_version == ssl.TLSVersion.TLSv1_2)

# ── C · the tar checkpoint refuses an escaping member ───────────────────────
_tmp = tempfile.mkdtemp(prefix="sf-v1313-")
_state = os.path.join(_tmp, "state")
_work = os.path.join(_tmp, "work")
os.makedirs(_work, exist_ok=True)
_store = setup_blocks._Store(_state, _work)

_block_dir = os.path.join(_state, "setup", setup_blocks._safe("b1"))
os.makedirs(_block_dir, exist_ok=True)
_tar_path = os.path.join(_block_dir, "snapshot.tar.gz")
with tarfile.open(_tar_path, "w:gz") as _tar:
    for _name, _body in (("safe.txt", b"ok"), ("../escape.txt", b"pwn")):
        _info = tarfile.TarInfo(_name)
        _info.size = len(_body)
        _tar.addfile(_info, io.BytesIO(_body))

with open(os.path.join(_block_dir, "manifest.json"), "w", encoding="utf-8") as _fh:
    json.dump({"tarball": "snapshot.tar.gz", "created": 1}, _fh)

_man = _store.restore("b1")
check("C1 the checkpoint restores its safe member",
      _man is not None and os.path.isfile(os.path.join(_work, "safe.txt")))
check("C2 an escaping `../` member is never written",
      not os.path.exists(os.path.join(_tmp, "escape.txt")))

print()
if FAILED:
    print("FAILED %d/%d: %s" % (len(FAILED), len(CHECKS), ", ".join(FAILED)))
    sys.exit(1)
print("OK %d/%d" % (len(CHECKS), len(CHECKS)))
