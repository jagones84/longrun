#!/usr/bin/env python3
"""v457 — per-session chat scroll and provider-specific vision detection."""
import base64
import json
import os
import sys
import tempfile
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server as _server
from longrun.agent import agent as agent_mod
from longrun.model import providers, rllm

results = []


def check(name: str, ok: bool) -> None:
    """Record and print one deterministic acceptance check."""
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name)


class _Response:
    """Small context-managed HTTP response for mocked router metadata."""

    def __init__(self, payload: dict) -> None:
        self._payload = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._payload


_provider = {
    "id": "win",
    "local": True,
    "base_url": "http://provider.example/v1",
    "models": [{"id": "vision-model"}],
}
_seen_urls: list[str] = []


def _open(request: object, timeout: int) -> _Response:
    """Return a vision-capable mock roster and retain the requested endpoint."""
    _seen_urls.append(getattr(request, "full_url", request))
    return _Response({"data": [{
        "id": "vision-model",
        "meta": {"architecture": {"input_modalities": ["text", "image"]}},
    }]})


with mock.patch.object(providers, "resolve", return_value=(_provider, "vision-model")):
    with mock.patch.object(rllm.urllib.request, "urlopen", side_effect=_open):
        _supports = rllm.model_supports_vision("win:vision-model")
check("1a local vision detection queries the resolved provider roster",
      _supports and _seen_urls == ["http://provider.example/v1/models"])

with mock.patch.object(providers, "resolve", return_value=(_provider, "vision-model")):
    with mock.patch.object(
            rllm.urllib.request, "urlopen",
            return_value=_Response({"data": [{
                "id": "vision-model",
                "meta": {"architecture": {"input_modalities": ["text"]}},
            }]})):
        _text_only = rllm.model_supports_vision("win:vision-model")
check("1b local text-only roster does not claim vision", not _text_only)

_tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
try:
    _tmp.write(b"\x89PNG\r\nmock image bytes")
    _tmp.close()
    _message = "The user attached the following:\n- file: %s\n\nDescribe this image." % _tmp.name
    _msgs = [{"role": "user", "content": _message}]
    with mock.patch.object(agent_mod, "model_supports_vision", return_value=False):
        _plain = agent_mod._inject_vision_blocks(_msgs, "win:text-model")
    # JAG-461: the content stays TEXT (no image block) but the harness now tells the
    # model the truth so it cannot invent a "I can see it" answer.
    check("2a unsupported model receives no image block but an explicit note",
          isinstance(_plain[-1]["content"], str)
          and "cannot" in _plain[-1]["content"]
          and "[harness]" in _plain[-1]["content"])

    with mock.patch.object(agent_mod, "model_supports_vision", return_value=True):
        _vision = agent_mod._inject_vision_blocks(_msgs, "win:vision-model")
    _blocks = _vision[-1]["content"]
    check("2b compatible model receives attachment as an image data URL",
          len(_blocks) == 2
          and _blocks[0]["type"] == "text"
          and _blocks[1]["type"] == "image_url"
          and base64.b64decode(_blocks[1]["image_url"]["url"].split(",", 1)[1])
          == b"\x89PNG\r\nmock image bytes")
finally:
    os.unlink(_tmp.name)

print("---")
ok = sum(results)
print("v457: %d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
