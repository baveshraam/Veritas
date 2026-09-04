# Veritas — Strategic Reset (2026-09-04/05)

**Purpose.** A ground-up product/investigative/technical/domain audit, done on request, to
answer one question before any more features get built: *what must Veritas become to be the
strongest possible answer to the KSP/SCRB challenge, and something a real police professional
would genuinely find useful* — not what's fastest to add to an already-long feature list.

**Method, and how to read this document.** The code was read directly, not trusted from
`CLAUDE.md`'s own claims (which itself warns it can drift stale). Findings are tagged:
- **[VERIFIED]** — confirmed directly against the live code or a live deploy, this pass.
- **[SOURCE]** — external research, cited.
- **[JUDGMENT]** — this document's own synthesis or recommendation, not independently checkable.

This document is a **point-in-time analysis**, not a steering document that gets kept current
line-by-line the way `CLAUDE.md` is. `docs/CAPABILITY_TARGET_AND_GAPS.md` and
`docs/INDUSTRY_GAP_ANALYSIS.md` already exist as living gap-analysis documents from an earlier
pass (2026-08-27) and remain independently useful — this document supersedes their conclusions
about current state where they overlap (this analysis is newer and was done by directly reading
the code a second time), but does not replace them wholesale. Part 8 below records what was
actually *built* against this document's own roadmap in the same session it was written —
treat that section as the freshest, and re-verify against `CLAUDE.md`'s changelog before trusting
it further, per that file's own stated discipline.

---

## Part 1 — What Veritas genuinely does today

### The load-bearing part is real
**[VERIFIED]** `packages/ml_models/.../fellegi_sunter.py` is not decorative. It's a careful,
correct implementation of the actual 1969 method: multi-level (not binary) field comparison, EM
estimation of m/u with the non-identifiability of the prior handled correctly (fixing `p`
because blocked pairs aren't a random sample), and — the most telling detail — a documented,
fixed bug in the u-estimate (using co-accused-on-the-same-FIR pairs as guaranteed non-matches,
because random pairs were secretly ~1% true matches and inflated the false-agreement rate 50x,
silently killing recall). This is a team that understood the statistics, not one that called
`import recordlinkage`. It's the one piece of the system defensible unconditionally to a
data-science judge.

### The trust discipline is real, and it's been tested by breaking it
**[VERIFIED]** The CRAG accept/widen/refuse loop, the provenance ("why is this here") chain, and
the contradiction checker aren't a single clever feature — they're a discipline that's been
through ~15 rounds of "found live, fixed, regression-tested" per `CLAUDE.md`'s own changelog
(evidence padding a correct answer, a refusal shipping the evidence it just rejected, a
citation-count heuristic painting a successful board pin as a failure). That history is a
stronger signal than a clean first pass would be: the trust boundary keeps getting attacked and
keeps getting repaired, not "never attacked."

### The six v24/25 conversational operations are the most under-sold part of the product
**[VERIFIED]** Read `orchestrator.py`'s `CROSS_STATION_LINKAGE`, `INTERROGATION_PREP`,
`CASE_HANDOFF`, `PREFILING_CHECK` handlers directly. `CROSS_STATION_LINKAGE` correctly reports a
genuine cross-jurisdiction link even when RBAC forbids naming the other case ("the link is real,
the case cannot be named here — contact that station directly") — a real, correct answer to a
real policy tension, not a shortcut. `INTERROGATION_PREP` was rebuilt in v25 specifically because
the first version briefed the officer on the officer's own paperwork gaps instead of questions a
suspect could actually answer — a genuine, non-obvious product bug, caught and fixed. These six
operations sit at entries #24-25 of a (then) 25-entry changelog dominated by Catalyst
infrastructure war stories. That ordering is backwards for judging purposes.

### A data-generation ceiling verified independently
**[VERIFIED]** `_MO_VARIANTS` in `data/generator/build.py`, post the "BUG-023 fixed" claim: real,
and a real improvement (all 20 crime types now have narrative content vs. 12 with none before) —
but still 3 hand-written MO sentences per crime type, chosen per-offender via a "signature"
weighting, plus slot-filled locality/time/section/status. Combinatorially richer than one
template, but still a closed template space, not free narrative.

**[SOURCE]** This matters because of what the academic cross-case-linkage literature says the
diagnostic signal actually is: "for it to be possible to link crimes committed by the same
offender, criminals must show consistent but *distinctive* behavior" (Burrell & Bull's
foundational Comparative Case Analysis research; Davies 2019 review, *J. Investigative
Psychology & Offender Profiling*). "Pickpocketing in a crowded market" is common, not
distinctive — exactly the kind of MO statement CCA theory says doesn't discriminate one offender
from another.

**[JUDGMENT]** So the honest characterization: Veritas's "similar cases"/"case-similarity watch"
features currently answer "same crime type + same district + same IPC/BNS sections, phrased as a
sentence" — real and useful, but not yet the thing the challenge language ("modus operandi across
time and station boundaries") and a ViCAP-modernization pitch actually claim. A sharp judge
asking "show me two cases that look different on the surface but share a genuinely idiosyncratic
detail" will find the well runs dry after three sentences. Fixable (Blueprint #4) — a
data-generation fix now that QuickML is live, not a retrieval-code fix. **Deliberately deferred**
this session pending a real look at Catalyst billing history (see Part 8) — it's the one
blueprint item that touches meaningful LLM call volume.

### A domain-currency gap found and fixed this pass
**[VERIFIED, now fixed — see Part 8]** `data/generator/refdata.py` populated every crime-section
citation exclusively from "Indian Penal Code, 1860," despite `manifest.py` itself claiming an
"IPC/BNS section mix" as a data source — an aspiration that had never been implemented.
**[SOURCE]** The Bharatiya Nyaya Sanhita (BNS) 2023 replaced the IPC for all offences committed on
or after 2024-07-01; FIRs registered through 2025-2026 legally cite BNS sections for anything
post-transition. The dataset's own date range (generation anchor 2026-07-01, cases spanning back
~3 years) means most generated cases fall after the transition and should cite a code the
platform never generated. A real KSP officer would notice a citation to a defunct code in about
four seconds.

