# Veritas vs. the industry — gap analysis

**Newer analysis exists.** `docs/STRATEGIC_RESET_2026-09-04.md` re-audited current state
directly against the code with a four-way gap analysis and a ranked capability list — series
discovery and behavioral profiling, both flagged below as missing, were built in that pass.
This document's platform comparisons (Gotham/i2/Maltego) remain useful background; defer to
the newer document for what's actually built today. **All three §7 recommendations below
(case board, lead disposition, cross-entity timeline) have since shipped** — CLAUDE.md v16 and
v17 — this document is kept for the comparative research, not as an open task list.

**Purpose**: an honest comparison of Veritas against mature investigation platforms (Palantir
Gotham, IBM i2 Analyst's Notebook, Maltego) and general law-enforcement/financial-intelligence
practice, to find what would materially improve a judge's experience — without recommending
work this dataset or competition scope cannot support. Method: live web research (2026-08-27)
cross-referenced against Veritas's actual capability.

---

## 1. What the mature platforms actually provide

| Platform | Core workflow | Built for |
|---|---|---|
| **Palantir Gotham** | Fuses disparate source systems into one searchable graph ("ontology"); analysts pivot across entities, run ML pattern detection | Large agencies, many source systems, a standing analyst corps |
| **IBM i2 Analyst's Notebook** | Analyst builds a persistent **link chart** by hand/import, adds a **timeline chart** overlaying multiple entities' events to spot simultaneity, saves it as a case artifact | One case, one analyst, refining a chart over days/weeks |
| **Maltego** | **Transforms** auto-enrich an entity from external sources; **Machines** chain transforms into a saved pipeline; result is a persistent, editable graph | OSINT-heavy investigation across many external sources |
| **Chain-of-custody / DFIR practice** | Every evidence item is hashed at each handling stage | Court-admissibility of digital evidence |

Common thread, independent of data model: **the analyst owns a persistent, editable
investigation artifact** that survives across sessions and accumulates their own annotations —
the tool does not just answer a question and forget it asked.

Sources: [Palantir Gotham Europa](https://www.palantir.com/platforms/gotham/europa/),
[i2 Analyst's Notebook](https://i2group.com/solutions/i2-analysts-notebook),
[Maltego link analysis](https://www.maltego.com/blog/infographic-what-is-link-analysis/),
[Digital evidence chain of custody](https://acecomputers.com/chain-of-custody-in-digital-forensics/).

---

## 2. Where Veritas already matches or beats this bar

- **Grounded, cited natural-language answers** — none of Gotham/i2/Maltego generate prose at
  all; Veritas's CRAG evaluator refuses on `no_evidence` rather than fabricating, with every
  claim traced to a `source_query`, a trust property those platforms never need to solve.
- **Entity resolution as identity inference**, not string matching — Fellegi-Sunter
  reconstructing `vx_person` (F1 0.989) is the same problem Gotham's ontology fusion solves for
  cross-source records, done with a published 1969 method and a measured accuracy.
- **Audit hash chain** (§7 of CLAUDE.md) — tamper-evident, cron-verified every 12h. None of the
  three platforms researched here publish an equivalent for their own analyst-facing outputs.
- **Deliberate lead-generation restraint** — capping leads at direct co-accused rather than the
  full 4-hop connected component is the opposite failure mode from Gotham's "show everything"
  reputation.
- **Provenance depth** — citing the literal SQL string (`source_query`) per evidence item is
  finer-grained than i2's per-link source attribution.

## 3. What Veritas does only superficially

- **Graph exploration is a read-only, per-query render**, not an interactive canvas —
  `NetworkView.tsx` draws whatever the current turn returned, with no "expand this node," no
  manual re-layout, no persistence once the topic changes. i2/Maltego's value proposition is
  the opposite: the chart *is* the case file.
- **Timeline was single-case, not cross-entity.** *(Closed — see §4 item 3 below.)*
- **Briefing/report export is platform-blocked**, not absent by design — the Copilot draft and
  leads are real, but the only durable export is an honest HTML fallback, not a polished PDF.

## 4. What was genuinely missing (status: closed)

**The largest gap at the time**: no persistent, editable **investigation memory that outlives
one chat session**. `SessionFocus`/`vx_conversation_turn` gave continuity *within* one
conversation, but nothing survived to the next time anyone opened that FIR. Ranked by how
load-bearing the absence was:

1. **No cross-session case memory.** — **Closed, CLAUDE.md v16**: the Investigation Board
   (`vx_case_board_item`) persists pinned evidence/findings/people/leads/notes across sessions
   and officers.
2. **No lead/next-step disposition.** An officer couldn't tell Veritas "checked lead 2, dead
   end." — **Closed**, as part of the same board (`open`/`pursued`/`dismissed`, with a reason).
3. **No cross-entity timeline correlation** — the one concrete capability i2 has that Veritas
   structurally lacked. — **Closed, CLAUDE.md v17.**
4. **No analyst correction path into entity resolution.** An officer who spots a Fellegi-Sunter
   miss (or false merge) still has no way to flag it. **Still open** — deliberately: it touches
   the trust-critical identity layer directly, and a wrong manual override propagating
   downstream (graph, financial, risk scoring) is a worse failure mode than the gap it would
   close. Worth a dedicated pass, not a bolt-on.

## 5. What is unnecessary to build

- **Arbitrary multi-source OSINT fusion** (Maltego's core value) — no external source systems
  exist in this dataset or competition scope.
- **Mixed-reality / drone / satellite situational awareness** (Gotham) — outside this dataset
  and this challenge entirely.
- **A general-purpose graph database migration** — already correctly declined (CLAUDE.md §4):
  NetworkX in-memory is the right trade at this data scale.
- **A full case-management/ticketing system** (assignment queues, SLA tracking) — CLAUDE.md
  §9's "human-in-the-loop by design, nothing automated" ethos argues against an automated
  workflow-routing layer; that's a CRM, not an investigation-support tool.
- **Manual link-chart drawing tools** — the *effect* an officer wants (a durable, added-to case
  artifact) is better solved by the case board than by rebuilding i2's canvas editor inside a
  conversational product.

## 6. Conversational AI — is it still the main product?

| Capability | Status | Evidence |
|---|---|---|
| Understand natural investigator language | **Yes** | `intents.py` routes 30+ intents; multiple live passes found and fixed real phrasing gaps |
| Maintain investigation state | **Yes, within a session** (now also across sessions, §4) | `SessionFocus` persists `active_fir`/`active_person`/`active_location` across turns |
| Resolve references | **Yes** | Pronoun resolution, ambiguous-name tie-break, pronoun-after-multi-person clarification |
| Handle ambiguity | **Yes** | Asks which of N candidates rather than guessing |
| Plan multi-step investigation | **Yes** (was Partial) | HippoRAG/Think-on-Graph plan within a retrieval; the N-step investigation planner (CLAUDE.md v17) added a standing multi-turn plan |
| Select appropriate tools | **Yes** | Intent → SQL/Graph/Vector/Prediction agent routing, evidence-evaluator-gated |
| Combine results | **Yes** | CRAG evaluator + extractive synthesis merges multi-source evidence into one grounded answer |
| Ground claims | **Yes** | Every claim traces to a citation; refusal on empty/rejected evidence |
| Explain why results were surfaced | **Yes** | `provenance.py`/`GET /explain` (CLAUDE.md v20) — the actual CLAIM/RECORDS chain, not a restatement of the trace |
| Connect conversation to map/graph/timeline/financial views | **Yes** | Workspace tabs auto-switch by intent |
| Produce a coherent briefing | **Yes** | Investigation Copilot: timeline, leads, similar cases, draft diary paragraph |

Veritas is no longer only a **reactive per-turn planner** — the case board (§4) and the N-step
planner give it a standing artifact and plan that accumulate across turns and sessions, closing
what was this document's one named architectural gap.

## 7. Smallest winning additions — ranked (all shipped)

1. **Persistent per-case investigation board** — closed §4 item 1. Built as
   `vx_case_board_item` + 6 board intents + `Board.tsx` (CLAUDE.md v16). Demoable as: pin a
   lead → open a fresh session as a different officer → the pin is still there.
2. **Lead/next-step disposition** — closed §4 item 2, built on the same board schema/UI
   (`open`/`pursued`/`dismissed` with a reason).
3. **Cross-entity timeline correlation** — closed §3/§4 item 3, built in the undocumented run
   of work CLAUDE.md v17 caught this file up on.

**Not built, named rather than silently skipped**: analyst correction into entity resolution
(§4 item 4) — deliberately deferred; see that item's reasoning.
