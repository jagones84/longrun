"""Shared single-source readers for config/data values (JAG-483).

Three primitives had been re-implemented all over the codebase and had drifted
apart: the ``int`` coercion (four copies, two different failure defaults), the
YAML-or-JSON document loader (four copies, three different fallbacks) and the
request-body unwrap (two byte-identical copies). Behaviour that "looks the same"
but is not — a fallback of ``{}`` here and ``None`` there — is exactly how a
store and its panel end up disagreeing, so the implementation lives HERE and
every previous copy is now a one-line delegation.

Stdlib-only, imports nothing from the rest of the package: no import cycle.
"""

import json
import logging
import os

_log = logging.getLogger(__name__)


def as_int(x, default=0):
    """``int(x)`` with a fallback; never raises.

    Values arrive hand-edited in YAML or straight off the wire, so ``128k`` or
    ``abc`` must not crash the caller (JAG-231).
    """
    try:
        return int(x)
    except (TypeError, ValueError):
        return default


def load_yaml(text, default=None):
    """Parse YAML when available, else JSON, else ``default``.

    A config file written as YAML and one written as JSON are both accepted; a
    missing PyYAML install must not be fatal.
    """
    try:
        import yaml
        return yaml.safe_load(text)
    except Exception:  # noqa: BLE001 — no PyYAML, or malformed input: try JSON
        pass
    try:
        return json.loads(text)
    except Exception:  # noqa: BLE001
        # Audit F5: malformed input used to answer `default` with zero trace —
        # a typo in tools.yaml/routing.yaml then booted the WRONG config.
        # Never fatal, but always loud.
        _log.warning("dataio: malformed document, returning default: %r",
                     (text or "")[:120])
        return default


def dump_yaml(data):
    """Serialise to YAML when available, else to JSON (indent 2)."""
    try:
        import yaml
        return yaml.safe_dump(data, sort_keys=False)
    except Exception:  # noqa: BLE001
        return json.dumps(data, indent=2)


def read_yaml(path, default=None, only_dict=True):
    """Read a small YAML/JSON document from ``path``; never fatal.

    A missing file, an unreadable one and a malformed one all answer
    ``default``. With ``only_dict`` (the default) a document that parses to a
    list/scalar also answers ``default``, because every caller wants a mapping.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError:
        if os.path.isfile(path or ""):
            # Exists but unreadable (permissions, transient FS error) — loud.
            _log.warning("dataio: cannot read %s, returning default", path)
        return default
    doc = load_yaml(text, default)
    if doc is default:
        # load_yaml already warned; name the file so the operator finds it.
        _log.warning("dataio: malformed %s, returning default", path)
        return default
    if only_dict and not isinstance(doc, dict):
        return default
    return doc


def json_body(body):
    """Unwrap a request body that may be a dict or raw bytes -> dict, ``{}`` else."""
    if isinstance(body, dict):
        return body
    if isinstance(body, (bytes, bytearray)):
        try:
            return json.loads(body.decode("utf-8", "replace") or "{}")
        except Exception:  # noqa: BLE001
            return {}
    return {}
