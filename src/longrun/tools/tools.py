#!/usr/bin/env python3
"""Longrun tool implementations (shell, fs.read, fs.write, git, http, web, browser).

Each `execute(tool, args, run_id)` returns a normalised dict:
    {tool, ok, backend, sandboxed, exit_code, stdout, stderr, duration_ms, ...}

Policy (allowlist / approval) is enforced by the caller (server.py) via
registry.classify(); this module only *runs* an already-permitted action.
"""

import ipaddress
import json
import os
import re
import shlex
import time
import urllib.parse
import urllib.request

from longrun.util import osutil
from longrun.tools import registry
from longrun.tools import sandbox

REPO = registry.REPO


def _truncate(s, n):
    if not isinstance(s, str):
        s = str(s)
    return s if len(s) <= n else s[:n] + "\n…[truncated %d chars]" % (len(s) - n)


def _host_allowed(url, allow_hosts):
    try:
        host = urllib.parse.urlparse(url).hostname or ""
    except Exception:
        return False, "unparseable url"
    if host in allow_hosts:
        return True, host
    for entry in allow_hosts:
        try:  # support CIDR entries like 10.0.0.0/8
            net = ipaddress.ip_network(entry, strict=False)
            if ipaddress.ip_address(host) in net:
                return True, host
        except ValueError:
            continue
    return False, host


# ------------------------------------------------------------------ shell ----

def _shell(args, run_id):
    command = str(args.get("command", ""))
    if not command.strip():
        return {"ok": False, "error": "empty command"}
    # JAG-386/388: honour an explicit working directory. `cwd` is the advertised
    # name (mirrors the `git` tool) and WINS over `workspace`; `workspace` stays
    # supported for back-compat (the chat loop injects the session workspace under
    # that key — the sensible default cwd). A RELATIVE `cwd` resolves against the
    # session workspace, matching the boundary `registry.touches_outside` checks.
    # Validated up front so a bad dir returns a clear error, not a traceback.
    base = args.get("workspace")
    cwd = args.get("cwd")
    if cwd and base and not os.path.isabs(str(cwd)):
        cwd = os.path.join(str(base), str(cwd))
    cwd = cwd or base
    if cwd and not os.path.isdir(cwd):
        return {"ok": False, "error": "cwd not found: %s" % cwd}
    res = sandbox.run(command, run_id=run_id,
                      timeout=args.get("timeout_secs"),
                      workspace=cwd)
    res["ok"] = res.get("exit_code") == 0
    return res


# --------------------------------------------------- JAG-426 baseline tools ---
# Three primitives every standard harness ships that Longrun was missing natively
# (python was only reachable through the external pmcp MCP client).

def _python(args, run_id):
    """Run a Python snippet in the sandbox (native REPL substitute).

    The code is written to a file inside the sandbox workspace and executed as
    `python3 <file>` — no inline quoting, so it works identically under the
    docker and `none` backends (the workspace is /work or the host dir).
    """
    code = str((args or {}).get("code") or "")
    if not code.strip():
        return {"ok": False, "error": "code required"}
    try:
        ws = sandbox.workspace_for(run_id)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "no sandbox workspace: %s" % e}
    name = "_repl_%s.py" % os.urandom(4).hex()
    path = os.path.join(ws, name)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(code)
        res = sandbox.run("python3 " + name, run_id=run_id,
                          timeout=args.get("timeout_secs"), workspace=ws)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    res["ok"] = res.get("exit_code") == 0
    return res


def _process(args, run_id):
    """List or terminate processes (Linux /proc; stdlib only)."""
    import signal
    action = str((args or {}).get("action") or "list").lower()
    if not os.path.isdir("/proc"):
        return {"ok": False, "error": "process management needs /proc (Linux only)"}
    if action in ("kill", "stop", "terminate"):
        try:
            pid = int((args or {}).get("pid"))
        except (TypeError, ValueError):
            return {"ok": False, "error": "pid (int) required for action=kill"}
        if pid <= 1:
            return {"ok": False, "error": "refusing to signal pid %d" % pid}
        if pid == os.getpid():
            return {"ok": False, "error": "refusing to signal the harness itself"}
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError as e:
            return {"ok": False, "error": "kill failed: %s" % e}
        return {"ok": True, "exit_code": 0, "stdout": "sent SIGTERM to %d" % pid,
                "backend": "host", "sandboxed": False}
    # action=list
    match = str((args or {}).get("match") or "").lower()
    try:
        limit = max(1, min(int((args or {}).get("limit") or 40), 500))
    except (TypeError, ValueError):
        limit = 40
    rows = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        pid = int(entry)
        try:
            with open("/proc/%d/cmdline" % pid, "rb") as f:
                cmd = f.read().replace(b"\x00", b" ").decode("utf-8", "replace").strip()
            with open("/proc/%d/statm" % pid, "r", encoding="utf-8") as f:
                rss_pages = int(f.read().split()[1])
        except (OSError, ValueError, IndexError):
            continue
        if not cmd or (match and match not in cmd.lower()):
            continue
        rows.append({"pid": pid, "cmd": cmd[:180], "rss_mb": round(rss_pages * 4096 / 1e6, 1)})
    rows.sort(key=lambda r: -r["rss_mb"])
    lines = ["%7d %8.1f MB  %s" % (r["pid"], r["rss_mb"], r["cmd"]) for r in rows[:limit]]
    return {"ok": True, "exit_code": 0, "count": len(rows), "processes": rows[:limit],
            "stdout": "\n".join(lines) or "(no match)", "backend": "host", "sandboxed": False}


def _glob(args, run_id):
    """List files matching a glob pattern, inside the allowed roots (read-only)."""
    import glob as _g
    pattern = str((args or {}).get("pattern") or "").strip()
    if not pattern:
        return {"ok": False, "error": "pattern required"}
    # An ABSOLUTE pattern makes os.path.join discard `root`, so `{"pattern":
    # "/etc/*"}` listed the whole filesystem regardless of the allow-list. Reject
    # it up front; a `../` pattern is caught by the confinement filter below.
    if os.path.isabs(pattern):
        return {"ok": False,
                "error": "pattern must be RELATIVE to the root (absolute paths escape the allow-list)"}
    try:
        roots = registry.tool_spec("glob")["roots"]
    except Exception:  # noqa: BLE001
        roots = ["."]
    root, err = registry.resolve_path(str((args or {}).get("root") or "."), roots,
                                      base=(args or {}).get("workspace"))
    if err:
        return {"ok": False, "error": err}
    if os.path.isfile(root):
        root = os.path.dirname(root)
    try:
        cap = max(1, min(int((args or {}).get("limit") or 200), 2000))
    except (TypeError, ValueError):
        cap = 200
    hits = []
    root_real = os.path.realpath(root)
    for m in _g.iglob(os.path.join(root, pattern), recursive=True):
        # Confinement: a `../` (or otherwise escaping) pattern may expand outside
        # `root`; keep only real paths that stay inside it. The tool is read-only,
        # but the roots are the advertised boundary — same rule as fs.read.
        if os.path.isfile(m) and registry._under(os.path.realpath(m), root_real):
            hits.append(os.path.relpath(m, root))
            if len(hits) >= cap:
                break
    files = sorted(hits)
    return {"ok": True, "exit_code": 0, "root": root, "count": len(files), "files": files,
            "stdout": "\n".join(files) or "(no match)", "backend": "host", "sandboxed": False}


