# LongRun verification report

## Scope and decision

This report checks whether LongRun is acceptable as an agentic harness. It combines the current static battery result with the live delegation, tool-contract, identity, and persistence probes recorded in the repository. No Nucleus source file was modified.

**Decision: not acceptable for unattended production use yet.** It remains potentially acceptable for controlled internal use while the observed defects are treated as release blockers.

## 1. Static regression gate

**CRITERION:** `bash tests/battery.sh` must terminate successfully and report `GREEN` with no failures.

**INPUT:**

```text
bash tests/battery.sh
```

**OBSERVED:** the command was run from `/home/jagones/Repositories/longrun` with a 120-second tool timeout. The tool reported `exit=124`, `timed_out=true`, and:

```text
=== battery: 458/471 (FAILURES — see above) ===
last full battery: never recorded
progress log: /home/jagones/Repositories/longrun/.agent/logs/battery-progress.log
```

The progress log records the completed aggregation:

```text
DONE  pass=458 total=471 fail=1 2026-11-03T20:33:43Z
```

A post-run process check found no remaining battery process. The launcher runs tests in isolated temporary data directories and aggregates each test return code (`tests/battery.sh:80-150`).

The failing test records are:

```text
END   v309_model_sync                            rc=1 2800ms
END   v414_self_diag                             rc=1 7293ms
END   v452_ui_kb_round                           rc=1 1398ms
END   v450_team_dispatch                         rc=1 2399ms
END   v539_agent_diagnostics_models              rc=1 12704ms
END   v584_closure_check                         rc=1 2305ms
END   v592_finish_gate                           rc=1 3295ms
END   v641_settings_ia                           rc=1 700ms
END   v643_harness_cards                         rc=1 596ms
END   v668_chat_taint                            rc=1 2698ms
END   v677_write_overlap                         rc=1 2998ms
END   v738_batch_shape_readonly_gate_voice       rc=1 3396ms
END   v757_inspect_arms                          rc=1 1099ms
```

**VERIFIED BY:** `.agent/logs/battery-progress.log:944`; captured command output; `tests/battery.sh:80-150`.

**ESITO: FAIL.** The static gate is not green.

## 2. Live delegation and identity probes

The existing probe report records the following live inputs and outputs:

- A49 designated `dispatch` returned exactly:

  ```text
  dispatching to teammates is not allowed here
  ```

  It produced zero A49 observations, so the designated-session path did not execute.

- A generic `subagent` returned:

  ```text
  LDD-SUB-3B8D1F6C9A2E7045 | agent_id=unknown | session_id=unknown | SUM=42
  ```

  The marker and arithmetic result were present, but the agent and session identities were not real.

**VERIFIED BY:** `trash/doubt-driven-probe-report.md:12-39`; the session JSONs and offload artifacts cited there.

**ESITO: FAIL** for designated dispatch and generic-subagent identity.

## 3. Tool and session introspection probes

Filtered `self.tools` calls requesting `fs.read`, `sessions.read`, and `self.info` all returned the same hint instead of a schema:

```text
[self.tools] exit=0 ok=True backend=host sandboxed=False
hint: paths, config, docs and the extension recipe: self.info (also in the system prompt)
```

A53 `self.info` returned:

```json
{"session_id":"vision-e2e-1791729815","role":null,"scope":"unrestricted","agent_id":"A53","agent_name":"misc test","trust":"standard"}
```

The agent and session IDs matched the live records, but `role` was null. The namespace catalog was global rather than scoped to the calling session. Todo `n68` was created and re-read with the same ID/state, so that persistence check passed.

**VERIFIED BY:** `trash/doubt-driven-probe-report.md:43-88`; session JSONs and offload artifacts cited there. The earlier cited report path was absent during this read-back, so this report relies on the still-present probe report and its cited session artifacts rather than claiming that missing path was re-read.

**ESITO:**

- `self.tools {tool:X}`: **FAIL**.
- `self.info` agent/session identity: **PARTIAL PASS**.
- `self.info` role and session-scoped namespaces: **FAIL**.
- Todo persistence: **PASS**.

## 4. Fresh-context adversarial review

Four isolated reviewers were attempted: `sub_f2582bbe0d`, `sub_49c520652d`, `sub_b59c954818`, and `sub_115cd0abf1`. All timed out without returning a verdict. The review is therefore recorded as **degraded self-review**, not as a completed fresh-context review.

## 5. Acceptance matrix

| Area | Concrete check | Current evidence | Status |
|---|---|---|---|
| Static regression gate | Battery exits 0 and prints GREEN | 458/471, fail=1; command timed out | **FAIL** |
| Designated delegation | Marked runs produce one observation per designated agent, correct session ID, no duplicates/delayed results | A49 dispatch rejected | **FAIL** |
| Generic delegation identity | Marked subagent returns real agent/session IDs | `agent_id=unknown`, `session_id=unknown` | **FAIL** |
| Tool schemas | Filtered calls return exactly one authoritative schema | Filtered calls returned the `self.info` hint | **FAIL** |
| Session introspection | `self.info` returns non-null role and session-scoped namespaces | `role=null`; namespaces global | **FAIL** |
| Todo persistence | Marker survives create/read/close | `n68` survived | **PASS** |
| Fresh-context review | Reviewer returns a verifiable verdict | Four reviewers timed out | **DEGRADED / NOT COMPLETE** |

## 6. Required evidence for production acceptance

LongRun would be acceptable for unattended production use only after all of the following are demonstrated:

1. `bash tests/battery.sh` exits 0 and reports `GREEN`.
2. At least 20 marked runs for each delegation path produce exactly one observation per agent, with the expected designated session ID and zero duplicates or delayed completions.
3. Filtered `self.tools` calls return exactly one matching schema; unfiltered calls return the full registry.
4. `self.info` returns non-null agent/session/role data and namespaces matching the calling session's grants.
5. Reload, restart, session switch, concurrent turns, large observations, and deleted-session transitions preserve every marker exactly once.
6. Unauthorized API/tool access returns `401` or `403`, with no secrets in logs or artifacts.
7. A fresh-context reviewer returns a verifiable verdict rather than timing out.

## 7. Limits

This is one static battery run plus n=1 live probes per live path. Authentication, anti-bot behavior, large batches, concurrent session switches, and the full battery were not completed in this verification. The live delegation result is an isolated observation, not a statistically representative rate.

## Sources

- `/home/jagones/Repositories/longrun/tests/battery.sh:80-150`
- `/home/jagones/Repositories/longrun/.agent/logs/battery-progress.log:944`
- `/home/jagones/Repositories/longrun/trash/doubt-driven-probe-report.md`
- `/home/jagones/Repositories/longrun/docs/TESTING-PLAYBOOK.md`
- `/home/jagones/.longrun/data/sessions/9b5db7c6a45f.json`
- `/home/jagones/.longrun/data/sessions/0e13bdb23c5b.json`
- `/home/jagones/.longrun/data/sessions/vision-e2e-1791729815.json`
