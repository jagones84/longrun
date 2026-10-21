#!/usr/bin/env python3
"""v527 — deterministic price refresh + hot reload (JAG-527).

The Cost panel's "refresh prices" action updates BOTH sources: OpenRouter's
public model list (the cache) AND `config/prices.yaml` from DeepSeek's OFFICIAL
pricing table. The second one must be deterministic: it parses the table, checks
that cache-hit < cache-miss < output for every model, and writes ONLY when the
whole shape validates — a changed/partial page can never install a wrong price.

The table must also be HOT: a new mtime on any source is picked up by the next
`price_for()`, with no restart. And a price change is never retroactive: the
ledger stores the USD of each call when it happens.

Deterministic: a file:// fixture, no network, no model.
Run: python3 tests/acceptance/v527_prices_refresh.py
"""
import os
import sys
import tempfile
from pathlib import Path

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v527-")
YAML = os.path.join(TMP, "prices.yaml")
os.environ["LONGRUN_PRICES_YAML"] = YAML
os.environ["LONGRUN_PRICES_FILE"] = os.path.join(TMP, "cache.json")
os.environ["LONGRUN_COSTS_DIR"] = os.path.join(TMP, "costs")
os.environ.pop("LONGRUN_PRICES", None)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.model import costs as C  # noqa: E402

# A missing implementation must FAIL the checks, not crash the file: this is the
# pre-fix state (RED) and it still has to report a count.
_refresh = getattr(C, "refresh_deepseek_prices",
                   lambda **kw: {"ok": False,
                                 "error": "refresh_deepseek_prices not implemented"})

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def page(models, peak_rows, header="MODEL"):
    """A minimal copy of the official table's shape (rowspans included)."""
    html = '<table><tr><td colspan="3">%s</td>' % header
    html += "".join("<td>%s<sup>(1)</sup></td>" % m for m in models) + "</tr>"
    for label, vals in peak_rows:
        html += ('<tr><td rowspan="6">PRICING</td><td rowspan="2">%s</td>'
                 "<td>OFF-PEAK</td>%s</tr>" % (label, "".join(
                     "<td>$%g</td>" % (float(v) / 2) for v in vals)))
        html += "<tr><td>PEAK</td>%s</tr>" % "".join("<td>$%s</td>" % v for v in vals)
    return html + "</table>"


CACHE_HIT = "1M INPUT TOKENS<br>(CACHE HIT)"
CACHE_MISS = "1M INPUT TOKENS<br>(CACHE MISS)"
OUTPUT = "1M OUTPUT TOKENS"

# An entry the official page does NOT list must survive a refresh.
write(YAML, "legacy/keep-me:\n  in: 9\n  out: 18\n")
check("A1 the fixture YAML is loaded", C.price_for("legacy/keep-me") == (9.0, 18.0),
      str(C.price_for("legacy/keep-me")))

fixture = write(os.path.join(TMP, "pricing.html"),
                page(["deepseek-flash", "deepseek-v4-pro"],
                     [(CACHE_HIT, ["0.006", "0.044"]),
                      (CACHE_MISS, ["0.3", "1.32"]),
                      (OUTPUT, ["1.2", "3.96"])]))
res = _refresh(url=Path(fixture).as_uri())
check("A2 the official table refreshes", bool(res.get("ok")), str(res))
check("A3 the parsed model is priced at its PEAK rates",
      C.price_for("deepseek-flash") == (0.3, 1.2), str(C.price_for("deepseek-flash")))
check("A4 the cache-hit rate is carried too",
      (C.rates_for("deepseek-flash") or {}).get("cache_read") == 0.006,
      str(C.rates_for("deepseek-flash")))
check("A5 the legacy provider ids follow the Flash price",
      C.price_for("deepseek-reasoner") == (0.3, 1.2)
      and C.price_for("deepseek-chat") == (0.3, 1.2),
      str(C.price_for("deepseek-reasoner")))
