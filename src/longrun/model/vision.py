"""Vision captions for the knowledge base (JAG-490).

An image is only searchable through text. OCR (docling) covers screenshots,
scans and documents, but a PHOTO or a chart without labels yields little or no
text. When ``config/index.yaml ▸ image_caption_model`` names an
OpenAI-compatible vision model, this module asks it for a factual description
(including a verbatim transcription of any visible text) and the knowledge base
indexes that caption next to the OCR text.

Optional by design: an empty model ref, a missing key or any provider error
returns ``None`` and the caller keeps the OCR text.
"""
import base64
import json
import mimetypes
import os
import urllib.request

PROMPT = (
    "Describe this image for a searchable knowledge base. First transcribe ALL "
    "visible text verbatim (labels, numbers, titles, UI text). Then describe the "
    "subject, the layout and any chart/table/diagram with its values and axes. "
    "Be factual and specific; never invent details that are not visible."
)


def caption(path, model, timeout=120, max_bytes=8 * 1024 * 1024):
    """A vision-model description of ``path`` (or None). Never raises."""
    if not model or not path or not os.path.isfile(path):
        return None
    try:
        if os.path.getsize(path) > max_bytes:
            return None
        mime = mimetypes.guess_type(path)[0] or "image/png"
        if not mime.startswith("image/"):
            return None
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        from longrun.model import providers
        ep = providers.endpoint(model)
        if not ep:
            return None
        url, headers, mid = ep
        body = {
            "model": mid,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": PROMPT},
                {"type": "image_url",
                 "image_url": {"url": "data:%s;base64,%s" % (mime, b64)}},
            ]}],
            "max_tokens": 400,
            "temperature": 0.1,
        }
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                     headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        choices = data.get("choices") or []
        msg = (choices[0] or {}).get("message") or {} if choices else {}
        text = msg.get("content")
        if isinstance(text, list):  # some providers return content blocks
            text = " ".join(str(b.get("text") or "") for b in text
                            if isinstance(b, dict))
        return str(text or "").strip() or None
    except Exception:  # noqa: BLE001 — a caption is an enhancement, never a failure
        return None
