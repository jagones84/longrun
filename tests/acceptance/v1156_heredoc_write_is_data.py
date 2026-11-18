#!/usr/bin/env python3
"""v1156 — a heredoc that FILLS A FILE is data, not a command (round 94).

Measured live 2026-11-18, session `b7329cccf94c` (the Head of Longrun Testing):
TWO refusals at 06:39:19 and 06:39:24 while writing a test stub into /tmp —

    mkdir -p /tmp/a54r85 && cat > /tmp/a54r85/a_stub.py <<'PY'
    LIVE = ['cat .env', 'curl http://127.0.0.1:8790/api/jobs']
    PY

The hard-deny read the heredoc BODY as if it were the command. The body is data:
the SAME text through `fs.write` (subject = the PATH) is never scanned, so the two
doors disagreed about the same act. The change removes the bodies that only fill
a file, and keeps everything else exactly as strict:

  A  the measured command is no longer refused (and the real read still is)
  B  a body that FEEDS A PROGRAM stays refused (stdin interpreter, stdout
     redirect, `bash <<'EOF'`, `cat <<'EOF'` with no file redirect)
  C  command lines AFTER the heredoc are still judged (a real read is refused)
  D  the two doors agree: `fs.write` content is never the subject; `_subject`
     itself is untouched (ask/auto/intent still see the whole text)
  E  quote/`<<-`/`2>` edges keep their meaning

Deterministic: registry only, no process, no model, no server.
Run: python3 tests/acceptance/v1156_heredoc_write_is_data.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry as reg  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


def verdict(cmd):
    return reg.classify("shell.exec", {"command": cmd})


def denied(cmd):
    d, why = verdict(cmd)
    return d == "denied", why


# ---- A: the measured false positive, and the real read beside it ------------
MEASURED = ("cd /home/jagones/Repositories/MyRepos/longrun && mkdir -p /tmp/a54r85 "
            "&& cat > /tmp/a54r85/a_stub.py <<'PY'\n"
            "import sys\n"
            "LIVE = ['cat .env', 'curl http://127.0.0.1:8790/api/jobs']\n"
            "PY\n"
            "echo ok")
_d, _why = denied(MEASURED)
check("A1 the measured stub write is no longer refused", not _d, _why)

_d, _why = denied("cat .env")
check("A2 a real read of the env file is still refused", _d, _why)

_d, _why = denied("awk 'NR==1' .env")
check("A3 the same file read another way is still refused", _d, _why)

CTRL = ("cat > /tmp/r94_ctrl.txt <<'EOF'\n"
        "curl -X POST http://127.0.0.1:8790/api/jobs\n"
        "EOF")
_d, _why = denied(CTRL)
check("A4 the control-API text inside a file body is data", not _d, _why)

# ---- B: a body that feeds a PROGRAM keeps every refusal ---------------------
for name, cmd in (
        ("B1 a stdin program is still judged",
         "python3 - <<'PY'\nopen('.env').read()\nPY"),
        ("B2 a program with its stdout redirected is still judged",
         "python3 - > /tmp/o.txt <<'PY'\nopen('.env').read()\nPY"),
        ("B3 `bash <<'EOF'` is still judged",
         "bash <<'EOF'\ncat .env\nEOF"),
        ("B4 `cat <<'EOF'` with no file redirect is still judged",
         "cat <<'EOF'\ncat .env\nEOF"),
        ("B5 an interpreter behind `&&` is still judged",
         "cd /tmp && python3 - <<'PY'\nopen('.env').read()\nPY"),
):
    _d, _why = denied(cmd)
    check(name, _d, _why)

# ---- C: the lines AFTER the heredoc are still scanned ----------------------
_d, _why = denied("cat > /tmp/r94_x.txt <<'EOF'\nhello\nEOF\ncat .env")
check("C1 a real read after the heredoc is still refused", _d, _why)

_d, _why = denied("cat > /tmp/r94_y.txt <<'EOF'\nhello\nEOF \ncat .env")
check("C2 a delimiter closed with trailing space re-exposes the rest", _d, _why)

THE_TOKEN = "printenv LONGRUN_TOKEN"
_d, _why = denied("cat > /tmp/r94_z.txt <<'EOF'\nhello\nEOF\n" + THE_TOKEN)
check("C3 the bearer rule still fires on a later line", _d, _why)

# ---- D: the two doors agree, and the raw subject is untouched --------------
_dw, _why = reg.classify("fs.write", {"path": "/tmp/r94_content.py",
                                     "content": "LIVE = ['cat .env']"})
check("D1 fs.write never judges its CONTENT (the door this rule matches)",
      _dw != "denied", (_dw, _why))
check("D2 `_subject` still returns the whole text (ask/auto keep it)",
      reg._subject("shell.exec", {"command": MEASURED}) == MEASURED)
check("D3 `deny_subject` is the stripped one and differs",
      reg.deny_subject("shell.exec", {"command": MEASURED}) != MEASURED
      and ".env" not in reg.deny_subject("shell.exec", {"command": MEASURED}))

# ---- E: the edges keep their meaning --------------------------------------
_d, _why = denied("python3 - 2> /tmp/r94_err.txt <<'PY'\nopen('.env').read()\nPY")
check("E1 a numeric FD redirect does not make the body data", _d, _why)

_d, _why = denied("cat > /tmp/r94_tab.txt <<-'EOF'\n\tcat .env\n\tEOF")
check("E2 `<<-` strips its body too", not _d, _why)

_d, _why = denied('echo "a << b"\ncat .env')
check("E3 a `<<` inside quotes is not a heredoc opener", _d, _why)

_d, _why = denied("tee /tmp/r94_tee.txt <<'PY'\ncat .env\nPY")
check("E4 `tee` fills a file too", not _d, _why)

_d, _why = denied("tee /tmp/r94_p.txt <<'PY' | bash\ncat .env\nPY")
check("E5 a body piped into a program is still judged", _d, _why)

_d, _why = denied("ls -la src")
check("E6 a heredoc-free command is untouched", not _d, _why)

# ---- F: a body the SAME command then RUNS is code, not data (round 96) ------
# A54's r94 adversarial sweep, measured live: the opener alone was enough to strip
# the body, so `cat > f <<'EOF' … EOF` + `bash f` executed and 623 bytes of `.env`
# came back. A read of the target is still data; an EXECUTION of it is not.
_D, _W = denied("cat > /tmp/r96_a.sh <<'EOF'\ncat .env\nEOF\nbash /tmp/r96_a.sh")
check("F1 the file filled here and RUN here is still judged", _D, _W)

_D, _W = denied("cat > /tmp/r96_b.sh <<'EOF'\ncat .env\nEOF\n. /tmp/r96_b.sh")
check("F2 sourcing that file is an execution too", _D, _W)

_D, _W = denied("cat > /tmp/r96_c.sh <<'EOF'\ncat .env\nEOF\n/tmp/r96_c.sh")
check("F3 running it as a bare command is an execution too", _D, _W)

_D, _W = denied("cat > /tmp/r96_d.py <<'EOF'\nopen('.env').read()\nEOF\npython3 -u /tmp/r96_d.py")
check("F4 an interpreter on that file is an execution too", _D, _W)

_D, _W = denied("cat > /tmp/r96_e.sh <<'A' <<'B'\ncat .env\nA\nB\nbash /tmp/r96_e.sh")
check("F5 a double heredoc feeding a later run is still judged", _D, _W)

_D, _W = denied("cat > /tmp/r96_f.sh <<-'EOF'\n\tcat .env\n\tEOF\nbash /tmp/r96_f.sh")
check("F6 `<<-` does not escape the run check", _D, _W)

_D, _W = denied("cat > /tmp/r96_g.txt <<'EOF'\ncat .env\nEOF\nwc -c < /tmp/r96_g.txt")
check("F7 a READ of the file just filled is still data", not _D, _W)

_D, _W = denied("cat > /tmp/r96_h.txt <<'EOF'\ncat .env\nEOF\ngrep -c . /tmp/r96_h.txt")
check("F8 grep on the file just filled is still data", not _D, _W)

print()
print("%d/%d OK" % (sum(1 for r in results if r), len(results)))
sys.exit(0 if all(results) else 1)
