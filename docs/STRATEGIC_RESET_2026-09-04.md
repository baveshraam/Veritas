# Veritas — Strategic Reset (2026-09-04/05)

**Purpose.** A ground-up product/investigative/technical/domain audit, done on request, to
answer one question before more features get built: what must Veritas become to be the
strongest answer to the KSP/SCRB challenge and something a real police professional would
genuinely find useful — not what's fastest to add to an already-long feature list.

**Method.** Code read directly, not trusted from `CLAUDE.md`'s own claims. Tags:
**[VERIFIED]** confirmed against live code/deploy this pass; **[SOURCE]** external research,
cited; **[JUDGMENT]** this document's own synthesis, not independently checkable.

This is a **point-in-time analysis**, not a steering document kept current line-by-line the way
`CLAUDE.md` is. `docs/CAPABILITY_TARGET_AND_GAPS.md` and `docs/INDUSTRY_GAP_ANALYSIS.md` are
earlier (2026-08-27) gap-analysis passes and remain independently useful; this document
supersedes their conclusions about *current state* where they overlap. Part 8 records what was
actually built against this document's own roadmap in the same session — re-verify against
`CLAUDE.md`'s changelog before trusting it further.

---

## Part 1 — What Veritas genuinely does today

**The load-bearing part is real. [VERIFIED]** `fellegi_sunter.py` correctly implements the
1969 method: multi-level field comparison, EM estimation of m/u with the prior's
non-identifiability handled correctly (fixing `p` because blocked pairs aren't a random
sample), and a documented fixed bug in the u-estimate — random pairs were secretly ~1% true
matches, inflating the false-agreement rate 50x and silently killing recall, until
co-accused-on-the-same-FIR pairs were used as guaranteed non-matches instead. Defensible
unconditionally to a data-science judge — this is not `import recordlinkage`.

**The trust discipline has been tested by breaking it. [VERIFIED]** The CRAG accept/widen/
refuse loop, the provenance chain, and the contradiction checker have been through ~15 rounds
of "found live, fixed, regression-tested" per `CLAUDE.md`'s changelog (evidence padding a
correct answer, a refusal shipping the evidence it just rejected, a citation-count heuristic
painting a successful board pin as a failure). A boundary that keeps getting attacked and
keeps getting repaired is a stronger signal than a clean first pass would be.

