# `data/seed/` — reference & raw-dataset staging

Two kinds of file live here:

- **Committed reference data** (small, we author or derive it): `karnataka_districts.csv`
  (canonical district map), and the derived prior tables the generator draws from.
- **Raw external datasets** (downloaded, gitignored): under `priors/`, `ground_truth/`,
  `corpus/` — one folder per dataset `local_path` in [`../data/manifest.py`](../data/manifest.py).

## Download checklist

`python -m data.manifest` prints the 16 datasets and how many are not yet present.
Drop each download at its manifest `local_path`, then run the ETL for that role.

```
seed/
  karnataka_districts.csv        # committed — canonical KA01..KA31 map
  priors/                        # gitignored — NCRB/KSP/Bengaluru CSVs, name corpus
  ground_truth/                  # gitignored — Census, GADM, KGIS, WorldPop, OSM, holidays
  corpus/                        # gitignored — D07/Chicago/PaySim/ILDC/IBM-AML (ML only, never in prod DB)
```

**ML corpora never enter the production database** — they train/validate models
offline; only fitted artifacts ship. Keeps the "synthetic crime on real
socio-demographic ground truth" claim clean.
