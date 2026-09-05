# Data Generation Audit — Veritas Synthetic Generator

Scope: `data/data/generator/`, `data/data/schema.py`, `data/data/graph.py`, `data/data/gds.py`,
`data/data/vectors.py`, `data/data/embeddings/index_job.py`, the consuming model code in
`packages/ml_models/` and `packages/rag_agent/`, and `data/tests/`. Every claim below cites
`file:line`. No files were modified, no data was regenerated. One read-only in-process run of
`fellegi_sunter.__main__` corroborated the F1 claim (precision 1.000, recall 0.997, F1 0.998 on
a 600-case sample vs. the claimed 0.989 on the full dataset); one read-only sample of 3,000
generated cases inspected `BriefFacts` diversity.

Rubric applied per dimension: does it carry real signal, is that signal tested (not just
assumed), what's the ground truth, is the design choice defensible, is the representation
right. Answered inline in prose below rather than as five repeated bullets per section.

---

## 1. Schema conformity — fine as-is
`schema.py:42-247` reproduces the organizers' 27 ER tables verbatim (names, casing, odd fields
like `caste_master_id`, `Rank` as a reserved-word table name). 10 `vx_`-prefixed tables are
declared separately (`schema.py:258-379`). `emit_sqlite()` (`schema.py:390-404`) derives the
offline DDL from the same table list so the two backends can't drift in shape;
`data/tests/test_schema.py` fails loudly on any deviation from the organizers' PDF.

## 2. Referential integrity — fine as-is
No FK-enforcement engine exists (Data Store has none, `schema.py:14-20`), so integrity is a
property of generation order: `build.py:275-413` inserts masters → units/employees → cases →
everything keyed to a case, in one forward pass with monotonic ids, every child row created in
the same loop iteration as its parent — a dangling reference is structurally impossible.
`test_integrity.py:17-36,120-165` assert this for every FK pair; `load.py`'s own self-check
re-asserts it after a full load/query round-trip. The suite over-invests here relative to risk
(by-construction correct).

## 3. Distributions — fine as-is, one disclosed caveat
`priors.py:33-54` weights crime-type and district draws from `seed/derived/crime_types.csv`,
explicitly marked in the code as "NCRB-shaped, approximate pending the D01/D02/D03 ETL" — not
verified-real figures. (`vx_district_socioeconomic` *is* real Census 2011 data,
`schema.py:363-368` — worth distinguishing from the crime-type CSV.) Two *derived* distributions
matter more and are directly tested: preferential attachment on priors (`build.py:220-267`,
`RECIDIVISM_ALPHA=4.0`) and crew-weighted co-accused draws (`CREW_WEIGHT=40.0`) —
`test_dataset.py:53-91` asserts top-decile offenders carry >25% of offences and Louvain finds ≥3
communities with none >80% of nodes. Tuning constants like `RECIDIVISM_ALPHA`/`CREW_WEIGHT` have
no external calibration source anywhere in this codebase — noted once here rather than repeated
per section below.

## 4. Temporal realism — fine as-is, one honest gap
Cases generate oldest-first (`build.py:297`) because `_pick_accused` weights by a running
`offences` counter (`build.py:244,374`) — "prior" genuinely means earlier in wall-clock time.
Incident/arrest/chargesheet offsets are all bounded realistically (`build.py:318-319,392,404,411`)
and `test_integrity.py:213-221` asserts no chargesheet predates its FIR. Gap: case status
(`_case_status`, `build.py:195-203`) draws from per-crime-type chargesheet/conviction rates with
**no coupling to case age** — a case filed yesterday draws status from the same distribution as
one filed three years ago. Untested, and nothing downstream currently asks "status vs. age," so
nothing is silently wrong because of it — but it would matter if one were built.

## 5. Geographic realism — fine for the algorithms, not for real-world placement
`geo.py:1-75` places incidents around 4 deterministic synthetic "activity centres" per district
rather than uniformly (fixing a real prior bug: uniform scatter gives KDE/DBSCAN nothing to
find) — 75% cluster within ~450m of an attractor, 25% scatter within ~16km of the district
centroid, both seeded per-district so hotspots stay fixed across runs.
`test_dataset.py:94-122` verifies mean nearest-neighbour distance in the busiest district is
<70% of a uniform-Poisson baseline — a real statistical check. The attractors themselves are
synthetic noise, not real POI/population data — the code says so plainly (`geo.py:12-14`).
**Net**: hotspot *detection* is demonstrably real; hotspot *location* is not — a panel should be
told the geography is algorithmically real but substantively synthetic (this file states it more
sharply than `CLAUDE.md` §3 does).

