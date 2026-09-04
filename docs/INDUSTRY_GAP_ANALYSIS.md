# Veritas vs. the industry — gap analysis

**Newer analysis exists.** `docs/STRATEGIC_RESET_2026-09-04.md` (2026-09-04/05) re-audited
current state directly against the code and added a four-way gap analysis (challenge brief vs.
investigator workflow vs. mature-platform practice vs. actual implementation) plus a ranked
capability list and a phased build — series discovery and behavioral profiling, both flagged
below, were built in that pass. This document's platform comparisons (Gotham/i2/Maltego) remain
independently useful background; defer to the newer document for what's actually built today.

**Purpose**: an honest comparison of Veritas against mature investigation platforms
(Palantir Gotham, IBM i2 Analyst's Notebook, Maltego) and general law-enforcement/
financial-intelligence/GIS-intelligence practice, to find what would materially
improve a judge's experience and differentiate the product — without recommending
work this dataset or this competition's scope cannot support.

**Method**: live web research (2026-08-27) on each platform's documented feature set,
cross-referenced against Veritas's actual current capability as recorded in
`CLAUDE.md`, `docs/QA_FUNCTIONALITY_MATRIX.md` and `docs/VERITAS_HANDOFF.md` — not
against an idealized description of what Veritas was meant to become.

---

## 1. What the mature platforms actually provide

| Platform | Core workflow | What it's built for |
|---|---|---|
| **Palantir Gotham** | Fuse disparate source systems into one searchable graph ("ontology"); analysts pivot across entities, run ML pattern detection, and get full situational awareness including geospatial/real-time feeds | Large agencies with many existing source systems and a standing analyst corps |
| **IBM i2 Analyst's Notebook** | Analyst builds a persistent **link chart** by hand or by import, adds a **timeline chart** overlaying multiple entities' events to spot simultaneity, annotates and saves it as a case artifact | One case, one analyst, building and refining a chart over days or weeks |
| **Maltego** | **Transforms** automatically enrich an entity from external sources; **Machines** chain transforms into a saved, repeatable pipeline; result is a persistent, editable graph | OSINT-heavy investigation across many external data sources |
| **Chain-of-custody / DFIR practice** | Every evidence item is hashed at each handling stage; "if you didn't write it down, it didn't happen" | Court-admissibility of digital evidence |

The common thread across all three commercial platforms, independent of their
different data models: **the analyst owns a persistent, editable investigation
artifact** (a chart, a case file) that survives across sessions and accumulates their
own annotations, corrections, and dispositions — the tool does not just answer a
question and forget it asked.

Sources: [Palantir Gotham Europa](https://www.palantir.com/platforms/gotham/europa/),
[What is Palantir's Gotham software](https://www.thelocal.de/20250805/what-is-palantirs-gotham-software-and-why-do-german-police-want-it),
[i2 Analyst's Notebook](https://i2group.com/solutions/i2-analysts-notebook),
[i2 ANB user help](https://www.ibm.com/docs/en/SSJSV9_9.2.1/com.ibm.i2.anb.doc/analysts_notebook_pdf.pdf),
[Maltego link analysis](https://www.maltego.com/blog/infographic-what-is-link-analysis/),
[Maltego OSINT workflow](https://netguardia.com/learning-development/tutorials-guides/building-an-osint-investigation-workflow-with-maltego-and-spiderfoot/),
[Digital evidence chain of custody](https://acecomputers.com/chain-of-custody-in-digital-forensics/).

---

## 2. Where Veritas already matches or beats this bar

These are not gaps — naming them so the recommendations below don't relitigate
settled strengths.

- **Grounded, cited natural-language answers.** None of Gotham/i2/Maltego generate
  prose at all — they are visualization and query tools an analyst reads. Veritas's
  CRAG evaluator (§5) refusing on `no_evidence` rather than fabricating, with every
  claim traced to a `source_query`, is a genuinely different and arguably stronger
  trust property for a conversational tool than anything these platforms need to
  solve, since they never generate a claim to begin with.
- **Entity resolution as identity inference**, not string matching — Fellegi-Sunter
  reconstructing `vx_person` from `Accused` rows (F1 0.989) is the same problem
  Gotham's "ontology" fusion solves for cross-source records, done rigorously with a
  published 1969 method and a measured accuracy, not a fuzzy-match heuristic.
- **Audit hash chain** (§7) — a tamper-evident log of the *system's own outputs*,
  cron-verified every 12h. This is a stronger, more specific claim than generic
  "enterprise-grade security" marketing copy, and it is a property none of the three
  platforms researched here publish about their own analyst-facing outputs.
- **Deliberate lead-generation restraint** — capping leads at direct co-accused
  rather than the full 4-hop connected component (CLAUDE.md §5: "a lead has to be
  actionable this week") is the opposite failure mode from Gotham's "show
  everything" reputation, and is a considered design choice, not a missing feature.
- **Provenance depth per evidence item** — citing the literal SQL string
  (`source_query`) alongside each evidence item is finer-grained than i2's
  per-link source attribution.

## 3. What Veritas does only superficially

- **Graph exploration is a read-only, per-query render**, not an interactive canvas.
  `NetworkView.tsx` draws whatever the current turn's retrieval returned; there is no
  "expand this node," no manual re-layout, no persistence of the graph an officer was
  just looking at once the next turn changes topic. i2/Maltego's entire value
  proposition is the opposite: the chart *is* the case file.
- **Timeline is single-case, not cross-entity.** The Copilot's timeline (§5,
  `Copilot.tsx`) sequences one case's own events. i2's signature Timeline Chart
  overlays *multiple* entities' events side by side specifically to catch
  simultaneity ("was suspect A active in district X the same week suspect B's
  transactions moved?") — Veritas has no equivalent, despite having all the
  underlying per-case dates and districts already in the record layer.
- **Briefing/report export is platform-blocked**, not absent by design (§4 below) —
  the Copilot draft paragraph and leads are real and correct, but the only durable
  export is an honest HTML fallback, not the polished, letterhead PDF a report-out
  workflow implies.

## 4. What is genuinely missing

**The single largest gap, and the reason it matters most**: Veritas has no
persistent, editable **investigation memory that outlives one chat session**.
`SessionFocus` and `vx_conversation_turn` (§5 of CLAUDE.md) give real, tested
continuity *within* one officer's live conversation — proven across many
multi-turn live sessions (RAG-17/18/24-36) — but nothing survives to the next
time anyone opens that FIR. A second officer, or the same officer tomorrow,
starts from zero: no record of which leads were already checked, which were
dismissed as dead ends, or what an officer's own working hypothesis was. Every
mature platform researched here treats exactly this — the accumulating case
artifact — as the core object the analyst works with, not an afterthought.

This is also the concrete answer to this pass's own "is Veritas genuinely
conversational, or intent-classification-plus-tools" question (already partly
investigated in the 2026-08-26 conversational-architecture pass, which found and
fixed the equivalent gap *within* a session — see RAG-33). The remaining edge of
the same problem is *across* sessions: today, Veritas can plan and execute one
turn's retrieval well, but it has no notion of an investigation as a standing
object with state that both the officer and the system can add to over time —
closer to always re-deriving a plan from scratch than to pursuing one.

Named, ranked by how load-bearing the absence is:

1. **No cross-session case memory.** (above)
2. **No lead/next-step disposition.** An officer cannot tell Veritas "checked lead
   2, dead end" — so `NEXT_STEPS` has no way to stop re-surfacing something already
   ruled out, and there is no record of what an officer actually did in response to
   a suggestion. This is the "human review" and "human-in-the-loop" pillar's missing
   half: Veritas surfaces leads but never learns their outcome.
3. **No cross-entity timeline correlation.** Named in §3 — the one concrete
   capability i2 has that Veritas structurally lacks, not merely under-polished.
4. **No analyst correction path into entity resolution.** An officer who spots a
   Fellegi-Sunter miss (or a false merge) has no way to flag it; the pipeline is a
   one-shot batch process with no feedback loop. Real, but touches the
   trust-critical identity layer directly — riskier to build than the items above,
   named here rather than recommended for this pass.

## 5. What is unnecessary to build

Stated as plainly as the gaps, since building the wrong things is its own failure
mode:

- **Arbitrary multi-source OSINT fusion** (Maltego's core value) — there are no
  external source systems in this dataset or this competition's scope; building
  transform infrastructure for sources that don't exist would be pure surface area
  with nothing behind it for a judge to test.
- **Mixed-reality / drone / satellite situational awareness** (Gotham) — outside
  this dataset entirely, and outside what a police-records platform for this
  challenge needs to demonstrate.
- **A general-purpose graph database migration** — already correctly declined
  (CLAUDE.md §4: NetworkX in-memory is the right trade at this data scale; Neo4j's
  advantage is traversal at a scale this dataset does not have).
- **A full case-management/ticketing system** (assignment queues, SLA tracking,
  multi-officer workflow states) — CLAUDE.md §9's own "human-in-the-loop by design,
  nothing is an automated trigger" ethos argues against building an automated
  workflow-routing layer; that is a different product (a CRM), not an
  investigation-support conversational tool.
- **Manual link-chart drawing tools** (dragging nodes, freehand annotation canvas) —
  the *effect* an officer wants (a durable, added-to case artifact) is better solved
  by the case-board recommendation below than by rebuilding i2's canvas editor from
  scratch inside a conversational product whose strength is not manual diagramming.

## 6. Conversational AI — is it still the main product?

Evaluated directly against the pass's own checklist, from the code and the live
verification history already on record (not re-derived here):

| Capability | Status | Evidence |
|---|---|---|
| Understand natural investigator language | **Yes** | `intents.py` routes 30+ intents from free-text phrasing; multiple live passes found and fixed real phrasing gaps (passive voice, bare demonstratives) rather than assuming coverage |
| Maintain investigation state | **Yes, within a session** | `SessionFocus` persists `active_fir`/`active_person`/`active_location` across turns, fixed at the point it was found broken (RAG-33) |
| Resolve references | **Yes** | Pronoun resolution (RAG-17), ambiguous-name tie-break (RAG-32), pronoun-after-multi-person clarification (RAG-34) |
| Handle ambiguity | **Yes** | Asks which of N candidates rather than guessing — the load-bearing trust property CRAG and `ambiguous_person` both share |
| Plan multi-step investigation | **Partial** | HippoRAG/Think-on-Graph plan *within* one retrieval; there is no standing, visible investigation plan an officer and the system both add to across turns — see §4 item 1 |
| Select appropriate tools | **Yes** | Intent → SQL/Graph/Vector/Prediction agent routing, evidence-evaluator-gated |
| Combine results | **Yes** | CRAG evaluator + extractive synthesis merges multi-source evidence into one grounded answer |
| Ground claims | **Yes** | Every claim traces to a citation; refusal on empty/rejected evidence (RAG-35, RAG-36) |
| Explain why results were surfaced | **Yes** | Reasoning Trace panel + `EXPLAIN_REASONING`/`EVIDENCE_FOR` intents re-describe the previous turn's own trace |
| Connect conversation to map/graph/timeline/financial views | **Yes** | `ContextView` auto-switches pane by intent (hotspot → map, network → graph, financial → Sankey, forecast → trend) |
| Produce a coherent briefing | **Yes** | Investigation Copilot: timeline, leads, similar cases, draft diary paragraph, reachable from chat via `BRIEFING` |

**The one real architectural gap**: Veritas is a **reactive per-turn planner**, not
an investigation that **accumulates a standing plan and its own history of what was
tried**. It is not a chatbot wrapped around isolated tools — the session-focus and
reference-resolution work above is real and tested, not superficial — but every
"investigation" still exists only for the lifetime of one conversation. This is not
a case for downgrading the conversational core; it is the specific, nameable next
step for it, and it is exactly what §4's top recommendation closes.

## 7. Smallest winning additions — ranked

Ranked by investigator value × judge impact against implementation effort, data
requirements, Catalyst compatibility, and risk. Three items, not twenty — anything
past this list is either already covered (§2), already correctly declined (§5), or a
reasonable future direction too risky/large for this pass (§4 item 4).

### 1. Persistent per-case investigation board (pin evidence & leads, officer notes)
**Closes**: §4 item 1, the single largest gap.
**What**: a new `vx_case_board` table (FIR id, officer id, item type, item ref,
note, created_time) and a handful of endpoints; a "pin" affordance on evidence cards
and Copilot leads; a new board tab in the Copilot overlay showing everything pinned
for that case, from any officer, across sessions. `SessionFocus`/conversation
history is untouched — this is a durable layer *underneath* it, not a replacement.
**Investigator value**: high — this is literally the object i2/Gotham analysts
build their case around; without it every session restarts from zero.
**Judge impact**: high — directly answers the "is this more than a chatbot"
question a judge is most likely to probe, with a concrete, demoable artifact.
**Effort**: moderate — one new table, simple CRUD endpoints, a pin button and a
list view; no change to retrieval/synthesis/policy.
**Data requirements**: none beyond what's already in the record layer.
**Catalyst compatibility**: full — another Data Store table, same pattern as
`vx_session`/`vx_conversation_turn`.
**Risk**: low — additive only, no path back into entity resolution, graph
construction, or the audit chain.

### 2. Lead/next-step disposition (mark pursued / dismissed, with a reason)
**Closes**: §4 item 2.
**What**: extends item 1's board with a status field on pinned leads
(`open`/`pursued`/`dismissed`) and an optional note; `NEXT_STEPS` filters out
dismissed leads for that case going forward.
**Investigator value**: high — stops the system re-suggesting something an officer
already ran down, and gives a real audit trail of what was tried.
**Judge impact**: medium-high — a natural follow-up demo beat once item 1 exists
("mark that lead pursued" → next `NEXT_STEPS` call correctly omits it).
**Effort**: low — almost entirely built on item 1's schema and UI; the only new
logic is a `WHERE status != 'dismissed'` filter in `leads_for_case`.
**Data requirements**: none new.
**Catalyst compatibility**: full.
**Risk**: low, for the same reason as item 1.

### 3. Cross-entity timeline correlation ("were X and Y active in the same place/time?")
**Closes**: §3/§4 item 3, the one concrete i2 capability Veritas structurally lacks.
**What**: a new intent that takes two or more named people (or a person and a
district) and renders a shared timeline — each entity's case dates plotted on one
axis — instead of Veritas's current single-case timeline.
**Investigator value**: high for the specific question it answers (simultaneity/
alibi-breaking), which is a real investigative pattern, not a novelty.
**Judge impact**: medium-high — visually distinctive, and directly recognizable to
anyone who has seen an i2 demo.
**Effort**: moderate-high — a new intent, a new query joining multiple people's
case histories, and a new frontend visualization component (nothing in
`apps/web/components/viz/` does this today).
**Data requirements**: none new — `IncidentFromDate`/`District` per case already
exist.
**Catalyst compatibility**: full — read-only, no new table.
**Risk**: low-medium — purely additive, but the new viz component is the largest
single piece of new frontend surface of the three.

**Not recommended for this list, named rather than omitted silently**: analyst
correction into entity resolution (§4 item 4) — real value, but touches the
trust-critical identity pipeline that every downstream system (graph, financial,
risk scoring) depends on; a wrong manual override propagating downstream is a worse
failure mode than the gap it would close. Worth a dedicated pass of its own, not a
bolt-on.

---

## 8. Next implementation step

Build item 1 (the case board) first — items 2 and 3 both either depend on it
directly (2) or are independent and can follow in any order once judge-facing time
remains. Item 1 alone, demoed as "pin this lead → close the app → open a fresh
session as a different officer → the pin is still there," is the single most
concrete rebuttal available to "this is just a chatbot over some tools."