### The rest, cross-checked against the project's own audits
Everything spot-checked in `docs/QA_FUNCTIONALITY_MATRIX.md` held up, and `CLAUDE.md`'s v17-v25
changelog closes most of what that document and `CAPABILITY_TARGET_AND_GAPS.md` flagged as open
(QuickML live with sane cost-routing, the case board closing the "no cross-session memory" gap
those docs called the single largest one, the explainability layer shipped, the PageRank display
bug fixed). What's still honestly open, unchanged by this pass: real PDF export (blocked on a
Catalyst identity requirement, not code), the GNN AML detector unverified against any true
positive live, Aequitas fairness auditing still a standalone script nobody runs on a schedule.

---

## Part 2 — Research: what exists, what's missing, what's contested

**[SOURCE]** CCTNS is fully deployed (all ~17,700+ stations) — the constraint is not data
existence, it's analytics adoption: "not all states use all modules," rural
infrastructure/training gaps persist. This validates Veritas's own framing ("a modern police
force does not lack data, it drowns in it") — but the pitch should be precise: Veritas doesn't
solve a data-*access* problem, it solves a data-*synthesis* problem.

**[SOURCE]** ICJS (Police/Courts/Prisons/Forensics/Prosecution) is explicitly working toward
"search and visual analytics" and "effective use of AI/ML tools," with mandatory digital
recording under BNS/BNSS/BSS targeted from January 2027. Veritas sits ahead of, not adjacent to,
this trajectory — worth stating explicitly in the pitch rather than implying disconnection from
where Indian criminal-justice IT is actually headed.

**[SOURCE]** Linkage blindness (Egger, 1984) — "a nearly total lack of sharing/coordinating of
investigative information" across jurisdictions — is the canonical, named failure mode FBI ViCAP
exists to fix; ViCAP's own literature names its own weakness as reliance on manual entry
requiring trained expertise. **[JUDGMENT]** `CROSS_STATION_LINKAGE` is a genuine, if narrow,
structural answer to this — narrower than full series detection, since (pre-Part-8) it only fires
when the same person is already named on both cases; it could not find a series with no common
suspect. That gap is exactly what Blueprint #1 / Part 8's Phase 1 addresses.

