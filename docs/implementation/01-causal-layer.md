# 01 — Census ground truth (D17) and the causal layer

**Status**: implemented and verified end-to-end through the live API.

## The problem

`district_socioeconomic` had **0 rows**. It is the only table the data strategy says a
real dataset "literally fills" (D17: Census 2011), there was no loader for it anywhere
in `data/`, and its sole consumer — `ml_models.causal.effects` — therefore raised
`SocioeconomicDataUnavailable` on every call.

The whole DoWhy layer was dead code. Two rows of the requirement traceability matrix
were unmet: *Socio-demographic insights* (Core) and *Causal social risk correlation*
(the flagged Differentiator).

## What was implemented

### `data/data/socioeconomic.py` — the D17 ETL

Loads the **Census of India 2011 Primary Census Abstract**, district level. Every
column is a ratio of two published Census counts; nothing is modelled, imputed or
smoothed. The raw PCA is fetched once into the gitignored `seed/ground_truth/`
staging area, and the derived 30-row table is committed to
`data/seed/derived/district_socioeconomic.csv` so it is reviewable in a diff rather
than opaque.

| Column | Definition (Census 2011) |
|---|---|
| `population` | verbatim |
| `literacy_rate` | literates / total population (**crude** rate — see below) |
| `urban_ratio` | urban households / all households |
| `poverty_index` | households under Rs 45,000 PPP annual income / all households |
| `marginal_worker_rate` | workers employed < 6 months / all workers |
| `youth_ratio` | population aged 0–29 / total population |

**Validated against published aggregates on every load.** If the source file ever
drifts from the real Census, the ETL raises rather than loading wrong ground truth:

| Check | Derived | Published |
|---|---|---|
| Karnataka population | 61,095,297 | 61,095,297 (exact) |
| Crude literacy rate | 66.53% | 66.53% |
| Work participation rate | 45.62% | 45.6% |

District spreads are authentic: literacy 43.4% (Yadgir) to 79.7% (Dakshina Kannada);
urban 14.9% (Kodagu) to 90.8% (Bengaluru Urban); Koppal highest on both poverty and
underemployment. These are the real deprivation gradients of the state.

### The causal layer, rewritten

`estimate_causal_effect` now runs the full identification pipeline — causal graph →
identify estimand → estimate (backdoor linear regression) → **refute** — and returns
`refutation_passed`, `refutation_detail`, `n_districts` and `unmeasured_confounders`
alongside the effect.

## Decisions, and why

**Crude literacy rate, not the effective one.** The widely-quoted Karnataka figure
(75.36%) is the *effective* rate, over population aged 7+. The PCA does not break out
the 0–6 population per district, so the effective rate is not derivable from it. Rather
than scale by a state-level constant — which would be fabrication dressed as precision
— we store the crude rate, which is real, consistently defined across all 30 districts,
and monotone in the quantity of interest. It is named and documented as crude.

**`unemployment` was removed from the schema.** India publishes unemployment
(PLFS/NSSO) at **state level only**. The district-level labour measure the Census does
publish is the marginal-worker rate — that is *under*employment, not unemployment. The
column is named for what it actually is. When an officer asks about unemployment, the
answer uses this measure **and says so explicitly**, rather than silently substituting
one concept for another.

**`police_per_lakh` was removed as a confounder.** BPR&D and KSP publish police strength
state-wide and rank-wise, never per district (Indiastat's district breakdown is
paywalled). So policing intensity is an **unmeasured confounder**. It is named in
`UNMEASURED_CONFOUNDERS` and reported with every estimate — "residual confounding cannot
be ruled out" — rather than adjusted for with a number we invented. This matters
especially here: over-policing → more recorded crime is the exact bias-laundering
mechanism Layer 10 exists to guard against.

**Vijayanagara (KA31) is absent, not back-filled.** It was carved out of Ballari in
2021, so Census 2011 has no record for it. Splitting Ballari's counts to manufacture a
row would be fabrication. The panel is 30 real districts.

**Refuters are seeded (`REFUTER_SEED = 42`).** DoWhy's refuters permute and resample.
Unseeded, the same question passed refutation on one turn and failed it on the next —
unacceptable for a system whose entire claim is defensibility.

**Significance is checked before refutation.** Refuting an effect already
indistinguishable from zero compares a placebo against noise, and reporting that as
"failed refutation" states something stronger and more alarming than the data supports.
The honest verdict is "not established"; "refuted" is a different claim.

## The generator defect this exposed

Loading real socioeconomic data made an existing bug visible: **only 16 of 31 districts
had any FIRs, and those 16 were near-uniform** (164–201 each) despite
`district_weights.csv` holding real KSP/NCRB weights (Bengaluru Urban = 28%).

Root cause, `data/data/generator/build.py`:
- `make_firs` picked a police station with `rng.choice(active_ps)` — **uniformly**. The
  district weights only ever decided *which districts got stations*, never how many
  FIRs each district received.
- `generate` sampled districts into a **set** (`{sample_district(rng) for _ in range(31)}`),
  which collides down to ~16 unique districts. A query about Raichur returned "no
  records" for a district that was simply never generated.

The district crime rate was therefore flat by construction — so the causal layer, the
socioeconomic risk story, the Isolation Forest district spike detector and the map
choropleth were all reading noise as their signal.

**Fixed**: every district gets stations (count scaled by its real crime weight), and
each FIR draws its district from the real weights *then* picks a station inside it.

Verified after rebuild: **31/31 districts** carry FIRs, and the generated distribution
correlates **r = 0.9985** with the real KSP/NCRB district crime weights (Bengaluru Urban
26.7% generated vs 28% real).

This is the same class of defect as the two recorded in the `CLAUDE.md` v4 changelog
(uniform-within-district placement, uniform accused sampling) — a real prior existed and
was simply not being applied at the point of sampling.

## Verified working

Through the live API (`POST /chat`, SSE), signed in as SP:

> **Q:** "Does poverty cause higher crime in Karnataka districts?"
>
> **A:** "The provided evidence does not support the claim that poverty causes higher
> crime in Karnataka districts [1]... the analysis could not be adjusted for
> police-per-lakh ratios due to a lack of district-level data, preventing the exclusion
> of residual confounding [1]."
>
> Trace: Orchestrator → Prediction Agent (causal, DoWhy backdoor on `poverty_index`,
> 5.0s) → Vector Search → CRAG evaluator (6 corroborating records) → Synthesis.
> 6 citations.

All three factors estimate and all three survive refutation. **Every confidence interval
crosses zero** — the honest result at n=30, and exactly what the responsible-AI layer
demands: the system reports "not established" instead of manufacturing a finding.

Note this is not a null result about a fake world. The outcome variable is a crime rate
built from *real* KSP/NCRB district crime weights over *real* Census population, so the
estimate relates two real quantities; only the individual FIRs realising it are synthetic.

## Tests

`data/tests/test_socioeconomic.py` (4 tests) guards the shipped ground truth: 30 real
districts, KA31 absent, population reproduces 61,095,297 exactly, literacy reproduces
66.53%, every ratio in (0,1), and cross-district variation has not collapsed (which
would silently zero out every causal estimate).

## Deferred / blocked

- **District-level police strength** — genuinely unavailable. Public sources are
  state-level; the district breakdown is behind Indiastat's paywall. Until then it
  stays an acknowledged unmeasured confounder.
- **Per-district causal effects** — impossible with Census 2011 alone: one year gives a
  30-district cross-section, not a panel. Estimating a *district-specific* effect needs
  district-year data. The API reports one state-wide effect and says so.
