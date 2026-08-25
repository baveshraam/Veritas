# Veritas — Implementation Strategy: North Star → Live System

**Purpose.** A minimum sequence of vertical investigation slices that takes the current system
to `docs/VERITAS_NORTH_STAR.md` without accumulating more disconnected feature work. No code
changes are prescribed here; no new feature ideas are introduced beyond what the North Star
already scoped. This is the sequencing decision, not the implementation.

**Definition of done, restated as the gate every phase must clear:**
```
DATA → correct algorithm/retrieval → evidence validation → conversational behavior
     → UI → authorization → live deployment → realistic investigator workflow
     → acceptance test
```
A phase is not complete because an API route or a UI panel works in isolation. It is complete
when an officer can run the realistic workflow, on the live deployment, under their actual role's
authorization, and get a cited, verified answer they could act on.

---

## Where the data-foundation correction (BUG-023) belongs

Stated directly, per the request to determine this exactly: **the narrative-diversity fix is
the DATA step of Phase 2 (Cross-Case Discovery), not a standalone phase, and not a prerequisite
for every other phase.**

The reasoning, grounded in what the data-generation audit actually found:

- HippoRAG (the primary multi-hop retrieval path), the `criminal_profile` vector collection, the
  co-offending graph, the financial layer, and hotspot detection are all independently confirmed
  to be **structured-field-driven and untouched by `BriefFacts`** (`docs/DATA_GENERATION_AUDIT.md`
  §12-16). Phases 1, 3, 4, and 5 below do not read case narrative text at all — gating them on
  the narrative fix would be blocking work on a dependency it does not have.
