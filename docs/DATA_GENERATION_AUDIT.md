# Data Generation Audit — Veritas Synthetic Generator

Scope: `data/data/generator/`, `data/data/schema.py`, `data/data/graph.py`, `data/data/gds.py`,
`data/data/vectors.py`, `data/data/embeddings/index_job.py`, the consuming model code in
`packages/ml_models/` and `packages/rag_agent/`, and the test coverage in `data/tests/`.

This is an audit, not a sales pitch. Where a design decision is defensible, this document
says so briefly and moves on. Where something is broken, it names the downstream capability
it breaks and why. Every claim below cites `file:line`.

No files were modified, no data was regenerated. One read-only invocation of
`ml_models.entity_resolution.fellegi_sunter.__main__` was run against an in-memory dataset to
corroborate the F1 claim in `CLAUDE.md` (result: precision 1.000, recall 0.997, F1 0.998 on a
600-case sample — consistent with the claimed 0.989 on the full dataset). One read-only sample
of 3,000 generated cases was pulled to inspect `BriefFacts` diversity. Neither touched the
committed dataset or any file.

---

## 1. Schema conformity

**Current state.** `data/data/schema.py:42-247` reproduces the organizers' 27 ER tables
verbatim — names, casing, and known-odd fields (`caste_master_id`, `csdate`,
`CrimeHeadName` on `CrimeSubHead`, `Rank` as a reserved-word table name). Ten `vx_`-prefixed
tables are declared separately at `schema.py:258-379`, clearly demarcated. `emit_sqlite()`
(`schema.py:390-404`) derives the offline DDL from the same table list, so the two backends
cannot drift in shape. The generator's own row-shape assertions in `build.py:426-461` cross-check
against the same table dict at load time.

1. **Signal**: Yes — the schema *is* the ground truth for what "conformant" means, and every
   row the generator emits is checked against it structurally.