## 6. Recurring identities — fine as-is
`TruePerson` pool sized at `n = max(20, 0.7 × n_cases)` (`build.py:60-76,283`) so recurrence is
structurally forced, then shaped by preferential attachment (§3). On the 600-case audit sample:
176 people from 1,022 accused rows (~5.8 accused-rows/person). `Dataset.accused_truth`
(`build.py:84,377`) is the exact answer key, held out of the record layer.

## 7. Identity ambiguity — fine as-is, strongest-engineered part of the generator
`_recorded_name` (`build.py:163-181`) applies a romanisation variant 35% of the time
(`VARIANT_RATE=0.35`) to the given name, 1/3 that rate to the patronym; `names.py:46-71`
documents *why* the patronym exists — bare given+surname collides at a measured 1.4% for
unrelated pairs, which would make name-agreement nearly worthless as Fellegi-Sunter evidence.
`_recorded_age` adds ±1-2yr noise, motivating FS's multi-level age comparator.
`fellegi_sunter.py:178-228` treats name as a structural two-part comparison rather than one
string — fixing a real bug where the literal " S/o " substring inflated apparent similarity of
total strangers to a 1% false-positive rate. `estimate_u` (`fellegi_sunter.py:254-317`) avoids
random-pair-sampling contamination by using same-case accused pairs as provable non-matches — a
genuinely careful piece of statistical hygiene. Both comparator bugs read as genuinely-found and
genuinely-fixed, not retrofitted narrative.

