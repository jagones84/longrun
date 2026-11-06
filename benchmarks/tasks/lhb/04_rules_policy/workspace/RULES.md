# Project rules (read before working)

R1 — Every deliverable lives under `out/`. Nothing else may be created or modified.
R2 — Each input `data/in/NN.json` becomes `out/items/item__NN.csv` with the header
     `id,value` and one row per item **in the input order**. `value` is an integer:
     strip surrounding whitespace and convert it.
R3 — `out/MANIFEST.json` is `{"version": 1, "files": {<relative path>: <sha256>}}`
     for EVERY file under `out/` except the manifest itself. Paths are relative to
     `out/` (for example `items/item__01.csv`).
R4 — `out/DECISIONS.md` contains one line per rule id, each starting at column 1:
     `R1: ...`, `R2: ...`, `R3: ...`, `R4: ...`.
R5 — No file whose name ends in `.tmp` may exist anywhere in the workspace.
R6 — `data/` and this file are read-only.
