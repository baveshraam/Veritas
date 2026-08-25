# Veritas — Product & System North Star

**Purpose.** This document defines what Veritas should ultimately be — the target state of an
industry-grade conversational investigation platform — and then systematically compares the
current implementation against that target. It is a steering document, not a pitch and not an
implementation plan: it does not prescribe code changes, and it says plainly where the current
system falls short.

**Sources synthesized.**
- `CLAUDE.md` and `README.md` — architecture and claims as documented.
- `docs/QA_FUNCTIONALITY_MATRIX.md` and `docs/PHASE1_FAILURE_LOG.md` — what has actually been
  live-verified, and 24 tracked defects (3 P0, 15 P1, 6 P2, 1 P3; 16 fixed and live-verified, 9
  open).
- `docs/DATA_GENERATION_AUDIT.md` — a 19-dimension audit of the synthetic data generator.
- Live web research into real investigative platforms and law-enforcement operating models
  (Palantir Gotham, IBM i2 Analyst's Notebook, ViCAP, CompStat, AML/FinCEN practice, CJIS,
  NIST AI RMF, the EU AI Act's predictive-policing provisions, and the academic crime-linkage
  and predictive-policing-bias literature). Every claim drawn from that research is tagged
  **[SOURCE]** (a specific cited fact), **[SYNTHESIS]** (a pattern generalized across sources),
  or **[INFERENCE]** (this document's own reasoning, not directly sourced) — the same tagging
  discipline the research brief itself used, carried through so a reader can tell what is
  externally verified from what is this document's own judgment.

**Non-goals.** No code is changed by this document. No data is regenerated. Part 3's priority
list is a ranked punch list of *what matters and why*, not a task breakdown — turning P0/P1
items into implementation work is a separate, later step.

---

## Part 1 — The North Star

### 1.1 The investigation workflow loop

The organizing idea: an investigating officer's work is one continuous loop, not a set of
disconnected screens. Mature platforms converge on this whether or not they name it explicitly.
**[SYNTHESIS]** Across i2 Analyst's Notebook, Palantir Gotham, and the AML/crime-linkage
literature, three views — graph, map, and timeline — recur as *co-equal, synchronized* windows
onto one case, not separate tools an analyst switches between and reconciles by hand
(i2's entity-link-property "ELP" methodology; Gotham's "common operating picture" combining
graph + map + timeline). Veritas's centre-pane design (map / network / Sankey / forecast,
cross-faded rather than hard-cut) is already in this lineage, not merely inspired by it.

Below, each of the 13 stages is defined as a target: what a real officer needs, and what
conversational AI must contribute at that point in the loop.

**1. Case initiation.** **[SOURCE]** In physical investigations, this stage is triage-then-lock:
a rapid classification decision immediately followed by a scope-freezing action — a scene
perimeter, an entry/exit log, an initial report (Police Executive Research Forum's Homicide
Investigation SOP). **[INFERENCE]** This stage happens *before* any record enters a system like
Veritas — Veritas's analog is not "opening a case" but "the first query against an FIR that
already exists in the record layer." The target for Veritas at this stage is narrower than the
literature's: recognize a case reference (an FIR number, a person's name) the moment it appears
in a query and orient every subsequent turn around it, rather than treating each question in
isolation.

