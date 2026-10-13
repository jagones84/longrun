"""v445 — chat attachments stay OPENABLE after a reload (JAG-431r11).

The live send built clickable attachment chips from the in-memory snapshot, but a
RELOAD only STRIPPED the model-facing attachment preamble off the stored user
message — so an old attachment (image or file) had nothing to click, and the ones
that did were dead. Now the same block is parsed back into
{kind,label,value} chips and re-bound, in the history render path too.

Deterministic, offline (the block parsing is mirrored in Python to prove the regex
handles BOTH real dash variants found in stored sessions: U+2014 and '-').
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


HTML = _read("webui", "index.html")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# --- 1) the helper exists + both render paths use it ------------------------
check("1a a _splitAttBlock() helper exists",
      "function _splitAttBlock(content)" in HTML, "")
check("1b the live send path builds clickable chips from the snapshot",
      "_attachmentChips(_attSnap)" in HTML and "_bindAttachmentChips(_bub)" in HTML, "")
check("1c the RELOAD path rebuilds the chips too (not just strips the block)",
      "_splitAttBlock(m.content)" in HTML
      and "_attachmentChips(_sp.atts)" in HTML
      and "_bindAttachmentChips(_ub)" in HTML, "")
check("1d chips are bound for BOTH click and keyboard",
      'el.onclick = go' in HTML and "el.onkeydown" in HTML, "")

# --- 2) functional: parse the REAL stored formats ---------------------------
_RX = re.compile(r"^The user attached the following[^\n]*\n((?:-[^\n]*\n)+)")


def _split(content):
    """Mirror of the JS _splitAttBlock: (values, rest)."""
    m = _RX.match(content)
    if not m:
        return [], content
    vals = [re.sub(r"^-\s*", "", ln).strip() for ln in m.group(1).split("\n") if ln]
    return vals, content[m.end():].lstrip("\n")


EM = ("The user attached the following \u2014 read/consider them FIRST:\n"
      "- file: /home/jagones/x/Anatomia.pdf\n\nmake a summary of the atatchment")
HY = ("The user attached the following - read/consider them FIRST:\n"
      "- file: /home/jagones/x/shot.png\n\ndescribe it")
TXT = ("The user attached the following \u2014 read/consider them FIRST:\n"
       "- some pasted note\n\nuse it")

a_em, r_em = _split(EM)
a_hy, r_hy = _split(HY)
a_tx, r_tx = _split(TXT)
check("2a the em-dash block parses to one file + the clean user text",
      a_em == ["file: /home/jagones/x/Anatomia.pdf"] and r_em == "make a summary of the atatchment",
      str(a_em) + " | " + r_em)
check("2b the hyphen variant (older sessions) parses too",
      a_hy == ["file: /home/jagones/x/shot.png"] and r_hy == "describe it", str(a_hy))
check("2c a pasted-text attachment stays a (text) chip",
      a_tx == ["some pasted note"] and r_tx == "use it", str(a_tx))
check("2d a plain message is left untouched (no false split)",
      _split("just a normal message") == ([], "just a normal message"), "")

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)