# ------------------------------------------------------------------- fs ------

def _fs_read(args, run_id):
    roots = registry.tool_spec("fs.read")["roots"]
    path, err = registry.resolve_path(str(args.get("path", "")), roots,
                                      base=args.get("workspace"))
    if err:
        return {"ok": False, "error": err}
    if not os.path.isfile(path):
        return {"ok": False, "error": "no such file: %s" % path}
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read(int(args.get("max_bytes", 65536)))
    return {"ok": True, "path": path, "content": content, "bytes": len(content),
            "backend": "host", "sandboxed": False, "exit_code": 0}


def _journal(run_id, path, before, after, action):
    """JAG-127: record the pre-image so the UI can diff and undo. Never raises."""
    try:
        from longrun.tools import edits
        edits.record(run_id, path, before, after, action)
    except Exception:  # noqa: BLE001 — the journal must never break a write
        pass


def _verify_edit(tool, path, snap, res, args, run_id):
    """JAG-131: 'apply-only-if-green' on fs.write/fs.edit.

    If the verifier is active, it runs the verification command in the sandbox: if
    it fails, the change is rolled back (to the pre-image) and `res` becomes
    a failure with the check error. Never blocks on internal exceptions.
    """
    try:
        from longrun.plan import verify as _v
    except Exception:  # noqa: BLE001
        return res
    try:
        if not _v.should_verify(tool, path):
            return res
    except Exception:  # noqa: BLE001
        return res
    workspace = args.get("workspace") if isinstance(args, dict) else None
    try:
        out, report = _v.verify(tool, path, snap, res, workspace=workspace,
                               run_id=run_id)
    except Exception as e:  # noqa: BLE001 — the verifier must never break a write
        return res
    try:
        from longrun.core import server
        server.publish("verify.run", run=run_id, tool=tool, path=path, **report)
    except Exception:  # noqa: BLE001
        pass
    return out


def _fs_write(args, run_id):
    spec = registry.tool_spec("fs.write")
    roots = spec["roots"]
    path, err = registry.resolve_path(str(args.get("path", "")), roots,
                                      base=args.get("workspace"))
    if err:
        return {"ok": False, "error": err}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    content = str(args.get("content", ""))
    append = bool(args.get("append"))
    existed = os.path.isfile(path)
    before = ""
    if existed:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            before = f.read()
    with open(path, "a" if append else "w", encoding="utf-8") as f:
        f.write(content)
    after = (before + content) if append else content
    _journal(run_id, path, before, after, "modified" if existed else "created")
    res = {"ok": True, "path": path, "bytes": len(content), "append": append,
           "backend": "host", "sandboxed": False, "exit_code": 0}
    return _verify_edit("fs.write", path, {"exists": existed, "content": before},
                        res, args, run_id)


def _fs_edit(args, run_id):
    """Surgical edit: replace exact search text with replacement text."""
    spec = registry.tool_spec("fs.edit")
    path, err = registry.resolve_path(str(args.get("path", "")), spec["roots"],
                                      base=args.get("workspace"))
    if err:
        return {"ok": False, "error": err}
    if not os.path.isfile(path):
        return {"ok": False, "error": "no such file: %s" % path}
    search = str(args.get("search", ""))
    replace = str(args.get("replace", ""))
    if not search:
        return {"ok": False, "error": "empty search string"}
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    count = content.count(search)
    if count == 0:
        return {"ok": False, "error": "search text not found in %s" % path}
    if count > 1 and not args.get("replace_all"):
        return {"ok": False, "error": ("search text matches %d times in %s; "
                                        "pass replace_all=true or use a more "
                                        "specific search") % (count, path)}
    n = count if args.get("replace_all") else 1
    new = content.replace(search, replace, n)
    with open(path, "w", encoding="utf-8") as f:
        f.write(new)
    _journal(run_id, path, content, new, "modified")
    res = {"ok": True, "path": path, "replacements": n, "bytes_before": len(content),
           "bytes_after": len(new), "backend": "host", "sandboxed": False,
           "exit_code": 0}
    return _verify_edit("fs.edit", path, {"exists": True, "content": content},
                        res, args, run_id)


# ------------------------------------------------------------------ git ------

def _git(args, run_id):
    raw = str(args.get("args", "")).strip()
    try:
        argv = shlex.split(raw)
    except ValueError as e:
        return {"ok": False, "error": "bad git args: %s" % e}
    if not argv:
        return {"ok": False, "error": "empty git args"}
    cwd = args.get("cwd") or args.get("workspace") or REPO
    if not os.path.isdir(cwd):
        return {"ok": False, "error": "cwd not found: %s" % cwd}
    t0 = time.time()
    import subprocess
    try:
        p = subprocess.run(["git"] + argv, cwd=cwd, capture_output=True, text=True, timeout=25)
        return {"ok": p.returncode == 0, "exit_code": p.returncode,
                "stdout": p.stdout, "stderr": p.stderr, "cwd": cwd,
                "duration_ms": int((time.time() - t0) * 1000),
                "backend": "host(git)", "sandboxed": False}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "git failed: %s" % e, "exit_code": 125}


# ----------------------------------------------------------------- http ------