**2. Case context.** **[SYNTHESIS]** No mature platform treats this as a separate front-loaded
dossier-building step; IALEIA's *Law Enforcement Analytic Standards* fold context-gathering into
the intelligence cycle's collection/processing phases, assembled continuously rather than once.
The target for Veritas: context is the live state of the retrieval graph at query time (what
HippoRAG's Personalized PageRank surfaces from the entities in the question), not a static
briefing document generated once and gone stale.

**3. Entity discovery.** **[SOURCE]** Entity resolution is the standard mechanism for linking
fragmented records into one profile across aliases and jurisdictions (WinPure; Semantic
Visions), and the textbook approaches are exact match, fuzzy match, and probabilistic linkage
(IJIS Institute). **[SOURCE]** Palantir Gotham lists "heavy investment in deduplication and
entity resolution" as a core capability underlying its investigative workflows. **[SOURCE]** For
government/justice deployments specifically, the practical bar is *auditability of match
decisions*, not raw match accuracy (IJIS, arXiv *Large Scale Record Linkage in the Presence of
Missing Data*). The target: every reconstructed person carries an inspectable match confidence,
not just a merged name — which is precisely what identity resolution must be for a schema with
no person entity to begin with (see §0 of `CLAUDE.md`).

**4. Link analysis.** **[SOURCE]** i2 Analyst's Notebook's ELP methodology (entities, links,
properties) has been the standard for 30+ years across 2,000+ organizations. **[SOURCE]** Gotham
pairs this with published-strength data integration, provenance discipline, and proven
operational history (its case-management system has run HSI's mission since 2011).
**[INFERENCE]** Neither platform's public documentation specifies its underlying graph
algorithms as explicitly as Veritas does (PageRank, Louvain, betweenness) — most commercial
link-analysis tools present the graph as a *visualization surface for analyst judgment*.
The target for Veritas is to keep running published GDS-equivalent algorithms as retrieval and
ranking signals, not just as a rendering — a genuine point of difference worth claiming, not
merely restating.

**5. Timeline construction.** **[SOURCE]** Both i2 and Gotham treat timeline as one of three
synchronized views (link, temporal, and — for Gotham — spatial), never as a separately-derived
artifact. **[INFERENCE]** The target for Veritas: the Investigation Copilot's timeline must stay
wired to the same evidence citations as chat answers and the graph pane, not become an isolated
feature computed from a different code path.

**6. Evidence handling.** **[SOURCE]** SWGDE/NIST digital-evidence guidance requires
chain-of-custody documentation to be contemporaneous to collection, to include a unique
identifier, collection timestamp, and every transfer, and requires a cryptographic hash over
acquired data for later integrity validation. **[SYNTHESIS]** This is structurally identical to
Veritas's own audit design (`ChainHash = sha256(PrevHash ‖ ResponseHash)`) — hashing to prove
non-tampering, contemporaneous append-only logging, unbroken transfer records. **[INFERENCE]**
The parallel is real but not exact: the literature's model is exhibit-centric (one physical
item, one custody log); Veritas's is answer-centric (one generated response, one hash chain).
The target: keep that distinction explicit rather than implying Veritas's chain proves an
*exhibit* wasn't altered — it proves the *audit log* wasn't altered, which is narrower but still
meaningful.

**7. Geographic intelligence.** **[SOURCE]** CompStat pairs crime mapping with accountability
meetings and resource-deployment decisions (NYPD/Bratton; Wilmington PD program). **[SOURCE]**
The predictive-policing bias literature is substantial and contested: independent studies found
PredPol-style targeting could direct 150–400% more patrol presence toward Black and Latino
communities relative to white communities in a modeled Indianapolis deployment (MIT Technology
Review, synthesizing published academic studies), and that such targeting tends to mirror
existing departmental arrest patterns rather than correct for them (HRDAG). A counter-study
(Brantingham et al.) found no such bias in a real LAPD comparison — the field is genuinely
unsettled, not one-sided. **[SYNTHESIS]** Every side of this debate converges on one mechanism:
historical crime-report data encodes historical *policing intensity*, not true incidence, so any
model trained on it risks a feedback loop unless training or evaluation explicitly accounts for
over-policing. The target for Veritas: hotspot detection is a real, published-algorithm
capability (KDE/DBSCAN), but its geographic *ground truth* — where hotspots actually are — must
never be presented as more real than the data underneath it, and the Aequitas geographic
subgroup audit and the causal layer's confounder disclosure exist specifically to guard against
this named, documented risk.

**8. Financial intelligence.** **[SOURCE]** FinCEN SAR filing has hard deadlines (30 days from
detection, up to 60 more if no suspect is identified) and dollar thresholds ($5,000 general,
lower for MSBs). **[SOURCE]** ACAMS frames AML investigation scope along two axes — "breadth"
(how many connected relationships to pull in) and "depth" (look-back period). **[SOURCE]**
Structuring (one actor splitting transactions to stay under a threshold) and smurfing
(distributing the same evasion across multiple actors) are the two canonical evasion patterns;
production tools like NICE Actimize's SAM-10 pair deterministic threshold rules with
network-risk analytics to catch both. **[SYNTHESIS]** The breadth × depth framing maps directly
onto graph-traversal parameters — Veritas's role-based traversal-depth cap and directed
`TRANSFERRED_TO` edges already encode this, just without naming it in AML terms. The target: keep
the two-detector pattern (an auditable rule for structuring, a GNN for coordinated multi-account
layering the rule cannot see) — this is not an invented design, it matches how production AML
platforms are actually built.

**9. Cross-case discovery.** **[SOURCE]** FBI ViCAP (1985) exists specifically to prevent
"linkage blindness" — failing to connect disparate crimes across jurisdictions — by centralizing
MO and offender-behavior data, but its own literature names its weakness: reliance on manual
entry, requiring trained expertise to produce reliable links. **[SOURCE]** Standard crime-linkage
practice combines MO similarity with proximity (victim age, location, time) using link analysis
and behavioral matrices; recent academic work explicitly frames this as a machine-learning
problem, including a 2026 industrial study of analysts using AI in high-stakes crime linkage.
**[SYNTHESIS]** Veritas's vector/hybrid similarity search plus the Copilot's "top-5 similar past
cases with outcomes" is a direct, modernized answer to the exact gap ViCAP has had since 1985 —
and the field is actively moving this direction right now, not toward a hypothetical future
capability. The target: this capability's value depends entirely on the underlying case
representation actually carrying case-specific signal — see §1.5 below.

**10. Investigative leads.** **[SOURCE]** Every mature pattern found — crime-linkage lead
generation, AML alert triage (ACAMS: a compliance professional always decides whether to
escalate or dismiss), and Palantir AIP's explicit "agents create proposals, not actions"
architecture — converges on the same shape: **an automated system surfaces a ranked candidate; a
human decides.** No source describes a mature platform where a model triggers action directly.
**[SYNTHESIS]** This directly validates the human-in-the-loop principle already stated in
`CLAUDE.md` §9 as matching, not merely aspiring to, current professional practice. The target:
leads stay capped to what is actionable this week (direct co-accused, not the full connected
component) — an unbounded candidate list is not a lead.

**11. Verification.** **[SOURCE]** US criminal procedure recognizes a graduated evidentiary
ladder — reasonable suspicion, then probable cause, then higher civil/criminal standards — each
requiring progressively more corroboration as the state's intrusion increases; an anonymous tip
alone is insufficient without independent corroboration. **[SYNTHESIS]** This is a real, legally
load-bearing precedent for exactly the shape Veritas's CRAG evaluator already implements
(accept / widen-and-retry / explicit refusal) — more consequential claims need more
corroboration before being asserted. **[INFERENCE]** This is an analogy across domains (legal
evidentiary standards vs. RAG confidence scoring), not a claim that Veritas meets any actual
evidentiary standard, and the North Star should not overstate it as such.

**12. Briefing / reporting.** **[SOURCE]** Prosecutor-facing case-referral reports follow a fixed
structural template (theory of the case, elements of the offense, witness/evidence list,
recommended charges — POST, IRS Internal Revenue Manual 9.5.8) rather than free narrative, and a
poorly documented investigation risks rejection by the prosecutor's office and damage to the
investigator's credibility (Police1). **[SYNTHESIS]** This is directly analogous to Veritas's own
citation-chain format (claim → evidence index → source record) and PDF export. **[INFERENCE]**
No source addresses AI-generated content specifically in a prosecutor-facing context — the
target for Veritas is to be explicit that its exports are investigator-facing decision-support
artifacts, not a substitute for the human-authored, evidentiarily-reviewed report these standards
actually require.

**13. Audit / collaboration.** **[SOURCE]** CJIS Security Policy — the US framework for
law-enforcement data — requires role-based access restricted by need-to-know, mandatory activity
logging with a minimum one-year retention, an unbroken audit trail, and independent audits every
three years. **[SYNTHESIS]** This triad (role-based access + mandatory audit log + periodic
independent verification) is the direct analog of Veritas's `Employee`-row policy enforcement,
tamper-evident hash chain, and the 12-hourly `veritas_audit_verify` Cron job. **[INFERENCE]**
Veritas is not CJIS-regulated (Karnataka Police falls under Indian, not US, law), and no
India-specific equivalent (an NCRB/MHA/CCTNS security standard) was located in this research
pass — the target is to describe this as "structurally analogous to," never as "compliant with."

### 1.2 What conversational AI/RAG must do at each stage

The single organizing constraint, restated from the research above: **AI output supports a
documented human decision; it never is the decision.** Every framework surveyed — NIST AI RMF,
the EU AI Act's Article 5(1)(d) predictive-policing provision (which prohibits *individual*
predictive policing based solely on profiling, with a carve-out precisely where AI supports a
human assessment grounded in objective facts), and Palantir AIP's "agents propose, operators
decide" architecture — draws exactly this line. **[SYNTHESIS]** Veritas's CRAG evaluator does not
just label this distinction in UI copy; it enforces it structurally, refusing to answer rather
than degrading into an unsupported claim. That refusal mechanism is the technical target this
whole layer exists to serve, and it should be read as the single most important property in the
system — more important than fluency, more important than coverage.

