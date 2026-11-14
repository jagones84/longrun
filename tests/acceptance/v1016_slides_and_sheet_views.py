#!/usr/bin/env python3
"""v1016 — slides, multi-sheet workbooks, video and audio have real viewers.

Measured gap: a `.pptx` fell through to the binary message and a workbook showed
one anonymous table. The preview now draws slide SHAPES with their geometry
(server-side python-pptx, never a second parser in the browser), gives a workbook
sheet TABS + column letters + row numbers, and the media containers keep their
players. Everything is bounded and every value is painted as text.
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


API = _read("src", "longrun", "core", "api_v02.py")
UI = _read("webui", "index.html")

RESULT = []


def check(name, ok, detail=""):
    RESULT.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# --- server: the deck is parsed once, bounded, with geometry -----------------
check("A1 the slides route exists and is wired",
      'if path == "/api/fs/slides":' in API and "fs_slides(qs)" in API)
check("A2 python-pptx reads the deck (no second parser shipped)",
      "from pptx import Presentation" in API and "prs = Presentation(p)" in API)
check("A3 every shape carries its real geometry as slide fractions",
      '"x": max(0.0, min(1.0, l / sw))' in API
      and '"h": max(0.0, min(1.0, h / shh))' in API)
check("A4 text keeps size/weight/colour/alignment; tables stay tables",
      '"sz": size, "b": bold, "c": color, "al": _slide_align(par)' in API
      and 'k="table", rows=rows' in API)
check("A5 pictures are data URLs, capped and type-checked",
      'src="data:%s;base64,%s"' in API and "SLIDES_MAX_IMAGE_BYTES" in API
      and '"image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp"' in API)
check("A6 the deck is bounded (slides, shapes, rows, cols)",
      "SLIDES_MAX = 60" in API and "SLIDES_MAX_SHAPES = 80" in API
      and "SLIDES_MAX_TABLE_ROWS = 30" in API and "SLIDES_MAX_TABLE_COLS = 12" in API)
check("A7 a legacy .ppt is an honest message, not a blank deck",
      'if ext not in (".pptx", ".pptm"):' in API and "save it as .pptx" in API)
check("A8 the workbook reports its declared dimensions",
      '"dims": {"rows": int(ws.max_row or 0),' in API)
check("A9 the same path safety as the other fs routes is reused",
      "def fs_slides(qs=None)" in API
      and '_safe_fs_path(_link_path(q.get("path"), q), _fs_allowed_roots(q))' in API)
check("A10 a midnight timestamp reads as a DATE, not T00:00:00",
      "if isinstance(v, _dt.datetime):" in API
      and "return v.date().isoformat() if v.time() == _dt.time(0, 0)" in API)

# --- client: which families, which views, what interaction -------------------
check("B1 .pptx/.pptm/.ppt open as SLIDES",
      'if (/\\.(pptx|pptm|ppt)$/i.test(path)) return "slides";' in UI)
check("B2 the switch offers Slides ⇄ Outline",
      'if (kind === "slides") return ["slides", "outline"];' in UI
      and 'slides: "Slides", outline: "Outline"' in UI)
check("B3 the slide canvas positions every shape by fraction",
      'el.style.left = (sh.x * 100) + "%";' in UI
      and 'el.style.width = (sh.w * 100) + "%";' in UI)
check("B4 text font size scales from the deck's own point size",
      "const pt = W / ((d.w || 12192000) / 12700);" in UI
      and 'p.style.fontSize = Math.round((pa.sz || 18) * pt) + "px";' in UI)
check("B5 arrows and ←/→ navigate the deck",
      'prev.title = "previous slide (←)"' in UI
      and 'if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;' in UI)
check("B6 the outline jumps to the slide it names",
      'card.onclick = () => { _pvSlideCache.idx = i; _pv.view = "slides"; renderPreview(); };' in UI)
check("B7 the workbook has sheet TABS driven by the server",
      'b.onclick = () => { if (name !== r.sheet) _pvRenderSheet(body, note, name); };' in UI
      and 'url += "&sheet=" + encodeURIComponent(sheetName);' in UI)
check("B8 a sheet reads like a grid: column letters + row numbers",
      "function _pvColName(i)" in UI and 'rn.className = "pv-rn";' in UI
      and 'th.className = "pv-colhead";' in UI and ".pv-grid tr.pv-headrow > *" in UI)
check("B9 the deck's text is painted as text nodes (no markup)",
      "p.textContent = pa.t || \"\";" in UI
      and "td.textContent = c;" in UI
      and "h.textContent = (i + 1) + \" · \"" in UI)
check("B10 video/audio keep their players on the raw route",
      'const v = document.createElement("video");' in UI
      and 'const a = document.createElement("audio");' in UI
      and '"video/mp4", "video/webm", "video/ogg", "video/quicktime",' in API)

print("---")
passed = sum(RESULT)
print("%d/%d PASS" % (passed, len(RESULT)))
sys.exit(0 if passed == len(RESULT) else 1)
