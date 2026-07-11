"""Dataset manifest — the selected external datasets and how each is used.

17 files: 11 core (6 Tier-1 + 5 Tier-2) + 6 capability-unlocker files. The
strategy/coverage docs say "16" because they count 5 capability *areas* —
WorldPop + OSM land-use are one area (spatial realism) but two separate files.

Single source of truth for what gets downloaded, its role in the pipeline, its
license, and where it lands on disk. Selection & rationale live in
DATA_ACQUISITION_STRATEGY.md and FEATURE_DATA_COVERAGE.md; this is the machine
-readable form the ETL loaders and the download checklist both read.

Roles (see the strategy doc's "governing correction"):
  PRIOR        — a distribution that weights the synthetic generator.
  GROUND_TRUTH — a real layer joined in verbatim.
  ML_CORPUS    — real record-level data to pre-train/validate a model offline;
                 NEVER enters the production DB (lives under seed/, stays there).
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Role = Literal["PRIOR", "GROUND_TRUTH", "ML_CORPUS"]
SEED_DIR = Path(__file__).resolve().parent / "seed"


@dataclass(frozen=True)
class Dataset:
    id: str
    name: str
    role: Role
    feeds: str            # what table/model/collection it populates or feeds
    source: str           # canonical download URL or portal
    license: str
    local_path: str       # relative to seed/, where the ingest expects the raw file(s)
    tier: int             # 1 mandatory · 2 strong · 5 capability-unlocker


DATASETS: tuple[Dataset, ...] = (
    # ---- Tier 1: mandatory real ground truth + core priors ----
    Dataset("D01_D02", "Karnataka Crime 2024+2025 (KSP/SCRB)", "PRIOR",
            "generator: IPC/BNS section mix + per-district crime-rate weights",
            "https://ksp.karnataka.gov.in/ (SCRB annual statistics)",
            "Govt. of Karnataka open data", "priors/karnataka_crime/", 1),
    Dataset("D03", "NCRB Crime in India 2024", "PRIOR",
            "generator: charge-sheet %, conviction %, arrest-per-case distributions",
            "https://ncrb.gov.in/crime-in-india.html",
            "NCRB public report", "priors/ncrb_cii/", 1),
    Dataset("D17", "Census 2011 Karnataka + NSSO unemployment", "GROUND_TRUTH",
            "district_socioeconomic (verbatim) + DoWhy/XGBoost features",
            "https://censusindia.gov.in/ ; http://mospi.nic.in/ (NSSO)",
            "Census of India / MoSPI public", "ground_truth/census_2011/", 1),
    Dataset("D18", "GADM admin boundaries (Karnataka)", "GROUND_TRUTH",
            "PostGIS district/taluk polygons; generator geo-placement; choropleth",
            "https://gadm.org/download_country.html (IND)",
            "GADM academic/non-commercial", "ground_truth/gadm/", 1),
    Dataset("D14", "KA/Bengaluru police station locations (KGIS)", "GROUND_TRUTH",
            "officer.ps_code geo anchor; FIR->PS assignment; map PS layer",
            "https://kgis.ksrsac.in/",
            "Karnataka GIS (KGIS) public", "ground_truth/kgis_ps/", 1),
    Dataset("D22", "India Code IPC / BNS", "GROUND_TRUTH",
            "fir.ipc_sections taxonomy + RAG legal collection (offence->punishment)",
            "https://www.indiacode.nic.in/",
            "Govt. of India public", "ground_truth/india_code/", 1),
    # ---- Tier 2: strongly recommended ----
    Dataset("D07", "Indian Crimes Dataset (Kaggle, ~40K incl. Bangalore)", "ML_CORPUS",
            "narrative/MO style corpus; MO-clustering pre-train; victim/weapon priors",
            "https://www.kaggle.com/datasets (search 'Indian Crimes Dataset')",
            "CC0", "corpus/indian_crimes/", 2),
    Dataset("D05", "NCRB Summary 2001-2024 (clean CSV)", "PRIOR",
            "24-yr state time series -> Prophet+MinT seasonality/trend backbone",
            "https://ncrb.gov.in/ (compiled summary)",
            "NCRB public", "priors/ncrb_summary/", 2),
    Dataset("D04", "Bengaluru Crime 2023 (detection rates)", "PRIOR",
            "detection/closure-rate priors for fir.case_status; Bengaluru demo",
            "https://data.gov.in/ (Bengaluru City Police)",
            "data.gov.in open", "priors/bengaluru_2023/", 2),
    Dataset("D23", "Chicago Crime (geocoded + narrative + arrest)", "ML_CORPUS",
            "pre-train/validate KDE, DBSCAN/ST-DBSCAN, forecasting, embeddings",
            "https://data.cityofchicago.org/ (Crimes 2001-present)",
            "City of Chicago open data", "corpus/chicago_crime/", 2),
    Dataset("D28", "PaySim (6M txns, fraud labels)", "ML_CORPUS",
            "train GNN AML classifier; validate rule-based structuring detector",
            "https://www.kaggle.com/datasets/ealaxi/paysim1",
            "CC-BY-SA", "corpus/paysim/", 2),
    # ---- Capability-unlockers (FEATURE_DATA_COVERAGE) ----
    Dataset("U1_WORLDPOP", "WorldPop gridded population (KA, 100m)", "GROUND_TRUTH",
            "weight intra-district incident placement; distance/density geo features",
            "https://www.worldpop.org/ (India constrained 100m)",
            "CC-BY", "ground_truth/worldpop/", 5),
    Dataset("U2_OSM_LANDUSE", "OSM POI + land-use (Karnataka)", "GROUND_TRUTH",
            "attractor points (markets/bars/ATMs/transit/highways) for placement + features",
            "https://download.geofabrik.de/asia/india.html",
            "ODbL", "ground_truth/osm_landuse/", 5),
    Dataset("U3_NAMES", "Indian/Karnataka name + surname frequency corpus", "PRIOR",
            "generator names + Fellegi-Sunter collision structure (via IndicXlit)",
            "https://www.kaggle.com/datasets (Indian Names) / AI4Bharat name lists",
            "CC0 / open", "priors/indian_names/", 5),
    Dataset("U4_ILDC", "ILDC Indian legal judgments corpus", "ML_CORPUS",
            "legal RAG precedent retrieval; charge->likely-outcome grounding",
            "https://github.com/Exploration-Lab/CJPE (ILDC, ACL 2021)",
            "research/academic", "corpus/ildc/", 5),
    Dataset("U5_IBM_AML", "IBM Transactions for AML (labeled typologies)", "ML_CORPUS",
            "GNN training on labeled laundering typologies (fan-in/out, cycles)",
            "https://www.kaggle.com/datasets/ealaxi/aml (IBM synthetic)",
            "CC-BY", "corpus/ibm_aml/", 5),
    Dataset("U6_HOLIDAYS", "Indian/Karnataka gazetted holiday + festival calendar", "GROUND_TRUTH",
            "Prophet holiday regressors (festival/dry-day effects)",
            "https://data.gov.in/ ; python `holidays` package",
            "open / public domain", "ground_truth/holidays/", 5),
)


def by_role(role: Role) -> list[Dataset]:
    return [d for d in DATASETS if d.role == role]


def get(dataset_id: str) -> Dataset:
    for d in DATASETS:
        if d.id == dataset_id:
            return d
    raise KeyError(dataset_id)


def missing() -> list[Dataset]:
    """Datasets whose raw files aren't present under seed/ yet (download checklist)."""
    return [d for d in DATASETS if not (SEED_DIR / d.local_path).exists()]


if __name__ == "__main__":
    ids = [d.id for d in DATASETS]
    assert len(ids) == len(set(ids)), "duplicate dataset id"
    assert len(DATASETS) == 17
    paths = [d.local_path for d in DATASETS]
    assert len(paths) == len(set(paths)), "duplicate local_path"
    print(f"{len(DATASETS)} datasets — "
          f"{len(by_role('PRIOR'))} PRIOR, {len(by_role('GROUND_TRUTH'))} GROUND_TRUTH, "
          f"{len(by_role('ML_CORPUS'))} ML_CORPUS")
    print(f"{len(missing())} not yet downloaded")