**[SOURCE]** RAG literature documents a specific, named failure mode this design must avoid:
"citation-shaped hallucination" — an answer that *looks* grounded (quotes, source markers) while
the underlying claim is unsupported or stitched from irrelevant evidence. This is precisely what
`BUG-006` in the failure log describes (five unrelated cyber-crime citations padding a correct
FIR lookup, at 0.97 confidence) — a documented, named failure class in the general literature,
not a Veritas-specific defect. The target: retrieval must be scoped to what genuinely supports
the claim, confidence must mean support-for-the-claim and never merely lexical/semantic
proximity, and a query that names a specific record must never fall back to unrelated context
once that record is found.

Conversational AI's job at each of the 13 stages, restated as a target:
- **Orient** (stages 1-2): recognize the subject of the conversation and keep it in view across
  turns, without re-deriving it every query.
- **Retrieve with structure, not string-matching** (stages 3-5): multi-hop graph retrieval
  (HippoRAG/PageRank) for relational questions; narrative/lexical retrieval only where case
  narrative genuinely carries signal a structured filter cannot express.
- **Never assert past what the evidence supports** (stages 6, 11): the CRAG accept/widen/refuse
  loop, on every turn, with no path that bypasses it.
- **Surface, never decide** (stages 9-10): rank candidates (similar cases, leads); a human acts.
- **Package for accountability, not just for reading** (stages 12-13): every artifact — a chat
  answer, a Copilot brief, a PDF export — carries its evidence chain forward, because the
  target reader (a prosecutor, a supervisor, an auditor) needs the same traceability the officer
  had.

