#!/usr/bin/env python3
"""Docs guard — do the tracked docs' links and anchors still resolve?

The docs are read by agents and by humans, and a link that points nowhere fails
silently: the README's own table of contents (30 same-file anchors), the cross-links
between `docs/`, and three `file:///…` citations into `src/` are checked by no test.
`v1271` pins the doc SET (README links every doc) and `v1278` the countable claims
INSIDE `ARCHITECTURE.md`; nothing resolved a link or an anchor.

  * `check(root)` — walk the declared scope, return one verdict:
      `{format, verdict: "clean"|"problems", stats: {docs, links, anchors},
        findings: [{file, line, kind, target}]}` with
      `kind ∈ {"broken-link", "missing-anchor", "stale-absolute"}`.
  * A relative link resolves against the file that holds it; `file.md#anchor` needs
    both the file and the heading; `#anchor` needs the heading in the same file; a
    `file://` target must exist (this is the class that broke when the checkout moved).
  * Link extraction skips fenced blocks and inline code, so a literal example is not
    a claim. Anchors use GitHub's slug (lowercase, punctuation/symbols dropped, spaces
    to `-`).

Scope is declared here, not derived from `git` (the checker must run offline and in a
fresh clone): the six root docs, `docs/**/*.md` and `.github/**/*.md`. `CHANGELOG.md`
is historical prose, and `benchmarks/**` / `market/**` hold fixtures and sample links.

The slug/anchor/fence logic is adapted from `kit/docs-lint.py` of the MIT-licensed
`ai-project-scaffold` (https://github.com/hellOoSaksit/ai-project-scaffold); the
frontmatter/`related:` parts of that tool are deliberately not adopted (Longrun's doc
identity is owned by `.agent/docs/tech-spec/SPEC-INDEX.md`, not by YAML).

Pure: paths in, verdict out. No network, no write. It lives at the `harness/` ROOT
because the running app reaches it: the `harness` tool's `docsguard` action
(`tools/tools.py`) and the CLI adapter (`core/forge.py`) call the same `check()`.
"""
from __future__ import annotations

import os
import re
import unicodedata
from urllib.parse import unquote

FORMAT = "longrun-docs-guard/1"

ROOT_DOCS = ("README.md", "AGENTS.md", "GLOSSARY.md", "CONTRIBUTING.md",
             "CODING_STANDARDS.md", "UserPrompts.md")
DOC_DIRS = ("docs", ".github")
SKIP_DIRS = {"__pycache__", ".git", "node_modules"}

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
LINK_RE = re.compile(r"\]\(([^)]+)\)")
INLINE_CODE_RE = re.compile(r"`[^`]*`")
EXTERNAL = ("http://", "https://", "mailto:", "tel:")


def slugify(heading: str) -> str:
    """GitHub-flavoured heading → anchor: lowercase, punctuation/symbols dropped,
    `-`/`_` and letters of every script kept, each whitespace char → one hyphen."""
    out = []
    for ch in heading.strip().lower():
        if ch in "-_":
            out.append(ch)
        elif unicodedata.category(ch)[0] in ("P", "S"):
            continue
        else:
            out.append(ch)
    return re.sub(r"\s", "-", "".join(out))


def _text_lines(path):
    """(lineno, line) for every line OUTSIDE a fenced block, inline code removed."""
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            raw = fh.read().splitlines()
    except OSError:
        return []
    out, fence = [], False
    for n, line in enumerate(raw, 1):
        if line.lstrip().startswith("```"):
            fence = not fence
            continue
        if fence:
            continue
        out.append((n, INLINE_CODE_RE.sub("", line)))
    return out


def anchors(path):
    """The set of anchor slugs a markdown file exposes (headings outside fences)."""
    out = set()
    for _n, line in _text_lines(path):
        m = HEADING_RE.match(line)
        if m:
            out.add(slugify(m.group(2)))
    return out


def scope(root):
    """The declared doc set, as repo-relative paths."""
    docs = [name for name in ROOT_DOCS if os.path.isfile(os.path.join(root, name))]
    for top in DOC_DIRS:
        base = os.path.join(root, top)
        if not os.path.isdir(base):
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
            for name in sorted(filenames):
                if name.endswith(".md"):
                    docs.append(os.path.relpath(os.path.join(dirpath, name), root))
    return docs


def _target(raw):
    """The path part of a `](target "title")`, without angle brackets."""
    target = raw.strip().split(" ", 1)[0].strip("<>")
    return target


def check(root):
    """Resolve every link/anchor in the declared scope. A finding is not a warning."""
    docs = scope(root)
    findings = []
    n_links = n_anchors = 0
    cache = {}

    def _anchors_of(path):
        key = os.path.normpath(path)
        if key not in cache:
            cache[key] = anchors(key)
        return cache[key]

    for rel in docs:
        path = os.path.join(root, rel)
        for lineno, line in _text_lines(path):
            for raw in LINK_RE.findall(line):
                target = _target(raw)
                if not target or target.startswith(EXTERNAL):
                    continue
                if target.startswith("file://"):
                    target_path = unquote(target[len("file://"):].partition("#")[0])
                    if not os.path.exists(target_path):
                        findings.append({"file": rel, "line": lineno,
                                         "kind": "stale-absolute", "target": target})
                    continue
                file_part, _, anchor = target.partition("#")
                file_part = unquote(file_part)
                if not file_part:
                    n_anchors += 1
                    if anchor and anchor not in _anchors_of(path):
                        findings.append({"file": rel, "line": lineno,
                                         "kind": "missing-anchor", "target": target})
                    continue
                n_links += 1
                if anchor:
                    n_anchors += 1
                dest = os.path.normpath(os.path.join(os.path.dirname(path), file_part))
                if not os.path.exists(dest):
                    findings.append({"file": rel, "line": lineno,
                                     "kind": "broken-link", "target": target})
                elif anchor and dest.endswith(".md") and anchor not in _anchors_of(dest):
                    findings.append({"file": rel, "line": lineno,
                                     "kind": "missing-anchor", "target": target})

    return {"format": FORMAT,
            "verdict": "clean" if not findings else "problems",
            "stats": {"docs": len(docs), "links": n_links, "anchors": n_anchors},
            "findings": findings}
