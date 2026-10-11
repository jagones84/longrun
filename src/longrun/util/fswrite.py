"""Shared atomic JSON helpers for the harness stores.

Single source of truth for reading and writing JSON state so every store
handles a crash (or concurrent writers) the same way: a UNIQUE temp file in the
target directory + ``os.replace``. A fixed ``<path>.tmp`` collides when two
threads write the same file at once — the first ``os.replace`` renames the tmp
away and the second raises ``FileNotFoundError`` (JAG-201 for transcripts,
JAG-287 for task graphs). Before this module each store re-implemented its own
variant, and some still used the racy fixed-name tmp.

Stdlib-only and imports nothing from the rest of the package, so it can never
create an import cycle.
"""

import json
import os
import uuid


def read_json(path, default=None):
    """Return the JSON document at ``path``, or ``default`` on any read/parse error."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return default


def write_json(path, obj, *, indent=2, ensure_ascii=False, sort_keys=False):
    """Atomically write ``obj`` as JSON to ``path``.

    Writes to a unique ``<path>.<uuid>.tmp`` in the same directory, then
    ``os.replace`` it onto the target so a reader never sees a half-written
    file. The unique temp name is deliberate — see the module docstring.
    """
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = "%s.%s.tmp" % (path, uuid.uuid4().hex)
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=indent, ensure_ascii=ensure_ascii, sort_keys=sort_keys)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass