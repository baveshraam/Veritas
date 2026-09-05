# Veritas — Implementation Strategy: North Star → Live System

**Status: all six phases below are complete and live-verified.** This document records why
phases were sequenced the way they were — especially where BUG-023 was placed — not an open
plan. For what's true today, read `CLAUDE.md`; for the fix-by-fix trail, read
`docs/PHASE1_FAILURE_LOG.md` and `docs/QA_FUNCTIONALITY_MATRIX.md`.

**The gate every phase had to clear**, which is why phases were sequenced by workflow rather
than by feature area:
```
DATA → correct algorithm/retrieval → evidence validation → conversational behavior
     → UI → authorization → live deployment → realistic investigator workflow
     → acceptance test
```
A phase closed only when an officer could run the workflow live, under their role's real
authorization, and get a cited, verified answer they could act on.

---

## Where the data-foundation correction (BUG-023) belonged

Placed as the **DATA step of Phase 2 (Cross-Case Discovery)**, not a standalone phase or a
prerequisite for every other phase:

- HippoRAG, the `criminal_profile` vector collection, the co-offending graph, the financial
  layer, and hotspot detection are all structured-field-driven and untouched by `BriefFacts` —
  gating them on the narrative fix would have blocked work on a dependency they don't have.
- Only cross-case similarity (`fir_narrative` search, the Copilot's "similar past cases") was
  structurally blocked by the narrative collapse — the North Star's largest named gap.
- Sequenced **second**, not deferred: it was cheap and self-contained (weighted slot-filling,
  the pattern `refdata.py`/`priors.py` already used), and fixing it early avoided building
  further UI/demo material on known-degenerate data.

---

## Phase 1 — Trusted Single-Record Lookup

**Workflow**: a case number, a person's name, or a specific question about one record gets a
correct, scoped, cited answer — or an explicit statement that the records don't support one.
This is the base every later phase's evidence-validation and authorization work reused.

**Closed**: `BUG-011` (similarity displayed as evidential confidence), `BUG-008` ("how many"
questions returned narratives, never a count), `BUG-014` (saturated 1.00 risk scores at the
same visual weight as a cited record), and locked the CRAG evaluator's floor logic behind a
regression suite broad enough to catch a dropped authoritative citation (the BUG-006/BUG-020
failure shape).

**Acceptance**: all six roles verified live on FIR-number/person-name/count-style questions —
citations genuinely support the claim, refusals name their specific reason, counts return
numbers, confidence values are labelled for what they measure, and role/station scoping holds
per-endpoint.

---

## Phase 2 — Data Foundation Correction + Cross-Case Discovery

**Workflow**: given an open case, surface past cases actually similar in method — not just
sharing a crime-type label.

**Closed**: `BUG-023` (12/20 crime types produced zero descriptive narrative content, the other
8 exactly one fixed sentence each) via widened weighted `_MO` slot-filling; added a
narrative-diversity CI check so this class of gap can't go undetected by manual sampling again;
persisted the identity-resolution answer key (`docs/DATA_GENERATION_AUDIT.md` §19) so F1 can be
recomputed against whatever dataset is actually live, not only a fresh local `generate()` call.

**Acceptance**: regenerated data produces more than one distinct narrative shape per crime type
across all 20 types; a live "similar cases" query is demonstrably driven by shared method
detail, not solely crime-type/district; every measurement elsewhere in the repo referencing
specific FIRs/people/citation counts was re-verified against the regenerated dataset before
this phase closed.

---

## Phase 3 — Person Network & Investigative Leads

**Workflow**: show who a person operates with, whether they have priors under a different name
spelling, and a short, actionable lead list for this week.

**Closed**: depended on Phase 2's identity-key persistence for independent re-verification;
closed `ML-08` (centrality output reaching `/person` and evidence) to VERIFIED; drove the
citation-chip-to-evidence-rail interaction end to end; fixed a mislabeled `risk_score`→
`pagerank` field found along the way.

**Acceptance**: a named-person query with a known spelling variant returns the correct
cross-case history live; the network view renders and a click lands on the correct supporting
record under real interactive verification; the Copilot's lead list stays capped at direct
co-accused, never an unbounded connected component; RBAC holds throughout.

---

## Phase 4 — Geographic Intelligence

**Workflow**: crime concentration in a district as an actual readable map — not an abstract
scatter — so resource-deployment reasoning works the way it would on a real geographic tool.

**Closed**: `UI-24` — the map rendered points/clusters with **no geographic reference at all**
(no district outlines, scale, or labels); fixed with 31 real district labels and a scale
control (later superseded by the real MapLibre basemap, CLAUDE.md v15). Also documented that
hotspot *placement* is a synthetic stand-in, not real POI-derived ground truth — made as
prominent as the capability claim, not buried in a docstring.

**Acceptance**: both a named-district and a bare "show hotspots" query render with recognizable
geographic anchoring live; the rendered geography was checked against the underlying KDE/DBSCAN
output for correctness, not just "something renders."

---

## Phase 5 — Financial Intelligence

**Workflow**: trace the money from an account or person, see the flow as a followable diagram,
and know whether either detector — the auditable rule or the pattern-catching model — flagged
anything, with the reasoning visible.

**Closed**: `ML-09`/`ML-10` — neither the rule-based structuring detector nor the GNN had been
exercised against a real money trail live; found and fixed a real bug making both structurally
unreachable. Resolved the `UI-26` Sankey label-overlap at high fan-out (60+ nodes) — exactly
the case a real launderer's trail produces. Scoped the GNN's deployed-image absence (`torch`
excluded by size) explicitly as "verified to degrade correctly, not verified to detect" rather
than leaving it ambiguous.

**Acceptance**: a real financial trail renders correctly in the Sankey view with legible labels
regardless of fan-out; at least one known AML ground-truth pattern is confirmed live via the
rule detector (GNN's degradation confirmed separately); an empty trail returns the correct
negative finding (`BUG-013`).

---

## Phase 6 — Full Investigation Briefing (capstone)

**Workflow**: everything on an open case in one place — timeline, leads, similar past cases, a
paste-ready diary paragraph — exportable as something handed to a supervisor or attached to a
case file. Deliberately last: it depends on every prior phase's slice being genuinely real,
since a briefing built on an unfixed narrative layer or an unverified detector would just
package the earlier gaps more attractively.

**Closed**: `BUG-018` (PDF export returned HTML, not a PDF — SmartBrowz claimed but not
reachable; 2 of 3 root causes fixed, one platform identity-scoping question remains open, see
"Platform gotchas" in CLAUDE.md); `BUG-022` (QuickML unreachable at the time, later resolved —
CLAUDE.md v12/v17) — scoped explicitly that the deterministic extractive diary is grounded and
correct on its own, just less fluent, rather than silently blocking on a vendor-side issue.

**Acceptance**: a real case, live, produces a complete Copilot brief where timeline/leads/
similar-cases are each independently correct per Phases 2-5's own criteria; the full
workflow — open case, read brief, follow a citation, export or copy — was driven end-to-end on
the live deployment under a realistic officer role.

---

## Summary sequencing table

| Phase | Workflow | Primary gate it closed | Depends on | Status |
|---|---|---|---|---|
| 1 | Trusted single-record lookup | Evidence/trust bar genuinely solid | — | **Done** — BUG-008/011/014 fixed |
| 2 | Data foundation + cross-case discovery | BUG-023, the North Star's largest named gap | Phase 1's evaluator discipline, not its output | **Done** — narrative diversity + explainable similarity |
| 3 | Person network & leads | Entity/link/leads stages, trustworthy identity | Phase 2 (identity-key persistence) | **Done** — fixed a mislabeled `risk_score`→`pagerank` field |
| 4 | Geographic intelligence | Map usability, honest ground-truth disclosure | Independent of 2, 3 | **Done** — 31 district labels + scale; boundary polygons deliberately not fabricated |
| 5 | Financial intelligence | Two-detector differentiator, live-verified | Independent of 2, 3, 4 | **Done** — fixed a bug making AML detectors structurally unreachable; GNN stays a documented platform constraint |
| 6 | Full investigation briefing | Briefing/reporting stage, capstone integration | 1-5 all closed | **Done** — multi-turn context, Copilot orchestration, 9-investigation acceptance pass confirmed; PDF export's one open item is a platform identity-scoping question |

Phases 3, 4, and 5 had no dependency on each other or on Phase 2 beyond the identity-key
persistence Phase 3 needed — they could and did proceed independently once Phases 1-2 closed.
Phase 6 was strictly last.