### 1.3 Evidence / trust / authorization bar

The target bar, stated plainly:

1. **Every claim in a free-text answer traces to a specific record**, and a claim that cannot be
   traced is not made — the system says "not found in the available records" instead. This is
   the single hardest-to-fake trust property, because it constrains what the *language model*
   is allowed to do, not just what the UI displays.
2. **Role and station scope is enforced at the point no later reformatting can undo** — inside
   query construction (a station filter as a `WHERE` clause, a traversal-depth cap before the
   graph walk runs), not only as post-hoc response masking. Masking a name out of already-generated
   prose is not reliable; not generating it in the first place is.
3. **The audit trail is tamper-evident by construction**, verified on a schedule nobody has to
   remember to run, and the verification itself is exercised (not merely present in code).
4. **No protected or proxy attribute is ever a model feature.** Attributes the schema requires
   storing (caste, religion) are stored; nothing reads them for scoring. Gender exists only as a
   fairness-audit subgroup label.
5. **Every prediction is decision support, with explicit uncertainty**, and the UI distinguishes
   "the model suggests" from "the record shows" in every surface that carries a model output —
   not just in the ones where it was convenient to add.

### 1.4 Capability tiers

**Foundational — must get right, no matter what else changes:**
- Identity resolution with inspectable match confidence (the schema has no person; nothing else
  works without this).
- The CRAG accept/widen/refuse loop, and specifically: a batch that clears no relevance floor
  cannot be cited; an exact-record hit suppresses semantic padding; every refusal names *why*.
- Role/station-scoped retrieval enforced at query-construction time.
- The tamper-evident audit chain, genuinely verified on schedule.
- A synthetic dataset whose structured signal (identity, co-offending, financial, temporal,
  geographic) is real and tested — this is infrastructure the rest of the platform stands on,
  not a demo prop (see §1.5).

**High-value differentiators — genuinely distinguish Veritas from a naive "chatbot over a
database":**
- Published, cited retrieval methods (HippoRAG, Think-on-Graph) instead of ad-hoc embedding
  search — genuine multi-hop reasoning without an LLM in the retrieval loop.
- Graph algorithms run as retrieval/ranking signal, not just as a rendering surface — the
  point of difference noted in §1.1's link-analysis discussion.
- The two-detector AML pattern (auditable rule + GNN) matching production financial-crime
  practice.
- Geographic and demographic fairness auditing (Aequitas) with an explicit unmeasured-confounder
  disclosure in the causal layer — addressing the predictive-policing bias literature head-on
  rather than ignoring it.
- Kannada voice/text, fully in-container, so no police record ever reaches a third-party
  translation API.
- Multi-turn conversational memory with correct pronoun/reference resolution.

**Optional future capabilities — real value, correctly deferred for this competition's scope:**
- Real-time CCTNS ingestion (Kafka/Flink) — described, not built, because the dataset scale
  does not justify it yet.
- A production-grade spatio-temporal forecaster beyond Prophet+MinT.
- Federated HR identity (Keycloak), a policy engine beyond a Python module (OPA/Rego) — correct
  to defer at this scale and this team size.

**Claimed but should be rethought:**
- **"BriefFacts narrative diversity supports genuine similarity search."** Confirmed false for
  60% of crime types today (BUG-023, §1.5) — the claim should be scoped to what the narrative
  layer can currently support, not asserted as a general capability.
- **SmartBrowz PDF export.** `CLAUDE.md`'s service table lists it as the deployed PDF path;
  live, `/export/pdf` returns HTML (BUG-018). The document should say "local fallback renderer,
  SmartBrowz not yet reachable," not imply the Catalyst service is serving.
- **"Weights left the image entirely" (v8 changelog).** Live evidence (BUG-017) contradicts
  this — Kannada works in ~2s with `VERITAS_MODELS_FOLDER_ID` unset, meaning weights are still
  served from inside the image via a different path than documented. The claim needs
  reconciling with what is actually deployed before it is repeated again.
- **Risk score confidence as a number an officer would act on (BUG-014).** A saturated 1.00
  score with unvalidated calibration should not be presented at the same visual weight as a
  cited record.

**Unnecessary for this competition:**
- Kubernetes/GitOps multi-environment lifecycle, MLflow model registry, Iceberg/MinIO — correctly
  described-not-built per `CLAUDE.md` Appendix A; nothing about the current dataset scale or team
  size argues for reconsidering this.
- A from-scratch India-specific CJIS-equivalent compliance certification — genuinely out of
  scope for a hackathon submission; the structural analogy (§1.1, stage 13) is the right level
  of ambition, a compliance claim would not be.

### 1.5 Data foundation as part of the North Star

The synthetic dataset is not implementation detail — it is the ground every claimed capability
stands on, and a capability whose underlying data carries no signal cannot be made to work by
fixing the code that reads it. The Data Generation Audit (`docs/DATA_GENERATION_AUDIT.md`)
evaluated this directly across 19 dimensions; the target-state summary:

- **Solid and correctly load-bearing:** identity resolution ground truth, co-offending/crew
  structure (the property that makes Louvain find real communities instead of one giant blob),
  financial ground truth kept genuinely separate from detector output, graph structural
  integrity, and full generation determinism. These are the parts of the generator built to the
  "best solution, not fastest" standard `CLAUDE.md` itself sets, and the audit found real,
  non-obvious statistical bugs fixed with documented reasoning (EM contamination in the
  Fellegi-Sunter `u`-estimate; string-concatenation inflation in the name comparator) — not
  retrofitted narrative.
- **Broken: narrative diversity (BUG-023).** 12 of 20 crime types produce a narrative with zero
  descriptive content beyond the crime-type label; the 8 that do have real modus-operandi text
  have exactly one fixed sentence each. This directly undermines two capabilities named as
  differentiators in §1.4: FIR semantic search and the Investigation Copilot's "similar past
  cases" feature. A generic query correctly returns real, distinct FIRs, but they are
  near-duplicates of each other in every way an embedding model can see — which is precisely
  what `BUG-006`'s citation-padding symptom surfaced as its underlying cause.
- **The audit's own root-cause verdict (reaffirmed here as the North Star position): improve
  narrative generation, not abandon narrative representation.** HippoRAG — the platform's
  primary multi-hop retrieval path per `CLAUDE.md` §5 — never touches `BriefFacts` at all, and
  the `criminal_profile` vector collection already demonstrates the correct pattern by building
  from structured fields (crime-type set, canonical name) rather than narrative text. But FIR
  semantic search and Copilot's similar-cases feature genuinely need free text — the entire
  reason a narrative embedding exists on top of already-available structured fields (crime type,
  district, status) is to catch similarity structured filtering cannot express, such as an
  unusually similar MO across two cases of the same crime type. Deleting the narrative
  representation in favor of pure structured-field matching would not fix the underlying
  degeneracy; it would make "similar cases" openly mean "same crime-type label," formalizing the
  defect rather than repairing it. The target state widens `_MO` to cover all 20 crime types
  (not 8), adds randomized case-specific slot-filling (victim/offender count, time-of-day,
  method variant), and adds a narrative-diversity test — the exact gap that let BUG-023 survive
  to manual discovery rather than CI.

---

## Part 2 — Current Veritas vs. North Star

Walking the same loop, stage by stage, using only what `README.md`, `CLAUDE.md`, the QA matrix,
and the failure log establish as actually verified — not what is merely claimed.

**1. Case initiation.** Target: recognize a case reference the instant it appears and orient the
turn around it. **Current:** `FIR_NUMBER_RE` now matches both the 18-digit and short FIR forms
(v10 fix) and exact-record lookups are live-verified (RAG-01/02). **Gap: none material** — this
stage is close to the target as scoped for Veritas.

**2. Case context.** Target: context assembled live per query, not a stale front-loaded dossier.
**Current:** HippoRAG seeds retrieval from the entities in the question each turn (RAG-19,
PARTIAL — trace shows it firing, not independently re-verified this pass). **Gap:** none
identified beyond general retrieval-quality gaps covered under stage 9/BUG-023.

**3. Entity discovery.** Target: inspectable match confidence per resolved person, auditable per
the government-context bar the research identifies. **Current:** Fellegi-Sunter produces
`vx_accused_identity` with match confidence, F1 0.989 claimed against the generator's own answer
key (independently corroborated this session at 0.998 on a 600-case sample). **Gap:** the F1
claim can currently only be recomputed in-process against a fresh `generate()` call — the answer
key is not persisted the way the AML labels are (`docs/DATA_GENERATION_AUDIT.md` §19), so it
cannot be independently re-verified against what is actually live on Catalyst.

**4. Link analysis.** Target: graph algorithms as ranking signal, not decoration. **Current:**
PageRank/Louvain/betweenness are ported exactly and run on the co-offending projection;
`ML-07` (Louvain) is VERIFIED live, `ML-08` (centrality) PARTIAL. Network view is VERIFIED
rendering live (UI-25). **Gap: minimal** — this stage is close to target.

**5. Timeline construction.** Target: wired to the same evidence as everything else. **Current:**
Copilot timeline exists (`UI-28`, API-level content extensively verified, overlay-click UNKNOWN
this pass). **Gap:** not a defect, an unclosed verification loop — the overlay's interactive
behavior has not been driven end to end.

**6. Evidence handling.** Target: contemporaneous, hashed, unbroken audit trail. **Current:** the
hash chain design matches the SWGDE/NIST pattern closely (§1.1); `DEP-14` confirms
`intact: true` against the real live audit log, not a fixture. **Gap: none material.**

**7. Geographic intelligence.** Target: real algorithms, honestly-scoped ground truth, explicit
bias-mitigation given the documented predictive-policing literature. **Current:** KDE/DBSCAN
verified at the API level (`ML-02`); map rendering verified live but with **no geographic
reference at all** — no district outlines, scale, or labels (`UI-24`), reading as an abstract
scatter plot rather than a geographic tool. The audit separately confirms the underlying
attractor placement is synthetic, not real POI data — honestly disclosed in code, not yet
restated as sharply in `CLAUDE.md`. **Gap:** a real usability defect (no map reference) plus a
documentation-sharpness gap, not a data-integrity problem.

