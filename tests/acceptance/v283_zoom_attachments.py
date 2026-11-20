#!/usr/bin/env python3
"""v283 — gradual zoom, clickable chat attachments, and plan/dispatch guidance.

JAG-283 (user):
  * Ctrl+± was the browser's coarse zoom — make it gradual;
  * an attached file must be openable from the chat (file -> editor, image -> the
    image window);
  * the model wrote todos AFTER answering and left them open — the policy/nudge must
    forbid planning work already done.

Deterministic, no live server. Run: python3 tests/v283_zoom_attachments.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
    ui = f.read()
with open(os.path.join(REPO, "src", "longrun", "core/server.py"), encoding="utf-8") as f:
    srv = f.read()
with open(os.path.join(REPO, "src", "longrun", "agent/agent.py"), encoding="utf-8") as f:
    srv += f.read()

# --- 1) gradual app zoom ------------------------------------------------------
check("Ctrl+±/0 do a gradual 5% app zoom",
      "function zoomBy" in ui and "zoomBy(0.05)" in ui
      and "document.documentElement.style.zoom" in ui and 'e.key === "0"' in ui)
check("Ctrl+wheel also zooms gradually",
      'document.addEventListener("wheel"' in ui and "e.deltaY < 0 ? 0.05" in ui)
check("the zoom level is remembered across reloads",
      'localStorage.getItem("sf_zoom")' in ui and 'setItem("sf_zoom"' in ui)
check("the zoom is bounded (no runaway)",
      "Math.min(1.6, Math.max(0.7" in ui and "Math.round((_zoom + d) * 100) / 100" in ui)

# --- 2) clickable chat attachments -------------------------------------------
check("an attachment renders as a clickable chip",
      "function _attachmentChips" in ui and 'class="chatatt"' in ui and 'class="attrow"' in ui)
check("a chip opens an image in the image window and any other file in the preview window (2026-11-21)",
      # Operator: "if i append in chat a pdf, doc, image, can i preview it [before and
      # after send]?". PDF/DOC used to open the EDITOR DOCK (raw bytes — no preview);
      # they now open the dedicated preview window (v1002) which renders a PDF in a
      # frame, markdown/CSV/sheets, and offers ⋯ › editor. The editor is still reachable.
      "function _openAttachment" in ui and "showImage(_rawUrl(path))" in ui
      and "openPreview(path)" in ui and "openInEditor(path)" in ui)
check("a PDF/DOC attachment chip PREVIEWS — the editor dock is no longer the target",
      # the defect state the operator reported: a file attachment opened the editor
      # (no preview for a PDF). The old routing must be gone from the chip handler.
      'if (path) { openInEditor(path); return; }' not in ui
      and "if (path) { openPreview(path); return; }" in ui)
check("chips are bound for mouse AND keyboard",
      "function _bindAttachmentChips" in ui and "el.onkeydown" in ui)
check("a raw-bytes URL helper exists (works behind the token)",
      "function _rawUrl" in ui and '"/api/fs/raw?path="' in ui and "authQS()" in ui)
check("image paths in a transcript linkify to the image window",
      'a.className = "imglink"; a.dataset.u = _rawUrl(p)' in ui)
check("the sent message shows the chips next to the bubble",
      "_attachmentChips(_attSnap)" in ui and "_bindAttachmentChips(_bub)" in ui)

# --- 3) plan vs. work guidance -----------------------------------------------
check("the policy forbids planning work already done",
      "Planning AFTER doing the work" in srv and "STILL TO DO" in srv)
check("the write_todos nudge requires still-to-do steps",
      "A step must describe work STILL TO DO" in srv)
check("the policy still requires done-with-evidence (unchanged contract)",
      "mark it 'done' with concrete evidence" in srv)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)

