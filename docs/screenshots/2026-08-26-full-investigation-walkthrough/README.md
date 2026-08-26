# The 19-turn golden investigation, driven live through the console

One continuous conversation, one CDP session, signed in as DSP (`?as=DSP`) against the
deployed console/API. Subject: FIR 100050504202300018 (Kidnapping, Bengaluru Urban,
4 accused — Usha Naika, Prashanth Krishnamurthy, Nithin Madar, Naveen Nayak). Turns 16-17
switch to an unrelated case (FIR 100222201202600022, Mandya, Hurt) and back, to test
context isolation; turn 19 deliberately asks an ambiguous pronoun after a multi-accused
`CASE_PEOPLE` turn.

This run is the SECOND of the pass — the first run (not committed) found four real bugs,
each fixed and redeployed before this run:

1. **`CASE_PEOPLE` never cleared a stale `active_person`.** A person named turns earlier
   survived opening a brand-new multi-accused case, so a pronoun follow-up silently
   answered about the old subject instead of asking. Fixed in
   `packages/rag_agent/rag_agent/orchestrator.py`; visible now at `t19-ambiguous-pronoun`
   — the engine correctly asks which of the 4 accused is meant.
2. **`EXPLAIN_REASONING`'s regex missed natural phrasing** ("why did you select those
   cases", "why were those associates surfaced") and fell through to `CAUSAL` or a bare
   repeat of the previous topic intent. Fixed in `intents.py`; visible at `t06-why-selected`
   and `t08-why-associates`, both now correctly re-describing the prior turn's own trace.
3. **`NEXT_STEPS`'s keyword list had "investigate next" but not "investigated next"**
   (passive voice) — "what should be investigated next" matched nothing and refused. Fixed
   in `intents.py`; visible at `t14-next-steps`, now returning real leads.
4. **A decided refusal (`ambiguous_person`, `person_not_on_file`) still ran a generic
   vector search afterward**, populating the Evidence rail with unrelated citations next
   to a message saying "I will not guess." Fixed in `orchestrator.py`'s `node_retrieve`;
   visible at `t19-ambiguous-pronoun` — the Evidence rail is now empty ("Evidence for the
   current answer appears here"), matching the refusal.

Also visible throughout: BUG-026's fix (Copilot leads / `NEXT_STEPS` now render
`"Usha Naika (filed as \"Usha Neik D/o Srinivas\" on this FIR)"` — the canonical identity
cross-referenced against the case's own as-filed spelling) at `t14-next-steps` and
`t15-briefing`.

`t10-where-concentrated` shows the map correctly re-centering on the actual FIR points
(real Bengaluru-area streets/labels) after CASE_LOCATIONS tallies the previous turn's
cited cases — the first run's screenshot of this same turn looked like an untargeted,
zoomed-out statewide view because the map's `fitBounds` animation (900ms) hadn't finished
when the screenshot fired; the driver's post-turn wait was increased from 400ms to 1500ms
for this run, and the fix held.

`t20-kannada` is a full round-trip Kannada query (`ಮಂಡ್ಯ ಜಿಲ್ಲೆಯಲ್ಲಿ ಎಷ್ಟು ಕಳವು
ಪ್ರಕರಣಗಳಿವೆ?`) — correct citations, RBAC-scope note translated, grammar imperfect in
places (known limitation, not new).

`log.json` carries every turn's query, full answer, citation count, refusal flag, and the
active context-pane tab, machine-readable.