**The six v24/25 conversational operations are the most under-sold part of the product.
[VERIFIED]** `CROSS_STATION_LINKAGE` correctly reports a genuine cross-jurisdiction link even
when RBAC forbids naming the other case ("the link is real, the case cannot be named here —
contact that station directly") — a real answer to a real policy tension. `INTERROGATION_PREP`
was rebuilt in v25 because the first version briefed the officer on their own paperwork gaps
instead of questions a suspect could answer. These six operations sat at entries #24-25 of a
25-entry changelog dominated by Catalyst infrastructure war stories — backwards ordering for
judging purposes.

**A data-generation ceiling verified independently. [VERIFIED]** `_MO_VARIANTS` post the
"BUG-023 fixed" claim: real, and an improvement (all 20 crime types now have narrative content
vs. 12 with none), but still only 3 hand-written sentences per crime type, chosen per-offender
by a "signature" weighting plus slot-filled locality/time/section/status — combinatorially
richer than one template, still a closed template space.

**[SOURCE]** This matters because the academic literature says the diagnostic signal is
*distinctiveness*: "for it to be possible to link crimes by the same offender, criminals must
show consistent but distinctive behavior" (Burrell & Bull's CCA research; Davies 2019 review).
"Pickpocketing in a crowded market" is common, not distinctive.

**[JUDGMENT]** Honest characterization: "similar cases"/"case-similarity watch" currently
answer "same crime type + district + section, phrased as a sentence" — real and useful, but
not yet what "modus operandi across time and station boundaries" and a ViCAP-modernization
pitch actually claim. A sharp judge asking for two surface-different cases sharing an
idiosyncratic detail will find the well runs dry after three sentences. Fixable (Blueprint #4)
via generation-time LLM authoring now that QuickML is live — **deliberately deferred** pending
a look at real Catalyst billing history (Part 8); it's the one blueprint item touching
meaningful LLM call volume.

**A domain-currency gap found and fixed this pass. [VERIFIED, fixed — Part 8]**
`data/generator/refdata.py` cited only "Indian Penal Code, 1860" for every case despite
`manifest.py` claiming an "IPC/BNS mix" that had never been implemented. **[SOURCE]** BNS 2023
replaced the IPC for offences on or after 2024-07-01; most generated cases (spanning ~3 years
back from a 2026-07-01 anchor) fall after the transition and should cite BNS. A real KSP
officer would notice a citation to a defunct code in seconds.

**The rest holds up.** Everything spot-checked in `docs/QA_FUNCTIONALITY_MATRIX.md` was
confirmed, and `CLAUDE.md`'s v17-v25 changelog closes most of what that document and
`CAPABILITY_TARGET_AND_GAPS.md` flagged open (QuickML live with cost-routing, the case board
closing the cross-session-memory gap, explainability shipped, the PageRank display bug fixed).
Still honestly open: real PDF export (blocked on a Catalyst identity requirement, not code),
the GNN AML detector unverified against any true positive live, Aequitas still a standalone
script.

---

## Part 2 — Research: what exists, what's missing, what's contested

**[SOURCE]** CCTNS is fully deployed (~17,700+ stations) — the constraint is analytics
adoption, not data existence ("not all states use all modules," rural infrastructure/training
gaps). Validates Veritas's framing, but precisely: it solves a data-*synthesis* problem, not a
data-*access* one.

**[SOURCE]** ICJS is explicitly working toward "search and visual analytics" and "effective
AI/ML use," with mandatory digital recording under BNS/BNSS/BSS targeted from January 2027.
Veritas sits ahead of, not adjacent to, this trajectory — worth stating explicitly rather than
implying disconnection from where Indian criminal-justice IT is headed.

**[SOURCE]** Linkage blindness (Egger, 1984) — near-total lack of cross-jurisdiction
information sharing — is the canonical failure ViCAP exists to fix, with ViCAP itself naming
manual-entry reliance as its own weakness. **[JUDGMENT]** `CROSS_STATION_LINKAGE` is a genuine
but narrow structural answer (pre-Part-8: fires only when the same person is already named on
both cases; can't find a series with no common suspect) — exactly the gap Part 8 Phase 1
addresses.

**[SOURCE]** India's deployed AI-policing tools (Delhi's FRS/CMAPS, UP's Trinetra, Punjab's
PAIS) have a documented failure mode: arrests made on an AI match with no corroborating
evidence, no privacy assessment, no governing regulatory framework (Wire/Pulitzer Center; Vidhi
Legal Policy; ORF). **[JUDGMENT]** The sharpest, most India-specific hook for the
responsible-AI story — sharper than the generic COMPAS/Aequitas reference. Veritas's
CRAG/refuse/provenance stack is, structurally, "the tool built to be unable to do what
Trinetra-style deployments have already been criticized for." Say this explicitly in the
pitch.

**[SOURCE]** A real competing submission (KAVACH 360, also on Catalyst) was pulled live for
comparison: hotspot mapping, forecast-with-confidence, co-accused network mapping, an
"operational risk index," NL search, disclaiming "does not infer guilt." **[JUDGMENT]**
Confirms map+graph+forecast+risk-score+chatbot is the default convergent solution — table
stakes, not a differentiator, near-zero marginal judging value from further polishing it.
Veritas already does this checklist better (real KDE/DBSCAN vs. a claimed score, GDS-equivalent
algorithms as a ranking signal, not decoration) — but "does it slightly better" isn't a winning
story against "does something else entirely."

**[SOURCE]** Predictive-policing bias research remains genuinely contested (already captured
correctly in the project's docs). **[JUDGMENT]** The unresolved point entering this session:
Veritas built the correct safeguard (Aequitas, geographic-subgroup audit, confounder
disclosure) but never wired it into the running product — a capability that exists only as a
script nobody runs is a claim, not a verifiable mitigation. **Still open** — Part 9 Item 1.

---

## Part 3 — Four-way gap analysis, beneath the labels

For each capability: **A** (does the challenge ask for it), **B** (what an investigator needs),
**C** (what mature systems/research say "good" looks like), **D** (what Veritas could do
*before this session*, verified).

**Crime pattern discovery.** Test: starting from one case, does it surface a
previously-unknown related case nobody queried for, across station/time, and explain why? **D:**
reactive only — `SIMILAR_CASES`/`CASE_SIMILARITY_WATCH` answer when asked; the Isolation Forest
alert feed is genuinely unprompted but operates on district-level counts, not case-level
content. The "it noticed and told you first" half — ViCAP's actual missing piece since 1985 —
didn't exist. **The single largest gap** → Part 8 Phase 1.

**Criminal network analysis.** Test: genuine multi-hop graph, key-player ID via real
centrality. **D:** genuinely strong — PageRank/Louvain/betweenness used as ranking signal, not
decoration (most commercial tools treat the graph as a visualization surface only); correctly
refuses to invent a "gang" label. **Gap:** static per-query snapshot, no temporal/edge-
annotation view — real but secondary (Blueprint #5, not done this session).

**Behavioral profiling.** Test: an evidence-backed picture of recurring behavior, not
demographics. **D:** implicit, not first-class — the generator's `_signature_choice` gives
offenders a genuinely recurring habitual detail, but nothing read it as "here is this person's
pattern." Named explicitly by the challenge → became Part 8 Phase 2.

**Proactive crime prevention intelligence.** Test: an emerging pattern, explained, with a
location/time window and a decidable next action. **D:** half-built — the alert feed states
observed vs. expected per district with real factors, honest and explainable. **Gap:** never
fuses into a decision — hotspot geography, trend direction, and recurring signature stay three
separate visualizations, and Aequitas (the mitigation for exactly the bias question this
capability invites) isn't live. **Still open** (Blueprint #3/Part 9 Item 2).

**Hotspot / geospatial.** **D:** solid — real KDE/DBSCAN, real basemap, legend, scale.
Checklist-parity-plus-execution-quality. Necessary, not differentiating (KAVACH 360 claims the
same feature).

**Cross-case / cross-station linkage.** **D (before):** real but narrow (person-anchored
only). Same gap as "crime pattern discovery" above — addressed by Part 8 Phase 1.

**Investigative lead generation / decision support.** **D:** genuinely strong and
under-marketed — capped-to-actionable leads, human-decides throughout, and the six v24/25
operations are real workflow tools requiring understanding of investigative process, not just
data, that no competing "map+graph+chat" submission is likely to have built.

---

## Part 4 — The product thesis

Not "chatbot + graph + prediction + hotspot." Stated as one claim:

> Veritas is the reasoning and memory layer that makes records the ER (and CCTNS/ICJS after it)
> can only store into records that can be connected — reconstructing the identities,
> associations, and behavioral patterns those systems have no mechanism to infer, surfacing what
> nobody explicitly searched for, and refusing to state anything the records don't support.

Why a spreadsheet / CCTNS-search / generic-LLM doesn't already do this:
- **CCTNS/ICJS store; they don't connect.** ICJS's own stated ambition is what Veritas already
  does, years before that rollout completes, on today's siloed data.
- **A human analyst can't run Fellegi-Sunter in their head** across ten thousand FIRs to notice
  "Ramesh Gowda" and "Ramesha Gouda" are the same man.
- **A generic LLM pointed at an export will hallucinate a case number with total confidence,**
  can't enforce station-scoped access inside its own reasoning, and has no tamper-evident
  trail — the same failure class as the real West Midlands Police Copilot incident (a
  fabricated match used to justify a real banning order — `CLAUDE.md`'s v24 entry cites this as
  the reason the case-diary export tags derived claims). Veritas's CRAG/provenance/audit stack
  exists to be *structurally incapable* of that failure, not to promise it away in a system
  prompt.

**The loop:** a case/question enters → Veritas orients on the actual entity → retrieves across
identity, graph, geography, and financial layers simultaneously → checks for what wasn't asked
(a cross-station match, a filing gap, a recurring signature) → answers with explicit evidence
and uncertainty → the officer acts, corrects, or challenges it → that becomes permanent case
memory for the next officer, session, or query.

**What stays human, always:** every lead, advisory, and flagged pattern is a *proposal*;
nothing triggers an action — the one point NIST AI RMF, the EU AI Act's predictive-policing
carve-out, and Palantir AIP's "propose not decide" architecture all converge on, and the
opposite of India's own deployed FRS tools' documented failure mode.

---

## Part 5 — Ranking every capability

### Existing

| Capability | Rank | Why |
|---|---|---|
| Fellegi-Sunter identity resolution | **CRITICAL** | Nothing downstream works without it; the ER has no person |
| CRAG refuse-or-widen + provenance/WHY chain | **CRITICAL** | Separates this from every LLM-wrapper submission |
| RBAC at query-construction + audit hash chain | **CRITICAL** | Table stakes for real police records; most hackathon teams do this worse |
| Investigation Board (cross-session memory) | **CRITICAL** | Closes the gap earlier research called the largest one vs. i2/Gotham |
| Six v24/25 conversational ops | **DIFFERENTIATING** | Real investigative-process tools unlikely in a checklist submission |
| Co-offending graph w/ GDS-equivalent algorithms as ranking signal | **DIFFERENTIATING** | Exceeds how most commercial tools actually use their own graphs |
| In-container Kannada ASR/MT | **DIFFERENTIATING** | Genuinely hard and real; most teams fake or skip this |
| Hybrid deterministic-first/LLM-fallback | **DIFFERENTIATING**, if pitched honestly | A defensible trust architecture — must be explained as a design choice, not glossed as "we have an LLM" |
| Hotspot KDE/DBSCAN + real basemap | SUPPORTING | Necessary hygiene, checklist-parity |
| Forecast (Prophet+MinT), risk/recidivism (XGBoost/LightGBM) | SUPPORTING | Solid, not a differentiator — every competitor claims this |
| Aequitas fairness audit (pre-Part-8) | SUPPORTING, capped | Right idea, but a script nobody runs isn't a verifiable mitigation |
| Catalyst platform-engineering hardening | Necessary for eligibility, invisible in a demo | Further investment has ~zero marginal judging return |
| DoWhy causal layer | NOISE | Honest, essentially unused by any realistic officer workflow |
| GNN AML detector | NOISE, currently | Unverified against any real positive case |

### Missing (status before Part 8's execution)

| Capability | Rank | Why |
|---|---|---|
| Unprompted cross-case/cross-station series discovery | **CRITICAL** | What "crime pattern discovery" and modernizing ViCAP actually mean |
| First-class evidence-backed behavioral profile | **CRITICAL** | Named explicitly by the challenge; signal already in the data |
| BNS section currency | **CRITICAL, cheap** | A real police panel catches this in seconds |
| Aequitas wired into the live refresh cycle | **CRITICAL** | Proactive prevention invites the bias question directly; the mitigation must be verifiable |
| Genuinely distinctive (LLM-authored) MO narrative | DIFFERENTIATING | Makes existing similarity/linkage features true to their claim |
| Fused proactive-prevention advisory | DIFFERENTIATING | Turns three mentally-combined charts into one decision-support statement |
| Minimal graph/edge annotation | SUPPORTING | Closes the last i2/Gotham gap; smaller than it sounds given the board exists |
| Full i2-style manual link-chart canvas | NOISE | The board already delivers the effect an officer wants |
| Full OSINT/Maltego-style external fusion | NOISE | No external sources exist in this dataset/scope |
| Kafka/Flink/Iceberg real-time ingestion | NOISE (now) | Correctly deferred; dataset scale doesn't justify it |

---

## Part 6 — The winning blueprint (see Part 8 for what was actually built)

**1. Unprompted series discovery — "the pattern nobody searched for."** Problem: five shop
burglaries across three districts, one IO each, unconnected — linkage blindness, ViCAP's own
named weakness since 1985. Approach: a standing batch job scans open, unresolved-suspect cases
for clusters sharing distinctive MO + geo/temporal proximity + no common IO, writing ranked
candidates to an analyst queue — e.g. five "House Burglary" FIRs across Kolar, Chikkaballapur,
and Bengaluru Rural, all rear-entry, all 2-4 AM, ~9-12 days apart, no shared suspect. Officer
sees the shared factors, asks why, pins it, notifies other stations via the existing
cross-station RBAC pattern. Built from existing graph/geo/temporal data, the WHY-chain, and the
alert SSE transport; states structural similarity, never confirmed common offender, never
auto-merges. Differentiated because no competing submission is likely to build the *push*
version. **Status: Built, Part 8 Phase 1.**

**2. Evidence-backed behavioral profile.** Problem: "behavioral profiling" is asked for
explicitly; before this pass it was a risk number. Approach: for a resolved person, assemble a
citable narrative (never demographic) — time-of-day pattern, method/weapon recurrence,
escalation, geographic range, association stability — each line tagged DERIVED and traced to
its cases. E.g. "Across 6 cases (2023-2026), incidents cluster 11PM-2AM (5 of 6); method has
shifted from petty theft to burglary over 18 months; operates within 12km of Malleshwaram; the
same 2 associates appear on 4 of 6 cases." Built entirely from existing data — no new model.
States small-N (<~3 cases) as a history, not a pattern. **Status: Built, Part 8 Phase 2.**

**3. Fused proactive-prevention advisory.** Problem: hotspot map, trend chart, and signature
data are three things an officer combines mentally; no single bounded recommendation exists,
and any "predictive" claim invites the bias question. Approach: one statement — "elevated
likelihood of [pattern] in [place] over [window], based on [n] points" — with the live Aequitas
geographic-subgroup result and the causal layer's confounder disclosure shown alongside, never
folded into the number. Advisory only, never a dispatch trigger. **Status: Not built.**

**4. Genuinely distinctive MO narrative (data-generation fix).** Problem: current MO text is 3
templates per crime type — common, not distinctive, so vector similarity is really a rephrased
WHERE clause. Approach: use the now-live QuickML LLM at generation time to author per-case
idiosyncratic detail seeded by real structured facts. **Status: Deliberately held** — the one
item touching meaningful QuickML volume, gated on a few real days of Catalyst billing data.

**5. Minimal graph/edge annotation.** Problem: the graph is read-only per query; an analyst's
own judgment has nowhere to live. Approach: extend the existing case-board pin mechanism to a
graph edge or node. **Status: Not built.**

**6. BNS section currency.** **Status: Built, Part 8 Phase 0.**

---

## Part 7 — The hero scenario (for the eventual demo)

A routine, deliberately unglamorous FIR: a shop burglary in Chikkaballapur — shutter lock
broken, cash box gone, no witness, no suspect.

1. *"What do we know about this case?"* → case Overview: facts, no leads yet, structural
   completeness check passes quietly.
2. *"Anything similar we should know about?"* → the series-discovery job already flagged it:
   4 other shop burglaries across 3 districts over 5 weeks, same rear-entry method, same 2-4AM
   window, ~10 days apart, no shared IO across any two.
3. *"Why do you think these are connected?"* → WHY chain fires the actual shared detail (entry
   method, time window — not "both are burglaries"), explicit confidence, and an explicit "what
   this does NOT establish: no shared suspect yet, no forensic link — behavioral pattern only."
4. *"Who's likely involved?"* → honest answer: none of the five cases has a named accused — "a
   pattern without a suspect, exactly what series detection exists to catch before an officer
   would think to cross-reference three other districts by hand."
5. *"Should we expect another one, and where?"* → the fused advisory (Blueprint #3, not yet
   built): a bounded next-window/location projection, moderate confidence stated plainly.
6. *"Poke holes in this."* (already built, v25) → Veritas names its own weak points: only 5
   data points, geographic progression assumed on straight-line distance not road network, two
   of five cases still under investigation so MO attribution isn't final.
7. Officer pins the pattern to a shared thread — visible to the other two stations' officers
   the next time either opens their own case.

**The one-sentence answer** to "why is this genuinely useful, not just another AI demo": the
moment Veritas tells an officer something true about their own open case that they didn't ask
for and couldn't have found by looking — stated with the actual FIR numbers, the actual shared
detail, and an explicit admission of what it doesn't yet prove.

---

## Part 8 — What was actually executed this session (2026-09-04/05)

Roadmap phasing: Phase 0 (BNS fix) → Phase 1 (series discovery) → Phase 2 (behavioral profile)
→ Phase 3 (Aequitas wiring + graph annotation) → Phase 4 (LLM-authored MO narrative, cost-gated)
→ Phase 5 (pitch/demo docs). **Phases 0-2 were built and deployed; Phases 3-5 were not
started.** Full detail — the QuickML spend-cap fix, a caught `docs/WORK_LOG.md` near-miss, the
`BEHAVIORAL_PROFILE` routing dead-code bug found and fixed, live-verification results — is in
`CLAUDE.md`'s v26 changelog entry and `docs/WORK_LOG.md`'s 2026-09-04 entry; not duplicated
here. Test suite reached 868 passed (from 830), 2 pre-existing environment-gated skips.

**Not done this session:** Phase 3 (Aequitas wiring, graph edge annotation), Phase 4
(LLM-authored MO narrative — gated on billing data), Phase 5 (pitch rewrite, demo recording).
Blueprint #3 (fused advisory) was scoped, not built. `CAPABILITY_TARGET_AND_GAPS.md` and
`INDUSTRY_GAP_ANALYSIS.md` were not rewritten against this pass's findings — they remain their
own dated snapshots; this document is the current source of truth for 2026-09-04/05.

---

## Part 9 — Plan of action for the remaining work (as of 2026-09-05)

**State verified directly at the start of this plan**: no background process, deploy, or
subagent running; `git status` clean; live `/health` responding and idle. The
`BEHAVIORAL_PROFILE` routing fix has since been corrected for real, tested, deployed, and
confirmed live (`CLAUDE.md` v26). Five items remain from Part 6/8's "not done" list.

**Item 1 — Aequitas wired into the live refresh cycle.** Tier: CRITICAL. Blocker: none.
`packages/ml_models/fairness_run_audit.py` is a real, working script — runs
`run_fairness_audit()` against `score_risk` and `predict_recidivism`, returns a
`disparate_impact_flagged` report — but nothing calls it except a person running it by hand.
Plan: add it as its own isolated step inside `/jobs/refresh`, matching the per-step-isolation
pattern the four existing steps already use (so one failing step can never silently cancel the
others, per Part 8's own `series_scan` lesson); cache the report the way `series_detection`'s
results are cached for `/alerts`; surface it as a real, checkable status line in `/health` and
the console's System panel. Do this first: zero external blockers, and Item 2 directly invites
the over-policing-bias question this closes. **Effort: ~1 day.**

**Item 2 — Fused proactive-prevention advisory.** Tier: DIFFERENTIATING. Blocker: none
(benefits from Item 1 first, not required). Hotspot detection, trend forecasting, and the
recurring-method signal (`series_detection`, Phase 1) all exist but as three separate outputs
an officer combines mentally. Plan: one new synthesis function reading all three for a given
district/window, producing "elevated likelihood of [pattern] in [place] over [window], based on
[n] points," with the Aequitas geographic-subgroup result (once Item 1 lands) and the causal
layer's confounder disclosure shown alongside, not folded into the number. Advisory only, never
a dispatch trigger. **Effort: ~1-2 days.**

**Item 3 — Minimal graph/edge annotation.** Tier: SUPPORTING. Blocker: none. `board.py`'s
`create_item()` already takes a generic `RefType`/`RefID` pair — built to be extensible, never
extended past case/person/evidence. Plan: add a `RefType` for a graph edge, one click target on
`NetworkView.tsx` opening the existing pin-a-note flow for the selected edge. Almost entirely UI
wiring plus one new `RefType` case. **Effort: ~1 day.**

**Item 4 — AI-authored distinctive MO narrative.** Tier: DIFFERENTIATING. Blocker: real —
`_MO_VARIANTS` gives each crime type 3 hand-written templates, chosen per-offender by signature
weighting — richer than one template, still a closed set (why cross-case similarity currently
reads as "same crime type + district + section," Part 1's CCA-theory gap). Re-confirmed this
session: live `/health` shows QuickML at **0 of 300** allowed calls used since going live — no
real billing history exists yet, because deterministic paths have handled every query so far.
Two options: **(a)** run a small capped test batch (50-100 cases) through QuickML, watch the
actual cost in Catalyst's Billing panel, then decide on the full ~10,000-case run; **(b)** skip
it — nothing currently visible in the UI depends on it; it would sharpen series-discovery
matching quality, not unlock a new screen. Recommendation unchanged: given the explicit "don't
send me a huge bill" instruction, default to (b) unless a specific date is set aside to check
(a) first. **Effort if pursued: ~1-2 days**, mostly validating generated narrative never
contradicts the case's own structured facts before being written — the same discipline
`narrative_backfill.py` already applies for the BNS fix.

**Item 5 — Pitch, demo, and documentation rewrite.** Not a capability, but required for
submission. Blocker: none — best done last, once the feature set is final. Plan: rewrite the
README/submission to lead with Series Discovery and the six conversational operations
(currently buried at changelog entries #24-25), not the Catalyst engineering story — real work,
wrong headline for a domain judge. Record the actual demo against the Part 7 hero scenario.
Prepare honest answers for the two hardest likely questions: "is this really conversational AI
or a search UI with an LLM bolted on" (the hybrid deterministic-first/LLM-fallback answer from
Part 5, told as a design choice) and the over-policing-bias question (Item 1's live Aequitas
result, once built).

**Suggested build order:** Item 1 (no blockers, closes a real exposure) → Item 2 (benefits from
Item 1) → Item 3 (small, independent, slots in anywhere) → Item 4 (hold pending the billing
decision) → Item 5 (last, once the feature set is final). Items 1-3 have no dependency on each
other beyond ordering; per Part 8's "batch deploys, don't deploy per-commit" lesson, build all
three then deploy and live-verify once as a batch, the way Phases 0-2 already did.
