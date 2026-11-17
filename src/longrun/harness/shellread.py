#!/usr/bin/env python3
"""Is a shell command PURE — does re-running it change only what the agent sees?

Two questions live here, and they are different questions:

* `looks_read_only` — *"did the turn re-OPEN what it wrote?"* A **hint** for the
  read-back gate, moved here from `agent.py` with its truth table unchanged:
  one segment whose first word is a reader, and no write hint anywhere.
* `reads_only` — *"may this command be RE-EXECUTED as a counterfactual?"* A
  **gate**. Every segment must be provably pure, so the answer is yes only for
  the allowlist below, with no redirect, no command substitution and no
  verb-specific side channel (`sort -o`, `find -delete`, `sed -i`,
  `git diff --output=…`).

Why purity is the precondition: a counterfactual replays ONE intervention and
holds everything else fixed (REFLECT, arXiv:2606.09071 — diagnosis-specific
patch, outcome flip as evidence; exact attribution by deterministic replay with
all descendants *pure*, which is bit-exact and costs no model call). A mutating
step is not an intervention, it is a second experiment: the replayed write
duplicates the effect it was meant to hold constant.

Fail-closed by construction: an unknown verb, a redirect, a `$(…)`, a backtick, a
process substitution or an unparseable segment all answer False. A false negative
costs one un-replayable card; a false positive duplicates an effect.

Pure module: no server import, no model, no store write.
"""
import os
import re
import shlex

# --------------------------------------------------------------- hint ---------
# Moved verbatim from `agent.py`: the read-back gate asks "does this look like a
# read?", and its own docstring says it is "never for attributing a file to a
# turn". It stays deliberately lenient; `reads_only` below is the strict gate.
#: First word of a shell segment that only LOOKS at bytes.
_LOOKS_READ_VERBS = ("cat", "head", "tail", "od", "xxd", "less", "more",
                     "cmp", "diff", "jq")
#: Anything that could WRITE inside a shell segment disqualifies it.
_LOOKS_WRITE_HINTS = (">", "tee ", "rm ", "mv ", "cp ", "ln ", "chmod ", "chown ",
                      "sed -i", "truncate ", "dd ")


def looks_read_only(command):
    """True when NO segment of `command` can write and at least one only reads."""
    text = str(command or "")
    if not text.strip() or any(h in text for h in _LOOKS_WRITE_HINTS):
        return False
    for seg in re.split(r"&&|\|\||[;|\n]", text):
        words = seg.strip().split()
        if words and os.path.basename(words[0]) in _LOOKS_READ_VERBS:
            return True
    return False


# --------------------------------------------------------------- gate ---------
#: Verbs whose own execution has no environment effect (stdout only). `cd` is
#: here on purpose: it changes the SHELL's directory, and the replay runs the same
#: `cd X && …` from the same workspace, so the fact under test is unchanged.
READ_VERBS = frozenset((
    "ls", "cat", "head", "tail", "wc", "stat", "file", "du", "df",
    "md5sum", "sha1sum", "sha256sum", "sha512sum", "cksum", "cmp", "diff",
    "diffstat", "nl", "cut", "tr", "uniq", "strings", "od", "xxd", "hexdump",
    "tree", "realpath", "basename", "dirname", "pwd", "printenv", "which",
    "type", "grep", "egrep", "fgrep", "jq", "column", "fold", "paste", "comm",
    "echo", "printf", "true", "false", "test", "[", "uname", "hostname", "id",
    "whoami", "groups", "locale", "sleep", "cd",
))

#: `git` subcommands that only read the repository. Anything else (commit,
#: checkout, stash, gc, config <key> <value>) can change it.
GIT_READ_SUBCOMMANDS = frozenset((
    "status", "log", "diff", "show", "rev-parse", "ls-files", "blame",
    "cat-file", "describe", "show-ref", "rev-list", "shortlog", "ls-tree",
    "grep", "count-objects", "whatchanged", "name-rev",
))

#: The ONE redirection that changes nothing durable: stderr discarded or merged
#: into stdout. `cmd 2>/dev/null | head` is the ordinary shape of a diagnostic
#: command (356 of 1076 live commands carried a `>`), and refusing every one of
#: them would make the gate look broken. Stripped BEFORE the deny check, so
#: `cmd 2>&1 > file` still fails on the surviving `>`, and `> /dev/null/x` does not
#: match (`(?![\w/])`).
_STDERR_DISCARD = re.compile(r"\s*(?:[12]?>\s*/dev/null|[12]>&1)(?![\w/])")