**[SOURCE]** India's actual deployed AI-policing tools (Delhi's FRS/CMAPS, UP's Trinetra,
Punjab's PAIS) have a well-documented, specific failure mode: arrests made on an AI match with no
corroborating evidence, no privacy assessment conducted before deployment, no governing
regulatory framework (Wire/Pulitzer Center investigation; Vidhi Legal Policy; ORF). **[JUDGMENT]**
This is the sharpest, most India-specific hook available for Veritas's responsible-AI story —
sharper than the generic COMPAS/Aequitas reference already in the docs. Veritas's entire
CRAG/refuse/provenance architecture is, structurally, "the tool built to be unable to do what
Trinetra-style deployments have already been criticized for doing." Say this explicitly, by name,
in the pitch.

**[SOURCE]** A real competing Datathon 2026 submission (KAVACH 360, also on Catalyst) was pulled
live for comparison: hotspot mapping, forecast-with-confidence, co-accused network mapping, an
"operational risk index," and NL search — explicitly disclaiming "does not infer guilt."
**[JUDGMENT]** This confirms map + graph + forecast + risk-score + chatbot is the default
convergent solution every competent team lands on. It is table stakes, not a differentiator, and
further polishing it has near-zero marginal judging value. Veritas already does this checklist
better than that description suggests (real KDE/DBSCAN vs. a claimed "confidence score," real
GDS-equivalent algorithms as a ranking signal, not decoration) — but "does it slightly better" is
not a winning story against "does something else entirely."

**[SOURCE]** Predictive-policing bias research remains genuinely contested (PredPol-style studies
showing 150-400% racial disproportion in a modeled deployment vs. Brantingham's real-LAPD
counter-study finding none) — already correctly captured in the project's own docs.
**[JUDGMENT]** The unresolved point going into this session: Veritas built the correct safeguard
(Aequitas, geographic-subgroup audit, unmeasured-confounder disclosure) but never wired it into
the running product. A capability that exists only as a script nobody runs is not a mitigation a
judge can verify — it's a claim. **Still open** — see Part 6/Part 8 (Phase 3, not done this
session).

---

## Part 3 — Four-way gap analysis, beneath the labels

For each challenge capability: the operational test, then **A** (does the challenge ask for it),
**B** (what an investigator actually needs), **C** (what mature systems/research say "good" looks
like), **D** (what Veritas could do *before this session*, verified).

### Crime pattern discovery
**Test**: starting from one case, does it surface a previously-unknown related case nobody
queried for, across station/time, and explain why?
**D (before)**: Reactive only. `SIMILAR_CASES`/`CASE_SIMILARITY_WATCH` answer when asked, the
latter only within the officer's own backlog/unsolved pool. The Isolation Forest alert feed is
genuinely unprompted, but operates on district-level monthly counts, not case-level pattern
content. **Verdict**: the "ask and it answers" half existed; the "it noticed and told you first"
half — the actual differentiator ViCAP has lacked since 1985 — did not. **This was the single
largest gap** between what the challenge language implies and what was built → became Part 8
Phase 1.