check("A6 an entry the page does not list is preserved",
      C.price_for("legacy/keep-me") == (9.0, 18.0), str(C.price_for("legacy/keep-me")))

# --- hot reload: edit the file, no restart, no explicit cache reset ----------
before = open(YAML, encoding="utf-8").read()
after = before.replace("deepseek-flash:\n  in: 0.3\n  out: 1.2",
                       "deepseek-flash:\n  in: 0.7\n  out: 1.4")
check("B1 the hot-reload fixture actually changed the file", after != before)
write(YAML, after)
check("B2 a new file mtime is picked up by the NEXT lookup",
      C.price_for("deepseek-flash") == (0.7, 1.4), str(C.price_for("deepseek-flash")))

# --- a changed price is NOT retroactive -------------------------------------
rec_old = C.record("led", "deepseek-flash", {"prompt_tokens": 1000000,
                                            "completion_tokens": 0})
check("C1 a call is priced with the table in force at that moment",
      bool(rec_old) and rec_old.get("usd") is not None
      and abs(rec_old["usd"] - 0.7) < 1e-9, str(rec_old))
fixture2 = write(os.path.join(TMP, "pricing2.html"),
                 page(["deepseek-flash"],
                      [(CACHE_HIT, ["0.006"]), (CACHE_MISS, ["0.6"]),
                       (OUTPUT, ["2.4"])]))
res2 = _refresh(url=Path(fixture2).as_uri())
check("C2 a later refresh installs the new price", bool(res2.get("ok"))
      and C.price_for("deepseek-flash") == (0.6, 2.4), str(C.price_for("deepseek-flash")))
rec_new = C.record("led", "deepseek-flash", {"prompt_tokens": 1000000,
                                            "completion_tokens": 0})
check("C3 a NEW call uses the new price",
      bool(rec_new) and rec_new.get("usd") is not None
      and abs(rec_new["usd"] - 0.6) < 1e-9, str(rec_new))
_recent = C.summary("led")["recent"]
_stored_old = [r for r in _recent if r.get("usd") is not None and abs(r["usd"] - 0.7) < 1e-9]
check("C4 the previous call keeps the price it was charged at",
      len(_stored_old) == 1, str([r.get("usd") for r in _recent]))

# --- the procedure refuses to write anything it cannot validate -------------
good = open(YAML, encoding="utf-8").read()
bad_pages = [
    ("only two PEAK rows", page(["deepseek-flash"],
                                [(CACHE_HIT, ["0.006"]), (CACHE_MISS, ["0.3"])])),
    ("cache-hit above cache-miss", page(["deepseek-flash"],
                                        [(CACHE_HIT, ["9"]), (CACHE_MISS, ["0.3"]),
                                         (OUTPUT, ["1.2"])])),
    ("no model header", page([], [], header="PRICES")),
]
for label, html in bad_pages:
    p = write(os.path.join(TMP, "bad.html"), html)
    r = _refresh(url=Path(p).as_uri())
    check("D1 %s -> error, never a raise" % label,
          r.get("ok") is False and bool(r.get("error")), str(r))
    check("D2 %s -> the YAML is untouched" % label,
          open(YAML, encoding="utf-8").read() == good)

r_net = _refresh(url="http://127.0.0.1:1/pricing", timeout=2)
check("E1 an unreachable source returns an error, never raises",
      r_net.get("ok") is False and "error" in r_net, str(r_net))

# --- the Cost panel exposes the action --------------------------------------
with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
    ui = f.read()
check("F1 the Cost panel has a refresh-prices button",
      'id="costRefresh"' in ui and "refresh prices" in ui)
check("F2 the handler reports BOTH sources (no vague 'done')",
      "r.openrouter" in ui and "r.deepseek" in ui and "/api/costs/refresh" in ui)
with open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"), encoding="utf-8") as f:
    api = f.read()
check("F3 the route runs the deterministic two-source refresh",
      "costs.refresh_prices()" in api)

print("---")
ok = sum(results)
print("v527: %d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
