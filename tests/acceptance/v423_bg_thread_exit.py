#!/usr/bin/env python3
"""v423 — background refresh threads must not die mid-libcrypto at exit.

`context_budget()` -> `providers.local_contexts()` used to spawn a bare
`daemon=True` thread that runs `urllib.request.urlopen` (-> SSL -> libcrypto).
At interpreter exit the main thread runs `exit()` -> `_dl_fini`, which UNLOADS
libcrypto while that daemon thread is still inside it -> SIGSEGV. Reproduced with
gdb (crash thread's stack: `X509_STORE_set_default_paths_ex` <- `_ssl`). ~80% of
short-lived `v258` runs died with exit 139 AFTER printing 7/7 PASS.

The fix routes these refreshes through `providers._spawn_bg`, which tracks the
thread and joins it from an `atexit` hook (runs during finalisation, BEFORE the
shared libraries are unloaded). This pins that mechanism.

Deterministic, no live server. Run: python3 tests/acceptance/v423_bg_thread_exit.py
"""
import os
import sys
import threading
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# capture the atexit registration made at import time of providers.
import atexit  # noqa: E402
_regs = []
_real_register = atexit.register
atexit.register = lambda fn, *a, **k: (_regs.append(fn), fn)[1]
try:
    from longrun.model import providers as P     # noqa: E402
finally:
    atexit.register = _real_register

check("1 the provider refresh threads are joined at interpreter exit",
      P._join_bg in _regs)
check("2 the joiner is bounded (a hung fetch cannot hang shutdown forever)",
      isinstance(P._BG_JOIN_TIMEOUT, (int, float)) and 0 < P._BG_JOIN_TIMEOUT <= 60)

# static: no bare daemon thread is started anymore in providers.py
with open(os.path.join(REPO, "src", "longrun", "model", "providers.py"), encoding="utf-8") as f:
    src = f.read()
check("3 local_contexts no longer spawns a bare daemon",
      "threading.Thread(target=lambda: local_contexts" not in src)
check("4 warm() no longer spawns a bare daemon",
      "threading.Thread(target=_run, daemon=True)" not in src)
check("5 both refresh sites go through the tracked spawner",
      src.count("_spawn_bg(") >= 3)   # def + 2 call sites


# behaviour: a tracked thread is registered while alive and removed when done.
done = threading.Event()


def _slow():
    time.sleep(0.25)
    done.set()


P._spawn_bg(_slow, name="v423-probe")
check("6 a live tracked thread is present in the registry",
      any(t.name == "v423-probe" for t in list(P._BG_THREADS)))
done.wait(2.0)
time.sleep(0.05)
check("7 a finished tracked thread is removed from the registry",
      not any(t.name == "v423-probe" for t in list(P._BG_THREADS)))
check("8 _join_bg() joins the registered threads without raising",
      P._join_bg() is None)

print("---")
okc = sum(results)
print("\nv423: %d/%d PASS" % (okc, len(results)))
sys.exit(0 if okc == len(results) else 1)
