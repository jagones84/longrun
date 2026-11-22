#!/usr/bin/env python3
"""v588 — CLI route parity: every forge.py endpoint exists on the server.

JAG-CLId  A CLI subcommand can point at a renamed/removed route and fail only
          at runtime (exit 0 + {"error":...}). This pins parity statically:
          every /api/* or /mcp literal used by forge.py must match a
          `path ==` literal or a `path.startswith` prefix in one of the four
          server route files. No live server, no model, no network.

Deterministic. Run:  python3 tests/acceptance/v588_cli_route_parity.py
"""
import os
import re
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="sf-588-")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(_tmp, "sessions")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_tmp, "cfg")
os.makedirs(os.environ["LONGRUN_SESSIONS_DIR"], exist_ok=True)
os.makedirs(os.environ["LONGRUN_CONFIG_DIR"], exist_ok=True)

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


ROUTE_FILES = [
    ("src", "longrun", "core/httpapi.py"),
    ("src", "longrun", "core/api_v02.py"),
    ("src", "longrun", "orchestrate/orchestration.py"),
    ("src", "longrun", "orbit/api.py"),
]

server = ""
for rf in ROUTE_FILES:
    server += read(*rf) + "\n"

exact = set(re.findall(r'path\s*==\s*"([^"]+)"', server))
# orchestration.py matches via _is(path, base) == exact-or-subpath
exact |= set(re.findall(r'_is\(\s*path\s*,\s*"([^"]+)"', server))
# api_v02.py matches `path in ("/mcp", "/api/mcp")` tuple form
for tup in re.findall(r'path\s+in\s*\(([^)]+)\)', server):
    exact |= set(re.findall(r'"([^"]+)"', tup))
prefixes = set(re.findall(r'path\.startswith\(\s*"([^"]+)"', server))
# dynamic sub-paths: "/api/x/" + var  and  "/api/x/%s" % var
dyn = set(re.findall(r'"/api/[^"]*/"\s*\+', server))
dyn |= set(re.findall(r'"/api/[^"]*/%s"', server))

fv = read("src", "longrun", "core/forge.py")
cli = set(re.findall(r'"/(?:api|mcp)[^"]*"', fv))
cli = {c.strip('"').split("?")[0] for c in cli}
# forge builds some paths by concatenation: "/api/approvals/" + id
cli |= {c.strip('"') for c in re.findall(r'"/api/[^"]*/"\s*\+', fv)}

check("server route files expose paths", len(exact) > 100, "exact=%d" % len(exact))
check("server route files expose prefixes", len(prefixes) > 0, "prefixes=%d" % len(prefixes))
check("CLI uses a sane number of endpoints", len(cli) > 40, "cli=%d" % len(cli))

dead = []
for c in sorted(cli):
    if c in exact:
        continue
    hit = False
    for q in prefixes:
        if c.startswith(q) or q.startswith(c.rstrip("/") + "/") or q == c:
            hit = True
            break
    if not hit:
        for e in exact:
            if e.startswith(c) and c.endswith("/"):
                hit = True
                break
    if not hit and c in dyn:
        hit = True
    if not hit:
        dead.append(c)

check("JAG-CLId every CLI path exists on the server", not dead,
      "dead=%s" % dead if dead else "cli=%d exact=%d prefixes=%d"
      % (len(cli), len(exact), len(prefixes)))

# ---- JAG-CLIe: method parity (clean-structure files only) --------------------
# api_v02 / httpapi / orbit/api gate methods structurally (do_GET/do_POST or
# `if method ==`), so every forge req(method, path) must be answered under the
# SAME method. orchestration.py mixes gates per-branch — path-only there.
METHOD_FILES = [
    ("src", "longrun", "core/api_v02.py"),
    ("src", "longrun", "core/httpapi.py"),
    ("src", "longrun", "orbit/api.py"),
    # orchestration.py mixes gates per-branch: nearest-gate attribution below.
    ("src", "longrun", "orchestrate/orchestration.py"),
]


def _regions(lines, markers):
    regs = []
    cur, start = None, 0
    for i, ln in enumerate(lines):
        for kind, rx in markers:
            if rx(ln):
                if cur is not None:
                    regs.append((cur, start, i))
                cur, start = kind, i
                break
    if cur is not None:
        regs.append((cur, start, len(lines)))
    return regs


def _lits(blob):
    out = {"exact": set(), "prefix": set()}
    out["exact"] |= set(re.findall(r'path\s*==\s*"([^"]+)"', blob))
    out["prefix"] |= set(re.findall(r'path\.startswith\(\s*"([^"]+)"', blob))
    out["exact"] |= set(re.findall(r'_is\(\s*path\s*,\s*"([^"]+)"', blob))
    for tup in re.findall(r'path\s+in\s*\(([^)]+)\)', blob):
        out["exact"] |= set(re.findall(r'"([^"]+)"', tup))
    return out


