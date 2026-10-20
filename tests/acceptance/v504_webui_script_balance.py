#!/usr/bin/env python3
"""Bracket balance of the WebUI inline script (JAG-504).

A single extra `)` in the classic inline script kills the WHOLE app: the script
never parses, so no function is defined — no sessions, no panels, no buttons.
That is exactly what shipped once. This checker tokenizes the inline script
(strings, TEMPLATE literals with `${…}` interpolation, comments, regex literals)
and reports a closer with no opener, or an opener left unclosed at EOF.

Exit 0 = balanced, 1 = broken. Deterministic, stdlib only, no JS runtime needed.
"""
import io
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PAIRS = {")": "(", "}": "{", "]": "["}
# a `/` starts a REGEX (not a division) after one of these characters …
REGEX_AFTER = set("(,=:[!&|?{};+-*%<>~^")
# … or after one of these words
REGEX_WORDS = {"return", "typeof", "case", "in", "of", "do", "else", "void",
               "delete", "throw", "new", "instanceof", "yield", "await"}


def inline_scripts(html):
    """Every inline <script> body (blocks with a src= are external)."""
    out, i = [], 0
    while True:
        s = html.find("<script", i)
        if s < 0:
            return out
        e = html.find(">", s)
        if e < 0:
            return out
        close = html.find("</script>", e)
        if close < 0:
            return out
        if "src=" not in html[s:e + 1]:
            out.append(html[e + 1:close])
        i = close + 9


def scan(src):
    """Return (problems, unclosed); problems are (line, col, message)."""
    problems, stack = [], []
    frames = ["code"]          # "code" | "template" | "interp"
    interp_depth = [0]         # brace depth inside each "interp" frame
    i, n, line, col = 0, len(src), 1, 0
    prev_sig, word = "", ""

    def at(ln, cl, msg):
        problems.append((ln, cl, msg))

    while i < n:
        ch = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if ch == "\n":
            line += 1
            col = 0
        else:
            col += 1

        if frames[-1] == "template":
            if ch == "\\":
                i += 2
                continue
            if ch == "`":
                frames.pop()
                prev_sig = "`"
                i += 1
                continue
            if ch == "$" and nxt == "{":
                frames.append("interp")
                interp_depth.append(0)
                prev_sig = "{"
                i += 2
                continue
            i += 1
            continue

        if ch == "/" and nxt == "/":
            j = src.find("\n", i)
            i = n if j < 0 else j
            continue
        if ch == "/" and nxt == "*":
            j = src.find("*/", i + 2)
            if j < 0:
                i = n
                continue
            segment = src[i:j + 2]
            line += segment.count("\n")
            col = len(segment) - segment.rfind("\n") if "\n" in segment else col + len(segment)
            i = j + 2
            continue
        if ch in "'\"":
            q = ch
            i += 1
            while i < n:
                c = src[i]
                if c == "\\":
                    i += 2
                    continue
                if c == q:
                    i += 1
                    break
                if c == "\n":
                    line += 1
                    col = 0
                i += 1
            prev_sig = q
            continue
        if ch == "`":
            frames.append("template")
            i += 1
            continue
        if ch == "/" and (prev_sig == "" or prev_sig in REGEX_AFTER or word in REGEX_WORDS):
            i += 1
            while i < n:
                c = src[i]
                if c == "\\":
                    i += 2
                    continue
                if c == "/":
                    i += 1
                    break
                if c == "\n":
                    break
                i += 1
            while i < n and src[i].isalpha():
                i += 1
            prev_sig = "/"
            word = ""
            continue

        if frames[-1] == "interp":
            if ch == "{":
                interp_depth[-1] += 1
            elif ch == "}":
                if interp_depth[-1] == 0:
                    frames.pop()
                    interp_depth.pop()
                    prev_sig = "}"
                    i += 1
                    continue
                interp_depth[-1] -= 1

        if ch in "({[":
            stack.append((ch, line, col))
            word = ""
        elif ch in ")}]":
            if not stack:
                at(line, col, "closer %r with no opener" % ch)
            elif stack[-1][0] != PAIRS[ch]:
                at(line, col, "%r closes %r opened at line %d"
                   % (ch, stack[-1][0], stack[-1][1]))
                stack.pop()
            else:
                stack.pop()
            word = ""
        elif ch.isalnum() or ch in "_$":
            word += ch
        elif not ch.isspace():
            word = ""
        if not ch.isspace():
            prev_sig = ch
        i += 1
    return problems, stack


def check_file(path):
    html = io.open(path, encoding="utf-8").read()
    ok, blocks = True, 0
    for idx, src in enumerate(inline_scripts(html)):
        if len(src.strip()) < 200:
            continue
        blocks += 1
        problems, unclosed = scan(src)
        if problems:
            ok = False
            print("FAIL block %d: %d problem(s)" % (idx, len(problems)))
            for ln, cl, why in problems[:5]:
                print("   line %d col %d: %s" % (ln, cl, why))
        if unclosed:
            ok = False
            print("FAIL block %d: %d unclosed opener(s) at EOF: %s"
                  % (idx, len(unclosed), [(c, l) for c, l, _ in unclosed[-5:]]))
    if not blocks:
        print("FAIL no inline script found")
        return False
    return ok


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else os.path.join(REPO, "webui", "index.html")
    good = check_file(target)
    print("OK balanced" if good else "BROKEN")
    sys.exit(0 if good else 1)