2. **True vs. coincidence**: N/A — this is a structural property, not a statistical one.
3. **Ground truth**: The organizers' PDF is the ground truth; `data/tests/test_schema.py`
   (not read in full here, but referenced by `CLAUDE.md`'s "fails loudly if anyone tries" claim)
   is the automated check.
4. **Defensible**: Yes.
5. **Representation appropriate**: Yes — a verbatim Python dict is the correct, auditable
   representation of a fixed external schema.

**Verdict: fine as-is.**

---

## 2. Referential integrity

**Current state.** The generator has no database and no FK enforcement engine — Data Store
itself has none (`schema.py:14-20`) — so integrity is entirely a property of generation order.
`build.py:275-413` inserts masters first (`rd.build()`, `build.py:277`), then units/employees,
then cases, then everything keyed to a case, in a single forward pass with monotonically
increasing ids (`ids = dict(case=0, comp=0, ...)`, `build.py:300`). Every child row is created
inside the same loop iteration as its parent case (`build.py:304-411`), so a dangling reference
is structurally impossible by construction, not merely unlikely.

`data/tests/test_integrity.py:17-36` (`test_no_orphans_anywhere_in_the_er`) and
`test_integrity.py:120-165` assert this for every FK pair the generator produces, and
`load.py:47-58`'s own `__main__` self-check (`load.py:125-129`) re-asserts it after a full
load/query round-trip through the ER's actual JOIN structure.

1. **Signal**: Yes.
2. **True vs. coincidence**: N/A — structural, not statistical.
3. **Ground truth**: The FK topology declared in the ER itself.
4. **Defensible**: Yes.
5. **Representation appropriate**: Yes.

**Verdict: fine as-is.** This is the one dimension the test suite over-invests in relative to
its risk — it is by-construction correct and would need a bug in the loop order to break.

---

## 3. Distributions

**Current state.** Two real distributions drive generation: `priors.py:33-45`
(`crime_types()`, IPC-head weighted by `weight` from `seed/derived/crime_types.csv`) and
`priors.py:48-54` (`district_weights()`, per-district crime volume). Both CSVs are
provenance-marked in `priors.py:1-11` as "hand-derived... shape follows NCRB... with exact
figures approximate pending the D01/D02/D03 ETL" — i.e., the code itself already discloses
that these are directionally-real, not verified-real, numbers. `refdata.py:71-79` derives the
KSP rank/designation ladder from a fixed literal list, not a distribution.

Two derived distributions matter more than the raw priors: preferential attachment on priors
(`build.py:220-267`, `RECIDIVISM_ALPHA=4.0` at `build.py:54`) and the crew-weighted co-accused
draw (`build.py:239-267`, `CREW_WEIGHT=40.0` at `build.py:56`). Both are asserted, not just
hoped for: `test_dataset.py:53-70` checks the top-decile-of-offenders share of total offences
exceeds 25%, and `test_dataset.py:73-91` checks Louvain finds ≥3 communities with no single
community holding >80% of nodes.

1. **Signal**: Yes for crime-type/district priors (real NCRB/KSP shape); yes and *measured* for
   the two derived distributions that matter to models (recidivism skew, crew structure).
2. **True vs. coincidence**: The tests directly measure this rather than assume it
   (`test_dataset.py:53-91`).
3. **Ground truth**: NCRB Crime-in-India / KSP volumes are the stated real-world reference,
   though the CSV values are self-described as approximate, not sourced figures.
4. **Defensible**: Yes for shape; the "approximate pending ETL" caveat in `priors.py:1-11` is
   the honest position and should stay documented rather than silently promoted to "real".
5. **Representation appropriate**: Weighted categorical sampling is the right representation
   for both.

**Verdict: fine as-is**, with one open item already flagged in the code itself — the priors CSVs
are approximate NCRB-shaped numbers, not the real ETL'd figures (D01/D02/D03), and `CLAUDE.md`
should not (and does not) claim otherwise for these two files specifically. It is worth
distinguishing from `vx_district_socioeconomic`, which *is* real Census 2011 data
(`schema.py:363-368`).

---

## 4. Temporal realism

**Current state.** Cases are generated oldest-first (`build.py:297`,
`filed_dates = sorted(...)`), which is load-bearing, not cosmetic: `_pick_accused` weights by
`p.offences` (`build.py:244`), a running counter incremented only after a case is generated
(`build.py:374`), so "prior" genuinely means "occurred earlier in wall-clock terms" — see the
docstring at `build.py:220-224`. Incident timestamps: `IncidentFromDate` precedes
`InfoReceivedPSDate`/filed by 2-240 hours (`build.py:318`), `IncidentToDate` is clamped to at
most 12 hours after `IncidentFromDate` and never after the filing (`build.py:319`). Arrests
follow filing by 0-30 days (`build.py:392`); chargesheets follow filing by 30-180 days when
chargesheeted, 60-240 days when closed (`build.py:404`, `build.py:411`). `test_integrity.py:213-221`
asserts no chargesheet predates its own FIR.

Case status (`_case_status`, `build.py:195-203`) is drawn from `chargesheet_rate` /
`conviction_rate` per crime type (from `priors.py`'s CSV) with no dependency on *how much time
has elapsed* since filing — a case filed yesterday and a case filed three years ago draw status
from the same distribution. In reality a case's likelihood of already being convicted rises
with its age; this generator has no such coupling.

1. **Signal**: Yes for the recidivism-relevant ordering (oldest-first, `offences` counter);
   partial for case-status realism (no age coupling).
2. **True vs. coincidence**: The recidivism ordering is real and testably load-bearing
   (§3 above). The missing age-coupling in status is not tested and would not be caught by
   any current assertion, because nothing checks status-vs-age jointly.
3. **Ground truth**: None asserted for status-vs-age; the chargesheet/conviction *rates* per
   crime type are the only calibrated numbers, and those come from `crime_types.csv`.
4. **Defensible**: The oldest-first ordering is clearly defensible and correctly prioritized.
   The status/age independence is a real gap but a minor one — no downstream capability in this
   codebase currently asks "how does status change with case age", so nothing is silently wrong
   because of it.
5. **Representation appropriate**: Yes.

**Verdict: fine as-is for what the system uses it for**, with one honestly-noted gap
(status independent of case age) that matters only if a future capability wants to answer
"how long does a chargesheet typically take relative to case age" — nothing today does.

---

## 5. Geographic realism

**Current state.** `geo.py:1-75` places incidents around 4 deterministic per-district
"activity centres" (`_N_ATTRACTORS=4`, `geo.py:23`) rather than uniformly — the docstring at
`geo.py:3-14` names this explicitly as the fix for a real prior bug ("KDE and DBSCAN over a
uniform scatter find nothing at all"). 75% of points cluster tightly around an attractor
(`_LOCAL_SPREAD≈450m`, `geo.py:25`), 25% scatter diffusely around the district centroid
(`_BACKGROUND_SHARE=0.25`, `geo.py:26`, `_BACKGROUND_SPREAD≈16km`, `geo.py:27`). Attractor
positions are derived from a district-seeded RNG (`geo.py:45`) so they are stable across
generator runs — necessary so a hotspot doesn't move between a forecast and the map that
renders it.

`test_dataset.py:94-122` verifies this statistically: mean nearest-neighbour distance in the
busiest district is required to be <70% of what a uniform Poisson scatter over the same
bounding box would produce. This is a real, non-trivial check, not a smoke test.

The attractors themselves are synthetic — 4 fixed points per district drawn from noise around
the centroid, not real market/bus-stand/POI locations. The code says so plainly
(`geo.py:12-14`): "This is a stand-in for the real attractor layer (WorldPop population grid +
OSM POI/land-use...)."

1. **Signal**: Yes — clustering exists and is strong enough for DBSCAN's `eps=500m,
   min_samples=10` (`hotspots.py:24-25`) to find real clusters.
2. **True vs. coincidence**: Tested directly (`test_dataset.py:94-122`).
3. **Ground truth**: None for *where* hotspots should be (the attractors are synthetic
   noise, not real POIs) — only for *that* hotspots exist somewhere.
4. **Defensible**: Yes, as an honestly-labeled stand-in.
5. **Representation appropriate**: Lat/lng doubles on `CaseMaster`, matching the ER
   (`schema.py:60-61`) and requiring no PostGIS geometry type — correct.

**Verdict: fine as-is for demonstrating that the hotspot pipeline works** on real algorithms
(KDE/DBSCAN); **not fine as ground truth for "is this actually where Bengaluru's real crime
concentrates"** — a panel should be told the geography is algorithmically real but
substantively synthetic, which the code already tells itself in `geo.py:12-14` but which
`CLAUDE.md` §3 does not restate as sharply as it could.

---

## 6. Recurring identities

**Current state.** `build.py:60-76` (`TruePerson`) is the private ground-truth cast; `n =
max(20, int(n_cases * 0.7))` (`build.py:283`) sizes the pool so cases outnumber people by
roughly 1.4:1 before any preferential attachment — i.e., recurrence is structurally forced to
exist, then shaped by the weighting in `_pick_accused`. `offences` on each `TruePerson`
increments every time they're chosen (`build.py:374`) and directly feeds next-time selection
weight (`build.py:244`), producing a genuinely skewed, self-reinforcing recurrence pattern
rather than a flat one.

`test_dataset.py:53-70` measures this: top decile of offenders must account for >25% of total
offences. On a 600-case sample the entity-resolution run (rerun for this audit) produced 176
people from 1,022 accused rows — roughly 5.8 accused-rows-per-person on average, consistent
with meaningful recurrence.

1. **Signal**: Yes, and measured.
2. **True vs. coincidence**: Directly asserted (`test_dataset.py:53-70`).
3. **Ground truth**: `Dataset.accused_truth` (`build.py:84`, populated at `build.py:377`) is
   the exact AccusedMasterID → TruePerson.uid answer key, held out of the record layer.
4. **Defensible**: Yes — `RECIDIVISM_ALPHA=4.0` is a tuning constant with no external
   calibration target (no published Karnataka recidivism-skew figure to match), but the
   qualitative shape (heavy-tailed) is realistic and the test enforces it stays heavy-tailed.
5. **Representation appropriate**: Yes.

**Verdict: fine as-is.**

---

## 7. Identity ambiguity

**Current state.** `_recorded_name` (`build.py:163-181`) applies a romanisation variant to the
given name 35% of the time (`VARIANT_RATE=0.35`, `build.py:57`) and to the patronym at 1/3 that
rate. `names.py:46-58` (`full_record_name`) documents *why* the patronymic exists at all: a bare
given+surname pool collides at 1.4% for unrelated pairs (measured and asserted at
`names.py:64-71`), which would make name-agreement nearly worthless as FS evidence — adding the
patronymic is both more realistic and functionally necessary for the field to carry signal.
`build.py:184-191` (`_recorded_age`) adds ±1-2 year noise to stated age, separately motivating
FS's multi-level (not binary) age comparator.

`fellegi_sunter.py:178-228` (`_compare`) treats name as a *structural* two-part comparison
(own name + patronym, 4 levels) rather than one string — the docstring at `fellegi_sunter.py:185-198`
documents the real bug this fixes: literal " S/o " substring inflating apparent similarity
of total strangers to 1% false-positive rate on edit distance over the concatenated string.

1. **Signal**: Yes, deliberately engineered and measured (`names.py:64-71`).
2. **True vs. coincidence**: `estimate_u` (`fellegi_sunter.py:254-317`) specifically avoids
   the contamination trap of random-pair sampling by using same-case accused pairs as
   provable non-matches (`fellegi_sunter.py:260-277`) — a genuinely careful piece of
   statistical hygiene, not a naive implementation.
3. **Ground truth**: `Dataset.accused_truth`, same as §6.
4. **Defensible**: Yes — `VARIANT_RATE=0.35` has no external calibration source (no published
   figure for "how often is a Karnataka FIR name transliterated inconsistently") but is a
   reasonable illustrative value, and it is large enough to be a real test of the resolver
   rather than a decorative one.
5. **Representation appropriate**: Yes.

**Verdict: fine as-is. This is the strongest-engineered part of the generator** — the two
comparator-design bugs referenced in the docstrings (contamination in `u`, string-concatenation
inflation in name comparison) read as genuinely-found and genuinely-fixed problems, not
retrofitted narrative.

---

## 8. Co-offending structure

**Current state.** `_pick_accused` (`build.py:215-267`) draws `k∈{1,2,3,4}` accused
(`build.py:243`) with the *lead* offender weighted by priors × locality
(`LOCAL_WEIGHT=15.0`, `build.py:55`), and every subsequent co-accused additionally weighted by
`crews[lead.uid][candidate.uid]` — how many prior cases they've already shared
(`CREW_WEIGHT=40.0`, `build.py:56`, applied at `build.py:257`). Every case that draws a crew
updates `crews` for every pair in it (`build.py:263-266`), so crew structure compounds across
the whole generation run. The docstring (`build.py:233-241`) explicitly documents the bug this
fixes: independent per-accused sampling makes co-offending a random graph, and "Louvain duly
found one giant community containing 254 of 255 people."

`graph_sync.py:42-61` (`co_accused_edges`) turns this into `CO_ACCUSED_WITH` edges weighted by
shared-case count, but **only between rows Fellegi-Sunter has already resolved to a person**
(`graph_sync.py:50`, `uid_of.get(...)`) — an unresolved accused row contributes no co-offending
edge at all. `gds.py:42-63` (`co_offending`) projects only this edge type before running
Louvain/PageRank/betweenness, explicitly to avoid the "every case joins its district" hub
problem (`gds.py:44-51`).

`test_dataset.py:73-91` asserts ≥3 communities and no community >80% of nodes — the direct
regression test for the historical bug.

1. **Signal**: Yes, and it is the load-bearing property for Louvain/PageRank/betweenness.
2. **True vs. coincidence**: Tested (`test_dataset.py:73-91`).
3. **Ground truth**: None for "are these the *right* communities" — only that community
   structure exists at all, not that it matches any real Karnataka crew topology (there is
   none to match against; this is entirely synthetic).
4. **Defensible**: `CREW_WEIGHT=40.0` is another uncalibrated constant, same caveat as §6/§7.
5. **Representation appropriate**: A weighted undirected projection is the right
   representation for Louvain/PageRank/betweenness, and the code is explicit
   (`gds.py:44-51`) about *why* it must be a projection rather than the whole graph.

**Verdict: fine as-is.**

---

## 9. Transaction networks

**Current state.** `financial.py:27-77` (`make_financial`) opens accounts for 30% of habitual
offenders and 10% of everyone else (`financial.py:39`), builds a background of random transfers
(`financial.py:70-73`, 3× account count), then injects two labeled patterns: structuring
(`_inject_structuring`, `financial.py:80-93` — 8-15 sub-threshold deposits into one account
within 10 days, roughly one ring per 40 accounts) and layering (`_inject_layering`,
`financial.py:95-107` — a large sum decaying through a 3-5-account chain, roughly one chain per
50 accounts). **Runs after entity resolution**, keyed on `vx_person`, not `Accused`
(`financial.py:10-13` — explicitly to avoid scattering one launderer's money across a dozen
per-case identities).

1. **Signal**: Yes, and it is deliberately structured so both the rule-based detector
   (sub-threshold clustering) and the GNN (multi-hop coordinated pattern the rule cannot see)
   have something real to find.
2. **True vs. coincidence**: The rule-based detector's window/threshold logic
   (`structuring.py:24-70`) is a direct match to the injection parameters
   (`REPORTING_THRESHOLD=50_000` in both files), so it is *designed* to find the injected
   pattern — this is appropriate for validating the detector's mechanics, but it means the
   detector's real-world false-positive/false-negative rate on organic (non-injected)
   structuring-like bursts is untested by this dataset, since none exist outside the injection.
3. **Ground truth**: `labels` dict returned by `make_financial` (`financial.py:31, 51-52,
   67, 92, 107`), written to `.veritas/aml_labels.json` by `run.py:27-30, 67-68` — a file, not
   a table column, specifically so the GNN's training label never sits in the column it scores
   (§16 below has the full leakage discussion).
4. **Defensible**: Ring/chain frequencies (1 per 40/50 accounts) are illustrative constants,
   same caveat as elsewhere — no external AML prevalence figure calibrates them.
5. **Representation appropriate**: Yes — `vx_account`/`vx_txn` plus a directed
   `TRANSFERRED_TO` edge (`graph_sync.py:77-82`, deliberately never symmetrized,
   `graph.py:52-53`) is the correct representation for a money-flow Sankey and for GNN
   message-passing.

**Verdict: fine as-is for detector-mechanics validation; a genuine limitation for
detector-generalization validation** — since 100% of the "dirty" labels are hand-injected with
parameters the rule detector already knows, there is no organic-but-innocent sub-threshold
burst in the dataset to test the detector's specificity against. Worth flagging (not fixing)
because a panel may ask "how do you know this doesn't just flag Diwali gift transfers" — the
honest current answer is "the dataset has no such case to test against."

---

## 10. Case lifecycle

**Current state.** `_case_status` (`build.py:195-203`) draws Under Investigation / Chargesheeted
/ Convicted / Acquitted from `chargesheet_rate` and `conviction_rate` per crime type
(from `crime_types.csv`, read via `priors.py:33-45`). `ChargesheetDetails` rows are written for
chargesheeted-or-later cases (`build.py:400-405`) and, with 5% probability, for cases that
close as false/undetected (`build.py:406-411`, `cstype` B/C). Arrest/surrender records are
written per accused at 70% probability (`build.py:385-398`), with 12% of those recorded as
surrender rather than arrest.

The `risk/features.py` module treats `CaseStatusID == 3` (Convicted) as ground truth for the
`conviction_count` feature (`features.py:27, 105`), and the 180-day recidivism label is built
from `build_labels` (`features.py:129-141`) over the same `CrimeRegisteredDate` field the
generator writes — i.e., the model's label and the generator's `_case_status` draw are the same
underlying random variable, drawn once by the generator and read as-is downstream. This is
correct and not a leakage — status is a real recorded fact, not a detector output — but it means
the *realism* of `_case_status`'s calibration (§4 above: no age coupling) directly bounds how
realistic the recidivism-label distribution can be.

1. **Signal**: Yes — status transitions exist and are keyed to real per-crime-type rates.
2. **True vs. coincidence**: Not directly tested — no test asserts the *distribution* of
   statuses matches `chargesheet_rate`/`conviction_rate` within tolerance; only referential
   consistency (chargesheet not before FIR, `test_integrity.py:213-221`) is checked.
3. **Ground truth**: The rates themselves come from the same approximate NCRB-shaped CSV
   flagged in §3.
4. **Defensible**: Yes, with the same caveat as §3/§4.
5. **Representation appropriate**: Yes — matches `CaseStatusMaster`/`ChargesheetDetails`
   exactly as the ER declares them.

**Verdict: fine as-is**, with a minor untested gap (no direct assertion that realized status
proportions match the input rates) that is low-risk given how simple the sampling logic is.

---

## 11. Crime/section relationships

**Current state.** `refdata.py:39-60` (`_CRIME_MAP`) hard-maps each of the 20 crime types to a
major head and an Act (IPC/NDPS/IT). `priors.py`'s `crime_types.csv` carries the IPC sections
per crime type (e.g. Theft → 379|380, Murder → 302) and `build.py:343-347` writes one
`ActSectionAssociation` row per section listed for the drawn crime type. `refdata.py:106-130`
(`_SECTION_DESC`) gives real IPC section descriptions for the sections actually used.
`refdata.py:223-236`'s self-check asserts every crime type's head/sub-head/act resolves to a
real row.

1. **Signal**: Yes — sections are not randomly assigned; they follow the crime type
   deterministically via the same CSV that drives crime-type sampling, so "Theft ⇒ IPC 379/380"
   is a fixed, correct mapping in every generated row.
2. **True vs. coincidence**: N/A — deterministic mapping, not statistical.
3. **Ground truth**: Real IPC/NDPS/IT-Act section numbers and descriptions.
4. **Defensible**: Yes.
5. **Representation appropriate**: `ActSectionAssociation` matches the ER's own junction-table
   design for a many-sections-per-case relationship.

**Verdict: fine as-is.**

---

## 12. Narrative diversity

**Current state — this is where BUG-023 lives.** `_narrative` (`build.py:270-272`):

```python
def _narrative(crime_type: str, district: str, filed: datetime, mo: str) -> str:
    return (f"On {filed:%d %b %Y}, a case of {crime_type.lower()} was registered in "
            f"{district} district. {mo}. Investigation is being carried out as per procedure.")
```

`mo` comes from `_MO` (`build.py:43-52`), a fixed dict with entries for only **8 of the 20**
crime types in `_CRIME_MAP`/`crime_types.csv` (Theft, House Burglary, Motor Vehicle Theft,
Robbery, Cheating, Cyber Crime, Murder, Narcotics). For the other 12 crime types (Hurt, Criminal
Breach of Trust, Assault on Woman, Criminal Intimidation, Riot, Rash Driving, Extortion,
Kidnapping, Attempt to Murder, Rape, Dowry Death, Dacoity), the fallback at `build.py:322` fires:
`f"{prior.crime_type} — routine method"`, e.g. literally `"Hurt — routine method"`. That is not
a narrative — it is the crime-type label restated with three extra words.

**Corroboration** (read-only sample, this audit): generating 3,000 cases at seed 7 produced
2,970 nominally-distinct `BriefFacts` strings, but the variation is almost entirely the date and
district substitution into one of 20 fixed sentence shapes — e.g. every "Hurt" case in Bengaluru
Urban differs from every other only by its date, and reads `"On {date}, a case of hurt was
registered in Bengaluru Urban district. Hurt — routine method. Investigation is being carried
out as per procedure."` There are effectively **20 crime types × 31 districts ≈ 620 distinct
narrative shapes**, out of which 12/20 crime types carry zero descriptive content beyond their
own name.

**No test in the repo checks narrative diversity.** `test_dataset.py` and `test_integrity.py`
were read in full for this audit; neither asserts anything about `BriefFacts` content, length,
distinctness beyond exact-string uniqueness, or MO-specificity. This is precisely why BUG-023
was only caught by sampling 60/60 narratives by eye, not by CI.

1. **Signal**: Very weak. The only real signal per narrative is crime type and district — both
   of which are *already* separately available as structured columns
   (`CrimeMajorHeadID`/`CrimeMinorHeadID`, `PoliceStationID` → district). The narrative text adds
   almost nothing crime-type-and-district didn't already carry.
2. **True vs. coincidence**: A downstream consumer trying to distinguish two Theft cases in the
   same district by narrative content cannot — there is no case-specific detail (weapon, target,
   suspect count, time of day beyond the fixed MO clause) to distinguish them.
3. **Ground truth**: None — there is no narrative-diversity answer key, unlike identity
   resolution or AML.
4. **Defensible**: No. Even granting that this is synthetic data, a fixed lookup string per
   crime type is a worse representation than the generator already has available in
   `_MO`/`refdata.py` (which has per-crime-type section text, gravity, and act) — nothing
   stops the narrative template from drawing on victim/complainant attributes, MO variants, or
   the specific IPC sections already computed for that case (`build.py:344-347`, computed
   *before* `_narrative` is called at `build.py:339` but not passed into it).
5. **Representation appropriate**: This is exactly the crux of the BUG-023 root-cause question
   below — see that section.

**Verdict: broken, and the highest-priority fix in this audit.**

---

## 13. Similarity ground truth

**Current state.** There is **no ground truth for narrative/case similarity** anywhere in the
generator. `TruePerson` (§6/§7) gives an answer key for *identity*; `aml_labels.json` (§9) gives
one for *laundering patterns*; nothing analogous exists for "these two cases are the same kind
of crime in the same way." `embeddings/index_job.py:24-28` (`fir_documents`) builds the
`fir_narrative` vector collection directly from `CaseMaster.BriefFacts` with no held-out
answer key to score retrieval quality against.

`embeddings/index_job.py:31-56` (`profile_documents`) is materially better: it builds the
`criminal_profile` collection from **structured fields** — `CanonicalName`, `GangAffiliation`,
and the set of `CrimeHeadName`s a resolved person has been accused under — not narrative text.
This collection *does* have implicit ground truth, because it is built from the same identity
resolution answer key as §6/§7: two profiles for the same `PersonUID` are trivially the "same
entity," and profile similarity across different people with overlapping crime-type sets is at
least traceable to a real structured fact, not an artifact of a shared MO template.

1. **Signal**: Present but weak for `fir_narrative` (bounded by §12's diversity collapse);
   present and reasonable for `criminal_profile` (structured, not narrative-derived).
2. **True vs. coincidence**: Untestable for `fir_narrative` — there is nothing to test against.
3. **Ground truth**: None for narrative similarity; implicit (via `vx_accused_identity`) for
   profile similarity.
4. **Defensible**: No, for `fir_narrative` specifically — a retrieval capability with no
   evaluation set cannot be validated, and the diversity collapse in §12 means even an eyeball
   check would show near-ties within a crime type.
5. **Representation appropriate**: The profile collection's structured-field representation is
   the right template for the narrative collection to move toward — see BUG-023 verdict below.

**Verdict: broken for `fir_narrative` (no answer key ever existed); fine for
`criminal_profile`.**

---

## 14. Graph ground truth

**Current state.** The graph's ground truth is exactly the identity-resolution answer key
(§6/§7): `graph_sync.co_accused_edges` (`graph_sync.py:42-61`) is a pure function of
`vx_accused_identity`, and `test_dataset.py:73-91` validates the resulting community structure
directly (not merely "the graph has edges" but "the graph has the *shape* Louvain needs").
`test_integrity.py:168-211` separately validates the graph's structural integrity (no dangling
person/case nodes, `TRANSFERRED_TO` stays directed, no duplicate relationship edges except the
explicitly-per-event ones). This is a genuinely well-tested dimension.

1. **Signal**: Yes, strong.
2. **True vs. coincidence**: Directly tested, both statistically (community structure) and
   structurally (no dangling nodes, correct directionality).
3. **Ground truth**: `Dataset.accused_truth`, transitively.
4. **Defensible**: Yes.
5. **Representation appropriate**: Yes — a flat, typed edge table materialised into
   NetworkX is the right representation given no Catalyst graph-DB service exists
   (`graph.py:1-33`).

**Verdict: fine as-is. Best-tested dimension in the generator.**

---

## 15. Financial ground truth

**Current state.** Covered substantively in §9. To restate the ground-truth-specific point:
`make_financial` returns `labels: dict[TxnID, pattern]` (`financial.py:31, 51-52`) as a
*separate return value*, never written to `vx_txn` (`financial.py:63`: `"FlaggedSuspicious":
False, # detector output. Never the generator's.`). `run.py:67-68` persists this to
`.veritas/aml_labels.json`, a file outside the record layer the models query.
`financial.py:126-128`'s self-check directly asserts `not any(t["FlaggedSuspicious"] for t in
txns)` and that every label points at a real TxnID.

1. **Signal**: Yes, strong and separated as claimed.
2. **True vs. coincidence**: The injected patterns are deterministic constructions (window,
   threshold, chain length) — real by construction, not by inference.
3. **Ground truth**: The labels file itself.
4. **Defensible**: Yes.
5. **Representation appropriate**: Yes.

**Verdict: fine as-is.**

---

## 16. Model signal — cross-cutting

Already covered per-model in §§8-15. Summary: entity resolution (§6/§7), co-offending/graph
algorithms (§8/§14), and AML (§9/§15) have real, separated, tested signal. Risk/recidivism
(`risk/features.py`) has real signal *conditional on* entity resolution being correct — its
`prior_offence_count` and `co_accused_degree` features are computed via
`vx_accused_identity` joins (`features.py:59-67`), so their quality is bounded by §6/§7, which
is solid. Hotspot detection (`spatial/hotspots.py`) has real signal per §5, bounded by the
"synthetic attractor, not real POI" caveat. Forecasting (`forecasting/forecast.py`) consumes
`CrimeRegisteredDate` counts per station/day directly — no generator-side realism issue beyond
what's already noted in §4 (no seasonality is deliberately injected by the generator; Prophet's
own seasonality terms have nothing but noise to fit against, since `filed_dates` are drawn
uniformly over `days_back` with no day-of-week or seasonal weighting —
`build.py:297, 416-418`: `_rand_datetime` draws a uniformly random day within the lookback
window with no weekly/seasonal component).

The causal layer (`causal/effects.py`) does **not** depend on the generator's synthetic crime
data quality for its independent variables — `_panel()` (`effects.py:56-85`) reads
`vx_district_socioeconomic`, which is real Census 2011 data loaded separately
(`schema.py:363-368`), and only the crime-rate *outcome* comes from the synthetic dataset
(`effects.py:71, 84`). So the causal estimate's covariates are real; only its outcome variable
is synthetic and therefore only as trustworthy as the district-level crime-count aggregation,
which has no generator-side realism issue beyond volume-by-district already covered in §3.

**Additional finding**: Prophet/MinT forecasting has no day-of-week or seasonal signal injected
into the generator's date sampling (`build.py:416-418`, uniform random hour/day within a
lookback window). Since Prophet explicitly fits `weekly_seasonality=True, yearly_seasonality=True`
(`forecast.py:63`), this means the seasonality terms are fitting synthetic noise on this dataset
— which is honest (Prophet will correctly find near-zero seasonal coefficients on
non-seasonal data) but means any demo of "the forecast captures a Friday-night spike" or similar
seasonal narrative would be **fabricated from noise**, not a real capability the dataset
supports. This is worth knowing before a demo script leans on seasonal forecasting language.

**Verdict: model signal is generally sound and honestly bounded, with one demo-risk item**
(no seasonal signal in incident timing, so Prophet's seasonality terms have nothing real to
learn on this dataset).

---

## 17. Leakage

**Current state — the two rules `CLAUDE.md` claims are enforced were verified in code, not
just asserted.**

- **AML**: `vx_txn.FlaggedSuspicious` is `False` for every generated row
  (`financial.py:63`), asserted by the generator's own self-check
  (`financial.py:127`). The GNN's training label (`gnn.py:33-49`, `_injected_txn_ids`) reads
  exclusively from `.veritas/aml_labels.json`, a file — never a column the detector or any
  downstream query touches. The rule-based detector (`structuring.py`) reads `vx_txn` directly
  for its window/threshold logic and does not consult the labels file at all — it is a pure
  rule, genuinely independent of the injected ground truth, so its output is not circular by
  construction either.
- **Protected attributes**: `risk/features.py:1-19` explicitly excludes CasteID, ReligionID,
  and GenderID from `FEATURE_NAMES` (`features.py:30-37`) — `_gender_label` (`features.py:125-126`)
  is used only to tag a `FeatureRow` for the fairness audit, never appended to the feature
  vector `x` itself (`features.py:110-121`).
- **Temporal leakage in risk features**: `build_features(cutoff)` (`features.py:87-122`) only
  counts prior offences with `filed < cutoff` (`features.py:101`), and `build_labels`
  (`features.py:129-141`) only counts labels with `filed >= cutoff`. This is correctly
  separated.

One thing worth flagging as **not leakage but a coupling to watch**: `IsHabitualOffender` on
`vx_person` (`fellegi_sunter.py:507`, `sum(1 for v in uid_of.values() if v == uid) > 2`) is
computed from the *same* Accused-row counts that `risk/features.py`'s `prior_offence_count`
also derives. This is not circular (it's the same real underlying fact, computed once and read
twice, not a model's output feeding its own input) but the account-holder probability in
`financial.py:38-39` (30% for habitual offenders vs 10% for everyone) means the financial
layer's *account-opening* signal is itself derived from `IsHabitualOffender`, which is itself
derived from raw offence count — so "is a habitual offender" and "has a bank account in this
dataset" are correlated by generator design, not by any model. Any capability that infers
"habitual offenders are more likely to have flagged accounts" would be rediscovering a
generator artifact, not a real-world pattern. This is a modest concern, not a serious one — the
correlation is disclosed in the docstring (`financial.py:38-39`'s own probabilities), and no
current model claims to have discovered this relationship as a novel insight.

**Verdict: fine as-is.** Both leakage rules `CLAUDE.md` claims are genuinely enforced in code,
not merely documented. The habitual-offender/account-probability coupling is a minor,
disclosed generator artifact worth knowing about but not fixing.

---

## 18. Reproducibility

**Current state.** `generate(rng: random.Random, n_cases: int)` takes an injected `Random`
throughout (`build.py:275`), and every sampling call in the file threads that same `rng` —
no module-level randomness, no wall-clock seeding. `test_integrity.py:250-263`
(`test_the_generator_is_deterministic_under_a_fixed_seed`) directly asserts two runs at the
same seed produce identical table contents, table-by-table. `run.py:36` defaults `--seed 42`.
The Fellegi-Sunter EM pass is itself deterministically seeded (`fellegi_sunter.py:441`,
`random.Random(0)`, "fixed seed: reproducible linkage"), and Louvain/betweenness are seeded too
(`gds.py:79, 83`, `seed=0`). DoWhy's refuters are explicitly seeded for the same reason
(`effects.py:49`, `REFUTER_SEED = 42`, with the docstring at `effects.py:46-49` naming exactly
why: "a system whose claim is defensibility cannot give two different verdicts on one question").

Geographic attractors use a district-string-seeded independent RNG
(`geo.py:45`, `random.Random(f"attractors:{district_code}")`) rather than the caller's `rng`,
which is deliberate and correct — it makes attractor placement independent of `n_cases` or
draw order, so attractors stay fixed even if the case count changes between runs
(`geo.py:41-44`'s docstring: "a hotspot must stay in the same place between a forecast and the
map that renders it").

1-5. **All five questions**: Yes across the board — this dimension is unambiguously solid.

**Verdict: fine as-is.**

---

## 19. Ground-truth answer key

**Current state.** Three separate answer keys exist, and none of them are written to the record
layer the models/queries read:

- **Identity**: `Dataset.accused_truth: dict[AccusedMasterID, TruePerson.uid]`
  (`build.py:84`), populated during generation (`build.py:377`), never persisted anywhere —
  it lives only in the `Dataset` object returned by `generate()`, consumed in-process by
  `fellegi_sunter.py`'s own `__main__` self-check (`fellegi_sunter.py:517-558`) and by
  `test_dataset.py`'s `dataset` fixture. It does not survive a `python -m data.generator.run`
  invocation — `run.py` never writes it anywhere, so **the identity answer key is only
  available when `generate()` is called directly in-process** (tests, the module's own
  self-check), not after a full pipeline run against Data Store. This means the claimed
  "F1 0.989 against the generator's answer key" (`CLAUDE.md` §0) is a fact about running the
  test suite / `fellegi_sunter.py` directly, not something that could be recomputed against a
  live-deployed dataset without regenerating in-process.
- **AML**: `.veritas/aml_labels.json`, written by `run.py:67-68`, persisted to disk (not the
  database) and read back by `gnn.py:33-49` on every GNN fit. This one *does* survive a pipeline
  run and is exactly the pattern the identity answer key should probably also follow if anyone
  ever wants to re-score entity resolution against a live-deployed Catalyst dataset without
  rerunning the whole generator in-process.
- **Narrative/similarity**: none, per §13.

1. **Signal**: Present for identity and AML; absent for narrative.
2. **True vs. coincidence**: The identity and AML keys are exact, not estimated.
3. **Ground truth**: Exists for identity and AML.
4. **Defensible**: The AML key's file-based persistence is the right pattern. The identity
   key's in-process-only lifetime is a gap — it means the resolver's real accuracy cannot be
   independently re-verified against a Catalyst-deployed dataset after the fact, only against
   a fresh in-process `generate()` call.
5. **Representation appropriate**: A JSON file mirrors the AML pattern well; the identity key
   should arguably follow the same pattern (a file, not a table) for the same reason AML labels
   are a file — but currently doesn't exist as an artifact at all post-generation.

**Verdict: minor gap, not urgent.** The identity answer key should be persisted the same way
the AML labels are (`run.py:67-68`), so that "F1 0.989" can be recomputed against whatever is
actually live on Catalyst, not only against a fresh local `generate()` call. This is a
nice-to-have for auditability, not a correctness bug — nothing downstream currently depends on
having it post-generation.

**Fixed (2026-08-26 North Star hardening pass).** `run.py` now writes `IDENTITY_ANSWER_KEY` to
`.veritas/identity_answer_key.json` immediately after `load_dataset()`, mirroring
`AML_LABELS` exactly, env-var overridable (`VERITAS_IDENTITY_ANSWER_KEY`) the same way
`gnn.py` overrides `VERITAS_AML_LABELS`. `data/generator/score_identity.py` recomputes
precision/recall/F1 from it against whatever `vx_accused_identity` is currently bound, using
cluster-size combinatorics rather than `fellegi_sunter.py`'s own O(n²) self-check loop, so it
stays fast at full dataset scale. 3 new tests (`data/tests/test_score_identity.py`). Not yet
exercised against the live 10k-case Catalyst dataset — that dataset was seeded before this
fix existed, and regenerating it solely to backfill this file would be exactly the casual
regeneration §20 of `CLAUDE.md` prohibits for a gap this minor.

---

## BUG-023 root cause analysis

**The question**: does case-narrative generation use free-text templates as the *primary*
representation consumed downstream, or do capabilities primarily use structured fields with
narrative as a secondary rendering — which would change the fix from "improve the templates"
to "stop routing capabilities through the templates at all"?

**Finding, with code evidence**: it is genuinely mixed, and the mix matters for the verdict.

**Capabilities that use structured fields, NOT narrative text, today:**
- SQL Agent's case object (`sql_agent.py:27-57`) surfaces `narrative` as one field among many
  (`CrimeSubHead.CrimeHeadName`, `CaseStatusMaster.CaseStatusName`, `Unit`/`District` names,
  lat/lng) — nothing in `sql_agent.py` parses or NLP-processes `BriefFacts`; it is passed
  through as a display string only.
- HippoRAG (`hipporag.py:1-51`) seeds Personalized PageRank from **person names resolved to
  graph node ids** (`hipporag.py:19-28`) and reads graph structure (`data.gds.personalized_pagerank`)
  — it never touches `BriefFacts` at all. This is the primary multi-hop retrieval mechanism per
  `CLAUDE.md` §5, and it is structurally immune to BUG-023.
- The `criminal_profile` vector collection (`embeddings/index_job.py:31-63`) is built entirely
  from structured fields (`CanonicalName`, `GangAffiliation`, the set of `CrimeHeadName`s) —
  not narrative text at all, despite living in the same vector store as `fir_narrative`.
- Graph/GDS algorithms (`graph.py`, `gds.py`) never touch `BriefFacts`.
- Risk scoring, recidivism, AML, hotspots, forecasting, causal effects — none read
  `BriefFacts` (verified per-model in §§8-16).

**Capabilities that genuinely depend on `BriefFacts` text today:**
- The `fir_narrative` vector collection (`embeddings/index_job.py:24-28`) — the *entire*
  document is `BriefFacts`, nothing else. This is what `vector_agent.search()`
  (`vector_agent.py:45-59`) retrieves from when a query needs FIR-level semantic search, and
  what `copilot/brief.py:85-102` (`_similar_cases`) retrieves from for "top-5 similar past
  cases" — a headline Investigation Copilot feature per `CLAUDE.md` §5's "given an open case"
  description.
- The lexical half of `hybrid_search` (`vectors.py:184-197`) also scores against
  `BriefFacts` content for the `fir_narrative` collection specifically (it operates on whatever
  `content` string was indexed, and for this collection that string is `BriefFacts` verbatim).

**Verdict: C — Both, but weighted toward B.**

The system's *primary* multi-hop reasoning path (HippoRAG, per `CLAUDE.md` §5's stated
architecture) already never touches narrative text, and the `criminal_profile` collection —
which exists in the same vector store as the broken one — already demonstrates the pattern the
fix should generalize: build the document from structured fields (crime type, section,
district, status, MO-relevant flags already computed at `build.py:339-347` before `_narrative`
is even called) rather than from a fixed-string template.

But `fir_narrative` genuinely is the sole representation for two real, user-facing capabilities
— FIR-level semantic search and Copilot's "similar past cases" — and neither can be moved to
"use structured fields instead" without losing what they're *for*. Crime-type + district +
status is already fully available as structured columns; the entire reason a narrative
embedding exists on top of them is to catch similarity that structured filtering can't express
— two Theft cases with an unusually similar MO, two robberies both involving impersonation, etc.
Deleting the narrative collection and routing Copilot's similarity purely through structured
equality (same crime type, same district) would not fix BUG-023, it would make the *existing*
degenerate behavior official: "similar cases" would become "cases with the same crime-type
label," which is what it already effectively is today, minus the pretense of narrative nuance.

So the correct fix is **A** for the specific capability that needs it (improve narrative
generation — more MO variants, victim/offender/circumstance slot-filling, coverage for all 20
crime types instead of 8) **combined with recognizing that B is already substantially true
elsewhere** and should be reinforced, not re-litigated: HippoRAG and `criminal_profile` should
stay structured-field-driven, and nothing should be moved *onto* narrative text that isn't
already there. Concretely:

1. Extend `_MO` (`build.py:43-52`) to cover all 20 crime types, not 8 — the fallback string
   (`build.py:322`) currently guarantees zero-content narratives for 60% of crime types.
2. Add randomized slot-filling to `_narrative` (`build.py:270-272`) — victim/offender count,
   time-of-day, location descriptor, weapon/method variant, drawn from small pools per crime
   type — rather than one fixed MO clause per crime type. This does not need an LLM: it is the
   same kind of weighted-template sampling `refdata.py` and `priors.py` already do elsewhere in
   this codebase, just applied to sentence construction instead of section codes.
3. Add a narrative-diversity test analogous to `test_dataset.py:73-91` and `:94-122` — e.g.,
   assert that within a single crime type, the embedding-space pairwise similarity distribution
   has meaningful spread (not near-1.0 for most pairs), or more simply that the number of
   distinct MO clauses used is proportional to case volume rather than fixed at 8. This is the
   gap that let BUG-023 exist undetected — no test in `data/tests/` currently checks anything
   about `BriefFacts` beyond its presence.
4. Do **not** attempt to move Copilot similarity or FIR search onto structured-field-only
   matching — that would formalize the degeneracy rather than fix it, and would make the
   feature strictly less useful than it already claims to be.

---

## Summary verdict

**Is the generator sufficient to support Veritas's claimed investigative capabilities?**
Mostly yes, with one clearly broken capability and a handful of honestly-disclosed but
under-tested approximations.

The generator's hardest problems — reconstructing identity signal onto a schema with no person,
building co-offending structure that survives Louvain, keeping AML ground truth genuinely
separated from detector output, keeping the whole pipeline deterministic — are **solved well**,
with real regression tests guarding the specific historical bugs that motivated each fix
(`test_dataset.py:53-122`). This is the part of the codebase where the "is this the best
solution, not what was fast" standard is actually met: the EM contamination fix in
`fellegi_sunter.py:254-277`, the crew-weighted co-accused draw in `build.py:233-267`, and the
structural (not string-concatenated) name comparator in `fellegi_sunter.py:185-228` are all
genuine, non-obvious fixes to real statistical bugs, documented with the reasoning that led to
them.

**What's actually broken:**
1. **Narrative diversity (§12/BUG-023)** — 12 of 20 crime types produce a narrative with zero
   descriptive content beyond the crime-type label; even the 8 with real MO text produce exactly
   one MO sentence per crime type, so within-crime-type similarity search has almost no signal
   to rank on. This degrades two real user-facing features: FIR semantic search and Investigation
   Copilot's "similar past cases." **Priority: fix first** — it is both the most user-visible
   defect and the cheapest to fix (weighted slot-filling, no LLM required, same pattern already
   used elsewhere in the generator).
2. **No narrative-diversity test exists** — this is why BUG-023 survived to be found by manual
   sampling rather than CI. Any fix to (1) needs a companion test, or it will regress silently
   again.
3. ~~**The identity answer key isn't persisted post-generation (§19)**~~ **Fixed 2026-08-26**
   — `run.py` now persists it the same way the AML labels already are; see §19 for detail. Not
   yet exercised against the live 10k-case Catalyst dataset, which predates the fix.

**What's cosmetically imperfect but fine as-is:**
- Priors CSVs are self-described as "approximate pending ETL," not fully sourced NCRB figures
  (§3) — already honestly disclosed in `priors.py:1-11`.
- Geographic attractors are synthetic stand-ins for real POI data, already disclosed in
  `geo.py:12-14` — algorithmically real clustering, substantively synthetic placement.
- Case status has no age-coupling (§4) and its realized distribution isn't tested against the
  input rates (§10) — low risk, nothing currently reads this joint relationship.
- AML injected patterns are the only "dirty" examples in the dataset, so detector specificity
  against organic-but-innocent bursts is untested (§9) — worth knowing before a panel asks about
  false-positive risk, not worth fixing before a demo.
- No seasonal signal in incident timing (§16) — means Prophet's seasonality terms fit noise;
  avoid leaning on "the forecast captures a weekly pattern" in a demo, since that pattern isn't
  really there to capture.

**What's genuinely fine:**
Schema conformity, referential integrity, recurring identities, identity ambiguity,
co-offending structure, financial ground truth, graph ground truth, reproducibility, and the
AML/protected-attribute leakage separation `CLAUDE.md` claims are enforced — all verified
directly against the code in this audit, not merely against the documentation's own claims
about itself.
