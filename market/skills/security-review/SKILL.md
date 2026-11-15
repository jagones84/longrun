---
name: security-review
description: "Review a change for secrets, injection, unsafe shell and widened permissions before it ships. Trigger on 'security review', 'check this diff for security', 'is this safe to merge', 'look for secrets', 'audit this change', or any diff that adds a command, a URL, a credential or a permission check."
---

# Security review — one pass, evidence in hand

Review the DIFF, not the repository. Every finding names a file and a line. A finding
you cannot locate is not a finding: say `not found` and what you searched.

## 1. Collect the change

1. `git diff --stat` and `git diff` for the range under review; read the full diff first.
2. List every file that adds or changes: a command line, a URL, a regex used for
   validation, an environment variable, a permission or approval check.

## 2. The four questions, in this order

| # | question | what a finding looks like |
|---|---|---|
| 1 | **Secret** | a token/key/password literal, a logged header, a value echoed back in a response, a secret written to a tracked file |
| 2 | **Injection** | a shell string built from input, `eval`/`exec`, a SQL string concatenated, HTML inserted without escaping |
| 3 | **Egress** | a new outbound host, a redirect followed without re-checking the host, a URL taken from input |
| 4 | **Permission** | a check removed, a default flipped to allow, an approval skipped, a path bound widened |

## 3. Rules that decide

- **A secret is a finding even in a test.** Report the file and the rule, never the value.
- **Validate at the boundary only.** Flag validation that is duplicated deeper.
- **Fail closed.** A missing key, an unreachable host or an unparseable config must
  refuse, not fall back to the permissive path.
- **One owner.** If the change adds a second place that decides the same thing, that is
  a finding even when both currently agree.

## 4. Output

```
FINDINGS
- <severity: high|medium|low> <file>:<line> — <one sentence>
  why: <the sentence above, applied>
  fix: <the smallest change that removes it>

NOT FOUND
- secrets in <files reviewed>
- unvalidated shell in <files reviewed>

RESIDUAL RISK
- <what this review could not see: generated code, runtime config, third-party code>
```

Severity is about impact if exploited, not about effort. Never upgrade a finding to
look thorough, and never downgrade one because the fix is large.