# path -> set(methods); prefix -> set(methods)
srv_exact, srv_prefix = {}, {}
for rf in METHOD_FILES:
    lines = read(*rf).splitlines()
    if rf[-1].endswith("orchestration.py"):
        # Branch structure: `if _is(path, X):` opens a block whose inner
        # `if method ==` gates all serve X (path literal often implicit).
        cur, pending = None, None
        for ln in lines:
            if re.match(r'\s*def ', ln):
                cur, pending = None, None
                continue
            opener = re.match(r'\s*if _is\(path, "([^"]+)"\)', ln)
            if opener:
                pending = opener.group(1)
                srv_exact.setdefault(pending, set())
                cur = None
                continue
            inl = re.match(r'(\s*)if method == "(GET|POST|PUT|PATCH|DELETE)" and\b(.*)', ln)
            if inl:
                for p in _lits(inl.group(3))["exact"]:
                    srv_exact.setdefault(p, set()).add(inl.group(2))
                for p in _lits(inl.group(3))["prefix"]:
                    srv_prefix.setdefault(p, set()).add(inl.group(2))
                continue
            gate = re.match(r'(\s*)if method == "(GET|POST|PUT|PATCH|DELETE)":', ln)
            if gate:
                cur = gate.group(2)
                if pending is not None and len(gate.group(1)) > 4:
                    srv_exact[pending].add(cur)
                else:
                    pending = None
                continue
            if cur is None:
                continue
            for p in _lits(ln)["exact"]:
                srv_exact.setdefault(p, set()).add(cur)
            got_prefix = set(_lits(ln)["prefix"])
            got_prefix |= set(re.findall(r'path\[len\("([^"]+)"\)', ln))
            for p in got_prefix:
                srv_prefix.setdefault(p, set()).add(cur)
        continue
    if rf[-1].endswith("httpapi.py"):
        regs, cur, start = [], None, 0
        for i, ln in enumerate(lines):
            mt = re.match(r'    def do_(GET|POST|PUT|PATCH|DELETE)\(self\):', ln)
            if mt:
                if cur is not None:
                    regs.append((cur, start, i))
                cur, start = mt.group(1), i
        if cur is not None:
            regs.append((cur, start, len(lines)))
    else:
        regs = _regions(lines, [("M", lambda ln: re.match(r'    if method == "(GET|POST|PUT|PATCH|DELETE)":', ln)
                                     and True or False)])
        # _regions stores kind "M"; recover the real method per region start
        fixed = []
        for _, s, e in regs:
            mt = re.match(r'    if method == "(GET|POST|PUT|PATCH|DELETE)":', lines[s])
            fixed.append((mt.group(1), s, e))
        regs = fixed
    for method, s, e in regs:
        blob = "\n".join(lines[s:e])
        for p in _lits(blob)["exact"]:
            srv_exact.setdefault(p, set()).add(method)
        for p in _lits(blob)["prefix"]:
            srv_prefix.setdefault(p, set()).add(method)

check("method map built", len(srv_exact) > 100, "exact=%d" % len(srv_exact))

# CLI (method, path) pairs: req("M", "lit"[ + var]) and bare sse("lit") == GET
pairs = []
for m, lit, plus in re.findall(r'req\(\s*"(GET|POST|PUT|PATCH|DELETE)"\s*,\s*("[^"]*")(\s*\+)?', fv):
    pairs.append((m, lit.strip('"').split("?")[0].split("%s")[0], bool(plus) or lit.endswith('/"')))
for lit in re.findall(r'sse\(\s*"([^"]+)"', fv):
    pairs.append(("GET", lit.split("?")[0], False))

# Declared routes are the STRONGER source: a migrated command has no inline literal,
# so without this the method check would silently stop covering it. Read the table in
# `forge.py` (the one place a CLI route is written) and add every declared pair.
sys.path.insert(0, os.path.join(REPO, "src"))
from longrun.core import forge as _forge                                        # noqa: E402

for _m, _p in sorted(_forge.ROUTES.values()):
    pairs.append((_m, _p.split("?")[0], _p.endswith("/")))

_missing_declared = [(m, p) for m, p in _forge.ROUTES.values()
                     if (m, p.split("?")[0], p.endswith("/")) not in pairs]
check("JAG-CLId every DECLARED route is in the parity pairs (table read, not regex)",
      bool(_forge.ROUTES) and not _missing_declared,
      "declared=%d missing=%s" % (len(_forge.ROUTES), _missing_declared))

# ---- ADR-0006: a CLI route is declared once, in ROUTES -----------------------
# The checks above find route literals wherever they live, so a NEW inline static route
# would sail through them while quietly splitting the truth. Assert the migration is
# COMPLETE instead: no static `req("M", "/…")` or `sse("/…")` remains in the source.
# Paths built at call time (`"/api/runs/" + id`) are not matched, by design — ADR-0006
# keeps those inline until a shape is designed for them. The pattern therefore requires a
# COMPLETE literal (closing quote then `,` or `)`), or the 24 concat sites would trip it.
_inline_req = re.findall(r'req\(\s*"(?:GET|POST|PUT|PATCH|DELETE)"\s*,\s*"/[^"]*"\s*[,)]', fv)
_inline_sse = re.findall(r'sse\(\s*"/[^"]*"\s*[,)]', fv)
check("JAG-CLIf no inline static route remains (ADR-0006: declared once)",
      not _inline_req and not _inline_sse,
      "inline req=%s sse=%s" % (_inline_req[:4], _inline_sse[:4]))


def _methods_for(c, is_pattern):
    got = set(srv_exact.get(c, ()))
    if is_pattern or c.endswith("/"):
        head = c
        for e, ms in srv_exact.items():
            if e.startswith(head):
                got |= ms
    for q, ms in srv_prefix.items():
        if c.startswith(q) or (is_pattern and q.startswith(c)):
            got |= ms
    return got


wrong = []
for m, c, plus in pairs:
    if not c.startswith("/api/") and not c.startswith("/mcp"):
        continue
    got = _methods_for(c, plus)
    if m not in got:
        wrong.append("%s %s (server: %s)" % (m, c, sorted(got)))

check("JAG-CLIe every CLI call uses a served method", not wrong,
      "mismatch=%s" % wrong if wrong else "pairs=%d" % len(pairs))

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
