MARKER: A49-DELEG-6B2C9F04
CASE_D1 SUBAGENT: osservazioni=1 marker_presente=sì verbatim="SUB-A49-DELEG-6B2C9F04-41"
CASE_D2 DISPATCH: osservazioni=1 marker_presente=no verbatim="dispatching to teammates is not allowed here. Do this work yourself and report the result."
CASE_D3 SESSION_FILE: A50 msgs=272 marker_hits=0
CASE_D4 SJ: ok/exit=0; nessun campo jobs/subjobs restituito da self.sj
CAUSA_ISOLATA: agent/agent.py:2347-2400 — il dispatch singolo passa dal gate dei rapporti diretti; A49 non è supervisore di A50, quindi A50 non viene attivata
LIMITI: non testati batch dispatch, ritardi o duplicati su retry; il dispatch è stato respinto prima dell’attivazione di A50.