## 8. Co-offending structure — fine as-is
`_pick_accused` (`build.py:215-267`) draws 1-4 accused, weighting the lead by priors × locality
and every subsequent co-accused by shared-case history with the lead (`CREW_WEIGHT=40.0`,
compounding across the whole run) — the docstring names the exact bug this fixes: independent
per-accused sampling made co-offending a random graph, and Louvain "duly found one giant
community containing 254 of 255 people." `graph_sync.co_accused_edges` only creates edges
between rows FS has already resolved to a person; `gds.co_offending` projects only this edge type
before running Louvain/PageRank/betweenness, avoiding the "every case joins its district" hub
problem. `test_dataset.py:73-91` is the direct regression test for the historical bug. No ground
truth exists for whether these are the *right* communities — only that community structure
exists at all (this is entirely synthetic; there's no real Karnataka topology to match).

## 9. Transaction networks — fine for detector mechanics, untested for detector generalization
`financial.py:27-107` opens accounts for 30% of habitual offenders / 10% of everyone else, keyed
on resolved `vx_person` (not `Accused`, explicitly to avoid scattering one launderer's money
across per-case identities), then injects structuring (8-15 sub-threshold deposits/10 days, ~1
ring/40 accounts) and layering (3-5-account decay chains, ~1/50 accounts) on top of a random
background. Ground truth is a returned `labels` dict, persisted to `.veritas/aml_labels.json` (a
file, never a `vx_txn` column) so the GNN's label never sits in the column it scores. The
rule-based detector's threshold logic directly matches the injection parameters
(`REPORTING_THRESHOLD=50_000` in both), which validates detector *mechanics* but leaves its
real-world false-positive rate on organic (non-injected) bursts untested — 100% of "dirty" labels
here are hand-injected with parameters the detector already knows, and there's no
organic-but-innocent sub-threshold case (e.g. a Diwali gift transfer) to test specificity
against. Worth flagging for a panel, not worth fixing before a demo.

## 10. Case lifecycle — fine as-is, minor untested gap
`_case_status` draws from per-crime-type rates (§3's CSV); chargesheets/arrests follow at
realistic offsets (§4). `risk/features.py` correctly treats `CaseStatusID==3` as ground truth for
`conviction_count`, and the recidivism label is drawn from the same `_case_status` random
variable the generator writes — not a leakage (status is a real recorded fact, not a detector
output), but its realism is bounded by §4's no-age-coupling gap. No test asserts realized status
proportions match the input rates within tolerance — low risk given how simple the sampling is.

## 11. Crime/section relationships — fine as-is
`refdata.py:39-60` hard-maps each of 20 crime types to a major head and Act (IPC/NDPS/IT);
`crime_types.csv` carries real IPC sections per type (Theft → 379/380, Murder → 302); one
`ActSectionAssociation` row is written per section. Deterministic mapping, not statistical — real
section numbers and descriptions throughout.

## 12. Narrative diversity — BROKEN (highest-priority fix)
`_narrative` (`build.py:270-272`) formats a fixed template around an MO clause from `_MO`
(`build.py:43-52`), which covers only **8 of 20** crime types. The other 12 (Hurt, Criminal
Breach of Trust, Assault on Woman, Criminal Intimidation, Riot, Rash Driving, Extortion,
Kidnapping, Attempt to Murder, Rape, Dowry Death, Dacoity) fall back to literally
`"{crime_type} — routine method"` (`build.py:322`) — not a narrative, the crime-type label
restated. Audit sample: 3,000 cases at seed 7 produced 2,970 nominally-distinct strings, but
variation is almost entirely date/district substitution into one of ~20 fixed sentence shapes
(≈620 distinct narrative shapes total, 12/20 crime types with zero descriptive content beyond
their own name). **No test in the repo checks narrative diversity or content** — `test_dataset.py`
and `test_integrity.py` assert only exact-string uniqueness, which is why this survived to be
caught by eyeballing 60/60 narratives rather than CI. The narrative text adds almost nothing that
crime-type + district (already separate structured columns) didn't already carry, and the fix is
cheap — every field a richer narrative would need (sections, gravity, act) is already computed
before `_narrative` is called (`build.py:339-347`) but not passed into it.

## 13. Similarity ground truth — broken for narrative, fine for profiles
No ground truth exists anywhere for "these two cases are similar." `fir_narrative`
(`embeddings/index_job.py:24-28`) embeds `BriefFacts` directly with no held-out answer key to
score retrieval against — and is bounded by §12's diversity collapse. `criminal_profile`
(`index_job.py:31-56`) is materially better: built from structured fields (`CanonicalName`,
`GangAffiliation`, crime-head set), so it inherits the identity-resolution answer key (§6/§7) as
implicit ground truth instead of being narrative-derived.

## 14. Graph ground truth — fine as-is, best-tested dimension
The graph's ground truth is exactly the identity-resolution answer key: `co_accused_edges` is a
pure function of `vx_accused_identity`, `test_dataset.py:73-91` validates the resulting community
*shape* (not just "has edges"), and `test_integrity.py:168-211` separately validates structural
integrity (no dangling nodes, `TRANSFERRED_TO` stays directed, no duplicate edges).

## 15. Financial ground truth — fine as-is
Restates §9's ground-truth point: `make_financial` returns `labels` as a value never written to
`vx_txn` (`financial.py:63`, explicit comment: "detector output. Never the generator's."),
persisted to a file outside the record layer, self-checked (`financial.py:126-128`) to assert no
row is pre-flagged and every label points at a real TxnID.

## 16. Model signal — cross-cutting — sound, one demo-risk item
Entity resolution, co-offending/graph, and AML (§§6-9,14-15) have real, separated, tested
signal. Risk/recidivism is real *conditional on* entity resolution (features join through
`vx_accused_identity`), which is solid. Hotspot detection is real per §5's caveat. The causal
layer's covariates are real Census 2011 data (`vx_district_socioeconomic`) — only its crime-rate
*outcome* is synthetic, bounded by §3. **Demo risk**: `build.py:416-418` draws incident
timestamps uniformly over the lookback window with no day-of-week or seasonal weighting, yet
Prophet fits `weekly_seasonality=True, yearly_seasonality=True` — honest (near-zero seasonal
coefficients on non-seasonal data) but means a demo claiming "the forecast captures a
Friday-night spike" would be fabricated from noise, not a real capability this dataset supports.

## 17. Leakage — fine as-is, both claimed rules verified in code
**AML**: `vx_txn.FlaggedSuspicious` is `False` for every generated row, self-checked; the GNN's
label reads exclusively from the JSON file, never a queried column; the rule-based detector reads
`vx_txn` directly and never consults the labels file, so it isn't circular either. **Protected
attributes**: `risk/features.py` explicitly excludes CasteID/ReligionID/GenderID from
`FEATURE_NAMES`; gender is used only to tag rows for the fairness audit, never appended to the
feature vector. **Temporal leakage**: `build_features(cutoff)` only counts priors before cutoff,
`build_labels` only counts outcomes after — correctly separated. **Worth watching, not fixing**:
`IsHabitualOffender` and `prior_offence_count` derive from the same raw offence count, and
account-opening probability (30% vs 10%) is itself gated on `IsHabitualOffender` — so "habitual
offender" and "has a flagged-eligible account" are correlated by generator design, not by any
model. Disclosed in the code's own probabilities; no current model claims this as a discovered
insight, so it's a minor, known artifact rather than a real leakage.

## 18. Reproducibility — fine as-is, unambiguously solid
`generate(rng, n_cases)` threads one injected `Random` through every draw — no module-level or
wall-clock randomness. `test_integrity.py:250-263` asserts two runs at the same seed produce
identical tables. FS's EM pass, Louvain/betweenness, and DoWhy's refuters are all separately
seeded for the same reason (the causal layer's own docstring: "a system whose claim is
defensibility cannot give two different verdicts on one question"). Geographic attractors use a
district-string-seeded independent RNG rather than the caller's, deliberately — so attractor
placement doesn't shift if `n_cases` changes between runs (a hotspot must stay put between a
forecast and the map that renders it).

## 19. Ground-truth answer key — fixed
Three answer keys exist, none originally written to the record layer models/queries read.
**AML** (`.veritas/aml_labels.json`) persists correctly and survives a pipeline run. **Identity**
(`Dataset.accused_truth`) originally lived only in-process — available to tests and
`fellegi_sunter.py`'s own self-check, but never written by `run.py`, so the claimed "F1 0.989"
could only be recomputed by regenerating in-process, not against a live-deployed Catalyst
dataset. **Narrative/similarity**: none, per §13.

**Fixed (2026-08-26).** `run.py` now writes `IDENTITY_ANSWER_KEY` to
`.veritas/identity_answer_key.json` immediately after `load_dataset()`, mirroring the AML
pattern exactly (env-override `VERITAS_IDENTITY_ANSWER_KEY`). New
`data/generator/score_identity.py` recomputes precision/recall/F1 against whatever
`vx_accused_identity` is currently bound, using cluster-size combinatorics rather than FS's own
O(n²) self-check loop so it stays fast at full scale. 3 new tests. Not yet exercised against the
live 10k-case Catalyst dataset (predates the fix) — regenerating solely to backfill this would be
the casual regeneration this project's rules exclude.

---

## BUG-023 root cause: does narrative text drive capabilities, or do structured fields?

**Genuinely mixed, weighted toward structured fields already.** SQL Agent surfaces `narrative`
as one display field among many, never parsing it. HippoRAG — the system's primary multi-hop
retrieval path per `CLAUDE.md` §5 — seeds Personalized PageRank from resolved person names and
graph structure, never touching `BriefFacts` at all, so it's structurally immune to BUG-023.
`criminal_profile` embeddings are built entirely from structured fields. Graph/GDS, risk,
recidivism, AML, hotspots, forecasting, and causal effects all bypass `BriefFacts` too.

But two real, user-facing capabilities genuinely depend on the narrative text: the
`fir_narrative` vector collection (the entire document *is* `BriefFacts`) backs FIR-level
semantic search and Copilot's "top-5 similar past cases" — neither can move to structured-field-
only matching without losing what they're *for* (crime-type + district + status are already
structured columns; the whole point of a narrative embedding is to catch similarity structured
filtering can't express, like two thefts with an unusually similar MO). Deleting the narrative
collection would make the *existing* degenerate behavior official rather than fix it.

**Correct fix**: improve narrative generation for the capabilities that need it, while
reinforcing (not touching) the parts already correctly structured-field-driven:
1. Extend `_MO` to cover all 20 crime types, not 8 — the fallback guarantees zero-content
   narratives for 60% of them.
2. Add randomized slot-filling (victim/offender count, time-of-day, location descriptor,
   weapon/method variant) instead of one fixed MO clause per type — the same weighted-template
   pattern `refdata.py`/`priors.py` already use elsewhere, no LLM required.
3. Add a narrative-diversity test analogous to `test_dataset.py:73-122` (e.g. embedding-space
   pairwise similarity spread within a crime type, or MO-clause count proportional to case
   volume) — this is the gap that let BUG-023 survive undetected.
4. Do **not** move Copilot similarity or FIR search onto structured-field-only matching — that
   formalizes the degeneracy rather than fixing it.

---

## Summary verdict

**Mostly yes, with one clearly broken capability and a handful of honestly-disclosed
approximations.** The generator's hardest problems — reconstructing identity onto a schema with
no person, building co-offending structure that survives Louvain, keeping AML ground truth
genuinely separated from detector output, keeping the whole pipeline deterministic — are solved
well, each with a real regression test guarding the specific historical bug that motivated it.
This is the part of the codebase where "best solution, not what was fast" is actually met.

**Broken:**
1. **Narrative diversity (§12/BUG-023)** — 12/20 crime types have zero descriptive content;
   degrades FIR semantic search and Copilot's "similar past cases." Fix first: cheapest fix,
   most user-visible defect, no LLM required.
2. **No narrative-diversity test** — why BUG-023 survived to manual discovery instead of CI; any
   fix to (1) needs a companion test or it regresses silently.
3. ~~Identity answer key not persisted (§19)~~ — **fixed**; not yet re-run against the live
   dataset, which predates the fix.

**Cosmetically imperfect, fine as-is:** priors CSVs are disclosed-approximate, not sourced NCRB
figures (§3); geographic attractors are disclosed synthetic stand-ins (§5); case status has no
age-coupling and isn't tested against input rates (§4/§10); AML has no organic-but-innocent test
case for detector specificity (§9); no seasonal signal exists for Prophet to find (§16) — avoid
demo language claiming a captured seasonal pattern.

**Genuinely fine:** schema conformity, referential integrity, recurring identities, identity
ambiguity, co-offending structure, financial ground truth, graph ground truth, reproducibility,
and the AML/protected-attribute leakage separation `CLAUDE.md` claims — all verified directly
against code in this audit, not against the documentation's claims about itself.
