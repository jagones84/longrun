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
import socket
import time
import urllib.parse
import urllib.request
from typing import Any

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
    from longrun.tools import matrix_guard
    ok_cmd, err_cmd = matrix_guard.check_shell_command(command, cwd=cwd)
    if not ok_cmd:
        return {"ok": False, "exit_code": 126, "error": err_cmd,
                "backend": "host", "sandboxed": False}
    snap = matrix_guard.snapshot_nucleus_digests()
    res = sandbox.run(command, run_id=run_id,
                      timeout=args.get("timeout_secs"),
                      workspace=cwd)
    reverted = matrix_guard.restore_if_nucleus_tampered(snap)
    if reverted:
        return {"ok": False, "exit_code": 126,
                "error": "NUCLEUS_PROTECTED: shell command modified Nucleus files (reverted %d file(s))" % len(reverted),
                "backend": res.get("backend", "host"), "sandboxed": res.get("sandboxed", False)}
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
    from longrun.tools import matrix_guard
    snap = matrix_guard.snapshot_nucleus_digests()
    res = None
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(code)
        res = sandbox.run("python3 " + name, run_id=run_id,
                          timeout=args.get("timeout_secs"), workspace=ws)
    except OSError as e:
        # JAG-431r4: the sandbox workspace can be missing/read-only; report the real
        # I/O error instead of a NameError on the (unbound) `res` below.
        return {"ok": False, "exit_code": 1, "error": "cannot stage the script: %s" % e,
                "backend": "host", "sandboxed": False}
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    reverted = matrix_guard.restore_if_nucleus_tampered(snap)
    if reverted:
        return {"ok": False, "exit_code": 126,
                "error": "NUCLEUS_PROTECTED: python snippet modified Nucleus files (reverted %d file(s))" % len(reverted),
                "backend": res.get("backend", "host"), "sandboxed": res.get("sandboxed", False)}
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

# JAG-509: how many bytes a LINE-RANGE read may scan. A range request must not
# pull a multi-hundred-MB file into memory just to return 20 lines; past this
# the read is marked truncated.
FS_LINE_SCAN_MAX_BYTES = 4 * 1024 * 1024