### Criminal network analysis
**Test**: genuine multi-hop association graph (not a labeled field), key-player identification
via real centrality, not just a picture.
**D**: genuinely strong. PageRank/Louvain/betweenness are computed and used as retrieval/ranking
signal, not rendered for their own sake — research confirms most commercial link-analysis tools
(i2, Gotham) treat the graph as a visualization surface for human judgment, not a ranking input
the way Veritas does. Correctly refuses to invent a "gang" label. **Gap**: static per-query
snapshot — no "is this community growing" temporal view, no edge annotation. Real but secondary
(Blueprint #5, not done this session).

### Behavioral profiling
**Test**: an evidence-backed picture of recurring behavior, not demographics.
**D (before)**: implicit, not first-class. The generator's `_signature_choice` mechanism gives
offenders a genuinely recurring habitual MO/detail across their own cases — real signal already
sitting in the data — but no dedicated capability read as "here is this person's behavioral
pattern." The challenge names this explicitly; the underlying signal existed and was unsurfaced.
→ became Part 8 Phase 2.

### Proactive crime prevention intelligence
**Test**: an emerging pattern, explained, with a location/time window and a decidable next
action — not a chart.
**D**: half-built, and the good half is genuinely good. The alert feed states observed vs.
expected per district with real factors — honest, explainable anomaly detection, not an opaque
score. **Gap**: it never fuses into a decision — hotspot geography, trend direction, and
recurring signature stay three separate visualizations an officer has to mentally combine, and
nothing states a bounded, actionable advisory. This is also exactly where the over-policing-bias
question lands hardest, and Veritas's own mitigation (Aequitas) isn't live. **Still open**
(Blueprint #3 / Part 6, not done this session).

### Hotspot / geospatial
**D**: solid — real KDE/DBSCAN, real basemap, legend, scale. Checklist-parity-plus-execution-
quality. Necessary, not differentiating (KAVACH 360 claims the same feature).

### Cross-case / cross-station linkage
**D (before)**: real but narrow (person-anchored only, via `CROSS_STATION_LINKAGE`). See "crime
pattern discovery" above — the general case (a series with no common named suspect yet) was the
gap, now addressed by Part 8 Phase 1's series discovery.

### Investigative lead generation / decision support
**D**: genuinely strong and under-marketed. Capped-to-actionable leads, human-decides-not-system-
decides throughout, and the six v24/25 operations are real workflow tools no competing
"map+graph+chat" submission is likely to have built, because they require understanding
investigative process, not just investigative data.

---

## Part 4 — The product thesis

Veritas is not "chatbot + graph + prediction + hotspot." Stated as one claim:

> Veritas is the reasoning and memory layer that makes records the ER (and CCTNS/ICJS after it)
> can only store into records that can be connected — reconstructing the identities,
> associations, and behavioral patterns those systems have no mechanism to infer, surfacing what
> nobody explicitly searched for, and refusing to state anything the records don't support.

Why a spreadsheet / CCTNS-search / generic-LLM doesn't already do this:
- **CCTNS/ICJS store; they don't connect.** ICJS's own stated ambition ("search and visual
  analytics... AI/ML tools") is what Veritas already does, years before that rollout completes —
  on today's siloed data, not tomorrow's interoperable one.
- **A human analyst can't run Fellegi-Sunter in their head** across ten thousand FIRs to notice
  "Ramesh Gowda" and "Ramesha Gouda" are the same man. Identity resolution is the mechanical
  version of what a very patient analyst would eventually find manually.
- **A generic LLM pointed at an export will hallucinate a case number with total confidence,**
  cannot enforce station-scoped access inside its own reasoning, and has no tamper-evident trail —
  not hypothetical: it's the same failure class as the real West Midlands Police Microsoft
  Copilot incident (a fabricated match used to justify a real banning order), the exact incident
  `CLAUDE.md`'s v24 entry already cites as the reason the case-diary export tags derived claims.
  Veritas's CRAG/provenance/audit stack exists to be *structurally incapable* of that failure, not
  to promise it away in a system prompt.

**The loop**: a case or question enters → Veritas orients on the actual entity (never a fresh
unscoped search) → retrieves across identity, graph, geography, and financial layers
simultaneously → checks for what wasn't asked (a cross-station match, a structural filing gap, a
recurring signature) → answers with explicit evidence and explicit uncertainty → the officer
acts, corrects, or challenges it → that becomes permanent case memory available to the next
officer, the next session, the next query.

**What stays human, always**: every lead, every advisory, every flagged pattern is a *proposal*;
nothing triggers an action. Not a hedge — the one point every serious framework surveyed (NIST AI
RMF, the EU AI Act's predictive-policing carve-out, Palantir AIP's own "propose not decide"
architecture) converges on, and the opposite of the failure mode already documented in India's
own deployed FRS tools.

---

## Part 5 — Ranking every capability

### Existing capabilities

| Capability | Rank | Why |
|---|---|---|
| Fellegi-Sunter identity resolution | **CRITICAL** | Nothing downstream works without it; the ER literally has no person |
| CRAG refuse-or-widen + provenance/WHY chain | **CRITICAL** | The property that separates this from every LLM-wrapper submission |
| RBAC at query-construction + audit hash chain | **CRITICAL** | Table stakes for any tool touching real police records; most hackathon teams do this worse |
| Investigation Board (cross-session memory) | **CRITICAL** | Closes the exact gap the project's own earlier research called the largest one vs. i2/Gotham |
| Six v24/25 conversational ops | **DIFFERENTIATING** | Real investigative-process tools no competing checklist submission is likely to build |
| Co-offending graph w/ GDS-equivalent algorithms as ranking signal | **DIFFERENTIATING** | Confirmed by research to exceed how most commercial tools actually use their own graphs |
| In-container Kannada ASR/MT | **DIFFERENTIATING** | Genuinely hard, genuinely real; most teams fake or skip this |
| Hybrid deterministic-first/LLM-fallback interpretation | **DIFFERENTIATING**, if pitched honestly | A mature, defensible trust architecture — must be explained as a design choice, not glossed as "we have an LLM" |
| Hotspot KDE/DBSCAN + real basemap | SUPPORTING | Necessary hygiene, checklist-parity with every competitor |
| Forecast (Prophet+MinT), risk/recidivism (XGBoost/LightGBM) | SUPPORTING | Technically solid, not a differentiator — every competing team claims this |
| Aequitas fairness audit (as built, pre-Part-8) | SUPPORTING, capped | Right idea, but a script nobody runs isn't a verifiable mitigation |
| Catalyst platform-engineering hardening | NOISE for judging / necessary for eligibility | Invisible in a demo; further investment has ~zero marginal return on investigative value |
| DoWhy causal layer | NOISE | Intellectually honest, essentially unused by any realistic officer workflow |
| GNN AML detector | NOISE, currently | Unverified against any real positive case; a claim, not a demonstrated capability |

### Missing capabilities (status as of this document's writing, before Part 8's execution)

| Capability | Rank | Why |
|---|---|---|
| Unprompted cross-case/cross-station series discovery | **CRITICAL** | What "crime pattern discovery" and modernizing ViCAP actually mean |
| First-class evidence-backed behavioral profile | **CRITICAL** | Named explicitly by the challenge; underlying signal already in the data |
| BNS section currency | **CRITICAL, cheap** | A real police panel catches this in seconds |
| Aequitas wired into the live refresh cycle | **CRITICAL** | "Proactive prevention" invites the over-policing-bias question directly; the mitigation must be verifiable |
| Genuinely distinctive (LLM-authored, non-templated) MO narrative | DIFFERENTIATING | Makes the existing similarity/linkage features actually true to their claim |
| Fused proactive-prevention advisory | DIFFERENTIATING | Turns three charts an officer combines mentally into one decision-support statement |
| Minimal graph/edge annotation | SUPPORTING | Closes the last i2/Gotham gap; smaller than it sounds given the board already exists |
| Full i2-style manual link-chart canvas | NOISE | The board already delivers the effect an officer wants |
| Full OSINT/Maltego-style external fusion | NOISE | No external sources exist in this dataset or challenge scope |
| Kafka/Flink/Iceberg real-time ingestion | NOISE (now) | Correctly deferred; dataset scale doesn't justify it |

---

## Part 6 — The winning blueprint (as proposed; see Part 8 for what was actually built)

### 1. Unprompted series discovery — "the pattern nobody searched for"
**Problem**: Five shop burglaries across three districts, all one IO each, no one connected —
linkage blindness, ViCAP's own named weakness since 1985.
**What it does**: A standing batch job scans open, unresolved-suspect cases for clusters sharing
distinctive MO facts + geographic/temporal proximity + no common investigating officer, and
writes ranked candidate series to an analyst queue.
**Example**: Five "House Burglary" FIRs across Kolar, Chikkaballapur, and Bengaluru Rural, all
rear-entry, all 2-4 AM, ~9-12 days apart, no shared suspect on file.
**Officer sees/does**: "Candidate series — 5 cases, 3 districts, no shared IO. Shared: rear-entry
method, 2-4 AM window, ~10-day interval." Clicks through, asks "why," pins it to a shared
case-thread, notifies other stations via the existing cross-station-linkage RBAC pattern.
**Built from**: existing graph/geo/temporal data, the existing WHY-chain, the existing
analyst-alert SSE transport.
**Evidence/limitation**: must state structural similarity, not confirmed common offender; capped
confidence; never auto-merges cases.
**Why differentiated**: no competing "map+graph+chat" submission is likely to build a *push*,
cross-jurisdiction pattern detector — every one builds the query-driven version.
**Status**: **Built, Part 8 Phase 1.**

### 2. Evidence-backed behavioral profile
**Problem**: "Behavioral profiling" is asked for explicitly; before this pass it was a risk
number, not a readable pattern.
**What it does**: For a resolved person, assembles (never demographic) a citable narrative:
time-of-day pattern, method/weapon recurrence, escalation trajectory, geographic range,
association stability — each line tagged DERIVED and traced to the specific cases it comes from.
**Example**: "Across 6 recorded cases (2023-2026), incidents cluster 11PM-2AM (5 of 6); method
has shifted from petty theft to burglary over 18 months; operates within a 12km radius of
Malleshwaram; the same 2 associates appear on 4 of 6 cases."
**Built from**: data already in `vx_person`/`Accused`/graph — no new model.
**Limitation**: explicitly states small-N cases (fewer than ~3) don't support a "pattern," only a
history.
**Status**: **Built, Part 8 Phase 2.**

### 3. Fused proactive-prevention advisory
**Problem**: hotspot map, trend chart, and signature data are three things an officer combines in
their head; no single bounded, actionable recommendation exists, and any "predictive" claim
invites the bias question.
**What it does**: Combines current hotspot geography + recent trend direction + recurring
MO/signature into one statement: "elevated likelihood of [pattern] in [place] over [window],
based on [n] points" — with the Aequitas geographic-subgroup check run live (not scripted) and
stated alongside it, plus the causal layer's confounder disclosure in the same panel.
**Limitation**: advisory only, never a dispatch trigger; explicit about small-sample fragility.
**Status**: **Not built.** Named rather than silently skipped.

### 4. Genuinely distinctive MO narrative (data-generation fix)
**Problem**: current MO text is 3 templates per crime type — common, not distinctive, per CCA
theory — so vector similarity is really a rephrased SQL filter.
**What it does**: Use the now-live QuickML LLM at generation time to author per-case idiosyncratic
detail, seeded by the case's real structured facts, so two cases can share a genuinely
non-obvious detail an embedding — not a WHERE clause — would need to find.
**Status**: **Deliberately held.** The one blueprint item touching meaningful QuickML volume;
gated on watching a few real days of Catalyst billing-panel usage first (see Part 8's cost
section). Not started.

### 5. Minimal graph/edge annotation
**Problem**: the graph is read-only per query; an analyst's own judgment ("confirmed via
informant," "coincidental, ruled out") has nowhere to live.
**What it does**: extend the existing case-board pin mechanism to a specific graph edge or node.
**Status**: **Not built.**

### 6. BNS section currency
**Status**: **Built, Part 8 Phase 0** — see below.

---

## Part 7 — The hero scenario (for the eventual demo)

A routine FIR, deliberately unglamorous: a shop burglary in Chikkaballapur — shutter lock broken,
cash box gone, no witness, no suspect named.

1. Officer: *"What do we know about this case?"* → Veritas gives the case Overview: facts, no
   leads yet, structural completeness check passes quietly.
2. Officer: *"Anything similar we should know about?"* → the standing series-discovery job has
   already flagged it: *"This case matches a pattern: 4 other shop burglaries across 3 districts
   over 5 weeks — same rear-entry method, same 2-4AM window, roughly 10 days apart. No two of
   these cases share an investigating officer."*
3. Officer: *"Why do you think these are connected?"* → the WHY chain fires with the actual
   shared distinctive detail (not "both are burglaries" — the entry method and time window), an
   explicit confidence, and an explicit "what this does NOT establish: no shared suspect yet, no
   forensic link — this is a behavioral pattern only."
4. Officer: *"Who's likely involved?"* → honest answer: none of the five cases has a named
   accused — "this is a pattern without a suspect, which is exactly the case series detection
   exists to catch before an officer would ever think to cross-reference three other districts by
   hand."
5. Officer: *"Should we expect another one, and where?"* → the fused advisory (Blueprint #3, not
   yet built): a bounded next-window/location projection, moderate confidence stated plainly.
6. Officer: *"Poke holes in this."* (already built, v25) → Veritas names its own weak points:
   only 5 data points, geographic progression assumed on straight-line distance not road network,
   two of five cases still under investigation so their true MO attribution isn't final.
7. Officer pins the pattern to a new shared thread; it's now visible to the other two stations'
   officers the next time either opens their own case.

This sequence shows discovery, explanation, uncertainty, a preventive recommendation, and
self-skepticism — on a case an officer would otherwise have filed and forgotten — ending in
something concretely actionable that five different desks didn't know to share.

**The one-sentence answer** to "what makes a KSP officer understand this is genuinely useful and
not just another AI demo": the moment Veritas tells them something true about their own open case
that they did not ask for and could not have found by looking — a burglary in their own station
quietly linked to four others across district lines nobody had connected — stated with the actual
FIR numbers, the actual shared detail, and an explicit admission of what it doesn't yet prove.

---

## Part 8 — What was actually executed this session (2026-09-04/05)

The roadmap from Part 6 was phased: Phase 0 (BNS fix, credibility) → Phase 1 (series discovery,
flagship) → Phase 2 (behavioral profile) → Phase 3 (Aequitas live-wiring + graph annotation) →
Phase 4 (LLM-authored MO narrative, cost-gated) → Phase 5 (pitch/demo docs). **Phases 0-2 were
built and deployed this session; Phases 3-5 were not started.** Full commit-by-commit detail is
in `CLAUDE.md`'s changelog (v26, once written) and `docs/WORK_LOG.md`'s dated entry for
2026-09-04 — this section is a pointer, not a duplicate.

**A real cost concern was raised and answered honestly, not with a guessed number.** Zoho does
not publish a static QuickML rate card; pricing is account-specific. Rather than invent a figure,
the session (a) pointed the user at Catalyst's own Settings → Billing panel, which shows real
historical spend and supports a hard budget cap with alert thresholds — the authoritative
control, enforced by the platform itself — and (b) added defense-in-depth in code regardless:
every QuickML call was discovered to have **no `max_tokens` cap at all** (the model supports up
to 128K tokens of output — a genuinely open-ended cost per call, independent of the budget
conversation), fixed with a hard cap plus a persistent, Cache-backed call-count circuit breaker
that degrades to the deterministic fallback path once a conservative ceiling is hit. This shipped
ahead of the phase work, in its own commit.

**One real near-miss this session caught and fixed, unrelated to the roadmap itself**: the prior
session's last write, made as it hit its usage limit, truncated `docs/WORK_LOG.md` from 1293
lines to a 2-line `PREPEND_MARKER` stub — mid-way through a prepend-new-entry operation. Caught
before being committed; recovered with `git restore`. No content was actually lost (it was never
committed in the truncated state), but it is the reason this document exists as a durable
artifact rather than trusting the truncated file or the chat transcript alone.

**One real bug in the roadmap's own execution, caught by writing the regression test the fix
itself had skipped**: the live-found `BEHAVIORAL_PROFILE` routing fix (originally committed as
`9567318`) turned out to be dead code — it wrapped only the pronoun alternative of its regex in
`(?i:...)` and left the literal `how`/`does`/`operate` case-sensitive, while `classify()` matches
against the *raw*, non-lowercased query. A real sentence starts with capital "How," so the "fix"
matched nothing, for either the pronoun or the named-subject phrasing it was meant to catch. It
had shipped without a test asserting the exact named-subject case reported live
("How does Usha Naika operate?") — only the already-working pronoun case was tested, which would
have passed either way and proved nothing. Found and corrected the same session, with a proper
regression test added first (confirmed to fail against the pre-fix code), then deployed.

**Full local test suite: 868 passed** at the end of this session (up from 830 at the start),
0 skipped-that-matter (2 environment-gated skips, pre-existing). Deployed and live-verified —
see `CLAUDE.md`'s v26 entry for the exact live checks run post-deploy.

**Not done this session, named rather than left implicit**: Phase 3 (Aequitas live-wiring, graph
edge annotation), Phase 4 (LLM-authored MO narrative — deliberately gated on billing data), Phase
5 (pitch rewrite, demo recording). The fused proactive-prevention advisory (Blueprint #3) was
scoped but not built. `docs/CAPABILITY_TARGET_AND_GAPS.md` and `docs/INDUSTRY_GAP_ANALYSIS.md`
were not rewritten to reflect this pass's findings — they remain as their own dated snapshots;
this document is the current source of truth for what changed 2026-09-04/05 specifically.
