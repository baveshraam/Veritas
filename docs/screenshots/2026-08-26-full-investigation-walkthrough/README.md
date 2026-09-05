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
   survived opening a new multi-accused case, so a pronoun follow-up silently answered
   about the old subject instead of asking. Fixed in `orchestrator.py`; see
   `t19-ambiguous-pronoun` (now correctly asks which of the 4 accused is meant).
2. **`EXPLAIN_REASONING`'s regex missed natural phrasing** ("why did you select those
   cases") and fell through to `CAUSAL` or a repeat of the prior intent. Fixed in
   `intents.py`; see `t06-why-selected`, `t08-why-associates`.
3. **`NEXT_STEPS`'s keyword list had "investigate next" but not the passive
   "investigated next"** — refused instead of matching. Fixed in `intents.py`; see
   `t14-next-steps`.
4. **A decided refusal (`ambiguous_person`, `person_not_on_file`) still ran a generic
   vector search afterward**, populating the Evidence rail with unrelated citations next
   to "I will not guess." Fixed in `orchestrator.py`'s `node_retrieve`; see
   `t19-ambiguous-pronoun` (Evidence rail now empty, matching the refusal).

Also visible throughout: BUG-026's fix — Copilot leads / `NEXT_STEPS` render the
canonical identity cross-referenced against the case's own as-filed spelling
("Usha Naika (filed as \"Usha Neik D/o Srinivas\")") — at `t14-next-steps` and
`t15-briefing`.

`t10-where-concentrated`: the map correctly re-centers on the actual FIR points after
`CASE_LOCATIONS` tallies the previous turn's cited cases (the first run's screenshot of
this turn looked untargeted because the map's 900ms `fitBounds` animation hadn't
finished when it fired — the driver's post-turn wait went 400ms → 1500ms).

`t20-kannada`: a full round-trip Kannada query — correct citations, RBAC-scope note
translated, grammar imperfect in places (known limitation, not new).

`log.json` carries every turn's query, full answer, citation count, refusal flag, and the
active context-pane tab, machine-readable.
