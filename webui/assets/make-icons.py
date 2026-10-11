#!/usr/bin/env python3
"""Generate the Longrun PWA icons (JAG-390).

Dev-only build script (needs Pillow). Draws the Longrun mark — a STYLIZED
RUNNING MAN — in the brand gradient on a dark rounded tile, and writes the PNG
icons referenced by `webui/manifest.webmanifest` into `webui/assets/`.
Run from anywhere:

    python3 webui/assets/make-icons.py

The `.py` extension is NOT in the served asset whitelist, so this script is
never exposed over HTTP.
"""
import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
BG = (10, 12, 20, 255)      # --bg / dark shell
A1 = (139, 123, 240)        # --accent  #8b7bf0
A2 = (181, 108, 255)        # #b56cff

# The runner, in a 0..1 unit box: a head disc + round-capped limb/torso strokes.
HEAD = (0.585, 0.145, 0.085)            # cx, cy, r
LIMBS = [
    [(0.545, 0.26), (0.44, 0.55)],                  # torso  (shoulder -> hip)
    [(0.545, 0.27), (0.70, 0.35), (0.78, 0.26)],    # front arm
    [(0.545, 0.27), (0.40, 0.39), (0.26, 0.31)],    # back arm
    [(0.44, 0.55), (0.63, 0.56), (0.71, 0.73)],     # front leg (forward stride)
    [(0.44, 0.55), (0.26, 0.68), (0.10, 0.58)],     # back leg  (extended)
]
LW = 0.075                  # stroke width, unit


def _runner_mask(size, pad_frac):
    """(L) mask with the runner drawn and fitted into the padded square."""
    pad = size * pad_frac
    box = size - 2 * pad
    hw = LW / 2.0
    cx, cy, r = HEAD

    xs, ys = [], []
    for pl in LIMBS:
        for x, y in pl:
            xs += [x - hw, x + hw]
            ys += [y - hw, y + hw]
    xs += [cx - r, cx + r]
    ys += [cy - r, cy + r]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)

    s = box / max(x1 - x0, y1 - y0)                 # keep aspect ratio
    ox = pad + (box - (x1 - x0) * s) / 2.0 - x0 * s
    oy = pad + (box - (y1 - y0) * s) / 2.0 - y0 * s

    def t(x, y):
        return ox + x * s, oy + y * s

    m = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(m)
    w = max(2, int(round(LW * s)))
    for pl in LIMBS:
        pts = [t(x, y) for x, y in pl]
        d.line(pts, fill=255, width=w, joint="curve")
        for px, py in pts:                          # round caps at every joint
            d.ellipse([px - w / 2.0, py - w / 2.0, px + w / 2.0, py + w / 2.0], fill=255)
    px, py = t(cx, cy)
    rr = r * s
    d.ellipse([px - rr, py - rr, px + rr, py + rr], fill=255)
    return m


def _gradient(size):
    g = Image.new("RGB", (size, size))
    d = ImageDraw.Draw(g)
    for y in range(size):
        f = y / (size - 1)
        d.line([(0, y), (size, y)],
               fill=tuple(int(A1[i] + (A2[i] - A1[i]) * f) for i in range(3)))
    return g


def make(size, pad_frac, rounded, name):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    bg = ImageDraw.Draw(img)
    if rounded:
        bg.rounded_rectangle([0, 0, size - 1, size - 1], radius=int(size * 0.22), fill=BG)
    else:
        bg.rectangle([0, 0, size - 1, size - 1], fill=BG)
    img.paste(_gradient(size), (0, 0), _runner_mask(size, pad_frac))
    path = os.path.join(HERE, name)
    img.save(path)
    print("wrote", path, "%dx%d" % (size, size))


make(192, 0.16, True, "icon-192.png")
make(512, 0.16, True, "icon-512.png")
make(512, 0.24, False, "icon-maskable-512.png")
make(180, 0.16, False, "apple-touch-icon.png")
