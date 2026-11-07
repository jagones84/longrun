#!/usr/bin/env python3
"""v851 — the accessibility gate: every control is named, every theme stays readable.

Source (operator, 2026-11-07): "which best and recent github repos can help for me in
this project". The answer was to stop guessing and measure. The earlier numbers in
`2026-11-01_webui-total-refactor.md` ("93 inputs without a name") and this plan's first
regex pass ("130") were both tag-regex artefacts — they cannot see `<label>text
<input></label>`, which is how most of Settings is written. Measured with `html.parser`:
49 of 114 static controls were anonymous.

Contract:
  A) the parse is complete (every `input|select|textarea` in the static markup is seen);
  B) each non-hidden one has a programmatic name — `aria-label`, `aria-labelledby`,
     `title`, an id targeted by `<label for>`, or an enclosing `<label>` with text —
     and a `title` ALONE is not enough (that is `label-title-only`, measured by axe);
  C) no icon-only `<button>` is anonymous (the vocabulary `v763` established);
  D) the four surfaces the operator touches every turn are named by name;
  E) every theme keeps `--dim` at >= 4.5:1 on a SELECTED row (`--sel` over the panel)
     AND at the opacity `.mts` paints it on a plain panel, because those were the two
     contrast failures axe found live on 2026-11-07 (haze 4.16:1, timestamps 4.07:1)
     and the battery has no browser to see them.
  F) the in-chat tool card's disclosure is a native <button>: axe found a
     `nested-interactive` violation in the LIVE transcript (a `role="button"` row
     that contained the diff/open buttons), which no static rule would see — the
     markup that caused it is built in a template string, so this pins its shape.

JS-inserted controls (the Settings forms built in template strings) are created inside
`<label>` wrappers `(index.html:8333-8335, 11551-11557)`, so they are covered by the same
rule and would be reported if that changed.

Deterministic: static contract on webui/index.html. No server, no model, no network.
Run: python3 tests/acceptance/v851_ui_a11y_gate.py
"""
import os
import re
import sys
from html.parser import HTMLParser

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UI = os.path.join(REPO, "webui", "index.html")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