def _http_fetch(url, allow_hosts, max_bytes, method="GET"):
    ok, host = _host_allowed(url, allow_hosts)
    if not ok:
        return None, "host %r not in allow_hosts %s" % (host, allow_hosts)
    req = urllib.request.Request(url, method=method,
                                 headers={"User-Agent": "Longrun/0.2 (+harness)"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read(max_bytes).decode("utf-8", "replace")
            return {"status": resp.status, "body": body, "host": host,
                    "duration_ms": int((time.time() - t0) * 1000)}, None
    except Exception as e:  # noqa: BLE001
        return None, "fetch failed: %s" % e


def _http(args, run_id):
    spec = registry.tool_spec("http")
    data, err = _http_fetch(str(args.get("url", "")), spec["allow_hosts"],
                            int(args.get("max_bytes", 32768)), args.get("method", "GET"))
    if err:
        return {"ok": False, "error": err, "backend": "host(http)", "sandboxed": False}
    body = _truncate(data["body"], 8192)
    return {"ok": True, "exit_code": 0, "stdout": "HTTP %s (%s)\n%s" % (
        data["status"], data["host"], body), "stderr": "",
        "status": data["status"], "bytes": len(data["body"]),
        "duration_ms": data["duration_ms"], "backend": "host(http)", "sandboxed": False}


def _browser(args, run_id):
    spec = registry.tool_spec("browser")
    if not spec["enabled"]:
        return {"ok": False, "error": "browser tool is disabled (set enabled: true in config/tools.yaml)"}
    data, err = _http_fetch(str(args.get("url", "")), spec["allow_hosts"],
                            int(args.get("max_bytes", 32768)))
    if err:
        return {"ok": False, "error": err, "backend": "host(browser)", "sandboxed": False}
    html = data["body"]
    html = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = re.sub(r"&nbsp;?", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    return {"ok": True, "exit_code": 0, "stdout": _truncate(text, 8192), "stderr": "",
            "status": data["status"], "bytes": len(html), "backend": "host(browser)",
            "sandboxed": False, "note": "lightweight HTML->text extractor, not a headless browser"}


# ------------------------------------------------------------------ web ------

_WEB_UA = "Mozilla/5.0 (X11; Linux aarch64) Longrun/0.7 (+harness)"
_HERMES_ENV = os.path.expanduser("~/.hermes/.env")


def _secret(name):
    """Env var, falling back to ~/.hermes/.env (the DGX's shared secret store)."""
    val = os.environ.get(name)
    if val and val.strip():
        return val.strip()
    try:
        with open(_HERMES_ENV, "r", encoding="utf-8", errors="replace") as f:
            for ln in f:
                m = re.match(r"\s*(?:export\s+)?%s\s*=\s*(.*)$" % re.escape(name), ln)
                if m:
                    v = m.group(1).strip().strip('"').strip("'")
                    if v:
                        return v
    except OSError:
        pass
    return None


def _strip_html(s):
    s = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", s or "")
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    for a, b in (("&nbsp;", " "), ("&amp;", "&"), ("&quot;", '"'),
                 ("&#x27;", "'"), ("&#39;", "'"), ("&lt;", "<"), ("&gt;", ">")):
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip()


def _public_host(url):
    """SSRF guard for `web`: only public http(s) hosts are reachable."""
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:  # noqa: BLE001
        return False, "unparseable url"
    if parsed.scheme not in ("http", "https"):
        return False, "only http/https is allowed"
    host = parsed.hostname or ""
    if not host:
        return False, "no host in url"
    if host.lower() in ("localhost", "localhost.localdomain"):
        return False, "localhost is not allowed"
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return False, "private/loopback address %s is not allowed" % host
    except ValueError:
        pass  # a DNS name -> allowed
    return True, host


def _web_search(query, n):
    """Tavily/Brave when a key is present, else the keyless DuckDuckGo HTML page."""
    n = max(1, min(int(n or 5), 10))
    if not query.strip():
        return None, "empty query"
    tav = _secret("TAVILY_API_KEY")
    if tav:
        try:
            payload = json.dumps({"api_key": tav, "query": query,
                                  "max_results": n}).encode("utf-8")
            req = urllib.request.Request("https://api.tavily.com/search", data=payload,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=25) as r:
                data = json.loads(r.read().decode("utf-8", "replace"))
            res = [{"title": it.get("title", ""), "url": it.get("url", ""),
                    "snippet": _strip_html(it.get("content", ""))[:300]}
                   for it in (data.get("results") or [])]
            if res:
                return res, "tavily"
        except Exception:  # noqa: BLE001
            pass
    brave = _secret("BRAVE_API_KEY")
    if brave:
        try:
            u = ("https://api.search.brave.com/res/v1/web/search?q="
                 + urllib.parse.quote(query) + "&count=%d" % n)
            req = urllib.request.Request(u, headers={"Accept": "application/json",
                                                     "X-Subscription-Token": brave})
            with urllib.request.urlopen(req, timeout=25) as r:
                data = json.loads(r.read().decode("utf-8", "replace"))
            res = [{"title": it.get("title", ""), "url": it.get("url", ""),
                    "snippet": _strip_html(it.get("description", ""))[:300]}
                   for it in ((data.get("web") or {}).get("results") or [])]
            if res:
                return res, "brave"
        except Exception:  # noqa: BLE001
            pass
    u = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
    req = urllib.request.Request(u, headers={"User-Agent": _WEB_UA,
                                             "Accept-Language": "it,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=25) as r:
        html = r.read(500000).decode("utf-8", "replace")
    links = re.findall(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html, re.S)
    snips = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', html, re.S)
    res = []
    for i, (href, title) in enumerate(links[:n]):
        if "uddg=" in href:
            found = re.search(r"uddg=([^&]+)", href)
            if found:
                href = urllib.parse.unquote(found.group(1))
        res.append({"title": _strip_html(title), "url": href,
                    "snippet": _strip_html(snips[i])[:300] if i < len(snips) else ""})
    return res, "duckduckgo"


def _web_fetch(url, max_bytes):
    """Readable page text: try the keyless r.jina.ai reader, else direct HTML->text."""
    if not re.match(r"^https?://", url):
        url = "https://" + url
    ok, host = _public_host(url)
    if not ok:
        return None, host
    try:
        req = urllib.request.Request("https://r.jina.ai/" + url,
                                     headers={"User-Agent": _WEB_UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            text = r.read(max_bytes).decode("utf-8", "replace")
        if text.strip():
            return {"url": url, "text": text, "via": "jina", "host": host}, None
    except Exception:  # noqa: BLE001
        pass
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _WEB_UA})
        with urllib.request.urlopen(req, timeout=25) as r:
            raw = r.read(max_bytes).decode("utf-8", "replace")
        return {"url": url, "text": _strip_html(raw), "via": "direct", "host": host}, None
    except Exception as e:  # noqa: BLE001
        return None, "fetch failed: %s" % e


def _web(args, run_id):
    """Harness-native public-internet tool: search + fetch (read-only)."""
    action = (args.get("action") or "search").strip().lower()
    t0 = time.time()
    if action in ("fetch", "get", "read"):
        url = str(args.get("url") or args.get("query") or "").strip()
        if not url:
            return {"ok": False, "error": "url required for action=fetch",
                    "backend": "host(web)", "sandboxed": False}
        data, err = _web_fetch(url, int(args.get("max_bytes", 8192)))
        if err:
            return {"ok": False, "error": err, "backend": "host(web)", "sandboxed": False}
        return {"ok": True, "exit_code": 0, "stderr": "", "stdout": _truncate(data["text"], 8192),
                "url": data["url"], "via": data["via"],
                "duration_ms": int((time.time() - t0) * 1000),
                "backend": "host(web)", "sandboxed": False}
    query = str(args.get("query") or "").strip()
    try:
        results, engine = _web_search(query, args.get("max_results", 5))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "search failed: %s" % e,
                "backend": "host(web)", "sandboxed": False}
    if not results:
        return {"ok": False, "error": "no results for %r" % query, "engine": engine,
                "backend": "host(web)", "sandboxed": False}
    lines = ["%d. %s\n   %s\n   %s" % (i + 1, r["title"], r["url"], r["snippet"])
             for i, r in enumerate(results)]
    return {"ok": True, "exit_code": 0, "stderr": "", "engine": engine,
            "count": len(results), "stdout": _truncate("\n".join(lines), 8192),
            "results": results, "duration_ms": int((time.time() - t0) * 1000),
            "backend": "host(web)", "sandboxed": False}


def _skills(args, run_id):
    """Skills registry: list, SEARCH, or read one SKILL.md."""
    from longrun.memory import skills as skills_mod
    action = str(args.get("action", "list"))
    if action == "read":
        name = str(args.get("name", ""))
        got = skills_mod.get_skill(name)
        if got is None:
            avail = ", ".join(s["name"] for s in skills_mod.list_skills())
            return {"ok": False, "error": "skill %r not found; available: %s"
                    % (name, avail), "stdout": "", "stderr": ""}
        content = got.pop("content")
        return {"ok": True, "exit_code": 0, "stdout": content, "stderr": "",
                "skill": got, "backend": "host", "sandboxed": False}
    if action in ("search", "find"):
        # JAG-198: progressive discovery — find the ONE relevant skill by keyword
        # without loading the whole (large) library into context.
        q = str(args.get("query") or args.get("q") or "").strip()
        if not q:
            return {"ok": False, "error": "query required for action=search",
                    "stdout": "", "stderr": ""}
        try:
            limit = int(args.get("limit") or 10)
        except (TypeError, ValueError):
            limit = 10
        hits = skills_mod.search_skills(q, limit=limit)
        body = "\n".join("  %s :: %s" % (h["name"], (h["description"] or h["title"] or "")[:120])
                         for h in hits) or "  (no match — try action=list)"
        stdout = ("%d skill(s) matching %r (read one with action=read):\n%s"
                  % (len(hits), q, body))
        return {"ok": True, "exit_code": 0, "stdout": stdout, "stderr": "",
                "count": len(hits), "matches": [h["name"] for h in hits],
                "backend": "host", "sandboxed": False}
    if action in ("audit", "health", "dupes"):
        # JAG-203: read-only health report of the skill library (duplicates,
        # missing descriptions, oversized SKILL.md). Never deletes anything.
        rep = skills_mod.audit_skills()
        lines = ["%d skills | %d duplicate-description group(s) | %d near-duplicate "
                 "name pair(s) | %d missing description | %d oversized (SKILL.md>20KB)"
                 % (rep["count"], len(rep["duplicate_descriptions"]),
                    len(rep["near_duplicate_names"]), len(rep["missing_description"]),
                    len(rep["oversized"]))]
        for _d, _ns in list(rep["duplicate_descriptions"].items())[:6]:
            lines.append("  same description: %s" % ", ".join(_ns))
        for _pair in rep["near_duplicate_names"][:6]:
            lines.append("  near names: %s" % " ~ ".join(_pair))
        if rep["missing_description"]:
            lines.append("  no description: %s" % ", ".join(rep["missing_description"][:8]))
        return {"ok": True, "exit_code": 0, "stdout": "\n".join(lines), "stderr": "",
                "count": rep["count"], "report": rep, "backend": "host", "sandboxed": False}
    skills = skills_mod.list_skills()
    lines = []
    cats = {}
    for s in skills:
        cats.setdefault(s["category"], []).append(s)
    for cat in sorted(cats):
        lines.append("[%s]" % cat)
        for s in cats[cat]:
            lines.append("  %s :: %s" % (s["name"], (s["description"] or s["title"])[:120]))
    stdout = ("%d skills from %s (read one with the skills tool, "
              "action=read):\n%s" % (len(skills), skills_mod.SKILLS_DIR,
                                       "\n".join(lines)))
    return {"ok": True, "exit_code": 0, "stdout": stdout, "stderr": "",
            "count": len(skills), "backend": "host", "sandboxed": False}


def _self(args, run_id):
    """v0.5 self-knowledge: paths, config, docs, systemd state, extension recipe.

    JAG-426: `action` (default "info") adds DYNAMIC self-diagnosis with no new
    tool name and no PMC dependency — diagnose | logs | context | tools.
    """
    import subprocess as sp
    action = str((args or {}).get("action", "info") or "info").strip().lower()
    # JAG-347: report the LIVE version, not a stale hardcoded string - a wrong
    # self-report is exactly the kind of misleading guidance this review targets.
    try:
        from longrun.core import server as _srv
        _version = str(getattr(_srv, "VERSION", "unknown"))
    except Exception:  # noqa: BLE001
        _version = "unknown"
    info = {
        "ok": True, "backend": "host", "sandboxed": False, "exit_code": 0,
        "name": "Longrun", "version": _version,
        "repo_path": REPO,
        "data_dir": os.path.join(REPO, "data"),
        "sessions_dir": os.path.join(REPO, "data", "sessions"),
        "webui": os.path.join(REPO, "webui"),
        "entrypoint": os.path.join(REPO, "server.py"), "port": 8790,
        "router": os.environ.get("LONGRUN_ROUTER", "http://127.0.0.1:8080"),
        "config": {"tools": os.path.join(REPO, "config", "tools.yaml"),
                   "tools_overlay": os.path.join(REPO, "data", "tools.overlay.yaml"),
                   "routing": os.path.join(REPO, "config", "routing.yaml"),
                   "mcp_clients": os.path.join(REPO, "config", "mcp_clients.yaml")},
        "docs": {"plan": os.path.join(REPO, "docs", "PLAN.md"),
                 "readme": os.path.join(REPO, "README.md"),
                 "architecture": os.path.join(REPO, "docs", "ARCHITECTURE.md")},
        "service": {"unit": "longrun.service", "scope": "user",
                    "unit_file": os.path.join(REPO, "deploy", "longrun.service"),
                    "restart_cmd": osutil.service_hint()},
        "skills_dir": os.path.join(REPO, "skills"),
        "install_skill": (
            "A skill is a directory with a SKILL.md. Drop/clone it into a "
            "category under skills/ (e.g. skills/ops/<name>/SKILL.md), or symlink "
            "an existing distribution dir: `ln -sfn <source-dir> skills/<cat>`. "
            "Skills are picked up automatically by the `skills` tool (no reload "
            "needed). External MCP servers: add an entry to "
            "config/mcp_clients.yaml with either command+args (stdio) or url "
            "(HTTP); tools are discovered via tools/list and exposed as "
            "<client>__<tool> in the registry. Harness-native tools go in "
            "registry.TOOL_SCHEMAS + tools.py with policy in config/tools.yaml. "
            "Apply with POST /api/tools (reload) or restart: %s."
        ) % osutil.service_hint(),
    }
    try:
        from longrun.memory import skills as skills_mod
        sk = skills_mod.list_skills()
        info["skills"] = {"dir": info["skills_dir"], "count": len(sk),
                          "categories": sorted({s["category"] for s in sk})}
    except Exception as e:  # noqa: BLE001
        info["skills"] = {"error": str(e)}
    try:
        if osutil.IS_POSIX:
            out = sp.run(["systemctl", "--user", "is-active", "longrun.service"],
                         capture_output=True, text=True, timeout=4).stdout.strip()
            info["service"]["active"] = out or "unknown"
        else:
            info["service"]["active"] = "n/a (no systemd on this host)"
    except Exception:
        info["service"]["active"] = "unknown"
    # JAG-426: on-demand dynamic diagnosis. Every branch is additive: the static
    # info above always ships, so the model never loses the paths/recipe it had.
    if action not in ("info", ""):
        from longrun.tools import diag as diag_mod
        if action in ("diagnose", "health"):
            info["diagnose"] = diag_mod.health()
        elif action in ("logs", "log", "history"):
            info["logs"] = diag_mod.log_tail(session=(args or {}).get("session") or run_id,
                                             limit=(args or {}).get("limit") or 100,
                                             kind=(args or {}).get("kind"))
        elif action in ("context", "ctx"):
            info["context"] = diag_mod.context((args or {}).get("session") or run_id)
        elif action in ("tools", "tooling"):
            info["tools"] = diag_mod.tools_report()
        else:
            info["error"] = ("unknown action %r — use info|diagnose|logs|context|tools" % action)
    info["action"] = action
    return info


def _memory(args, run_id):
    """Agent memory (JAG-73): store a durable note, or recall/search memories.

    action=store   {content, kind?, source?, ttl_secs?} → append-only record
    action=recall  {query, kind?, limit?, include_invalid?} → search
    action=recent  {kind?, limit?}             → newest first
    action=core    {}                          → read the always-visible CORE block
    action=set_core {content}                  → rewrite the CORE block (JAG-127f)
    action=invalidate {target|query, reason?}  → tombstone a wrong/outdated memory (JAG-204)
    action=forget  {target|query}              → PERMANENTLY delete (true compaction, JAG-317)
    action=purge   {}                          → physically drop invalidated/expired records
    action=health  {}                          → expired / invalidated / no-source counts

    Closes a real gap: the store existed and was auto-injected, but the agent had
    NO tool to deliberately remember or recall anything.
    """
    from longrun.memory import memory as mem
    action = (args.get("action") or "recall").strip().lower()
    limit = int(args.get("limit") or (10 if action == "recent" else 5))
    if action in ("core", "core_read", "read_core"):
        txt = mem.core_read().strip()
        return {"ok": True, "count": 1 if txt else 0,
                "stdout": txt or "(core memory is empty)", "backend": "host",
                "sandboxed": False}
    if action in ("set_core", "core_write", "write_core"):
        content = (args.get("content") or "").strip()
        if not content:
            return {"ok": False, "error": "content required for action=set_core",
                    "backend": "host", "sandboxed": False}
        res = mem.core_write(content)
        return {"ok": True, "count": 1,
                "stdout": "core memory updated (%d chars)" % res.get("chars", len(content)),
                "backend": "host", "sandboxed": False}
    if action == "store":
        content = (args.get("content") or "").strip()
        if not content:
            return {"ok": False, "error": "content required for action=store",
                    "backend": "host", "sandboxed": False}
        kind = (args.get("kind") or "memory.store").strip()
        meta = {"session": run_id or "", "source": str(args.get("source") or "agent")}
        # JAG-204: optional expiry (ttl_secs) — a memory can be time-bounded.
        try:
            ttl = float(args.get("ttl_secs") or args.get("ttl") or 0)
        except (TypeError, ValueError):
            ttl = 0.0
        if ttl > 0:
            meta["expires_ts"] = round(time.time() + ttl, 3)
        rec = mem.store(kind, content, **meta)
        return {"ok": True, "count": 1, "mid": rec.get("mid"),
                "stdout": "stored %d chars as %s (id=%s)"
                          % (len(content), kind, rec.get("mid")),
                "backend": "host", "sandboxed": False}
    if action in ("forget", "purge", "erase", "delete"):
        # JAG-317: a TRUE delete — physically compact the store. `invalidate`
        # below stays a soft, append-only tombstone (the audit trail is kept).
        target = str(args.get("target") or args.get("id") or "").strip()
        query = str(args.get("query") or "").strip()
        if action == "purge" or (not target and not query):
            res = mem.purge_invalidated()
            return {"ok": True, "count": res.get("removed", 0),
                    "stdout": "purged %d invalidated/expired memory(ies)"
                              % res.get("removed", 0),
                    "backend": "host", "sandboxed": False}
        if target:
            res = mem.forget(target)
            return {"ok": True, "count": res.get("removed", 0),
                    "stdout": "forgot %s (%d record removed)"
                              % (target, res.get("removed", 0)),
                    "backend": "host", "sandboxed": False}
        ids = [r.get("mid") for _s, r in mem.search(query, args.get("kind"), 20, True)
               if r.get("mid")]
        removed = sum(mem.forget(i).get("removed", 0) for i in ids)
        return {"ok": True, "count": removed,
                "stdout": "forgot %d memory(ies): %s" % (removed, ", ".join(ids)),
                "backend": "host", "sandboxed": False}
    if action in ("invalidate", "retract"):
        # JAG-204: retire a memory you know is wrong/outdated (append-only tombstone).
        target = str(args.get("target") or args.get("id") or "").strip()
        reason = str(args.get("reason") or "").strip()
        if not target:
            q = (args.get("query") or "").strip()
            if not q:
                return {"ok": False,
                        "error": "target or query required for action=invalidate",
                        "backend": "host", "sandboxed": False}
            ids = [r.get("mid") for _s, r in mem.search(q, args.get("kind"), 20, True)
                   if r.get("mid")]
            for i in ids:
                mem.invalidate(i, reason=reason or ("query:" + q))
            return {"ok": True, "count": len(ids),
                    "stdout": "invalidated %d memory(ies): %s" % (len(ids), ", ".join(ids)),
                    "backend": "host", "sandboxed": False}
        mem.invalidate(target, reason=reason)
        return {"ok": True, "count": 1, "stdout": "invalidated %s" % target,
                "backend": "host", "sandboxed": False}
    if action in ("health", "audit"):
        h = mem.health()
        return {"ok": True, "count": h["total"], "report": h,
                "stdout": ("memory: %d records (%d stores) | %d expired | "
                           "%d invalidated | %d no-source"
                           % (h["total"], h["stores"], h["expired"],
                              h["invalidated"], h["no_source"])),
                "backend": "host", "sandboxed": False}
    include_invalid = bool(args.get("include_invalid"))
    try:
        if action == "recent":
            hits = [(1.0, r) for r in mem.query("", args.get("kind"), limit)]
        else:
            query = (args.get("query") or "").strip()
            if not query:
                return {"ok": False, "error": "query required for action=recall",
                        "backend": "host", "sandboxed": False}
            hits = mem.search(query, args.get("kind"), limit, True)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "memory lookup failed: %s" % e,
                "backend": "host", "sandboxed": False}
    if not include_invalid:
        bad = mem.invalid_targets()
        now = time.time()
        hits = [(s, r) for s, r in hits if mem.is_valid(r, now=now, invalid=bad)]
    lines = ["- (%s, %.2f) %s" % (r.get("kind"), s, (r.get("content") or "")[:200])
             for s, r in hits]
    return {"ok": True, "count": len(hits), "stdout": "\n".join(lines) or "(no memories)",
            "backend": "host", "sandboxed": False}


def _diff(args, run_id):
    """Native diff tool: unified diff of two files (roots-checked) or two texts."""
    import difflib
    action = str(args.get("action") or "files").strip().lower()
    ctx = int(args.get("context", 3))
    if action == "text":
        a = str(args.get("text_a", ""))
        b = str(args.get("text_b", ""))
        label_a, label_b = "a", "b"
    else:
        roots = registry.tool_spec("fs.read")["roots"]
        pa, err = registry.resolve_path(str(args.get("a", "")), roots)
        if err:
            return {"ok": False, "error": err, "backend": "host", "sandboxed": False}
        pb, err = registry.resolve_path(str(args.get("b", "")), roots)
        if err:
            return {"ok": False, "error": err, "backend": "host", "sandboxed": False}
        if not os.path.isfile(pa):
            return {"ok": False, "error": "no such file: %s" % pa,
                    "backend": "host", "sandboxed": False}
        if not os.path.isfile(pb):
            return {"ok": False, "error": "no such file: %s" % pb,
                    "backend": "host", "sandboxed": False}
        with open(pa, "r", encoding="utf-8", errors="replace") as f:
            a = f.read()
        with open(pb, "r", encoding="utf-8", errors="replace") as f:
            b = f.read()
        label_a, label_b = pa, pb
    diff = list(difflib.unified_diff(a.splitlines(), b.splitlines(),
                                     fromfile=label_a, tofile=label_b, n=ctx, lineterm=""))
    added = sum(1 for ln in diff if ln.startswith("+") and not ln.startswith("+++"))
    removed = sum(1 for ln in diff if ln.startswith("-") and not ln.startswith("---"))
    return {"ok": True, "exit_code": 0, "stderr": "", "identical": not diff,
            "added": added, "removed": removed,
            "stdout": _truncate("\n".join(diff) if diff else "(identical)", 8192),
            "backend": "host", "sandboxed": False}


def _improve(args, run_id=None):
    """Register a self-improvement proposal (skill/rules).

    scope=mine (JAG-133/135): self-evolving works on the tool sequences
    actually observed. action:
      - mine   (default) -> mine the history and deposit a DRAFT per pattern;
      - evolve           -> stage 2: draft -> synth -> verify in sandbox ->
                            archive (only if green, write-gate);
      - verify           -> run the check of a proposal (`path`);
      - promote          -> archive a verified proposal (`path`).
    """
    from longrun.util import improve
    args = args or {}
    scope = str(args.get("scope", "")).strip()
    action = str(args.get("action", "propose") or "propose").strip()
    content = str(args.get("content", "")).strip()
    if scope == "mine":
        from longrun.util import selfevolve
        out = os.path.join(registry.REPO, "data", "proposals", "skills")
        path = str(args.get("path", "") or "").strip()

        def _pub(ev, **kw):
            try:
                from longrun.core import server as _srv
                _srv.publish(ev, **kw)
            except Exception:  # noqa: BLE001 — an event must never break the tool
                pass

        if action == "verify":
            if not path:
                return {"error": "path required for action=verify"}
            rep = selfevolve.verify(path)
            _pub("improve.verify", path=path, green=bool(rep.get("green")))
            return {"ok": True, "verify": rep}
        if action == "promote":
            if not path:
                return {"error": "path required for action=promote"}
            res = selfevolve.promote(path)
            if res.get("ok"):
                _pub("improve.archived", name=res.get("name"), rel=res.get("rel"))
            return res
        if action == "evolve":
            c = selfevolve.cfg()
            reports = []
            for cand in selfevolve.mine(selfevolve.history(), c):
                rep = selfevolve.pipeline(cand["pattern"], out, cand["support"])
                green = bool((rep.get("verify") or {}).get("green"))
                reports.append({"pattern": cand["pattern"], "green": green,
                                "archived": rep.get("archived")})
                _pub("improve.evolve", pattern=cand["pattern"], green=green)
            return {"ok": True, "evolved": len(reports), "reports": reports}
        try:
            paths = selfevolve.mine_history(out, note=str(args.get("reason", "")))
        except Exception as e:  # noqa: BLE001
            return {"error": "mine failed: %s" % e}
        recs = []
        for p in paths:
            rec = {"scope": "skill", "path": p, "status": "proposed",
                   "reason": "repeated tool pattern detected (selfevolve)"}
            recs.append(rec)
            _pub("improve.proposal", **rec)
        return {"ok": True, "mined": len(recs), "proposals": recs}
    if scope not in ("skill", "project", "global") or not content:
        return {"error": "scope in {skill,project,global,mine} and content required"}
    if improve.AGENT_WRITE.get(scope) == "forbidden":
        return {"error": "scope not writable"}
    rec = improve.propose(scope, content, reason=str(args.get("reason", "")))
    try:
        from longrun.core import server as _srv
        _srv.publish("improve.proposal", **rec)
    except Exception:  # noqa: BLE001 — the event must never break the tool
        pass
    return {"ok": True, "proposal": rec}


def _reconcile(args, run_id):
    """JAG-263: agent-callable recovery of sessions orphaned by a hard restart."""
    try:
        from longrun.core import server
        sid = (args.get("session") or "").strip() or None
        n = server.reconcile_orphan_turns(session=sid)
        return {"ok": True, "reconciled": n, "session": sid,
                "observation": "reconciled %d session(s)" % n}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "reconcile failed: %s" % e}


def _hms(ts):
    """Clock label (HH:MM:SS) for a stored epoch timestamp; '--:--:--' if invalid."""
    try:
        return time.strftime("%H:%M:%S", time.localtime(float(ts)))
    except (TypeError, ValueError, OSError):
        return "--:--:--"


def _render_transcript(sess, limit=30, tail=False):
    """Flatten one session into an ordered, model-readable log.

    Merges the three side stores by timestamp: `messages` (the real turns),
    `tool_cards` (every tool call + result) and `injects` (harness steering that
    never reaches the model). Without this the coordinator could only see raw
    JSON — unusable in context — so "why is coder 1 failing" stayed unanswerable.
    """
    evs = []
    for m in sess.get("messages", []) or []:
        evs.append((m.get("ts") or 0,
                    "%s: %s" % (str(m.get("role", "?")).upper(),
                                _truncate(str(m.get("content", "")).strip(), 2000))))
    for c in sess.get("tool_cards", []) or []:
        body = c.get("error") or c.get("result") or ""
        ec = c.get("exit_code")
        bad = (not c.get("ok")) or (isinstance(ec, int) and ec != 0)
        label = "FAIL" if bad else "ok"
        if isinstance(ec, int):
            label += " exit=%d" % ec
        evs.append((c.get("ts") or 0,
                    "TOOL %s(%s) -> %s\n    %s"
                    % (c.get("tool"), _truncate(str(c.get("args", "")), 200),
                       label, _truncate(str(body).strip(), 700))))
    for j in sess.get("injects", []) or []:
        evs.append((j.get("ts") or 0,
                    "HARNESS(%s): %s" % (j.get("kind"),
                                         _truncate(str(j.get("text", "")).strip(), 600))))
    evs.sort(key=lambda x: x[0])
    evs = (evs[-limit:] if tail else evs[:limit])
    head = ("session %s | job=%s | workspace=%s | %d message(s), %d tool card(s), "
            "%d harness note(s)\n"
            % (sess.get("id"), sess.get("job") or "-", sess.get("workspace") or "-",
               len(sess.get("messages", []) or []), len(sess.get("tool_cards", []) or []),
               len(sess.get("injects", []) or [])))
    body = "\n".join("%s  %s" % (_hms(e[0]), e[1]) for e in evs) or "  (empty transcript)"
    return _truncate(head + body, 24000)


def _sessions(args, run_id):
    """JAG-350: read-only view of OTHER sessions — the coordinator's missing eye.

    The Master could delegate a subjob to a teammate but had NO tool to look at
    that teammate's chat: no DISCOVERY (which session is 'coder 1'?) and no clean
    transcript (raw `data/sessions/*.json` is unusable in context). So "understand
    why coder 1 is failing and help it" was impossible. This tool closes both
    gaps: `action=list` maps sessions to agent names, `action=read` renders the
    full transcript (messages + tool calls + harness injections).
    """
    from longrun.core import server
    action = str(args.get("action", "list") or "list").strip().lower()
    if action in ("read", "get", "show", "transcript"):
        sid = str(args.get("session") or args.get("id") or "").strip()
        if not sid:
            return {"ok": False, "stdout": "", "stderr": "",
                    "error": "session id required for action=read (use action=list "
                             "to find the session first)",
                    "backend": "host", "sandboxed": False}
        sess = server.load_session(sid)
        if not sess:
            return {"ok": False, "stdout": "", "stderr": "",
                    "error": "no such session: %s" % sid,
                    "backend": "host", "sandboxed": False}
        try:
            limit = int(args.get("limit") or 30)
        except (TypeError, ValueError):
            limit = 30
        limit = max(1, min(limit, 400))
        text = _render_transcript(sess, limit=limit, tail=bool(args.get("tail")))
        return {"ok": True, "exit_code": 0, "stdout": text, "stderr": "",
                "session": sid, "backend": "host", "sandboxed": False}
    # action=list — every session, annotated with its agent name when it has one
    try:
        from longrun.agent import agents as agents_mod
        amap = {a.get("session"): (a.get("name") or a.get("id"))
                for a in agents_mod.REGISTRY.list()["agents"] if a.get("session")}
    except Exception:  # noqa: BLE001 — the list must survive a registry hiccup
        amap = {}
    q = str(args.get("query") or "").strip().lower()
    rows = server.list_sessions()
    if q:
        rows = [r for r in rows
                if q in str(r.get("id", "")).lower()
                or q in str(r.get("title", "")).lower()
                or q in str(amap.get(r.get("id")) or "").lower()]
    try:
        limit = int(args.get("limit") or 30)
    except (TypeError, ValueError):
        limit = 30
    lines = []
    for r in rows[:max(1, limit)]:
        lines.append("  %s | agent=%s | %s | msgs=%s | %s%s"
                     % (r.get("id"), amap.get(r.get("id")) or "-",
                        (r.get("title") or "")[:48], r.get("messages"),
                        r.get("age") or "", " | RUNNING" if r.get("running") else ""))
    stdout = ("%d session(s)%s (read one with action=read, session=<id>):\n%s"
              % (len(rows), (" matching %r" % q) if q else "",
                 "\n".join(lines) or "  (none)"))
    return {"ok": True, "exit_code": 0, "stdout": stdout, "stderr": "",
            "count": len(rows), "backend": "host", "sandboxed": False}


def _index(args, run_id):
    """JAG-400: the CODEBASE index for the CURRENT workspace (per path).

    action=search -> top chunks as path:line + snippet. action=reindex -> rebuild the
    workspace index. action=status -> counts. bm25 always; semantic when an embed model
    is set. Scoped to the workspace folder (like project rules), never global.
    """
    from longrun.memory import codeindex as ci
    from longrun.memory import rules as rules_mod
    args = args or {}
    ws = args.get("workspace") or rules_mod.get_workspace()
    action = (args.get("action") or "search").lower()
    if action == "status":
        return {"ok": True, "exit_code": 0, "workspace": ws,
                "stdout": "codebase[%s]: %s" % (ws, ci.status(ws))}
    if action in ("reindex", "build"):
        st = ci.build(ws, force=bool(args.get("force")))
        return {"ok": True, "exit_code": 0, "workspace": ws, "files": st.get("files"),
                "chunks": st.get("chunks"),
                "stdout": "indexed %s files / %s chunks" % (st.get("files"), st.get("chunks"))}
    query = args.get("query") or args.get("q") or ""
    if not str(query).strip():
        return {"ok": False, "exit_code": 1, "error": "query required for action=search"}
    try:
        k = int(args.get("k") or 8)
    except (TypeError, ValueError):
        k = 8
    if not ws:
        return {"ok": False, "exit_code": 1, "error": "no workspace set for this session"}
    # JAG-415: refresh the index first (incremental; waits for any build already
    # running) so the agent searches fresh code and never a half-built index.
    ci.ensure_fresh(ws)
    res = ci.search(ws, query, k=k, kind=args.get("kind"))
    lines = ["%s:%s  %s" % (r["path"], r["start"],
                            (r.get("snippet") or "").replace("\n", " ")[:200])
             for r in res.get("results", [])]
    return {"ok": True, "exit_code": 0, "workspace": ws,
            "stdout": "\n".join(lines) or "(no matches)",
            "results": res.get("results", []), "mode": res.get("mode"),
            "count": len(res.get("results", []))}


def _knowledge(args, run_id):
    """JAG-401: the GLOBAL knowledge base (notebooks of sources).

    action=list_notebooks | create_notebook | add_source | add_text | search |
    discover (web -> candidate URLs) | import (URLs -> a notebook) | status.
    """
    from longrun.memory import knowledge as kb
    args = args or {}
    action = (args.get("action") or "search").lower()
    if action in ("status", "info"):
        return {"ok": True, "exit_code": 0, "stdout": "knowledge: %s" % kb.status()}
    if action in ("notebooks", "list_notebooks"):
        nbs = kb.list_notebooks()
        # JAG-427 fix: show the notebook ID — `search` scopes by ID, so a list that
        # omits it forces the model to guess (it guessed the NAME -> zero hits).
        return {"ok": True, "exit_code": 0, "notebooks": nbs,
                "stdout": "\n".join("%s  id=%s  (%s sources)" % (n["name"], n["id"], n["sources"])
                                    for n in nbs) or "(no notebooks)"}
    if action == "create_notebook":
        r = kb.create_notebook(args.get("name"))
        return {"ok": bool(r.get("ok")), "notebooks": kb.list_notebooks(),
                "stdout": "notebook %s" % r.get("name"), **r}
    if action == "add_text":
        r = kb.add_text(args.get("notebook"), args.get("title"), args.get("text") or args.get("content"))
        return {"ok": bool(r.get("ok")), "stdout": "stored %s chunk(s)" % r.get("chunks"), **r}
    if action in ("add_source", "add"):
        vals = args.get("refs") or args.get("ref") or args.get("url") or args.get("query") or ""
        r = kb.add_sources(args.get("notebook"), vals)
        return {"ok": bool(r.get("ok")), "added": r.get("added"), "chunks": r.get("chunks"),
                "stdout": "added %s/%s source(s), %s chunk(s)" % (r.get("added"), r.get("total"), r.get("chunks")),
                **r}
    if action == "discover":
        return kb.discover(args.get("query") or args.get("q"), args.get("n", 5))
    if action == "import":
        return kb.import_candidates(args.get("notebook"), args.get("urls") or args.get("refs"))
    query = args.get("query") or args.get("q") or ""
    if not str(query).strip():
        return {"ok": False, "exit_code": 1, "error": "query required for action=search"}
    try:
        k = int(args.get("k") or 8)
    except (TypeError, ValueError):
        k = 8
    res = kb.search(query, args.get("notebook"), k=k, kind=args.get("kind"))
    lines = ["%s:%s  %s" % (r.get("ref") or r.get("path"), r.get("start"),
                            (r.get("snippet") or "").replace("\n", " ")[:200])
             for r in res.get("results", [])]
    stdout = "\n".join(lines) or "(no matches)"
    # JAG-427 fix: a scoped search that finds nothing is usually a bad notebook name/id —
    # tell the model the valid options instead of leaving it stuck on "(no matches)".
    if not res.get("results") and args.get("notebook"):
        try:
            avail = ", ".join("%s=%s" % (n["name"], n["id"]) for n in kb.list_notebooks())
            stdout += ("\n(no matches in notebook '%s'. Valid notebooks: %s — "
                       "or omit `notebook` to search them ALL.)" % (args.get("notebook"), avail))
        except Exception:  # noqa: BLE001
            pass
    return {"ok": True, "exit_code": 0, "stdout": stdout,
            "results": res.get("results", []), "mode": res.get("mode"),
            "count": len(res.get("results", []))}


_DISPATCH = {"shell": _shell, "fs.read": _fs_read, "fs.write": _fs_write,
             "fs.edit": _fs_edit, "diff": _diff,
             "git": _git, "http": _http, "browser": _browser, "self": _self,
             "skills": _skills, "memory": _memory, "web": _web, "improve": _improve,
             "reconcile": _reconcile, "sessions": _sessions, "index": _index,
             "knowledge": _knowledge,
             # JAG-426: baseline tools every standard harness ships
             "python": _python, "process": _process, "glob": _glob}


def _dispatch_execute(tool, args, run_id=None):
    fn = _DISPATCH.get(tool)
    if fn is None:
        # external MCP tools (<client>__<tool>) route through the MCP client
        if "__" in tool:
            try:
                from longrun.interop import mcp_client
                res = mcp_client.call_tool(tool, args, run_id=run_id)
                res["duration_ms"] = res.get("duration_ms", 0)
                res["tool"] = tool
                return res
            except Exception as e:  # noqa: BLE001
                return {"ok": False, "error": "external MCP call failed: %s" % e,
                        "tool": tool}
        return {"ok": False, "error": "no implementation for tool %r" % tool, "tool": tool}
    args = args or {}
    try:
        res = fn(args, run_id)
    except Exception as e:  # noqa: BLE001
        res = {"ok": False, "error": "tool error: %s" % e}
    res["tool"] = tool
    res["args"] = args
    res.setdefault("exit_code", 0 if res.get("ok") else 125)
    return res


def execute(tool, args, run_id=None):
    """Run a tool through the lifecycle hooks (JAG-69), then dispatch.

    `PreToolUse` may BLOCK the call (hook exit 2); `PostToolUse` receives the
    observation. Both are deterministic shell scripts — the model is not asked.
    """
    try:
        from longrun.tools import hooks
        pre = hooks.run("PreToolUse", tool=tool, args=args or {}, run_id=run_id)
    except Exception:  # noqa: BLE001 — a hook must never break tool execution
        pre = {"blocked": False}
    if pre.get("blocked"):
        return {"ok": False, "tool": tool, "args": args or {}, "exit_code": 126,
                "hook_blocked": True,
                "error": "blocked by PreToolUse hook: %s" % pre.get("reason")}
    # JAG-426 (Domain 6): the local decision layer may reject a futile/denied action
    # BEFORE the approval round-trip. `mode: null` is a no-op and every error fails
    # OPEN, so this can never block a legitimate call.
    try:
        from longrun.model import decision as _decision
        _v = _decision.pre_tool(tool, args)
        if not _v.get("ok", True):
            return {"ok": False, "tool": tool, "args": args or {}, "exit_code": 127,
                    "decision_blocked": True, "decision_model": _v.get("model"),
                    "error": "blocked by the decision layer: %s" % _v.get("reason")}
    except Exception:  # noqa: BLE001 — the decision layer must never break a tool
        pass
    res = None
    try:
        res = _dispatch_execute(tool, args, run_id=run_id)
    except Exception as e:  # noqa: BLE001 — a tool must never crash the harness
        res = {"ok": False, "tool": tool, "args": args or {}, "exit_code": 1,
               "error": "tool crashed: %s" % e}
    try:
        from longrun.tools import hooks
        obs = (res.get("observation") or res.get("error") or res.get("content")
               or res.get("stdout"))
        hooks.run("PostToolUse", tool=tool, args=args or {}, observation=obs,
                  run_id=run_id)
    except Exception:  # noqa: BLE001
        pass
    return res


# Transport/metadata keys that are never the payload the model needs.
_OBS_NOISE = ("tool", "ok", "exit_code", "backend", "sandboxed", "duration_ms",
              "status", "approval")


def observation(res, max_chars=1600):
    """Render a tool result as the agent's observation line.

    JAG-347: the payload MUST always reach the model. The renderer used to emit
    only stdout/stderr/path, so any tool whose payload lives elsewhere (fs.read ->
    `content`; fs.write/fs.edit -> counters; self/improve -> structured dicts)
    answered the model with an EMPTY observation (exit=0, no error) and the agent
    acted blind. Now: stdout/stderr/content/path, then an explicit `observation`
    string, and - when the tool produced none of those - a JSON fallback of its
    remaining fields, so no tool can ever render as empty again.
    """
    if not res.get("ok") and res.get("error"):
        return "[%s] ERROR: %s" % (res.get("tool"), res["error"])
    bits = ["[%s] exit=%s backend=%s sandboxed=%s"
            % (res.get("tool"), res.get("exit_code"), res.get("backend"), res.get("sandboxed"))]
    has_body = False
    if res.get("stdout"):
        bits.append("stdout: " + _truncate(str(res["stdout"]).strip(), max_chars))
        has_body = True
    if res.get("stderr"):
        bits.append("stderr: " + _truncate(str(res["stderr"]).strip(), max_chars))
        has_body = True
    if res.get("content") is not None and not res.get("stdout"):
        bits.append("content: " + _truncate(str(res["content"]).strip(), max_chars))
        has_body = True
    if res.get("path"):
        bits.append("path: " + str(res["path"]))
    if res.get("observation"):
        bits.append(_truncate(str(res["observation"]).strip(), max_chars))
        has_body = True
    if not has_body:
        extras = {k: v for k, v in res.items()
                  if k not in _OBS_NOISE and k not in ("path", "content", "stdout", "stderr")}
        if extras:
            bits.append("result: " + _truncate(
                json.dumps(extras, ensure_ascii=False, default=str), max_chars))
    return "\n".join(bits)