- The one capability that is genuinely, structurally blocked by the narrative collapse is
  cross-case similarity (`fir_narrative` search and the Copilot's "similar past cases") — the
  North Star names this the largest substantive gap for exactly this reason
  (`docs/VERITAS_NORTH_STAR.md` Part 2, stage 9). Building a UI, a conversational answer path, or
  an acceptance test around that capability before the underlying signal exists would mean
  shipping a vertical slice whose own DATA step fails — precisely the "API/UI works
  independently but the capability isn't real" failure mode this strategy exists to prevent.
- It is sequenced **second**, immediately after hardening the foundational lookup slice, rather
  than deferred to the end, for two reasons: it is cheap and self-contained (weighted
  slot-filling per the audit's own recommended fix — no LLM, no new dependency, the same pattern
  `refdata.py`/`priors.py` already use elsewhere in the generator), and doing it early removes
  the single biggest risk of building further UI/demo material on top of data known to be
  degenerate. It does not need Phase 1's authorization or citation work to be finished first,
  and nothing later in the sequence needs to wait on it except Phase 2 itself.

---

## Phase 1 — Trusted Single-Record Lookup

**1. Investigator workflow.** *"I have a case number, a person's name, or a specific question
about one record — I ask, and I get a correct, scoped, cited answer, and I can trust that if the
records don't support an answer, I'm told that plainly instead of getting a confident guess."*
This is the base workflow every other phase's "evidence validation" and "authorization" steps
reuse — it must be unconditionally solid before anything is built on top of it.

**2. North-Star capabilities satisfied.** §1.3 (evidence/trust/authorization bar) in full;
§1.2's citation-shaped-hallucination guard; the stage-1 (case initiation) and stage-11
(verification) loop stages; the RBAC portion of stage 13.

**3. Existing components reused.** `FIR_LOOKUP`/`PERSON_HISTORY`/`ALIAS_CHECK` intents
(`orchestrator.py`), the CRAG evaluator's accept/widen/refuse loop, `evaluator.supporting()`,
the `Employee`-row role/station policy (`packages/policy`), the two-place enforcement pattern
(middleware masking + query-construction scoping), the audit hash chain.

**4. Current gaps that block it.**
- `BUG-011` — similarity is displayed as evidential confidence; an officer cannot currently
  trust the confidence band on a citation to mean what it should mean.
- `BUG-008` — "how many" questions return narratives, never a count — a foundational query
  pattern with no answer today.
- `BUG-014` — saturated 1.00 risk scores presented at the same visual weight as a cited record.
- The delicacy already surfaced by `BUG-006`/`BUG-020` (a fix to the evaluator's floor logic
  regressed an authoritative refusal in the same session) — this phase must close with the
  evaluator's behavior locked down by tests broad enough that a future change to it cannot
  silently reintroduce either failure mode.

**5. Acceptance criteria (whole workflow, not the API alone).**
- An officer at each of the six roles asks a real FIR-number, person-name, and count-style
  question against the **live** deployment; every answer's citations genuinely support the
  claim (no BUG-006-shape padding), every refusal states which of the named reasons applies
  (no BUG-010-shape generic refusal), counting questions return a number, and confidence values
  displayed to the officer are labeled for what they actually measure.
- Role/station scoping is verified live for all six roles on this workflow specifically (not
  inherited from a prior pass) — masked identities stay masked, out-of-station cases stay 403
  on every endpoint that can surface them.
- A regression suite exists that would fail if the BUG-020 regression shape recurred (an
  authoritative low-confidence item silently dropped by the relevance floor).

**6. What must NOT be built yet.** Any new intent beyond fixing the existing ones (no new query
types); no narrative-similarity work (that's Phase 2's DATA step); no graph/network UI beyond
what already renders; no financial detector work; no LLM-fluency debugging (BUG-022) — this
phase's answers stay on the deterministic extractive path, which is already correct, and fixing
QuickML reachability is not on this workflow's critical path.

---

## Phase 2 — Data Foundation Correction + Cross-Case Discovery

**1. Investigator workflow.** *"Given an open case, show me past cases that are actually
similar in method — not just the same crime-type label — so I can see how they were handled and
whether there's a pattern I should be looking for."*

**2. North-Star capabilities satisfied.** Stage 9 (cross-case discovery) in full; the
narrative-diversity portion of §1.5 (data foundation); the "similar cases" half of the
Investigation Copilot named in §1.4 as a claimed-but-needs-rework capability, moved to
genuinely-working.

**3. Existing components reused.** The generator's existing weighted-template pattern
(`refdata.py`, `priors.py`) as the model for widened `_MO` slot-filling; the already-correct
`criminal_profile` collection as the structural pattern the fixed `fir_narrative` collection
should follow; `vector_agent.search()`, `copilot/brief.py:_similar_cases`, `SIMILAR_CASES` intent
routing (already correctly classified per `BUG-007`'s fix).

**4. Current gaps that block it.**
- `BUG-023` itself — 12/20 crime types produce zero descriptive narrative content; the other 8
  produce exactly one fixed sentence each.
- No narrative-diversity test exists — the gap that let BUG-023 go undetected until manual
  sampling found it.
- The identity answer key (used to validate entity-resolution quality, a prerequisite for
  trusting *any* of this dataset's derived signal) is not persisted post-generation
  (`docs/DATA_GENERATION_AUDIT.md` §19) — should be brought in line with the AML-label pattern
  in this same phase, since it is the same class of fix (persist an answer key as an artifact)
  and this phase is already touching the generator.

**5. Acceptance criteria.**
- Regenerated data: sampling N cases per crime type and normalizing date/district produces more
  than one distinct narrative shape per crime type, for all 20 crime types (not 8) — the exact
  check the audit recommends, now automated and running in CI, not manual.
- A live "similar cases" query against a real case returns cases whose narrative similarity is
  demonstrably driven by shared method detail, not solely by shared crime-type/district — spot
  checked against cases that share a crime type but differ in method, which should now score
  measurably lower than cases that genuinely share a method.
- The Copilot's similar-cases panel, on the live deployment, under a real officer role, renders
  results an investigator would recognize as substantively similar, not merely same-labeled.
- The identity answer key is persisted and can be used to recompute the F1 claim against
  whatever dataset is actually live on Catalyst, not only a fresh local `generate()` call.
- Every measurement elsewhere in the repo that references specific FIR numbers, specific people,
  or specific citation counts is re-verified against the regenerated dataset before this phase
  is called done — regenerating data is a decision with consequences beyond this phase, and
  those consequences must be closed out inside it, not left as a surprise for a later phase.

**6. What must NOT be built yet.** No LLM-assisted narrative generation (the audit's own verdict
is that weighted slot-filling is sufficient and cheaper); no move of HippoRAG, `criminal_profile`,
or any structured-field-driven capability onto narrative text — those stay as they are, correctly
unaffected by this phase; no new similarity capability beyond what "similar past cases" already
claims (no cross-district search expansion, no MO-clustering visualization not already scoped).

---

## Phase 3 — Person Network & Investigative Leads

**1. Investigator workflow.** *"Show me who this person operates with, whether they have priors
under a different name spelling, and give me a short, actionable list of leads I could follow up
on this week."*

**2. North-Star capabilities satisfied.** Stage 3 (entity discovery), stage 4 (link analysis),
stage 10 (investigative leads); the "graph algorithms as ranking signal, not decoration"
differentiator (§1.4).

**3. Existing components reused.** Fellegi-Sunter identity resolution and `vx_accused_identity`
(already independently corroborated at F1 0.998 on a sample this audit cycle); the co-offending
projection and `gds.py` (PageRank/Louvain/betweenness, already live-verified — `ML-07`); the
Network view (`UI-25`, already VERIFIED rendering live); the Copilot's direct-co-accused-only
leads design (already correctly capped per the North Star's human-in-the-loop analysis).

**4. Current gaps that block it.**
- The identity-answer-key persistence gap, already closed in Phase 2 — this phase depends on
  Phase 2 having landed it, since a network/leads workflow is only as trustworthy as the
  identity resolution underneath it, and that trust needs to be independently re-verifiable
  post-Phase-2.
- Centrality output (`ML-08`, PageRank/betweenness values reaching `/person` and evidence) is
  only PARTIAL-verified — needs closing to VERIFIED before this workflow can be called complete.
- Citation-chip-to-evidence-rail interaction (`UI-13`, `UI-16`) is UNKNOWN — the workflow
  requires an officer to actually follow a lead from the network view back to its supporting
  record, which needs this interaction driven and confirmed.

**5. Acceptance criteria.**
- An officer asks about a named person with a known name-spelling variant and gets back the
  correct cross-case history (priors under the alternate spelling included), live.
- The network view for that person renders, an officer can click a node/citation and land on the
  correct supporting record, live, under CDP-driven or equivalent interactive verification (not
  just an API-level check).
- The Copilot returns a short, capped lead list for a real case with a real co-offending
  structure, and each lead traces to a specific relationship in the graph, not an unbounded
  "857 associates" list.
- Role scoping holds throughout: an IO sees only their station's people/network; higher ranks see
  the full picture per the existing verified RBAC matrix.

**6. What must NOT be built yet.** No expansion of traversal depth beyond the existing
role-capped limits; no new graph algorithm beyond the three already ported; no cross-referencing
into narrative similarity (that stays Phase 2's concern, already closed by the time this phase
runs); no financial-layer integration into leads (that's Phase 5).

---

## Phase 4 — Geographic Intelligence

**1. Investigator workflow.** *"Show me where crime is concentrated in my district, as an actual
map I can read — not an abstract scatter — so I can reason about resource deployment the way I
would from a real geographic tool."*

**2. North-Star capabilities satisfied.** Stage 7 (geographic intelligence) in full, including
the explicit bias-mitigation stance (§1.1's predictive-policing literature discussion) —
this phase must ship the honest disclosure of synthetic-attractor ground truth alongside the map
fix, not the map fix alone.

**3. Existing components reused.** KDE/DBSCAN hotspot detection (`ML-02`, already VERIFIED at
API level), the self-drawn dark-canvas map renderer (chosen specifically so FIR coordinates never
reach a third-party tile service — that constraint carries forward unchanged), the `HOTSPOT`
intent's named-district and no-district-fallback paths (both already live-verified in v11).

**4. Current gaps that block it.**
- `UI-24` — the map renders points and clusters correctly but has **no geographic reference at
  all**: no district outlines, scale, or labels. This is the single defect that makes the
  workflow currently unusable as described — an officer cannot orient a scatter plot to a real
  place.
- The documentation-sharpness gap the data audit flagged: `CLAUDE.md` should state as plainly as
  `geo.py`'s own docstring already does that hotspot *placement* is a synthetic stand-in, not
  real POI-derived ground truth — this phase should close that gap in the same pass that fixes
  the rendering, so the corrected map isn't paired with an overstated claim about what it shows.

**5. Acceptance criteria.**
- An officer asks for hotspots in a named district and, separately, a bare "show me hotspots"
  query, and both render on the live deployment with recognizable district context (outline,
  scale, or equivalent geographic anchor) — not just colored points on a blank canvas.
- The rendered hotspot geography is checked against the underlying KDE/DBSCAN output for
  correctness (the cluster an officer sees on the map is the cluster the algorithm actually
  found), not just checked for "something renders."
- Documentation accompanying this feature states the synthetic-attractor caveat at the same
  prominence as the capability claim.

**6. What must NOT be built yet.** No real-world POI/WorldPop integration (explicitly named in
`geo.py`'s own docstring as future work, and out of scope for this competition per the North
Star's tiering); no drill-down/pan-zoom capability beyond what's already scoped; no tile-service
integration of any kind — the self-hosted canvas constraint is a hard requirement, not a
preference to reconsider.

---

## Phase 5 — Financial Intelligence

**1. Investigator workflow.** *"Trace the money from this account or person, see the flow as a
diagram I can follow, and know whether either detector — the auditable rule or the pattern-catching
model — flagged anything, with the reasoning visible."*

**2. North-Star capabilities satisfied.** Stage 8 (financial intelligence) in full, including
the two-detector differentiator (§1.4) actually verified working, not merely present in code.

**3. Existing components reused.** `graph_agent.money_trail()`, the `FINANCIAL` intent
(including its already-fixed negative-finding behavior from `BUG-013`), the Sankey view
(`UI-26`, VERIFIED with a known high-fan-out label-overlap issue), the rule-based structuring
detector and the GNN (both present in code, both currently unverified live).

**4. Current gaps that block it.**
- `ML-09`/`ML-10` — neither the rule-based structuring detector nor the GNN has been exercised
  against a real money trail live. This phase cannot be called done on code presence alone; it
  needs an actual flagged trail driven end-to-end.
- `UI-26`'s label-overlap at high fan-out (60+ destination nodes observed) needs resolving so the
  visualization stays legible on the cases most likely to actually need it — a launderer's real
  trail is exactly the high-fan-out case.
- The GNN's deliberate absence from the deployed image (`torch` excluded by design, per the size
  constraint) means this phase must define what "done" means for the GNN specifically on the
  live deployment: the rule-based detector must be fully verified live regardless, and the GNN's
  correct behavior is verified either in an environment where `torch` is present or is
  explicitly scoped as "verified to degrade correctly, not verified to detect" for the live
  deployment — this decision belongs to this phase, not left implicit.

**5. Acceptance criteria.**
- A real financial trail (an account/person combination known to have transfers) is queried live
  and renders correctly in the Sankey view with legible labels regardless of fan-out.
- At least one known-structured or known-layered pattern from the generator's injected AML
  ground truth is queried and the correct detector output (rule flag, GNN flag, or both) is
  confirmed live, or the GNN's live-degradation behavior is confirmed correct and documented as
  the scoped outcome for the deployed image.
- An empty trail still returns the correct negative finding (already fixed by `BUG-013`,
  re-verified as part of this phase's regression pass rather than assumed still correct).

**6. What must NOT be built yet.** No new detector beyond the two that exist; no expansion of the
financial graph traversal beyond current role-capped depth; no attempt to add `torch` back into
the deployed image purely to unblock this phase — that tradeoff (image size vs. GNN live
reachability) is a platform-constraint decision this phase should surface clearly, not silently
route around.

---

## Phase 6 — Full Investigation Briefing (capstone)

**1. Investigator workflow.** *"Give me everything on this open case in one place: a
chronological timeline, the leads, the similar past cases, a paste-ready diary paragraph — and let
me export it as something I could actually hand to a supervisor or attach to a case file."*
This phase is the North Star's stage-12 (briefing/reporting) target realized, and it is
deliberately last because it is the one workflow that genuinely depends on every prior phase's
slice being real: a briefing built on an unfixed narrative layer, an illegible map, or an
unverified financial detector would just be packaging the earlier gaps more attractively.

**2. North-Star capabilities satisfied.** Stage 12 (briefing/reporting) in full; stage 5
(timeline construction) closed out (the Copilot timeline's interactive verification gap from
Phase 3 gets its final check here in the context of a full briefing); the LLM-fluency
differentiator (§1.4), scoped to this workflow specifically rather than left as a standing
platform-wide gap.

**3. Existing components reused.** The full Investigation Copilot (`Copilot.tsx`, `/copilot/{id}`,
timeline/leads/diary/similar-cases, all four sub-capabilities now genuinely correct from Phases
2-5); the citation-chain/evidence-rail pattern from Phase 1; the export pipeline.

**4. Current gaps that block it.**
- `BUG-018` — PDF export returns HTML, not a PDF; SmartBrowz is claimed but not reachable. This
  phase is the natural place to resolve it, since it is exactly the reporting-format claim this
  workflow depends on.
- `BUG-022` — QuickML unreachable. This phase is where LLM fluency actually matters most (a
  paste-ready diary paragraph benefits from fluent synthesis in a way a single-record lookup does
  not) — if BUG-022 remains unresolved by this point, this phase should explicitly decide whether
  the deterministic extractive diary is an acceptable shipped outcome (it is grounded and correct,
  per §1.2, just less fluent) rather than silently blocking on a vendor-side issue outside this
  team's control.
- `UI-29` (diary copy button) and the remaining UNKNOWN interactive Copilot-overlay items from
  Phase 3 need closing here, in the context of the complete workflow.

**5. Acceptance criteria.**
- An officer opens a real case, live, and receives a complete Copilot brief where the timeline,
  leads, and similar-cases are each independently correct per Phases 2-5's own acceptance
  criteria — this phase's test is that assembling them together introduces no new defect, not
  that each sub-capability is separately re-invented.
- PDF export produces an actual PDF (via SmartBrowz) or, if that remains unresolved, the console
  honestly represents what it is producing — no format claim exceeds what's actually served.
  currently.
- The full workflow — open case, read brief, follow a citation back to its record, export or copy
  the result — is driven end-to-end on the live deployment under a realistic officer role, not
  verified piecemeal across separate sessions.

**6. What must NOT be built yet.** No new report formats beyond PDF/paste-ready text; no
automated report submission or routing (the North Star is explicit that this stays
investigator-facing decision support, not a prosecutor-submission pipeline); no further LLM
provider integration beyond resolving QuickML reachability — if QuickML remains unreachable after
reasonable effort, the deterministic path is the correct shipped state, not a reason to add a
different LLM service.

---

## Summary sequencing table

| Phase | Workflow | Primary gate it closes | Depends on | Status |
|---|---|---|---|---|
| 1 | Trusted single-record lookup | Evidence/trust bar (§1.3) genuinely solid | — | **Done, live-verified** — BUG-008/011/014 fixed |
| 2 | Data foundation + cross-case discovery | BUG-023, the North Star's largest named gap | Phase 1's evaluator discipline, not its output | **Done, live-verified** — narrative diversity + explainable similarity |
| 3 | Person network & leads | Entity/link/leads stages, trustworthy identity | Phase 2 (identity-key persistence) | **Done, live-verified** — network/leads already solid; fixed a mislabeled `risk_score`→`pagerank` field |
| 4 | Geographic intelligence | Map usability, honest ground-truth disclosure | Independent of 2, 3 | **Done, live-verified** — 31 real district labels + scale control; boundary polygons deliberately not fabricated |
| 5 | Financial intelligence | Two-detector differentiator, live-verified | Independent of 2, 3, 4 | **Done, live-verified** — found & fixed a real bug making AML detectors structurally unreachable; GNN stays unavailable (documented platform constraint) |
| 6 | Full investigation briefing | Briefing/reporting stage, capstone integration | 1-5 all closed | **Done, live-verified** — multi-turn context, Copilot orchestration, 9-investigation final acceptance pass all confirmed; PDF export 2/3 root causes fixed, 1 platform identity question remains open |

All six phases complete and live-verified as of this pass. See `docs/PHASE1_FAILURE_LOG.md` and `docs/QA_FUNCTIONALITY_MATRIX.md` for the full evidence trail per fix.

Phases 3, 4, and 5 have no dependency on each other and no dependency on Phase 2 beyond the
identity-key persistence Phase 3 specifically needs — they may proceed in any order, or in
parallel, once Phase 1 and Phase 2 are done. Phase 6 is strictly last.