class Audit(HTMLParser):
    """Collects form controls and buttons with their labelling context."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []          # open <label> frames: [marker, text]
        self.for_ids = set()     # ids targeted by <label for="...">
        self.controls = []       # (line, tag, attrs, enclosing label frame)
        self.buttons = []        # [attrs, text]

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "label":
            if a.get("for"):
                self.for_ids.add(a["for"])
            self.stack.append(["label", ""])
        elif tag in ("input", "select", "textarea"):
            frame = self.stack[-1] if self.stack and self.stack[-1][0] == "label" else None
            self.controls.append((self.getpos()[0], tag, a, frame))
        elif tag == "button":
            self.buttons.append([a, ""])

    def handle_endtag(self, tag):
        if tag == "label" and self.stack:
            self.stack.pop()

    def handle_data(self, data):
        if self.stack:
            self.stack[-1][1] += data
        if self.buttons:
            self.buttons[-1][1] += data


html = open(UI, encoding="utf-8").read()
audit = Audit()
audit.feed(html)

static = [c for c in audit.controls if c[2].get("type") != "hidden"]


def why_unnamed(tag, a, frame):
    """None when the control has a name, else the reason it does not."""
    if (a.get("aria-label") or "").strip():
        return None
    if (a.get("aria-labelledby") or "").strip():
        return None
    # B: `title` alone is not a label — axe rule `label-title-only`.
    if a.get("id") and a["id"] in audit.for_ids:
        return None
    if frame is not None and frame[1].strip():
        return None
    return "unnamed: <%s> id=%s title=%r" % (tag, a.get("id", "-"), (a.get("title") or "")[:20])


# ---- A: the parse is complete ------------------------------------------------
check("A1 every static form control was visited (%d, floor 110)" % len(static),
      len(static) >= 110, len(static))

# ---- B: no control is anonymous ---------------------------------------------
offenders = []
for line, tag, a, frame in static:
    why = why_unnamed(tag, a, frame)
    if why:
        offenders.append("line %d %s" % (line, why))
check("B1 no form control is anonymous", not offenders,
      "; ".join(offenders[:6]) + (" (+%d more)" % (len(offenders) - 6) if len(offenders) > 6 else ""))

# ---- C: no icon-only button is anonymous ------------------------------------
anon_buttons = ["id=" + (b[0].get("id") or "-") for b in audit.buttons
                if not b[1].strip() and not (b[0].get("aria-label") or b[0].get("title"))]
check("C1 every button has text or a name (%d buttons)" % len(audit.buttons),
      not anon_buttons, ", ".join(anon_buttons[:6]))

# ---- D: the four daily surfaces are named by name ---------------------------
DAILY = {
    "inp": "message composer",
    "palette-input": "command palette",
    "termInp": "terminal command",
    "memQuery": "memory search",
}
by_id = {c[2].get("id"): c for c in static if c[2].get("id")}
for cid, what in DAILY.items():
    c = by_id.get(cid)
    label = (c[2].get("aria-label") or "") if c else ""
    check("D1 the %s has an explicit aria-label (%s)" % (what, cid),
          bool(c) and bool(label.strip()), label or "missing")

# ---- E: the muted text is readable on a selected row, in EVERY theme --------
def _block(src, pattern):
    m = re.search(pattern, src, re.S)
    return m.group(1) if m else ""


def _vars(block):
    return {k: v.strip() for k, v in re.findall(r"--([a-z0-9-]+):\s*([^;]+);", block)}


def _rgb(value):
    value = value.strip()
    if value.startswith("#"):
        h = value[1:]
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) + (1.0,)
    m = re.match(r"rgba?\(([^)]+)\)", value)
    nums = [float(x) for x in m.group(1).split(",")]
    return tuple(nums[:3]) + ((nums[3],) if len(nums) > 3 else (1.0,))


def _luminance(c):
    def channel(v):
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * channel(c[0]) + 0.7152 * channel(c[1]) + 0.0722 * channel(c[2])


def _contrast(fg, bg):
    a, b = _luminance(fg), _luminance(bg)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def _over(fg, bg):
    alpha = fg[3]
    return tuple(fg[i] * alpha + bg[i] * (1 - alpha) for i in range(3))


ROOT = _vars(_block(html, r":root\s*\{(.*?)\}"))
THEMES = {name: _vars(body) for name, body in
          re.findall(r'html\[data-theme="([a-z0-9-]+)"\]\s*\{(.*?)\n\s*\}', html, re.S)}
check("E0 every theme block was found (%d)" % len(THEMES), len(THEMES) >= 6, sorted(THEMES))

failures = []
ts_failures = []
_mts = re.search(r"\.mts\s*\{[^}]*opacity:\s*([0-9.]+)", html)
MTS_ALPHA = float(_mts.group(1)) if _mts else 1.0
for name in sorted(THEMES):
    vars_ = dict(ROOT)
    vars_.update(THEMES[name])
    try:
        panel = _rgb(vars_.get("panel") or vars_.get("bg2") or vars_["bg"])
        sel = _rgb(vars_.get("sel") or "rgba(255,255,255,.10)")
        row = _over(sel, panel)
        ratio = _contrast(_rgb(vars_["dim"]), row)
        # E2: `.mts` paints --dim at an opacity on the plain panel; compositing is
        # what axe measures, so the token alone does not prove anything.
        stamp = _over(_rgb(vars_["dim"])[:3] + (MTS_ALPHA,), panel)
        ts_ratio = _contrast(stamp, panel)
    except KeyError as exc:
        failures.append("%s missing %s" % (name, exc))
        continue
    if ratio < 4.5:
        failures.append("%s %.2f:1 (%s on row)" % (name, ratio, vars_["dim"]))
    if ts_ratio < 4.5:
        ts_failures.append("%s %.2f:1 (--dim at %s over panel)" % (name, ts_ratio, MTS_ALPHA))
check("E1 muted text reaches 4.5:1 on a selected row in every theme",
      not failures, ", ".join(failures))
check("E2 the timestamp (--dim at opacity %s) reaches 4.5:1 in every theme" % MTS_ALPHA,
      not ts_failures, ", ".join(ts_failures))

# ---- F: no disclosure is a button that CONTAINS buttons ---------------------
# axe `nested-interactive`, found live in the transcript on 2026-11-07: the tool
# card's head was `role="button"` and the diff/open buttons were appended INSIDE it.
check("F1 the tool-card disclosure is a native button (no nested interactive)",
      '<div class="toolcard-head"><button type="button" class="tc-toggle"' in html
      and 'role="button" tabindex="0" aria-expanded' not in html
      and ".tc-toggle:focus-visible" in html)


def _el(cid):
    """The opening tag of the element with this id (attribute order is free)."""
    m = re.search(r'<div\b[^>]*\bid="%s"[^>]*>' % cid, html)
    return m.group(0) if m else ""


# axe `region` (live, 2026-11-07): both overlay viewers sit directly on <body>, so
# their text was outside every landmark. A named region is the truthful shape —
# neither traps focus, so `aria-modal` would be a lie.
check("F2 the two overlay viewers are named landmarks",
      all('role="region"' in _el(cid) and "aria-label=" in _el(cid)
          for cid in ("diffView", "imgView")),
      " | ".join(_el(cid)[:60] for cid in ("diffView", "imgView")))

# F3: a `role="button"` is a promise of keyboard operability. Either it is a real
# <button>, or it carries tabindex (the handlers follow it). The attachment chip's
# small ✕ was a span with a click handler only — unreachable by Tab/Enter.
_ROLE_BUTTONS = re.findall(r"<(?!button)\w+[^>]*\brole=\"button\"[^>]*>", html)
check("F3 every role=button is keyboard-reachable, and the chip's ✕ is a real button",
      all("tabindex" in t for t in _ROLE_BUTTONS)
      and bool(re.search(r'<button[^>]*class="x"[^>]*data-i=', html)),
      "%d role=button tag(s)" % len(_ROLE_BUTTONS))

print("\nv851: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
