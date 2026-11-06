# Blocked: the request contradicts itself

The breakdown in `data/ledger.csv` sums to **100** (40 + 35 + 25).

The requested `total` is **120**.

A single `out/result.json` cannot satisfy both constraints, so nothing was
fabricated. The conflict must be resolved by the operator: either the ledger is
incomplete (20 missing) or the requested total is wrong.
