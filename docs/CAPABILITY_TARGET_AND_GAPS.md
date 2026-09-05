# Veritas — Capability Target & Gap Analysis

**Superseded.** `docs/STRATEGIC_RESET_2026-09-04.md` re-did this comparison 2026-09-04/05 by
reading the code a second time; its conclusions about *current state* win where they overlap.
Part 1 (North Star research) and the P0-P3 framework stay useful as reference; Parts 2-4 are
condensed to what's still open.

**Purpose.** Defines the target state of an industry-grade conversational investigation
platform, then compares the implementation against it — a steering document, not a pitch.

**Sources.** `CLAUDE.md`/`README.md`; `docs/QA_FUNCTIONALITY_MATRIX.md` and
`docs/PHASE1_FAILURE_LOG.md` (24 tracked defects); `docs/DATA_GENERATION_AUDIT.md` (19-dimension
generator audit); web research on real investigative platforms and law-enforcement operating
models (Palantir Gotham, IBM i2 Analyst's Notebook, ViCAP, CompStat, AML/FinCEN practice, CJIS,
NIST AI RMF, the EU AI Act's predictive-policing provisions, crime-linkage/predictive-policing-
bias literature). Tagged **[SOURCE]** (a cited fact), **[SYNTHESIS]** (a pattern generalized
across sources), or **[INFERENCE]** (this doc's own reasoning).

**Non-goal.** No code is changed here; Part 3 is a ranked punch list, not a task breakdown.

---

## Part 1 — The North Star

### 1.1 The investigation workflow loop

**[SYNTHESIS]** Across i2, Gotham, and the crime-linkage literature, graph/map/timeline are
*co-equal, synchronized* windows onto one case (i2's "ELP"; Gotham's "common operating
picture"). Veritas's cross-faded centre-pane (map/network/Sankey/forecast) is in this lineage.

Thirteen stages, each with the source fact and the Veritas target:

1. **Case initiation. [SOURCE]** Physical investigations triage-then-lock (PERF Homicide SOP).
   Target: recognizing an FIR reference orients every later turn around it.
2. **Case context. [SYNTHESIS]** No mature platform front-loads a dossier (IALEIA folds context
   into continuous collection). Target: context is live retrieval-graph state (HippoRAG PPR),
   not a stale briefing.
3. **Entity discovery. [SOURCE]** ER links fragmented records via exact/fuzzy/probabilistic
   matching (WinPure; Semantic Visions; Gotham); for gov/justice work the bar is *auditability of
   match decisions*, not raw accuracy (IJIS; arXiv). Target: every reconstructed person carries
   inspectable match confidence — the reason identity resolution exists at all (`CLAUDE.md` §0).
4. **Link analysis. [SOURCE]** i2's ELP: 30+ years, 2,000+ orgs; Gotham pairs it with
   provenance. **[INFERENCE]** Neither documents graph algorithms as explicitly as Veritas —
   most commercial tools present the graph for analyst judgment, not as a ranking signal.
   Target: keep GDS-equivalent algorithms (PageRank, Louvain, betweenness) as retrieval inputs.
5. **Timeline construction. [SOURCE]** i2/Gotham treat timeline as one of several synchronized
   views, never separately derived. Target: Copilot timeline stays wired to the same citations
   as chat and graph.
6. **Evidence handling. [SOURCE]** SWGDE/NIST require contemporaneous chain-of-custody, a unique
   ID, and a crypto hash. **[SYNTHESIS]** Structurally identical to
   `ChainHash = sha256(PrevHash ‖ ResponseHash)`. **[INFERENCE]** Not exact — literature is
   exhibit-centric, Veritas's chain is answer-centric; keep that distinction explicit.
7. **Geographic intelligence. [SOURCE]** CompStat pairs mapping with accountability (NYPD/
   Bratton). The bias literature is contested: one study found PredPol-style targeting could
   direct 150-400% more patrol toward Black/Latino communities in a modeled deployment (MIT Tech
   Review); a counter-study (Brantingham et al.) found no such bias in a real LAPD comparison.
   **[SYNTHESIS]** Both sides agree historical crime data encodes policing *intensity*, not true
   incidence. Target: hotspot detection (KDE/DBSCAN) must never look more real than the data
   underneath — why the Aequitas geographic audit and causal-layer confounder disclosure exist.
8. **Financial intelligence. [SOURCE]** FinCEN SAR has hard deadlines/thresholds; ACAMS frames
   AML scope as breadth × depth; production tools (NICE Actimize) pair deterministic rules with
   network-risk analytics. **[SYNTHESIS]** Maps onto Veritas's role-based depth cap and directed
   `TRANSFERRED_TO` edges. Target: keep the two-detector pattern (auditable rule + GNN) — matches
   production AML architecture.
9. **Cross-case discovery. [SOURCE]** FBI ViCAP (1985) exists to prevent "linkage blindness" but
   names its own weakness: manual entry needing trained expertise. Standard practice combines MO
   similarity with proximity; recent work frames this as ML. **[SYNTHESIS]** Veritas's hybrid
   similarity search + Copilot's "top-5 similar cases" is a modernized answer to ViCAP's gap.
   Target: value depends entirely on the narrative actually carrying case-specific signal (§1.5).
10. **Investigative leads. [SOURCE]** Every mature pattern surveyed — crime-linkage generation,
    AML triage, Palantir AIP's "agents propose, not act" — converges: system surfaces a ranked
    candidate, human decides. **[SYNTHESIS]** Validates `CLAUDE.md` §9's human-in-the-loop
    principle as matching professional practice. Target: leads capped to direct co-accused only.
11. **Verification. [SOURCE]** US criminal procedure has a graduated evidentiary ladder
    (reasonable suspicion → probable cause → higher standards). **[SYNTHESIS]** A real precedent
    for the CRAG evaluator's accept/widen-and-retry/refuse shape. **[INFERENCE]** Cross-domain
    analogy only — not a claim of meeting any actual evidentiary standard.
12. **Briefing/reporting. [SOURCE]** Prosecutor-facing referral reports follow a fixed structural
    template (POST; IRM 9.5.8); poor documentation risks rejection. **[SYNTHESIS]** Analogous to
    Veritas's citation-chain format and PDF export. **[INFERENCE]** Target: exports are
    decision-support artifacts, not a substitute for the human-authored report.
13. **Audit/collaboration. [SOURCE]** CJIS requires role-based need-to-know, mandatory logging
    (≥1yr retention), an unbroken audit trail, independent audits every 3 years.
    **[SYNTHESIS]** Analogous to Veritas's `Employee`-row policy, hash chain, and the 12-hourly
    `veritas_audit_verify` job. **[INFERENCE]** Karnataka Police is under Indian law, not CJIS —
    describe as "structurally analogous to," never "compliant with."

### 1.2 What conversational AI/RAG must do at each stage

Organizing constraint: **AI output supports a documented human decision; it never is the
decision** (NIST AI RMF; EU AI Act Art. 5(1)(d); Palantir AIP's "propose not decide").
**[SYNTHESIS]** Veritas's CRAG evaluator enforces this structurally — the single most important
property in the system.

**[SOURCE]** RAG literature names "citation-shaped hallucination" — an answer that looks
grounded while unsupported — exactly what `BUG-006` was (unrelated citations padding a correct
FIR lookup at 0.97 confidence): a named general failure class, not Veritas-specific.

Per stage: **orient** (1-2) — recognize the subject, keep it in view across turns. **Retrieve
with structure, not string-matching** (3-5) — multi-hop graph retrieval for relational
questions, narrative retrieval only where it carries signal. **Never assert past the evidence**
(6, 11) — CRAG on every turn, no bypass. **Surface, never decide** (9-10) — rank, don't act.
**Package for accountability** (12-13) — every artifact carries its evidence chain forward.

### 1.3 Evidence / trust / authorization bar

1. Every claim in free text traces to a specific record; untraceable → "not found" instead.
   Constrains the language model itself, not just the UI.
2. Role/station scope enforced at query-construction time (`WHERE` clause, depth-cap before the
   walk runs) — not only post-hoc masking, which can't reliably redact a name from prose.
3. Audit trail tamper-evident by construction, verified on a schedule, verification itself
   exercised.
4. No protected/proxy attribute is ever a model feature. Caste/religion stored (conformance)
   but never scored; gender exists only as a fairness-audit subgroup label.
5. Every prediction is decision support with explicit uncertainty — "the model suggests" vs.
   "the record shows," on every surface carrying a model output.

### 1.4 Capability tiers

**Foundational:** identity resolution with inspectable match confidence; CRAG accept/widen/
refuse loop; role/station-scoped retrieval at query-construction time; a verified tamper-evident
audit chain; a synthetic dataset whose structured signal (identity, co-offending, financial,
temporal, geographic) is real and tested (§1.5).

**High-value differentiators:** HippoRAG/Think-on-Graph over ad-hoc embedding search; graph
algorithms as ranking signal, not decoration; two-detector AML (rule + GNN); Aequitas fairness
auditing with an explicit unmeasured-confounder disclosure; in-container Kannada voice/text;
multi-turn memory with correct reference resolution.

**Optional, correctly deferred at this scale:** real-time CCTNS ingestion (Kafka/Flink); a
production-grade spatio-temporal forecaster beyond Prophet+MinT; federated HR identity
(Keycloak); a policy engine beyond a Python module (OPA/Rego).

**Historical, largely resolved (see `STRATEGIC_RESET`):** narrative diversity overclaimed for
60% of crime types (`BUG-023`, since all 20, still template-bounded — §1.5); SmartBrowz PDF
export claimed live while falling back to HTML (`BUG-018`, still honestly disclosed); a v8
weight-location claim corrected in v12; a saturated 1.00 risk score shouldn't carry a record's
visual weight (`BUG-014`, addressed by v19's provenance channels).

**Unnecessary for this competition:** Kubernetes/GitOps, MLflow, Iceberg/MinIO — correctly
described-not-built (`CLAUDE.md` Appendix A); a from-scratch India-specific CJIS-equivalent
certification — out of scope; the structural analogy (§1.1 stage 13) is the right ambition.

### 1.5 Data foundation as part of the North Star

A capability whose underlying data carries no signal can't be fixed by fixing the code that
reads it. `docs/DATA_GENERATION_AUDIT.md` evaluated 19 dimensions:

- **Solid:** identity-resolution ground truth, co-offending/crew structure (what lets Louvain
  find real communities), financial ground truth kept separate from detector output, graph
  structural integrity, full generation determinism — with real statistical bugs fixed (EM
  contamination in the Fellegi-Sunter `u`-estimate; string-concatenation inflation in the name
  comparator).
- **Was broken, now partially fixed (`BUG-023`):** 12 of 20 crime types produced zero
  descriptive narrative content, undermining FIR semantic search and Copilot similarity directly
  — the near-duplicate-narrative symptom `BUG-006`'s citation-padding surfaced. Now all 20 have
  real content, but per `STRATEGIC_RESET` Part 1 it's still a closed 3-variant template set —
  common, not *distinctive*, per crime-linkage theory. HippoRAG never touches this field; only
  FIR semantic search and Copilot similarity depend on it. Target state (wider slot-filling, a
  narrative-diversity regression test) remains open — see `STRATEGIC_RESET` Part 6 item 4
  (LLM-authored narrative, deliberately gated on billing data).

---

## Part 2 — Current vs. North Star (2026-08-27 snapshot; superseded by `STRATEGIC_RESET`)

At the time, already close to target on: case initiation (FIR-number regex fixed), case context
(HippoRAG live), link analysis (GDS algorithms verified live), evidence handling (audit chain
intact, Cron-verified), investigative leads (capped to direct co-accused), and audit/
collaboration (all six roles RBAC-verified, two P0 auth defects fixed).

Real gaps found then, **all since resolved** (`CLAUDE.md` v10-v19; `STRATEGIC_RESET` Part 1): no
map geographic reference (`UI-24`, fixed v14-v15); "how many" returned no count (`BUG-008`);
similarity scores shown as evidential confidence (`BUG-011`); identity F1 answer key not
persisted (fixed v13); a CRAG regression (`BUG-020`) briefly reintroduced by `BUG-006`'s own fix.

**Gaps real then and still open** (confirmed by `STRATEGIC_RESET`):
- **Cross-case discovery (stage 9)** — the largest gap: narrative signal too collapsed for
  genuine MO linkage, closer to "same crime type, same district." Partially closed; see §1.5.
- **Financial intelligence (stage 8)** — the GNN AML detector remains unverified against any
  real positive case live.
- **Briefing/reporting (stage 12)** — PDF export still an honestly-labeled HTML fallback;
  SmartBrowz blocked on an interactive Catalyst identity no automated session can drive.
- **AI interface** — fully blocked at this snapshot (`BUG-022`); QuickML is live since v17, but
  Aequitas remains a script nobody schedules — see `STRATEGIC_RESET` Part 9, Item 1.

---

## Part 3 — Prioritized gap ranking

Ranked by cost to an officer and to the judging objective, not implementation difficulty.
**RESOLVED** items kept for the reasoning trail only.

### Still open

**Narrative distinctiveness (was P0-1/P0-2, `BUG-023`).** All 20 crime types have real MO text,
but only 3 template variants each — common, not distinctive. No regression test guards against
this collapsing again. *Why it matters:* "similar past cases" is a headline capability; today
it's closer to a crime-type filter than genuine MO linkage — the ViCAP gap since 1985. Cheapest
real fix: LLM-authored per-case detail at generation time, gated on watching real QuickML
billing first.

**Aequitas not wired into any live schedule.** `fairness_run_audit.py` exists, nothing calls it.
*Why it matters:* predictive components invite the over-policing-bias question directly, and an
unscheduled mitigation is a claim, not a verifiable safeguard. Ranked CRITICAL in
`STRATEGIC_RESET` Part 9, Item 1 — no blocker, ready to build.

**Financial detectors (`ML-09`/`ML-10`) unverified against a real positive live.** The
two-detector AML pattern is architecturally sound and matches production practice, but neither
has been exercised against a real money trail live.

**Real PDF export blocked.** SmartBrowz needs an interactive Catalyst identity no automated
session can drive; console downloads an honestly-labeled HTML fallback. Not a correctness
defect — the console never misrepresents the file type — but the claimed service isn't serving.

**Seasonal signal absent from generated incident timing.** Prophet's seasonality terms fit noise
here — not a defect, but a demo risk: don't claim "the forecast captures a weekly pattern."

### Resolved (reasoning trail only)

`BUG-006`/`BUG-020` (citation padding / CRAG regression) — fixed, regression-tested.
`BUG-008` (no count returned) — fixed. `BUG-011` (similarity as evidential confidence) — fixed.
`BUG-014` (saturated risk score visual weight) — addressed by v19 provenance channels.
`BUG-017` (weight-location doc) — corrected v12. `BUG-018` (PDF-as-HTML) — disclosed, format gap
remains. `BUG-021`/`BUG-022` (QuickML unreachable) — live since v17. `BUG-023` (12/20 crime
types with no narrative) — partially fixed. `UI-24` (map had no geographic reference) — fixed
v14-v15. `BUG-026` (Copilot name cross-reference) — fixed v19. `BUG-027` (Cron never fired
unattended) — fixed v13.

### Correctly deferred/cut

`BUG-016` (Kannada latency, 13.4s) — a performance characteristic, not a trust gap; improved
since (`CLAUDE.md` v12 §12). `BUG-019` (`"fir"` substring match) — fixed v12. `BUG-005`'s
WebSocket verification gap — moot; `/alerts` moved to SSE in v12. AML detector specificity
against organic transactions — honestly disclosed as untested, not worth a synthetic-corpus
build under competition constraints. A from-scratch CJIS-equivalent certification — out of
scope; the structural analogy (§1.1 stage 13) is the right ambition.

---

## Summary

The North Star isn't a larger feature set — it's the discipline already visible in the system's
best-built parts (identity resolution, the CRAG evaluator, the audit chain, the co-offending
graph) applied consistently to what still falls short: a narrative layer with genuinely
distinctive case-specific signal, financial detectors verified against real data, and a fairness
audit that runs on a schedule rather than existing only as a script. Most gaps from this
document's original pass have closed (`CLAUDE.md` v10-v27); what remains open is tracked in
`docs/STRATEGIC_RESET_2026-09-04.md` Part 9.

---

## Part 4 — Industry-baseline snapshot (2026-08-26, historical)

Point-in-time comparison against real platforms and standards. Treat "Veritas today" as
historical — cross-check against `STRATEGIC_RESET` before relying on it.

| Capability | Industry expectation | Gap found then | Resolution |
|---|---|---|---|
| Entity resolution w/ inspectable confidence | i2/Gotham: heavy dedup investment, auditable matches | Copilot leads didn't cross-reference a resolved name against the case's as-filed name (`BUG-026`) | **Fixed v19** |
| Link/graph analysis as ranking signal | Most COTS tools treat the graph as a visualization surface only | None — Veritas already ran PageRank/Louvain as retrieval input, confirmed live | Already a differentiator |
| Anomaly/alert feed w/ explainable factors | ACAMS: a human decides, but factors must be visible | None — `/alerts` streams district/metric/observed/expected/severity | Already met |
| Briefing/reporting export | POST/IRS fixed-template reports need structural consistency | Real PDF blocked on interactive-OAuth; HTML fallback is a genuine, citation-carrying record | Fallback disclosed; format gap **still open** |
| LLM-fluent synthesis | Most COTS platforms sit an LLM over retrieved evidence | `QUICKML_ENDPOINT_KEY` unset — every answer was the deterministic extractive path | **Resolved — QuickML live since v17** |
| Scheduled integrity verification firing unattended | CJIS: periodic independent audit, not just present in code | `veritas_audit_verify` silently non-functional despite an earlier "fixed" claim (`BUG-027`) | **Fixed v13**, confirmed live |
| Fairness/bias auditing | NIST AI RMF, EU AI Act Art. 5(1)(d): geographic + demographic subgroup audits | Aequitas exists but is a standalone script, not scheduled | **Still open** — `STRATEGIC_RESET` Part 9, Item 1 |
| Real-time ingestion (CCTNS/Kafka) | Modern platforms increasingly integrate live feeds | N/A at this dataset scale | Correctly out of scope |
| India-specific CJIS-equivalent certification | No such standard located for Indian state police | N/A | Correctly out of scope — structural analogy only |

**Verdict:** no item ever required new architecture. The two credential-blocked items (real PDF,
and — at the time — LLM fluency) shipped as BLOCKED with an honest fallback; LLM fluency has
since resolved itself once the credential was obtained. Aequitas scheduling is the one item on
this table still genuinely open.
