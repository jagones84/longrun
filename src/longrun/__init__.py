"""Longrun — local agent harness (package).

All runtime modules live in subpackages under `src/longrun/` (core, agent,
orchestrate, plan, tools, model, memory, interop, util, orbit). Filesystem
anchors are centralised in `longrun.util.paths` so a module never depends on
its own location.
"""
import os
import re
import subprocess

# The ONE version string. `core.server.VERSION` and the self-knowledge block in
# the system prompt both read it: an agent that says "Longrun v0.6" while the
# service answers 1.0.0 is giving the model a false self-image (found live
# 2026-11-07 in A54's context, verified against `/api/self`).
#
# 2026-11-25 (operator: *"non e la versione 1.0 di longrun ..perche mente l'agente?"*):
# the ONE string was a hand-typed literal that had not moved since the 1.0.0 release
# (2026-10-07) while the tree passed two tagged releases (v1.1.0, v1.2.0) and 139+
# commits — so the service, `/api/self` and every agent's self-knowledge stated a
# version the code no longer was. It is now DERIVED from the checkout itself; the
# literal below is only the fallback for a copy that has no `.git` (an sdist, a
# container without history), and `v1306` pins it to the newest tag.
_BASE = "1.2.0"

_VER_RE = re.compile(r"^\d+\.\d+")
_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")


def _version_from_describe(desc, base=None):
    """PEP 440 version for a `git describe --tags --always --dirty` string.

    `v1.2.0` -> `1.2.0` · `v1.2.0-139-ge963a3be` -> `1.2.0+139.ge963a3be` ·
    a bare sha (no tag in reach) -> `<base>+g<sha>` · any of these `-dirty` ->
    `.dirty` appended. Nothing is invented: an unreadable string yields `base`.
    """
    base = base or _BASE
    d = str(desc or "").strip()
    if not d:
        return base
    dirty = d.endswith("-dirty")
    if dirty:
        d = d[:-len("-dirty")]
    if d.startswith("v"):
        d = d[1:]
    if "-g" in d:
        head, sha = d.rsplit("-g", 1)
        tag, _, count = head.rpartition("-")
        if _VER_RE.match(tag) and count.isdigit():
            out = "%s+%s.g%s" % (tag, count, sha)
        else:
            out = "%s+g%s" % (base, sha)
    elif _VER_RE.match(d):
        out = d                      # exactly on a release tag
    elif _SHA_RE.match(d):
        out = "%s+g%s" % (base, d)   # `--always` with no tag in reach
    else:
        out = base + "+" + re.sub(r"[^0-9A-Za-z.]+", ".", d).strip(".")
    return out + (".dirty" if dirty else "")


def _derive_version(base=None):
    """The checkout's own version, or the literal `base` when git cannot answer."""
    base = base or _BASE
    # src/longrun/__init__.py -> src/longrun -> src -> <repo root>
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        out = subprocess.run(
            ["git", "-C", root, "describe", "--tags", "--always", "--dirty"],
            capture_output=True, text=True, timeout=3)
        desc = (out.stdout or "").strip() if out.returncode == 0 else ""
    except Exception:  # noqa: BLE001 — no git / no repo / no permission: the literal stands
        desc = ""
    return _version_from_describe(desc, base) if desc else base


__version__ = _derive_version(_BASE)