def _int_or_none(value):
    """Parse an int argument, or None when absent/not a number."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _line_view(text, start_line=None, end_line=None, scan_capped=False):
    """A 1-based inclusive line window over `text` (JAG-509).

    `fs.read` could only return a BYTE prefix, so reading lines 40-60 of a large
    file meant guessing byte offsets and eye-filtering a truncated dump. This
    returns the exact window plus honest bounds: the file's line count, the
    first/last line actually returned, how many lines came back, and whether the
    window was clipped (EOF, or the scan cap — then `total_lines` is a LOWER
    bound of the file's real line count).
    """
    lines = str(text or "").splitlines(keepends=True)
    total = len(lines)
    first = max(1, _int_or_none(start_line) or 1)
    requested_end = _int_or_none(end_line)
    last = total if requested_end is None else min(max(first, requested_end), total)
    picked = lines[first - 1:last] if first <= total else []
    return {"content": "".join(picked), "total_lines": total, "start_line": first,
            "end_line": last, "returned_lines": len(picked),
            "truncated": bool(scan_capped
                              or (requested_end is not None and requested_end > last))}


def _fs_read(args, run_id):
    roots = registry.tool_spec("fs.read")["roots"]
    path, err = registry.resolve_path(str(args.get("path", "")), roots,
                                      base=args.get("workspace"))
    if err:
        return {"ok": False, "error": err}
    if not os.path.isfile(path):
        return {"ok": False, "error": "no such file: %s" % path}
    max_bytes = int(args.get("max_bytes", 65536))
    start_line = args.get("start_line")
    end_line = args.get("end_line")
    want_range = start_line is not None or end_line is not None

    def _window(text, scan_capped=False):
        """Shape a text blob into the reply: whole-file bytes, or a line window."""
        if not want_range:
            content = text[:max_bytes]
            return {"content": content, "truncated": len(text) > len(content)}
        view = _line_view(text, start_line, end_line, scan_capped=scan_capped)
        content = view.pop("content")
        if len(content) > max_bytes:
            # Keep the byte budget honest AND line-aligned: cut at the last
            # newline that still fits, never mid-line.
            cut = content.rfind("\n", 0, max_bytes)
            content = content[:cut + 1] if cut > 0 else content[:max_bytes]
            view["truncated"] = True
        view["content"] = content
        view["bytes"] = len(content)
        return view

    # JAG-490: a PDF/DOCX/image attached to the chat is a PATH the model is told
    # to read. Decoding its bytes as UTF-8 returned binary garbage, so binary
    # documents go through the same extractor the knowledge base uses.
    try:
        from longrun.memory import docio as _docio
    except Exception:  # noqa: BLE001
        _docio = None
    if _docio is not None and _docio.supported(path):
        res = _docio.extract(path, max_kb=max(1024, max_bytes // 1024))
        text = res.get("text") or ""
        if not text:
            return {"ok": False, "path": path,
                    "error": "no extractable text: %s" % (res.get("engine") or "?"),
                    "engine": res.get("engine"),
                    "recommend_visual": res.get("recommend_visual"),
                    "exit_code": 1}
        shaped = _window(text)
        shaped.update({"bytes": len(shaped["content"])})
        return {"ok": True, "path": path, "engine": res.get("engine"),
                "quality": res.get("quality"), "backend": "host", "sandboxed": False,
                "exit_code": 0, **shaped}
    if want_range:
        # A range may live far past the byte prefix, so scan further — bounded.
        size = os.path.getsize(path)
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read(FS_LINE_SCAN_MAX_BYTES)
        shaped = _window(text, scan_capped=size > FS_LINE_SCAN_MAX_BYTES)
        return {"ok": True, "path": path, "backend": "host", "sandboxed": False,
                "exit_code": 0, **shaped}
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read(max_bytes)
    return {"ok": True, "path": path, "content": content, "bytes": len(content),
            "truncated": len(content) >= max_bytes,
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
    from longrun.tools import matrix_guard
    ok_mw, err_mw = matrix_guard.check_write_allowed(path)
    if not ok_mw:
        return {"ok": False, "exit_code": 126, "error": err_mw, "path": path}
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
    from longrun.tools import matrix_guard
    ok_mw, err_mw = matrix_guard.check_write_allowed(path)
    if not ok_mw:
        return {"ok": False, "exit_code": 126, "error": err_mw, "path": path}
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
    # JAG-431r4b: a relative `cwd` resolved against the SERVER process cwd —
    # inconsistent with the shell tool (which resolves against the session
    # workspace) and surprising in production where the server is launched from
    # a different directory than the user. Mirror the shell: relative -> REPO.
    if not os.path.isabs(str(cwd)):
        cwd = os.path.join(REPO, str(cwd))
    if not os.path.isdir(cwd):
        return {"ok": False, "error": "cwd not found: %s" % cwd}
    # JAG-510: `git checkout/restore/rm/apply/...` writes working-tree files, so
    # the same Nucleus write-target gate as the shell tool must run first —
    # otherwise this tool is a second front door into `src/longrun/`.
    from longrun.tools import matrix_guard
    ok_git, err_git = matrix_guard.check_shell_command("git " + raw, cwd=cwd)
    if not ok_git:
        return {"ok": False, "exit_code": 126, "error": err_git,
                "backend": "host(git)", "sandboxed": False}
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
    """SSRF guard for `web`: only public http(s) hosts are reachable.

    JAG-431r4b: a hostname-based URL (e.g. `evil.example.com`) passed the
    textual check, then `urlopen` resolved it at fetch time to a private
    IP — classic DNS rebind / name-smuggle bypass. Resolve the name NOW
    and reject any private/loopback address it points at.
    """
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
        # JAG-431r4b: DNS name -> resolve it and reject any private/loopback
        # record. Catches `internal.cdn.example` pointing at 10.x.
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror as e:
            return False, "dns resolution failed: %s" % e
        for fam, *_rest, sockaddr in infos:
            try:
                ip = ipaddress.ip_address(sockaddr[0])
            except ValueError:
                continue
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False, "host %s resolves to private/loopback %s" % (host, sockaddr[0])
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
    if not query:
        return {"ok": False, "error": "query required for action=search",
                "backend": "host(web)", "sandboxed": False}
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
    # JAG-513: `tool`/`query` only make sense for discovery, so passing one is an
    # unambiguous request for it — the model should not have to repeat `action`.
    if (args or {}).get("tool") or (args or {}).get("query"):
        if action in ("info", ""):
            action = "tools"
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
    # JAG-462: report the EFFECTIVE external MCP surface. Without this, a model asked
    # "what MCP do I have?" read the TRACKED `config/mcp_clients.yaml` (which ships
    # `clients: {}` as an example) and wrongly answered "no external MCP servers are
    # active" while the gateway was connected with 26 tools.
    try:
        from longrun.interop import mcp_client as _mc
        _doc = _mc.load_doc() or {}
        _clients = sorted((_doc.get("clients") or {}).keys())
        try:
            _tools = sorted(t.get("name") for t in (_mc.list_tools() or []) if t.get("name"))
        except Exception:  # noqa: BLE001
            _tools = []
        info["mcp"] = {
            "clients": _clients,
            "tools_count": len(_tools),
            "tools_available": _tools[:40],
            "note": ("the tracked config/mcp_clients.yaml holds EXAMPLES; the real "
                     "clients live in the gitignored config/mcp_clients.local.json"),
        }
    except Exception:  # noqa: BLE001 — the self report must never fail on MCP
        pass
    # JAG-462: report the EFFECTIVE external MCP surface. Without this, a model asked
    # "what MCP do I have?" read the TRACKED `config/mcp_clients.yaml` (which ships
    # `clients: {}` as an example) and wrongly answered "no external MCP servers are
    # active" while the gateway was connected with 26 tools.
    try:
        from longrun.interop import mcp_client as _mc
        _doc = _mc.load_doc() or {}
        _clients = sorted((_doc.get("clients") or {}).keys())
        try:
            _tools = sorted(t.get("name") for t in (_mc.list_tools() or []) if t.get("name"))
        except Exception:  # noqa: BLE001
            _tools = []
        info["mcp"] = {
            "clients": _clients,
            "tools_count": len(_tools),
            "tools_available": _tools[:40],
            "note": ("the tracked config/mcp_clients.yaml holds EXAMPLES; the real "
                     "clients live in the gitignored config/mcp_clients.local.json"),
        }
    except Exception:  # noqa: BLE001 - the self report must never fail on MCP
        pass
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
            info["tools"] = diag_mod.tools_report(tool=(args or {}).get("tool"),
                                                  query=(args or {}).get("query"))
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
    limit = int(args.get("limit") or (10 if action in ("recent", "list") else 5))
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
        # JAG-447: provenance — `source` is the free tag, `origin` the segregation
        # key the WebUI/prompt group by (agent-stored vs. user-authored).
        meta = {"session": run_id or "",
                "source": str(args.get("source") or "agent"),
                "origin": str(args.get("origin") or "agent")}
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
        if action in ("recent", "list"):
            hits = [(1.0, r) for r in mem.query("", args.get("kind"), limit)]
        else:
            query = (args.get("query") or "").strip()
            if not query:
                return {"ok": False, "error": "query required for action=recall",
                        "backend": "host", "sandboxed": False}
            # JAG-431r4b: respect an explicit semantic flag. Default to keyword
            # (bm25) so a recall does not silently hit the embedding API for
            # hosts with no embedder configured (used to raise inside
            # semantic_query -> "memory lookup failed"). `semantic=True` opts in.
            sem_flag = args.get("semantic")
            if isinstance(sem_flag, str):
                sem_flag = sem_flag.strip().lower() in ("1", "true", "yes", "on")
            else:
                sem_flag = bool(sem_flag) if sem_flag is not None else False
            hits = mem.search(query, args.get("kind"), limit, sem_flag)
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
    # JAG-491: audit the WHOLE backlog (proposals + distilled lessons) with an LLM
    # against the current codebase. One implementation shared with the panel.
    if scope == "review" or action == "review":
        try:
            limit = int(args.get("limit") or 18)
        except (TypeError, ValueError):
            limit = 18
        rep = improve.review(limit=max(1, min(limit, 60)),
                             model=str(args.get("model") or "").strip() or None)
        if not rep.get("ok"):
            return {"ok": False, "error": rep.get("error") or "review failed",
                    "reviewed": len(rep.get("items") or [])}
        rows = []
        for it in rep.get("items") or []:
            line = "%-11s %-8s %s" % (it.get("verdict"), it.get("kind"),
                                      str(it.get("text") or "")[:140])
            if it.get("why"):
                line += "\n            why: " + it["why"][:220]
            if it.get("rewritten"):
                line += "\n            rewrite: " + it["rewritten"][:300]
            rows.append(line)
        return {"ok": True, "counts": rep.get("counts"), "unrated": rep.get("unrated"),
                "reviewed": len(rep.get("items") or []), "model": rep.get("model"),
                "report": rep.get("report"),
                "items": [{k: it.get(k) for k in
                           ("id", "kind", "scope", "verdict", "confidence",
                            "why", "rewritten")}
                          for it in (rep.get("items") or [])],
                "stdout": "\n".join(rows) or "(nothing to review)"}
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

        # JAG-431r4b: verify/promote must only operate on proposal dirs INSIDE
        # the harness proposals root — otherwise a hostile path could promote
        # arbitrary directories. Defence in depth: realpath + startswith check.
        proposals_root = os.path.realpath(out)

        def _inside_proposals(p):
            try:
                rp = os.path.realpath(p)
                return rp == proposals_root or rp.startswith(proposals_root + os.sep)
            except Exception:
                return False

        if action == "verify":
            if not path:
                return {"error": "path required for action=verify"}
            if not _inside_proposals(path):
                return {"error": "verify path must be under %s" % proposals_root}
            rep = selfevolve.verify(path)
            _pub("improve.verify", path=path, green=bool(rep.get("green")))
            return {"ok": True, "verify": rep}
        if action == "promote":
            if not path:
                return {"error": "path required for action=promote"}
            if not _inside_proposals(path):
                return {"error": "promote path must be under %s" % proposals_root}
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
    # JAG-451: honour the `proposals` approval policy (Settings ▸ Tools & approvals).
    pol = improve.approval_kind("proposals")
    if pol == "denied":
        return {"ok": False, "error": "proposals are DENIED by policy (Settings ▸ Tools & approvals)"}
    rec = improve.propose(scope, content, reason=str(args.get("reason", "")))
    try:
        from longrun.core import server as _srv
        _srv.publish("improve.proposal", **rec)
    except Exception:  # noqa: BLE001 — the event must never break the tool
        pass
    applied = False
    if pol == "auto" and scope in ("project", "global"):
        try:
            improve.decide(rec["id"], "approve")       # AUTO: apply without asking
            applied = True
            rec = improve.get_proposal(rec["id"]) or rec
        except Exception:  # noqa: BLE001
            pass
    return {"ok": True, "proposal": rec, "applied": applied}


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


def _chapters(args, run_id):
    """JAG-431j: the CURRENT session's THREAD — its chat groups, in order.

    The chat is a stream of GROUPS: TASK groups (one per todo-graph node) and FREE
    groups ("Free.N" — chat with no todo behind them). Long sessions are compacted IN
    PLACE (older turns collapse into one summary), so the agent can no longer READ an
    old free thread from its own context — even though the operator still sees it in
    the chat. This tool reads the harness's durable LEDGER instead (written before
    compaction can touch the transcript), so the agent can list, recover and TITLE
    groups from any point of a very long run.
    action=list (default) -> the whole thread, chronological (ids, ranges, previews).
    action=untitled -> a compact batch of free groups that still need titles.
    action=read  id=<gN>   -> one group's preserved content.
    action=title id=<gN> title="…" -> name a FREE group (todos already carry a label).
    """
    from longrun.memory import threads as th
    args = args or {}
    sid = str(args.get("session") or "").strip() or str(run_id or "")
    action = str(args.get("action") or "list").strip().lower()
    if not sid:
        return {"ok": False, "error": "no session in scope (pass session=)",
                "backend": "host", "sandboxed": False}
    if action == "untitled":
        return {"ok": True, "exit_code": 0, "session": sid,
                "stdout": th.render_untitled(sid, limit=args.get("limit", 8)),
                "backend": "host", "sandboxed": False}
    if action in ("list", "toc", "outline", ""):
        return {"ok": True, "exit_code": 0, "session": sid, "stdout": th.render(sid),
                "backend": "host", "sandboxed": False}
    gid = str(args.get("id") or args.get("group") or "").strip()
    if action in ("read", "get", "show", "content"):
        if not gid:
            return {"ok": False, "error": "id required for action=read (action=list for ids)"}
        g = th.get(sid, gid)
        if not g:
            return {"ok": False, "error": "unknown group %r (action=list for ids)" % gid}
        lines = ["%s %s %s [msg %s-%s]" % (gid, g["kind"], g.get("node") or "",
                                           g.get("from"), g.get("to"))]
        if g.get("kind") == "task":
            n = th.node_for(sid, g.get("node")) or {}
            lines.append("todo: %s [%s]" % (n.get("label") or "", n.get("status") or "?"))
            if n.get("reason"):
                lines.append("reason: %s" % str(n["reason"]).replace("\n", " ")[:300])
            ev = [e for e in (n.get("evidence") or []) if (e.get("text") or "").strip()]
            lines.append("justification (evidence):")
            lines += ["  - %s" % str(e["text"]).replace("\n", " ")[:300] for e in ev[-5:]] \
                or ["  (none recorded yet)"]
        else:
            if g.get("title"):
                lines.append("title: %s" % g["title"])
            if g.get("summary"):
                lines.append("summary: %s" % str(g["summary"]).replace("\n", " ")[:400])
            if g.get("req"):
                lines.append("request: %s" % g["req"])
            lines.append("content: %s" % (g.get("digest") or "(no text captured)"))
        return {"ok": True, "exit_code": 0, "group": g, "stdout": "\n".join(lines)}
    if action in ("title", "name", "rename"):
        title = args.get("title") or args.get("name") or ""
        summary = args.get("summary")
        if summary is None:
            summary = args.get("note")
        ok, res = th.set_title(sid, gid, title, summary=summary)
        if not ok:
            return {"ok": False, "error": res, "backend": "host", "sandboxed": False}
        out = "titled %s -> %r" % (gid, (res or {}).get("title"))
        if summary is not None:
            out += " (summary set)"
        return {"ok": True, "exit_code": 0, "group": res, "stdout": out,
                "backend": "host", "sandboxed": False}
    return {"ok": False, "error": "unknown action %r \u2014 use list|read|title" % action}


def _context(args, run_id):
    """JAG-431r2: THIS session's context meter + manual compaction.

    action=status  -> tokens used, budget, pct, over_threshold, over_budget.
    action=compact -> run a manual compaction now (config summarizer model,
                      keep_recent from config/compaction.yaml). Returns the
                      compaction stats so the agent can tell what changed.
    """
    from longrun.core import httpapi
    from longrun.model import rllm
    args = args or {}
    sid = str(args.get("session") or "").strip() or str(run_id or "")
    action = str(args.get("action") or "status").strip().lower()
    if not sid:
        return {"ok": False, "error": "no session in scope (pass session=)",
                "backend": "host", "sandboxed": False}
    if action == "status":
        info = httpapi.context_usage(session_id=sid)
        used = info.get("tokens_used", 0)
        budget = info.get("budget_tokens", 0)
        pct = info.get("pct", 0.0)
        thr = info.get("auto_compact_pct", 70)
        over_thr = info.get("over_threshold", False)
        over_bud = info.get("over_budget", False)
        msgs = info.get("messages", 0)
        out = ("context[%s]: %s / %s tokens (%.1f%%) | msgs=%d | "
               "trigger=%s%% | over_threshold=%s | over_budget=%s"
               % (sid, used, budget, pct, msgs, thr, over_thr, over_bud))
        return {"ok": True, "exit_code": 0, "session": sid, "info": info,
                "stdout": out, "backend": "host", "sandboxed": False}
    if action == "compact":
        stats = httpapi.compact_session(sid, origin="tool")
        if stats.get("error"):
            return {"ok": False, "error": stats["error"], "backend": "host",
                    "sandboxed": False}
        out = ("compact[%s]: %d -> %d msgs | %d -> %d tokens | "
               "compacted=%d kept=%d summary=%s"
               % (sid, stats.get("input_messages", 0), stats.get("input_messages", 0) - stats.get("compacted", 0) + stats.get("kept", 0),
                  stats.get("input_tokens", 0), stats.get("output_tokens", 0),
                  stats.get("compacted", 0), stats.get("kept", 0), stats.get("summary")))
        return {"ok": True, "exit_code": 0, "session": sid, "stats": stats,
                "stdout": out, "backend": "host", "sandboxed": False}
    return {"ok": False, "error": "unknown action %r — use status|compact" % action}


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
    """JAG-401: shared notebooks plus per-session attachment knowledge.

    action=list_notebooks | create_notebook | add_source | add_text | search |
    read_source | discover (web -> candidate URLs) | import (URLs -> a notebook) | status.
    """
    from longrun.memory import knowledge as kb
    args = args or {}
    action = (args.get("action") or "search").lower()
    sid = str(run_id or "").strip() or None
    requested_session = str(args.get("session") or "").strip()
    if requested_session and requested_session != (sid or ""):
        return {"ok": False, "exit_code": 1,
                "error": "session must match the current chat",
                "stdout": "session must match the current chat"}
    notebook_ref = str(args.get("notebook") or "").strip()
    if notebook_ref:
        selected_session_nb = next(
            (n for n in kb.list_sessions()
             if notebook_ref in (n.get("id"), n.get("name"))),
            None,
        )
        if selected_session_nb and selected_session_nb.get("owner") != sid:
            return {"ok": False, "exit_code": 1,
                    "error": "notebook is outside the current session",
                    "stdout": "notebook is outside the current session"}
    if action in ("status", "info"):
        return {"ok": True, "exit_code": 0, "stdout": "knowledge: %s" % kb.status()}
    if action in ("notebooks", "list_notebooks"):
        global_nbs = kb.list_notebooks()
        session_nbs = [n for n in kb.list_sessions()
                       if sid and n.get("owner") == sid]
        nbs = ([dict(n, scope="shared") for n in global_nbs] +
               [dict(n, scope="current session") for n in session_nbs])
        # JAG-427 fix: show the notebook ID — `search` scopes by ID, so a list that
        # omits it forces the model to guess (it guessed the NAME -> zero hits).
        return {"ok": True, "exit_code": 0, "notebooks": nbs,
                "global_notebooks": global_nbs, "session_notebooks": session_nbs,
                "stdout": "\n".join("%s  id=%s  (%s sources; %s)" %
                                    (n["name"], n["id"], n["sources"], n["scope"])
                                    for n in nbs) or "(no notebooks)"}
    if action == "create_notebook":
        r = kb.create_notebook(args.get("name"))
        return {"ok": bool(r.get("ok")), "notebooks": kb.list_notebooks(),
                "stdout": "notebook %s" % r.get("name"), **r}
    if action == "add_text":
        session_scope = sid if not args.get("notebook") else None
        r = kb.add_text(args.get("notebook"), args.get("title"),
                        args.get("text") or args.get("content"),
                        session_id=session_scope)
        return {"ok": bool(r.get("ok")), "stdout": "stored %s chunk(s)" % r.get("chunks"), **r}
    if action in ("add_source", "add"):
        vals = args.get("refs") or args.get("ref") or args.get("url") or args.get("query") or ""
        session_scope = sid if not args.get("notebook") else None
        r = kb.add_sources(args.get("notebook"), vals, session_id=session_scope)
        return {"ok": bool(r.get("ok")), "added": r.get("added"),
                "skipped": r.get("skipped"), "chunks": r.get("chunks"),
                "stdout": ("indexed %s new source(s), skipped %s already-indexed "
                           "duplicate(s), %s chunk(s)" %
                           (r.get("added"), r.get("skipped"), r.get("chunks"))),
                **r}
    if action == "discover":
        return kb.discover(args.get("query") or args.get("q"), args.get("n", 5))
    if action == "import":
        session_scope = sid if not args.get("notebook") else None
        return kb.import_candidates(args.get("notebook"),
                                    args.get("urls") or args.get("refs"),
                                    session_id=session_scope)
    if action == "read_source":
        result = kb.read_source(
            args.get("ref") or args.get("source"),
            notebook=args.get("notebook"),
            session=sid,
            max_chars=args.get("max_chars") or 20000,
        )
        if not result.get("ok"):
            return {"ok": False, "exit_code": 1, "stdout": result.get("error", ""),
                    **result}
        header = ("%s · %s chunks · %s/%s chars%s" %
                  (result.get("title") or result.get("ref"), result["chunks"],
                   min(result["total_chars"], result["max_chars"]),
                   result["total_chars"], " · truncated" if result["truncated"] else ""))
        return {"ok": True, "exit_code": 0, "stdout": header + "\n\n" + result["text"],
                **result}
    query = args.get("query") or args.get("q") or ""
    if not str(query).strip():
        return {"ok": False, "exit_code": 1, "error": "query required for action=search"}
    try:
        k = max(1, min(12, int(args.get("k") or 8)))
    except (TypeError, ValueError):
        k = 8
    # JAG-451: docs attached to a chat are auto-ingested into the session's own
    # notebook. Query THAT first (so an attached PDF is retrievable without
    # raw text extraction), then fall back to the global notebooks. An explicitly
    # named notebook still wins.
    notebook = args.get("notebook")
    if not notebook and sid:
        res = kb.search(query, None, k=k, kind=args.get("kind"), session=sid,
                        include_text=True)
        scope = "current session notebook"
        if not res.get("results"):
            res = kb.search(query, None, k=k, kind=args.get("kind"), include_text=True)
            scope = "shared notebooks (no session match)"
    else:
        res = kb.search(query, notebook, k=k, kind=args.get("kind"), include_text=True)
        scope = "selected notebook" if notebook else "shared notebooks"
    lines = ["scope: %s" % scope]
    remaining = 24000 - len(lines[0])
    for result in res.get("results", []):
        location = result.get("path") or result.get("ref") or "(source)"
        if result.get("start") is not None:
            location += ":%s" % result["start"]
            if result.get("end") not in (None, result.get("start")):
                location += "-%s" % result["end"]
        title = result.get("title") or result.get("ref") or "(source)"
        entry = "\n\n%s\n%s" % (title + " · " + location,
                                 result.get("text") or result.get("snippet") or "")
        if remaining <= 0:
            break
        if len(entry) > remaining:
            lines.append(entry[:remaining] + "\n...[TRUNCATED]")
            remaining = 0
            break
        lines.append(entry)
        remaining -= len(entry)
    if not res.get("results"):
        lines.append("(no matches)")
    stdout = "".join(lines)
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
            "count": len(res.get("results", [])), "scope": scope}


def _matrix(args, run_id):
    """Execute Matrix self-evolution suite actions."""
    from longrun.core import matrix
    action = str((args or {}).get("action") or "status").strip().lower()
    if action in ("status", "info"):
        return matrix.status()
    if action in ("seams", "list_seams"):
        return matrix.seams_catalog()
    if action == "scaffold":
        return matrix.scaffold(
            args.get("kind") or "tool",
            args.get("name") or "",
            description=args.get("description") or "",
        )
    if action == "enable":
        return matrix.set_enabled(True)
    if action == "disable":
        return matrix.set_enabled(False)
    if action in ("hotload", "reload"):
        return matrix.hotload()
    if action == "checkpoint_save":
        return matrix.checkpoint_save(args.get("slot"), label=args.get("label") or "")
    if action == "checkpoint_rollback":
        return matrix.checkpoint_rollback(args.get("slot"))
    if action == "git_commit":
        return matrix.git_commit(args.get("message") or "matrix update")
    if action == "git_log":
        return matrix.git_log(limit=args.get("limit") or 20)
    if action == "git_diff":
        return matrix.git_diff(rev=args.get("rev"))
    if action == "git_reset":
        return matrix.git_reset(rev=args.get("rev") or "HEAD")
    if action == "test":
        return matrix.run_test(
            script_name=args.get("script") or "test_matrix.py",
            code=args.get("code"),
            install_deps=args.get("install_deps"),
            timeout_secs=args.get("timeout_secs") or 60,
            target=args.get("target"),
        )
    if action == "verify_target":
        return matrix.verify_target(args.get("kind") or "tool", args.get("name") or "")
    if action == "promote_to_nucleus":
        return matrix.promote_to_nucleus(args.get("kind") or "tool", args.get("name") or "")
    if action == "clean_trash":
        return matrix.clean_trash(keep_recent=args.get("keep_recent") or 0)
    if action == "webui_init":
        return matrix.webui_init()
    if action == "webui_reset":
        return matrix.webui_reset()
    if action == "restart":
        sid = str(args.get("session") or run_id or "").strip()
        return matrix.schedule_restart(
            session_id=sid,
            reason=args.get("reason") or "",
            dry_run=bool(args.get("dry_run", False)),
        )
    return {"ok": False, "error": "unknown matrix action %r" % action}


_DISPATCH = {"shell": _shell, "shell.exec": _shell,
             "fs.read": _fs_read, "fs.write": _fs_write, "fs.edit": _fs_edit,
             "diff": _diff,
             "git": _git, "git.run": _git,
             "http": _http, "http.fetch": _http,
             "browser": _browser, "browser.fetch": _browser,
             "self": _self, "skills": _skills, "memory": _memory, "web": _web,
             "improve": _improve,
             "reconcile": _reconcile, "reconcile.run": _reconcile,
             "sessions": _sessions, "index": _index,
             "knowledge": _knowledge, "chapters": _chapters, "context": _context,
             # JAG-426: baseline tools every standard harness ships
             "python": _python, "python.run": _python,
             "process": _process,
             "glob": _glob, "glob.list": _glob,
             "matrix": _matrix}


def normalize_args(tool: str, args: Any) -> Any:
    """Unwrap one duplicate args layer when schema-required keys prove it safe."""
    if not isinstance(args, dict):
        return args
    try:
        from longrun.tools import registry
        schema = ((registry.tool_spec(tool) or {}).get("schema") or {})
        required = list(schema.get("required") or [])
    except Exception:  # noqa: BLE001 — normalization must never block a call
        return args
    nested = args.get("args")
    if not required or "args" in required or not isinstance(nested, dict):
        return args

    def absent(value: Any) -> bool:
        return value is None or (isinstance(value, str) and not value.strip())

    outer_missing = [key for key in required
                     if key not in args or absent(args[key])]
    if not outer_missing or any(key not in nested for key in required):
        return args

    normalized = dict(nested)
    for key, value in args.items():
        if key == "args":
            continue
        if not absent(value):
            normalized[key] = value
        else:
            normalized.setdefault(key, value)
    return normalized


def _missing_required(tool: str, args: Any) -> list[str]:
    """Required argument names absent from the schema-level object."""
    try:
        from longrun.tools import registry
        schema = ((registry.tool_spec(tool) or {}).get("schema") or {})
        required = list(schema.get("required") or [])
    except Exception:  # noqa: BLE001 — validation must never block a call
        return []
    got = args if isinstance(args, dict) else {}
    return [key for key in required if key not in got or got[key] is None]


def _empty_required(tool: str, args: Any) -> list[str]:
    """Required string arguments supplied as empty or whitespace-only values."""
    try:
        from longrun.tools import registry
        schema = ((registry.tool_spec(tool) or {}).get("schema") or {})
        required = list(schema.get("required") or [])
    except Exception:  # noqa: BLE001 — validation must never block a call
        return []
    got = args if isinstance(args, dict) else {}
    return [key for key in required if isinstance(got.get(key), str)
            and not got[key].strip()]


def _missing_args_reply(tool: str, missing: list[str],
                        empty: list[str] | None = None) -> dict[str, Any]:
    """A failure that teaches: which args are required, their types, the example."""
    empty = list(empty or [])
    try:
        from longrun.tools import diag
        full = (diag.tools_report(tool=tool) or {}).get("tool") or {}
    except Exception:  # noqa: BLE001
        full = {}
    props = full.get("properties") or {}
    problems = []
    if missing:
        problems.append("missing REQUIRED argument(s) %s"
                        % ", ".join(repr(name) for name in missing))
    if empty:
        problems.append("REQUIRED argument(s) present but empty %s"
                        % ", ".join(repr(name) for name in empty))
    required = list(full.get("required") or missing or empty)
    return {"ok": False, "tool": tool, "exit_code": 64,
            "missing_args": missing, "empty_args": empty,
            "error": ("%s: %s. Required: %s. "
                      "Arg types: %s. Example call: %s"
                      % (tool, "; ".join(problems), ", ".join(required),
                         {name: (props.get(name) or {}).get("type")
                          for name in required},
                         {"action": "tool", "tool": tool,
                          "args": full.get("example_args") or {}})),
            "schema": {"required": required,
                       "properties": props}}


def _dispatch_execute(tool, args, run_id=None):
    args = normalize_args(tool, args)
    missing = _missing_required(tool, args)
    empty = _empty_required(tool, args)
    if missing or empty:
        return _missing_args_reply(tool, missing, empty)
    fn = _DISPATCH.get(tool)
    injected_action = None
    if fn is None and "." in str(tool or "") and "__" not in str(tool or ""):
        ns, sub = str(tool).split(".", 1)
        if ns in _DISPATCH and ns not in ("fs",):
            fn = _DISPATCH[ns]
            injected_action = sub
    if fn is None:
        try:
            from longrun.core import matrix as _mtx
            pmap = _mtx.discover_promoted_tools()
            if tool in pmap or (tool + ".run") in pmap:
                res = _mtx.execute_promoted_tool(tool, args, run_id=run_id)
                res["tool"] = tool
                res["args"] = args or {}
                return res
            mmap = _mtx.discover_tools()
            if tool in mmap or (tool + ".run") in mmap:
                res = _mtx.execute_tool(tool, args, run_id=run_id)
                res["tool"] = tool
                res["args"] = args or {}
                return res
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": "Matrix tool dispatch failed: %s" % e,
                    "tool": tool, "origin": "matrix"}
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
    args = dict(args or {})
    if injected_action is not None:
        args.setdefault("action", injected_action)
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
    args = normalize_args(tool, args)
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