def _segments(text):
    """Split on `;`, `&&`, `||`, `|`, `&` and newline, respecting quotes."""
    out, cur, quote, i = [], [], None, 0
    while i < len(text):
        ch = text[i]
        if quote:
            cur.append(ch)
            if ch == quote and (i == 0 or text[i - 1] != "\\"):
                quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            cur.append(ch)
            i += 1
            continue
        if text.startswith("&&", i) or text.startswith("||", i):
            out.append("".join(cur))
            cur = []
            i += 2
            continue
        if ch in ";|&\n":
            out.append("".join(cur))
            cur = []
            i += 1
            continue
        cur.append(ch)
        i += 1
    out.append("".join(cur))
    return [s.strip() for s in out if s.strip()]


def _has(args, *needles):
    return any(a == n or a.startswith(n + "=") or a.startswith(n)
               for a in args for n in needles)


#: A sed script that only PRINTS: an optional single address (`3`, `1,5`, `$`,
#: `/re/`) followed by `p`. Everything else is refused — `s///w file` writes and
#: `s///e` executes, and telling them apart inside the sed language is exactly the
#: kind of regex guessing this module refuses to do.
_SED_ADDR = r"(?:[\d$]+|/[^/]*/)"
_SED_PRINT = re.compile(r"^(?:%s(?:,%s)?)?p$" % (_SED_ADDR, _SED_ADDR))


def _sed_script(rest):
    """The script argument of a sed argv (after `-n` / `-e`), '' when absent."""
    script, i = "", 0
    while i < len(rest):
        a = rest[i]
        if a in ("-n", "--quiet", "--silent"):
            i += 1
            continue
        if a in ("-e", "--expression"):
            if i + 1 < len(rest):
                script = rest[i + 1]
            i += 2
            continue
        if a.startswith("--expression="):
            script = a.split("=", 1)[1]
            i += 1
            continue
        if a.startswith("-"):
            i += 1
            continue
        if not script:
            script = a
        i += 1
    return script


def _verb_reason(argv):
    """'' when this one segment is pure, else why it is not."""
    verb = os.path.basename(str(argv[0]))
    rest = list(argv[1:])
    if verb not in READ_VERBS and verb not in ("sort", "sed", "find", "git", "date"):
        return "%r is not a read-only verb" % verb
    if any("--output" in a for a in rest):
        return "%r accepts --output, which writes" % verb
    if verb == "sort":
        # `sort -o FILE` writes FILE (the only side channel sort has).
        if _has(rest, "-o"):
            return "sort -o writes its output to a file"
    elif verb == "sed":
        if _has(rest, "-i", "--in-place"):
            return "sed -i edits the file in place"
        if _has(rest, "-f", "--file"):
            return "sed -f loads a script file"
        if not _has(rest, "-n", "--quiet", "--silent"):
            return "sed without -n echoes the whole file; only an addressed print is pure"
        script = _sed_script(rest)
        if not _SED_PRINT.match(script or ""):
            return "sed script %r is not an addressed print" % (script[:40],)
    elif verb == "find":
        if any(a in ("-delete", "-exec", "-execdir", "-ok", "-okdir")
               or a.startswith("-fprint") or a.startswith("-fls") for a in rest):
            return "find with -delete/-exec/-fprint writes"
    elif verb == "git":
        sub = rest[0] if rest else ""
        if sub not in GIT_READ_SUBCOMMANDS:
            return "git %r is not a read-only subcommand" % (sub or "(none)")
    elif verb == "date":
        if _has(rest, "-s", "--set"):
            return "date -s sets the clock"
    elif verb == "tree":
        if _has(rest, "-o"):
            return "tree -o writes a file"
    return ""


def reads_only(command):
    """(pure, reason) for a shell command string — the counterfactual gate.

    `pure` is True only when EVERY segment is on the read-only allowlist, with no
    redirect and no substitution anywhere. `reason` names the first disqualifier,
    so a refused card can say why instead of silently disappearing.
    """
    text = str(command or "")
    if not text.strip():
        return False, "empty command"
    for bad in ("$(", "${", "`", "<(", ">("):
        if bad in text:
            return False, "contains %r (command or process substitution)" % bad
    text = _STDERR_DISCARD.sub("", text)
    for bad in (">", "<"):
        if bad in text:
            return False, "contains %r (redirection)" % bad
    segs = _segments(text)
    if not segs:
        return False, "empty command"
    for seg in segs:
        try:
            argv = shlex.split(seg, posix=True)
        except ValueError as exc:
            return False, "unparseable segment %r (%s)" % (seg[:40], exc)
        if not argv:
            return False, "empty segment"
        why = _verb_reason(argv)
        if why:
            return False, why
    return True, "pure: %d segment(s)" % len(segs)