**8. Financial intelligence.** Target: the breadth × depth AML pattern with two complementary
detectors. **Current:** `RAG-07` (financial trail, real data) is VERIFIED live — a genuine
60-transfer trail rendered correctly with 12 citations. But `ML-09` (rule-based structuring) and
`ML-10` (GNN) are both **UNKNOWN live** — neither has been exercised against a real money trail
this session, and `torch` (the GNN's dependency) is deliberately absent from the deployed image
by design. **Gap:** the two-detector differentiator claimed in §1.4 is unverified live for its
actual detection logic, only for the underlying data/graph plumbing that would carry it.

**9. Cross-case discovery.** Target: modernized ViCAP — genuine MO-based similarity, not
label-matching. **Current: this is where the data-foundation gap bites hardest.** `RAG-13`
(SIMILAR_CASES) is VERIFIED as an intent that answers, but `docs/DATA_GENERATION_AUDIT.md` §12-13
establishes that the narrative signal underneath it has collapsed to ~620 shapes across the
whole dataset (20 crime types × 31 districts), with 12/20 crime types carrying zero descriptive
content. The 0.941 similarity score observed between two different Hurt cases in Mandya (Phase 1
audit) is symptomatic, not anomalous. **Gap: the largest substantive gap in this document** — a
capability positioned as a differentiator (§1.4) is currently closer to "same crime type, same
district" than to genuine MO-based linkage.

**10. Investigative leads.** Target: capped, actionable, human-decided. **Current:** Copilot
leads are direct-co-accused-only by design (matches the human-in-the-loop pattern §1.1 confirms
is industry-standard); `Show me the co-offender network` and `Show me the money trail` without a
named subject correctly refuse rather than inventing a subject (CRAG working as intended,
verified live in v11). **Gap: none material** — this stage matches the target closely.

**11. Verification.** Target: the CRAG accept/widen/refuse loop enforced on every turn, with no
bypass. **Current:** `BUG-006` (unsupporting citations at 0.97 confidence) was found and fixed;
`BUG-020` (a regression in the same session, where the relevance floor deleted an authoritative
refusal) was found and fixed within the same pass. Both are live-verified. **Gap:** the fact that
BUG-020 was a regression *introduced by* BUG-006's own fix, caught only because the same audit
pass re-tested immediately, is worth naming honestly: this loop is delicate, and its correctness
depends on discipline (re-testing every related path after any change to it) more than on any
single fix being permanent.

**12. Briefing / reporting.** Target: structured, prosecutor-adjacent export discipline. Current:
PDF export is gated correctly in the UI (`UI-08`, disabled with zero turns) but returns HTML, not
a PDF — SmartBrowz, listed in `CLAUDE.md`'s service table as the deployed path, is not actually
being used (`BUG-018`). **Gap:** a claimed Catalyst-service capability is currently a degraded
local fallback; not a correctness defect (the console does not lie about the file type), but a
documentation-vs-reality gap in exactly the place §1.4 flags it.

**13. Audit / collaboration.** Target: role-based access, mandatory logging, periodic independent
verification — the CJIS triad. **Current:** all six roles resolve correctly with live-confirmed
station/masking scoping; the audit-verify Cron job is live-verified (`{"intact":true}` against
the real chain). Two P0 authorization defects were found and fixed in this dimension specifically
(`BUG-002` stale token in unverified mode, `BUG-003` Copilot bypassing the station rule `/fir`
enforces) — both now live-verified fixed. **Gap:** none currently open at P0/P1 in this
dimension; the fact that two P0s existed here at all argues for continued scrutiny of this
specific surface before any further capability is added to it.

**AI interface / responsible AI (cross-cutting).** Target: AI output supports human decisions,
never replaces them, with an explicit refusal path and no protected-attribute leakage.
**Current:** the leakage rules (`CLAUDE.md` §6, AML labels never in `vx_txn`, no CasteID/
ReligionID/GenderID in model features) were independently re-verified in code by this session's
data-generation audit, not merely asserted. The LLM itself (QuickML/GLM-4.7-Flash) is **not
currently reachable live** — `BUG-021` (a nonexistent SDK method call) was found and fixed, but
`BUG-022` (the gateway rejects every request shape tried, `PATTERN_NOT_MATCHED`) remains open,
root-caused as far as this team can go without vendor documentation. Every answer in production
right now is the deterministic extractive path. **Gap:** per §1.2's own framing, this is a
fluency gap, not a truthfulness gap — every live answer is still grounded and cited — but a
platform whose stated differentiator includes an LLM-fluent synthesis layer is currently running
entirely on its fallback path.

**Data foundation (cross-cutting, per §1.5).** Target: every structured dimension real and
tested, narrative text carrying case-specific signal proportional to its role. **Current:**
schema conformity, referential integrity, recurring identities, identity ambiguity, co-offending
structure, financial ground truth, graph ground truth, and reproducibility are all independently
confirmed solid in code (`docs/DATA_GENERATION_AUDIT.md`). **Gap:** narrative diversity is
broken exactly as characterized in §1.5, and no test in the repository would catch a regression
of it — the diversity check does not exist yet, only the narrative-diversity finding does.

---

## Part 3 — Prioritized gap ranking

Each item below is ranked by what it costs an investigating officer and what it costs the
Datathon judging objective if left unaddressed — not by implementation difficulty.

### P0 — Foundational / correctness

**P0-1. `BUG-023` — narrative diversity collapse undermines a claimed differentiator.**
*Why it matters to an officer:* "similar past cases" is one of the seven headline capabilities
`README.md` demonstrates to a judge; today it is materially closer to "same crime type, same
district" than to genuine modus-operandi linkage, which is precisely the gap FBI ViCAP has had
since 1985 and precisely what Veritas claims to modernize (§1.1, stage 9). An officer trusting
this feature would be trusting a signal that, for 60% of crime types, does not exist.
*Why it matters to judging:* this is the finding most likely to surface under any scrutiny of the
"similar cases" or citation-quality claims, and it is the one dimension the data-generation audit
rates unambiguously broken rather than defensibly-approximate. It is also the cheapest P0 to
address — the audit's own verdict is weighted-template slot-filling, no LLM required, following a
pattern the generator already uses elsewhere.

**P0-2. No narrative-diversity test exists.** *Why it matters:* this is why BUG-023 was only
caught by manually sampling 60 records per crime type rather than by CI — the exact same defect
could be reintroduced silently after any future fix. *Judging relevance:* a system whose own
documentation claims "the RBAC rules... now run on every commit" (`CLAUDE.md` §3) should not have
a whole capability class with zero regression coverage.

**P0-3. `BUG-022` — the LLM fluency layer is not reachable live.** *Why it matters to an
officer:* every current answer is the deterministic extractive path, which is grounded and
correct but not the fluent synthesis the architecture is designed to provide. *Judging
relevance:* `README.md` and `CLAUDE.md` both describe QuickML/GLM-4.7-Flash as the language
layer; a judge testing the live system will see extractive-only answers, and the gap between
documented architecture and live behavior is exactly the kind of discrepancy this audit's
standard (verify live, not assumed) exists to catch before a panel does.

### P1 — North Star must-have

**P1-1. Map has no geographic reference (`UI-24`).** Hotspot detection is real (KDE/DBSCAN,
published algorithms, live-verified), but the rendering makes it illegible as a geographic tool
— no district outlines, scale, or labels. This directly undercuts the "geographic intelligence"
stage of the North Star loop (§1.1, stage 7), where the whole point is that an officer can
recognize *where* a hotspot is, not just that one exists as an abstract point cluster.

**P1-2. Financial detectors unverified live (`ML-09`/`ML-10`).** The two-detector AML pattern is
a genuine, sourced differentiator (§1.4) — matching how production platforms like NICE Actimize
are actually built — but neither detector has been exercised against a real money trail this
session. An unverified differentiator is a claim, not yet a capability.

**P1-3. Identity answer key not persisted (§1.5, §19 of the data audit).** The claimed F1 0.989
cannot currently be recomputed against what is actually deployed on Catalyst, only against a
fresh in-process generation run. For a platform whose central claim rests on this one number,
that is a real auditability gap against the same standard the AML labels already meet.

**P1-4. `BUG-011` — similarity is displayed to officers as evidential confidence.** The vector
agent's raw hybrid score flows unlabeled into the same "confidence" field used for genuine
evidential support, then renders as a strong/fair/weak band in the UI. This is a category error
with real consequences for an officer's trust calibration — cosine similarity to a query string
and "how well this record supports this claim" are different quantities, and the UI currently
does not distinguish them.

**P1-5. `BUG-008` — "how many" questions never return a count.** A basic counting question
returns narrative excerpts and no number. This is a foundational query pattern for an
investigating officer ("how many theft cases in Mandya this month") and its absence is more
noticeable in a live demo than almost any other gap in this document, because it is the kind of
question anyone would ask first.

### P2 — High-value differentiator (real, but not blocking)

**P2-1. `BUG-018` — PDF export is HTML, not a PDF.** SmartBrowz is claimed as the export path;
the actual output is the degraded local fallback. Worth fixing before the briefing/reporting
stage (§1.1, stage 12) can be demonstrated as designed, but the console is honest about the file
type and no officer is misled about the content's correctness — only its format.

**P2-2. `BUG-014` — saturated risk score with unvalidated calibration.** A 1.00 score presented
at the same visual weight as a cited record risks being read as more authoritative than it is.
Not urgent because the wording already correctly says "the model suggests," but worth resolving
before this capability is leaned on in a demo.

**P2-3. `BUG-017` — documentation vs. deployed reality on model weight location.** The changelog
claims weights left the image entirely; live evidence contradicts this. Low officer-facing
impact, but a documentation-integrity issue that should be resolved (verify which is true) before
it compounds into a larger discrepancy.

**P2-4. No seasonal signal in generated incident timing.** Prophet's seasonality terms are
fitting noise on this dataset (`docs/DATA_GENERATION_AUDIT.md` §16) — not a defect, but a
demo-risk: any narrative leaning on "the forecast captures a weekly pattern" would be describing
something the dataset does not actually contain.

### P3 — Defer / cut

**P3-1. `BUG-016` — Kannada latency (13.4s vs 0.5s English).** Correctness is fully verified; this
is a performance characteristic, not a trust or capability gap. Worth knowing before a live demo
paces itself around it, not worth fixing under time pressure.

**P3-2. `BUG-019` — "fir" substring-matches inside "firs".** Confirmed harmless today (the
downstream branch is a no-op without a real FIR number match); would only matter if that branch
gained independent behavior later.

**P3-3. `BUG-005`'s live WebSocket verification gap.** The fix is correct in-process (ASGI-level
test passes); live verification is blocked by an apparent AppSail gateway limitation on
WebSocket upgrades for custom-runtime apps, which is a platform question, not a code defect to
chase further within this project's control.

**P3-4. AML detector specificity against organic (non-injected) transactions is untested.**
Honestly disclosed in the data-generation audit as a real limitation ("the dataset has no such
case to test against") — worth knowing if a judge asks about false-positive risk, not worth
building a synthetic negative-example corpus for under competition time constraints.

**P3-5. CJIS-equivalent formal compliance claim.** Per §1.4, a from-scratch India-specific
regulatory compliance certification is out of scope for this competition; the structural analogy
already stated in §1.1 (stage 13) is the right level of ambition for this document.

---

## Summary

The North Star for Veritas is not a larger feature set — it is the discipline already visible in
the system's best-built parts (identity resolution, the CRAG evaluator, the audit chain, the
co-offending graph) applied consistently to the parts that currently fall short of it: a
narrative layer that actually carries case-specific signal, a map that reads as a geographic
tool, financial detectors verified against real data rather than assumed working, and
documentation that says what is deployed rather than what was once true. Every P0 and most P1
items in Part 3 are gaps between what the system already correctly claims to be — grounded,
cited, human-in-the-loop, structurally aligned with real investigative and AML practice — and
what a judge or an officer would actually observe testing it today. Closing them is a matter of
finishing the standard already set, not inventing a new one.
