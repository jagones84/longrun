---
name: sql-review
description: "Review a SQL query or a schema change for correctness, cost and safety before it runs on real data. Trigger on 'review this query', 'is this SQL correct', 'why is this query slow', 'check this migration', 'add an index', 'explain plan'."
---

# SQL review — correctness first, then cost

Read the query and the schema it targets. A review without the table definitions is a
guess: ask for `\\d <table>` (Postgres) or `PRAGMA table_info(<table>)` (SQLite) first.

## 1. Correctness (stop here if any fails)

- **Join fan-out** — does a one-to-many join duplicate rows the caller counts?
- **NULL semantics** — `NOT IN` with a NULL in the list returns nothing; `COUNT(col)`
  skips NULLs while `COUNT(*)` does not.
- **Filter placement** — a predicate in `WHERE` on the right side of a `LEFT JOIN`
  silently turns it into an inner join; it belongs in the `ON` clause.
- **Truncation** — `LIMIT` without `ORDER BY` returns a different set each run.
- **Timezone / type** — comparing a timestamp to a date string, or text to a number.

## 2. Cost

1. Ask for the plan: `EXPLAIN (ANALYZE, BUFFERS)` or `EXPLAIN QUERY PLAN`.
2. Name the scan: sequential scan on a large table, a nested loop over an unindexed
   column, a sort that spills to disk.
3. Every proposed index names the query it serves and the column order that matches
   the predicate and the `ORDER BY` — a wrong order is a wasted index.

## 3. Safety on real data

- **A write needs a `WHERE` you have tested with a `SELECT` first**, and the same
  predicate in both.
- **A migration is two steps** when the table is live: add nullable, backfill, then
  enforce — never a blocking rewrite in one statement.
- **DDL locks** — say which lock the statement takes and for how long.

## 4. Output

```
VERDICT: correct | wrong | unsafe | unknown
CORRECTNESS
- <issue> at <clause> — <why it changes the result>
COST
- <plan node> on <table> — <rows/loops> · <the index that fixes it, in column order>
SAFETY
- <what could touch more rows than intended, and the SELECT that proves the scope>
```

`unknown` is a valid verdict: it means the schema or the plan was not available, and it
is always better than a confident guess.
