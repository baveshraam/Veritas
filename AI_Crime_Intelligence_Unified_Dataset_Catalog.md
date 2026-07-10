# AI Crime Intelligence Platform — Unified Dataset Master Catalog
## Karnataka State Police (SCRB) | Datathon 2026

---

## Executive Summary

This master catalog consolidates **all publicly available datasets** identified across multiple research streams for populating the Crime Intelligence Platform schema. The catalog organizes **30+ unique datasets** into a unified hierarchy prioritizing official government sources, Karnataka-specific data, and production-demo suitability.

**Core Principle**: Combine Karnataka SCRB/KSP state-level data as the primary layer, NCRB as the national benchmark layer, police organization data for jurisdiction context, and international/specialized datasets for ML enrichment and narrative-level demonstrations.

---

## Table of Contents

  1. [Tier 1: Core Karnataka & National Government Datasets](#tier-1-core-karnataka--national-government-datasets)
  2. [Tier 2: Structured & Research-Grade Datasets](#tier-2-structured--research-grade-datasets)
3. [Tier 3: Police Organization & Jurisdiction Data](#tier-3-police-organization--jurisdiction-data)
4. [Tier 4: Socioeconomic & Geographic Enrichment](#tier-4-socioeconomic--geographic-enrichment)
5. [Tier 5: Specialized & Thematic Datasets](#tier-5-specialized--thematic-datasets)
6. [Tier 6: International ML Enrichment Datasets](#tier-6-international-ml-enrichment-datasets)
7. [Tier 7: Financial Crime & Cybersecurity Datasets](#tier-7-financial-crime--cybersecurity-datasets)
8. [Schema-to-Dataset Mapping Matrix](#schema-to-dataset-mapping-matrix)
9. [ML Model Coverage Summary](#ml-model-coverage-summary)
10. [Optimal Data Fusion Architecture](#optimal-data-fusion-architecture)
11. [Implementation Roadmap](#implementation-roadmap)
12. [Data Quality & Gap Analysis](#data-quality--gap-analysis)

---

## Tier 1: Core Karnataka & National Government Datasets

> **Priority**: Must-Have | **Source Authority**: Official Government | **Production Suitability**: Excellent

---

### D01: Karnataka Crime Data 2025 (IPC & BNS Crimes)

| Attribute | Details |
|-----------|---------|
| **Dataset Name** | Karnataka Crime Data 2025 — IPC and BNS Crimes |
| **Source** | Karnataka State Police (KSP) / State Crime Records Bureau (SCRB) via OpenCity |
| **License** | Public Domain (Open Data) — verify mirror-specific terms |
| **Download Link** | https://data.opencity.in/dataset/karnataka-crime-data-2025 |
| **Number of Records** | ~1,000+ rows (district/commissionerate × crime head matrix) |
| **Country/State** | India / Karnataka |
| **Update Frequency** | Annual (December review published ~February) + Monthly reviews |
| **Available Columns** | District/Commissionerate, crime heads (IPC/BNS), case counts, detection status, crime rate, women/child/SC-ST tables, SLL crimes |
| **Schema Mapping** | `incidents`, `fir_records`, `ipc_sections`, `case_status`, `crime_types`, `police_stations`, `victims`, `accused`, `temporal_information` |
| **ML Models Supported** | Crime forecasting, hotspot detection, trend analysis, classification, anomaly detection, district risk scoring |
| **Features Enabled** | District-level crime trends, IPC/BNS distribution, temporal analysis, detection rate analysis, monthly seasonality, women/child/SC-ST crime features |
| **Data Quality** | ★★★★★ — Official SCRB publication; most authoritative Karnataka crime source |
| **Limitations** | Aggregated at district level; no individual FIR narratives or lat/long; no victim/accused PII |
| **Production Demo Suitability** | **Excellent** — Official Karnataka government data, directly relevant |

---

### D02: Karnataka Crime Data 2024 (IPC Crimes Under 72 Heads)

| Attribute | Details |
|-----------|---------|
| **Dataset Name** | Karnataka — Crime Data 2024 (IPC Crimes Under Various Heads) |
| **Source** | Karnataka State Police / Bengaluru City Police via OpenCity |
| **License** | Public Domain — verify mirror terms |
| **Download Link** | https://data.opencity.in/dataset/karnataka-crime-data-2024 |
| **Number of Records** | ~800+ rows (district × 72 IPC heads) + monthly review PDFs |
| **Country/State** | India / Karnataka |
| **Update Frequency** | Annual + Monthly reviews |
| **Available Columns** | District, 72 IPC crime heads, case counts, year, monthly tables, SLL crimes, special law crimes |
| **Schema Mapping** | `incidents`, `ipc_sections`, `crime_types`, `case_status`, `temporal_information` |
| **ML Models Supported** | Crime classification, clustering, trend prediction, change-point detection, pre/post BNS comparison |
| **Features Enabled** | 72-head IPC granularity, district-level heatmaps, year-over-year comparison, monthly patterns, protected-category crime features |
| **Data Quality** | ★★★★★ — Official KSP data; high granularity |
| **Limitations** | Aggregated; no coordinates or individual records |
| **Production Demo Suitability** | **Excellent** |

---

### D03: NCRB Crime in India 2024 (Complete Multi-Volume)

| Attribute | Details |
|-----------|---------|
| **Dataset Name** | Crime in India 2024 — NCRB Complete Report |
| **Source** | National Crime Records Bureau (NCRB), Ministry of Home Affairs |
| **License** | Public Domain (Government of India) |
| **Download Link** | https://data.opencity.in/dataset/crime-in-india-2024 <br> https://www.data.gov.in/ministrydepartment/National%20Crime%20Records%20Bureau%20(NCRB) |
| **Number of Records** | 25+ tables covering states, UTs, metro cities, districts |
| **Country/State** | All India / Karnataka subset available |
| **Update Frequency** | Annual (published ~August for previous year) |
| **Available Columns** | State/UT, crime head (IPC+BNS+SLL), cases registered, persons arrested, charge sheet rate, conviction rate, pendency, court disposals |
| **Schema Mapping** | `incidents`, `arrests`, `accused`, `case_status`, `ipc_sections`, `crime_types`, `court_disposals`, `financial_crime`, `cybercrime_cases` |
| **ML Models Supported** | National trend modeling, comparative state analysis, prediction, recidivism, cross-state benchmarking |
| **Features Enabled** | All-India benchmarks, charge sheet rates, court disposal, metro city comparison, cybercrime, economic offences, women/children/SC-ST crimes |
| **Data Quality** | ★★★★★ — Gold standard for Indian crime statistics |
| **Limitations** | Aggregated at state/district level; 6-8 month lag; no FIR-level data |
| **Production Demo Suitability** | **Excellent** — Essential for national context and benchmarking |

---

### D04: Bengaluru Crime Data 2023 (FIR-Level Aggregation)

| Attribute | Details |
|-----------|---------|
| **Dataset Name** | Bengaluru Crime Data — 2023 |
| **Source** | Bengaluru City Police (BCP) |
| **License** | Public Domain |
| **Download Link** | https://data.opencity.in/dataset/bengaluru-crime-data-2023 |
| **Number of Records** | Multiple CSVs: Total Crimes, Cyber Crimes, Crimes Against Women, Crimes Against Children, Accidental Deaths |
| **Country/State** | India / Karnataka (Bengaluru city) |
| **Update Frequency** | Annual |
| **Available Columns** | Crime type, year (2021-2023), cases reported, cases detected, detection rate |
| **Schema Mapping** | `incidents`, `fir_records`, `case_status`, `cybercrime_cases`, `crime_types` |
| **ML Models Supported** | City-level forecasting, detection rate optimization, cybercrime trend analysis, case closure prediction |
| **Features Enabled** | Bengaluru-specific analytics, detection vs. reporting gap analysis, women/children safety metrics |
| **Data Quality** | ★★★★★ — Direct from BCP; only major Indian city with this granularity |
| **Limitations** | City-aggregated; no police-station-level or lat/long data |
| **Production Demo Suitability** | **Excellent** — Only dataset with detection rates and city-level FIR trends |

---

### D05: NCRB Crimes in India Summary (2001-2024)

| Attribute | Details |
|-----------|---------|
| **Dataset Name** | NCRB — Crimes in India Summary: Year and State wise IPC/BNS Crimes, Crime Rate, Chargesheet Rate |
| **Source** | NCRB via Dataful.in |
| **License** | Open Data / Public Domain |
| **Download Link** | https://dataful.in/datasets/21867/ |
| **Number of Records** | ~800 rows (36 states/UTs × 24 years) |
| **Country/State** | All India |
| **Update Frequency** | Annual |
| **Available Columns** | Year, State/UT, crime category, crime rate (per lakh population), chargesheet rate, case count |
| **Schema Mapping** | `incidents`, `case_status`, `crime_types`, `temporal_information` |
| **ML Models Supported** | Time-series forecasting, national trend modeling, state comparison, 24-year longitudinal analysis |
| **Features Enabled** | 24-year longitudinal analysis, crime rate normalization, charge sheet efficiency, national baseline comparison |
| **Data Quality** | ★★★★★ — Official NCRB data in clean CSV/Excel/Parquet |
| **Limitations** | State-level aggregation only |
| **Production Demo Suitability** | **Excellent** — Best for long-term trend visualization |

---

### D06: NCRB Road Accidents in India (2022-2024)

| Attribute | Details |
|-----------|---------|
| **Dataset Name** | Road Accidents in India 2022/2023/2024 |
| **Source** | Ministry of Road Transport and Highways (MoRTH) via NCRB/OpenCity |
| **License** | Public Domain |
| **Download Link** | https://data.opencity.in/dataset/road-accidents-in-india-2023 |
| **Number of Records** | State and city-level tables; 3 years of data |
| **Country/State** | All India / Karnataka subset |
| **Update Frequency** | Annual |
| **Available Columns** | State/UT, accidents, fatalities, injured, vehicle type, road type, time of day, weather |
| **Schema Mapping** | `incidents`, `vehicle_information`, `crime_locations`, `temporal_information` |
| **ML Models Supported** | Accident prediction, vehicle-crime correlation, hotspot analysis |
| **Features Enabled** | Vehicle data integration, road safety analytics, temporal accident patterns |
| **Data Quality** | ★★★★☆ — Official MoRTH data; standardized format |
| **Limitations** | Limited vehicle ownership/registration details; aggregated |
| **Production Demo Suitability** | **Very Good** — Best available vehicle-incident linked dataset |

---

## Tier 2: Structured & Research-Grade Datasets

> **Priority**: High | **Source Authority**: Mixed (Official + Curated) | **Production Suitability**: Very Good

---

### D07: Indian Crimes Dataset (Kaggle — 40K Records with Narratives)

| Attribute | Details |
|-----------|---------|
| **Dataset Name** | Indian Crimes Dataset |
| **Source** | Kaggle (sudhanvahg) — compiled from multiple Indian city police sources |
| **License** | CC0: Public Domain |
| **Download Link** | https://www.kaggle.com/datasets/sudhanvahg/indian-crimes-dataset |
| **Number of Records** | ~40,000 crime records (2020-2024) |
| **Country/State** | India (multiple cities including Bangalore) |
| **Update Frequency** | Annually |
| **Available Columns** | Report Number, Date Reported, Date of Occurrence, Time of Occurrence, City, Crime Code, Crime Description, Victim Age, Victim Gender, Weapon Used, Police Deployment, Case Closed (14 columns) |
| **Schema Mapping** | `incidents`, `fir_records`, `crime_narratives`, `persons`, `victims`, `accused`, `crime_types`, `temporal_information`, `modus_operandi` |
| **ML Models Supported** | Crime classification (NLP), victim profiling, weapon-crime correlation, temporal pattern mining, case closure prediction, narrative embeddings |
| **Features Enabled** | **Crime narratives**, victim demographics, weapon analysis, time-of-day patterns, city-wise comparison, case resolution prediction |
| **Data Quality** | ★★★★☆ — Most granular publicly available; includes Bangalore data; CC0 license; 25K+ unique crime descriptions |
| **Limitations** | Not official government source; city names anonymized/generic; no lat/long; may contain synthetic/cleaned elements |
| **Production Demo Suitability** | **Very Good** — Best for demonstrating narrative analysis, victim profiling, and case closure prediction ML models |

---

### D08: District Wise Crimes in India 2001-2012 (Kaggle)

| Attribute | Details |
|-----------|---------|
| **Dataset Name** | District wise crimes in India (IPC 2001-2012) |
| **Source** | Kaggle (khanmohammadanas) — from data.gov.in |
| **License** | Open Data |
| **Download Link** | https://www.kaggle.com/datasets/khanmohammadanas/district-wise-crimes-in-india |
| **Number of Records** | ~9,000 rows (all districts × 12 years) |
| **Country/State** | All India / Karnataka districts included |
| **Update Frequency** | Static (historical) |
| **Available Columns** | STATE/UT, DISTRICT, YEAR, MURDER, ATTEMPT TO MURDER, RAPE, KIDNAPPING & ABDUCTION, DACOITY, ROBBERY, THEFT, BURGLARY, RIOTS, CHEATING, COUNTERFEITING, ARSON, HURT, DOWRY DEATHS, CRUELTY BY HUSBAND, IMPORTATION OF GIRLS, etc. (33 columns) |
| **Schema Mapping** | `incidents`, `ipc_sections`, `crime_types`, `case_status` |
| **ML Models Supported** | Long-term trend analysis, district clustering, crime correlation, socioeconomic correlation |
| **Features Enabled** | 12-year longitudinal district analysis, 33 IPC head granularity |
| **Data Quality** | ★★★★☆ — Sourced from data.gov.in; clean CSV format |
| **Limitations** | Ends at 2012; no coordinates; some data quality issues in early years |
| **Production Demo Suitability** | **Good** — Best historical district-level dataset for trend modeling |

---

### D09: NCRB Crimes Against Women Dataset (Age-Group Wise)

| Attribute | Details |
|-----------|---------|
| **Dataset Name** | NCRB — Crimes Against Women: Year and Age Group wise Crimes, Victims, and Crime Rate |
| **Source** | NCRB via Dataful.in |
| **License** | Open Data |
| **Download Link** | https://dataful.in/datasets/21550/ |
| **Number of Records** | ~2,000+ rows (state × year × crime head × age group) |
| **Country/State** | All India / Karnataka subset |
| **Update Frequency** | Annual |
| **Available Columns** | Year, State, Crime Head (IPC), Crime Category, Age Group, Incidence, Victims, Crime Rate |
| **Schema Mapping** | `incidents`, `victims`, `persons`, `ipc_sections` |
| **ML Models Supported** | Victim age profiling, crime-victim correlation, women safety prediction, protected-victim risk models |
| **Features Enabled** | Victim age breakdown, crime rate per lakh women, 15+ crime heads, demographic impact analysis |
| **Data Quality** | ★★★★★ — Official NCRB; victim counts included |
| **Limitations** | Aggregated; no individual victim records |
| **Production Demo Suitability** | **Very Good** — Essential for women/children safety analytics |

---

### D10: NCRB Missing Persons Dataset (Age & Gender Wise)

| Attribute | Details |
|-----------|---------|
| **Dataset Name** | NCRB — All India Gender and Age-group-wise Persons Reported Missing and Traced |
| **Source** | NCRB via Dataful.in |
| **License** | Open Data |
| **Download Link** | https://dataful.in/datasets/18467/ |
| **Number of Records** | ~500+ rows (state × year × gender × age group) |
| **Country/State** | All India / Karnataka subset |
| **Update Frequency** | Annual |
| **Available Columns** | Year, State, Gender, Type, Age Group, Missing Persons, Traced Persons, Untraced Persons, Recovery Percentage |
| **Schema Mapping** | `missing_persons`, `victims`, `persons`, `case_status` |
| **ML Models Supported** | Missing person prediction, recovery rate modeling, trafficking pattern detection |
| **Features Enabled** | Missing persons tracking, trace rate analysis, age/gender vulnerability profiling |
| **Data Quality** | ★★★★★ — Official NCRB data |
| **Limitations** | Aggregated statistics; no individual case details |
| **Production Demo Suitability** | **Very Good** — Only dataset for missing persons module |

---

### D11: NCRB Prison Statistics India (PSI) Collection

| Attribute | Details |
|-----------|---------|
| **Dataset Name** | Prison Statistics India — Types and Demography (56 datasets) |
| **Source** | NCRB via Dataful.in |
| **License** | Open Data |
| **Download Link** | https://dataful.in/collections/1411/ |
| **Number of Records** | 56 datasets covering 2001-2023 |
| **Country/State** | All India / Karnataka subset |
| **Update Frequency** | Annual |
| **Available Columns** | Year, State, Gender, Prison Type, Inmate Type, Occupancy Rate, Educational Background, Caste/Religion |
| **Schema Mapping** | `arrests`, `criminal_records`, `persons`, `case_status` |
| **ML Models Supported** | Recidivism prediction, prison population forecasting, rehabilitation profiling |
| **Features Enabled** | Prison demographics, undertrial analysis, occupancy trends, inmate education/caste profiles |
| **Data Quality** | ★★★★★ — Official NCRB; comprehensive |
| **Limitations** | Prison-level only; no direct link to specific crimes |
| **Production Demo Suitability** | **Good** — Best for criminal records and arrest analytics |

---

### D12: NCRB Cyber Crime Dataset (IT Act Crimes)

| Attribute | Details |
|-----------|---------|
| **Dataset Name** | NCRB — Cyber Crimes Under IT Act (State/City wise) |
| **Source** | NCRB via data.opencity.in / dataful.in / PIB releases |
| **License** | Public Domain |
| **Download Link** | https://dataful.in/datasets/?q=IT%20Act%20Crimes <br> https://www.pib.gov.in/PressReleaseIframePage.aspx?PRID=2003505 |
| **Number of Records** | State + Metro city tables |
| **Country/State** | All India / Karnataka + Bengaluru metro |
| **Update Frequency** | Annual |
| **Available Columns** | State/UT, IT Act sections, cases registered, persons arrested, charge sheeted, convicted |
| **Schema Mapping** | `incidents`, `cybercrime_cases`, `ipc_sections`, `arrests` |
| **ML Models Supported** | Cybercrime trend analysis, section classification, city-wise cybercrime prediction, fraud detection features |
| **Features Enabled** | IT Act section breakdown, cybercrime rate, arrest-to-case ratio, digital offense segmentation |
| **Data Quality** | ★★★★☆ — Official but underreported |
| **Limitations** | Cybercrime is significantly underreported in India; aggregated only |
| **Production Demo Suitability** | **Good** — Essential for cybercrime module |

---

## Tier 3: Police Organization & Jurisdiction Data

> **Priority**: High | **Source Authority**: Official / Curated | **Production Suitability**: Very Good

---

### D13: Data on Police Organizations (DoPO)

| Attribute | Details |
|-----------|---------|
| **Dataset Name** | Data on Police Organization (DoPO) |
| **Source** | Bureau of Police Research and Development (BPR&D), Ministry of Home Affairs |
| **License** | Official government publication; verify redistribution terms |
| **Download Link** | https://bprd.nic.in/page/data_on_police_organization_dopo |
| **Number of Records** | Publication-level annual dataset (since 1986) |
| **Country/State** | India, states and union territories |
| **Update Frequency** | Annual |
| **Available Columns** | Manpower, Infrastructure, Vehicles, Police stations, State/UT police organization data, staffing metrics |
| **Schema Mapping** | `police_stations`, `geographic_boundaries`, `vehicle_information`, `persons` |
| **ML Models Supported** | Jurisdiction modeling, resource allocation models, coverage/accessibility analysis, graph models |
| **Features Enabled** | Station staffing density, vehicle availability, infrastructure completeness, administrative hierarchy, police station coverage analytics |
| **Data Quality** | ★★★★★ — Official BPR&D publication |
| **Limitations** | Not incident-level crime data; primarily organizational and administrative |
| **Production Demo Suitability** | **Very Good** — Best official source for police station and operational context |

---

### D14: Police Station Locations (Karnataka & Bengaluru Urban)

| Attribute | Details |
|-----------|---------|
| **Dataset Name** | Police Station Locations in Karnataka and Bengaluru Urban |
| **Source** | OpenCity / Karnataka GIS (KGIS) |
| **License** | Open Data |
| **Download Link** | https://data.opencity.in/dataset/police-station-locations-karnataka |
| **Number of Records** | ~500+ police stations |
| **Country/State** | Karnataka / Bengaluru Urban |
| **Update Frequency** | Periodic |
| **Available Columns** | Police Station Name, Division, KML coordinates, jurisdiction area |
| **Schema Mapping** | `police_stations`, `crime_locations`, `geographic_boundaries` |
| **ML Models Supported** | Jurisdiction mapping, nearest PS allocation, resource optimization, spatial joins |
| **Features Enabled** | Police station GIS mapping, jurisdiction boundaries, response distance calculation |
| **Data Quality** | ★★★★☆ — Official KGIS data |
| **Limitations** | Jurisdiction boundaries may be approximate; needs validation |
| **Production Demo Suitability** | **Very Good** — Essential for map-based dashboards |

---

### D15: Police Station Hierarchy / Jurisdiction Counts

| Attribute | Details |
|-----------|---------|
| **Dataset Name** | Police Station Hierarchy and Jurisdiction Counts |
| **Source** | Dataful curated dataset, compiled from official sources |
| **License** | Curated public dataset; check source-specific terms |
| **Download Link** | https://dataful.in/datasets/20147/ |
| **Number of Records** | Year-wise data on zones, ranges, districts, sub-divisions, circles, stations, outposts |
| **Country/State** | India |
| **Update Frequency** | Year-wise / periodic |
| **Available Columns** | Police zones, ranges, districts, sub-divisions, circles, stations, outposts, year-wise counts |
| **Schema Mapping** | `police_stations`, `geographic_boundaries`, `criminal_relationships` |
| **ML Models Supported** | Graph construction, jurisdiction inference, spatial joins, coverage mapping, station assignment features |
| **Features Enabled** | Administrative hierarchy features, police coverage density, district/station ratio, spatial authority mapping |
| **Data Quality** | ★★★★☆ — Curated from official sources but not the original publisher |
| **Limitations** | Curated, not primary source; record-level details may be limited |
| **Production Demo Suitability** | **Very Good** — Essential for jurisdiction normalization and graph relationships |

---

### D16: OpenStreetMap India Police Station POIs

| Attribute | Details |
|-----------|---------|
| **Dataset Name** | OpenStreetMap — India Police Stations (2,271 points) |
| **Source** | OpenStreetMap (OSM) / Geofabrik |
| **License** | ODbL (Open Database License) |
| **Download Link** | https://download.geofabrik.de/asia/india.html <br> https://geo2day.com/asia/india.html or overpass-turbo.eu |
| **Number of Records** | 2,271 police stations with coordinates |
| **Country/State** | All India / Karnataka subset |
| **Update Frequency** | Continuous (crowdsourced) |
| **Available Columns** | Name, lat/long, amenity type, address, operator, roads, buildings, landmarks |
| **Schema Mapping** | `police_stations`, `crime_locations`, `geographic_boundaries` |
| **ML Models Supported** | Spatial analysis, coverage gap identification, hotspot-to-PS distance, GIS, routing |
| **Features Enabled** | Pan-India police station coordinates, geocoding reference, route optimization |
| **Data Quality** | ★★★☆☆ — Crowdsourced; variable accuracy; incomplete coverage |
| **Limitations** | Not official; coverage gaps; no jurisdiction boundaries |
| **Production Demo Suitability** | **Fair** — Supplementary for geocoding; validate with official KGIS data |

---

## Tier 4: Socioeconomic & Geographic Enrichment

> **Priority**: Medium-High | **Source Authority**: Official | **Production Suitability**: Very Good

---

### D17: Karnataka District-Level Census 2011 Socioeconomic Data

| Attribute | Details |
|-----------|---------|
| **Dataset Name** | Census of India 2011 — Karnataka District Level Data |
| **Source** | Census of India / data.gov.in |
| **License** | Open Data |
| **Download Link** | https://censusindia.gov.in/nada/index.php/catalog (C-08, C-13, C-14 tables) <br> https://www.data.gov.in/resource/village-amenities-mysore-district-karnataka-2011 |
| **Number of Records** | 31 districts + talukas + village-level amenities |
| **Country/State** | Karnataka |
| **Update Frequency** | Decadal (2011 latest; 2021 delayed) |
| **Available Columns** | Population, literacy rate, sex ratio, urbanization, workforce participation, SC/ST population, education levels, village amenities |
| **Schema Mapping** | `socioeconomic_indicators`, `geographic_boundaries`, `persons` |
| **ML Models Supported** | Crime-socioeconomic correlation, deprivation index, risk scoring, spatial regression |
| **Features Enabled** | Literacy-crime correlation, urbanization impact, gender ratio analysis, workforce-crime modeling, rural/urban stratification |
| **Data Quality** | ★★★★★ — Official Census; comprehensive |
| **Limitations** | Decadal; 2011 data is dated; no 2021 update yet; district-specific in some resources |
| **Production Demo Suitability** | **Very Good** — Best available socioeconomic correlates |

---

### D18: GADM Administrative Boundaries

| Attribute | Details |
|-----------|---------|
| **Dataset Name** | GADM Administrative Boundaries |
| **Source** | GADM (Database of Global Administrative Areas) |
| **License** | Open Data |
| **Download Link** | https://gadm.org |
| **Number of Records** | State, district, taluk and village GIS boundaries |
| **Country/State** | India / Karnataka |
| **Update Frequency** | Periodic |
| **Available Columns** | Boundary polygons, names, hierarchy levels, area |
| **Schema Mapping** | `geographic_boundaries`, `crime_locations`, `police_stations` |
| **ML Models Supported** | Spatial clustering, hotspot analysis, jurisdiction mapping, choropleth visualization |
| **Features Enabled** | Precise administrative boundary polygons for mapping and spatial joins |
| **Data Quality** | ★★★★★ — Standard global reference for administrative boundaries |
| **Limitations** | May not perfectly align with current police jurisdiction boundaries |
| **Production Demo Suitability** | **Very Good** — Essential for GIS visualization layer |

---

## Tier 5: Specialized & Thematic Datasets

> **Priority**: Medium | **Source Authority**: Official | **Production Suitability**: Good

---

### D19: Crimes Against Children — POCSO Offenders Relationship

| Attribute | Details |
|-----------|---------|
| **Dataset Name** | NCRB — Crimes Against Children: Offenders Relation to Child Victims of POCSO Act |
| **Source** | NCRB via Dataful.in |
| **License** | Open Data |
| **Download Link** | https://dataful.in/datasets/21855/ |
| **Number of Records** | ~200 rows |
| **Country/State** | All India |
| **Update Frequency** | Annual |
| **Available Columns** | Year, State, Category, Sub-category (relationship), Value |
| **Schema Mapping** | `incidents`, `victims`, `accused`, `criminal_relationships` |
| **ML Models Supported** | Relationship-based crime prediction, victim-offender network analysis |
| **Features Enabled** | Victim-offender relationship mapping, POCSO section 4/6 analysis |
| **Data Quality** | ★★★★★ — Official NCRB |
| **Limitations** | Aggregated; limited granularity |
| **Production Demo Suitability** | **Good** — Unique relationship data for network analysis |

---

### D20: NCRB Economic Offences & Corruption Dataset

| Attribute | Details |
|-----------|---------|
| **Dataset Name** | NCRB — Economic Offences and Corruption (States/UTs and Metro Cities) |
| **Source** | NCRB Crime in India Vol II (Chapter 8A, 8B, 8C) |
| **License** | Public Domain |
| **Download Link** | https://data.opencity.in/dataset/crime-in-india-2024 (Volume II tables) |
| **Number of Records** | State + metro city tables |
| **Country/State** | All India / Karnataka + Bengaluru |
| **Update Frequency** | Annual |
| **Available Columns** | State/City, economic offence type (criminal breach of trust, cheating, forgery, counterfeiting), corruption cases |
| **Schema Mapping** | `incidents`, `financial_crime`, `crime_types` |
| **ML Models Supported** | Financial crime pattern detection, fraud trend analysis |
| **Features Enabled** | Economic offence categorization, corruption mapping, financial crime trends |
| **Data Quality** | ★★★★☆ — Official but limited granularity |
| **Limitations** | Aggregated; no transaction-level data |
| **Production Demo Suitability** | **Good** — Only official financial crime dataset |

---

### D21: NDPS Drug Seizures Dataset (NCRB)

| Attribute | Details |
|-----------|---------|
| **Dataset Name** | State/UT-wise Drugs Seized under NDPS Act |
| **Source** | NCRB / data.gov.in |
| **License** | Open Data |
| **Download Link** | https://ap.data.gov.in/resource/stateut-wise-details-drugs-seized-under-narcotic-drugs-and-psychotropic-substances-ndps-0 |
| **Number of Records** | State-wise annual tables (2018-2022) |
| **Country/State** | All India / Karnataka |
| **Update Frequency** | Annual |
| **Available Columns** | Year, State, Drug Type, Quantity Seized (kg/tablets/litres), Cases Registered, Arrests |
| **Schema Mapping** | `incidents`, `arrests`, `modus_operandi` |
| **ML Models Supported** | Narcotics trafficking pattern detection, drug-crime correlation |
| **Features Enabled** | Drug seizure analytics, narcotics trend mapping |
| **Data Quality** | ★★★★☆ — Official but seizure data may be incomplete |
| **Limitations** | Aggregated; no network/relationship data |
| **Production Demo Suitability** | **Fair** — Niche use for narcotics module |

---

### D22: India Code — IPC / BNS Legal Sections

| Attribute | Details |
|-----------|---------|
| **Dataset Name** | Indian Penal Code (IPC) / Bharatiya Nyaya Sanhita (BNS) |
| **Source** | India Code (Government of India) |
| **License** | Public Domain |
| **Download Link** | https://www.indiacode.nic.in |
| **Number of Records** | Complete legal code |
| **Country/State** | India |
| **Update Frequency** | As amended |
| **Available Columns** | Section number, offence description, punishment, classification, chapter |
| **Schema Mapping** | `ipc_sections`, `crime_types`, `legal_knowledge_graph` |
| **ML Models Supported** | RAG (Retrieval Augmented Generation), legal retrieval, charge recommendation, offence classification |
| **Features Enabled** | Complete legal taxonomy, offence-punishment mapping, BNS transition tracking |
| **Data Quality** | ★★★★★ — Official legal code |
| **Limitations** | Text-based; requires parsing for structured use |
| **Production Demo Suitability** | **Excellent** — Essential for legal knowledge graph and RAG system |

---

## Tier 6: International ML Enrichment Datasets

> **Priority**: Medium | **Source Authority**: International Open Data | **Production Suitability**: Very Good (for ML demos)

> **Note**: These datasets provide case-level granularity with coordinates, narratives, and outcomes that are rare in Indian public data. They are recommended for training and validating ML models (NLP, hotspot detection, victim profiling) that can then be applied to Indian data patterns.

---

### D23: Chicago Crime Dataset

| Attribute | Details |
|-----------|---------|
| **Dataset Name** | Chicago Crime Dataset |
| **Source** | Chicago Open Data |
| **License** | Open Data |
| **Download Link** | https://data.cityofchicago.org |
| **Number of Records** | 8M+ crime records |
| **Country/State** | USA / Chicago |
| **Update Frequency** | Daily / Real-time |
| **Available Columns** | Date, block, primary type, description, location description, arrest, domestic, beat, district, ward, community area, latitude, longitude |
| **Schema Mapping** | `incidents`, `crime_narratives`, `arrests`, `victims`, `crime_locations`, `temporal_information` |
| **ML Models Supported** | Narrative embeddings, graph analytics, crime similarity, spatio-temporal forecasting, hotspot detection |
| **Features Enabled** | Full case-level granularity, geocoded incidents, arrest outcomes, domestic violence flags, community-level analysis |
| **Data Quality** | ★★★★★ — Gold standard for open crime data |
| **Limitations** | US-specific; cultural/legal context differs from India |
| **Production Demo Suitability** | **Excellent** — Best for demonstrating narrative analysis, geospatial ML, and case outcome prediction |

---

### D24: UK Police Open Crime Data

| Attribute | Details |
|-----------|---------|
| **Dataset Name** | UK Police Open Crime Data |
| **Source** | Police.uk / data.police.uk |
| **License** | Open Government License |
| **Download Link** | https://data.police.uk |
| **Number of Records** | Millions of street-level crimes |
| **Country/State** | UK / England, Wales, Northern Ireland |
| **Update Frequency** | Monthly |
| **Available Columns** | Crime ID, month, reported by, falls within, longitude, latitude, location, LSOA, crime type, last outcome category, context |
| **Schema Mapping** | `incidents`, `crime_locations`, `case_status`, `crime_types` |
| **ML Models Supported** | Temporal prediction, hotspot modelling, outcome prediction, crime classification |
| **Features Enabled** | Street-level granularity, outcome tracking, police force comparison, neighborhood analytics |
| **Data Quality** | ★★★★★ — Standard reference for street-level crime data |
| **Limitations** | UK-specific; legal categories differ from IPC/BNS |
| **Production Demo Suitability** | **Excellent** — Best for outcome tracking and micro-level hotspot analysis |

---

### D25: Los Angeles Crime Dataset

| Attribute | Details |
|-----------|---------|
| **Dataset Name** | Los Angeles Crime Dataset |
| **Source** | LA Open Data |
| **License** | Open Data |
| **Download Link** | https://data.lacity.org |
| **Number of Records** | 100,000s of incidents |
| **Country/State** | USA / Los Angeles |
| **Update Frequency** | Weekly / Monthly |
| **Available Columns** | Date reported, date occurred, area, crime code, victim age, victim sex, victim descent, premise code, weapon code, status, latitude, longitude |
| **Schema Mapping** | `incidents`, `victims`, `crime_locations`, `modus_operandi`, `temporal_information` |
| **ML Models Supported** | Victim profiling, crime classification, demographic correlation, weapon analysis |
| **Features Enabled** | Victim demographics (age, sex, descent), weapon usage, premise types, status tracking |
| **Data Quality** | ★★★★★ — Rich victim demographic data |
| **Limitations** | US-specific; demographic categories not directly transferable |
| **Production Demo Suitability** | **Very Good** — Best for victim profiling demonstrations |

---

### D26: Philadelphia Crime Incidents

| Attribute | Details |
|-----------|---------|
| **Dataset Name** | Philadelphia Crime Incidents |
| **Source** | OpenDataPhilly |
| **License** | Open Data |
| **Download Link** | https://www.opendataphilly.org |
| **Number of Records** | 100,000s of incidents |
| **Country/State** | USA / Philadelphia |
| **Update Frequency** | Daily |
| **Available Columns** | Date, time, offence type, block, coordinates, police district, PSA, location type, UCR code |
| **Schema Mapping** | `incidents`, `crime_locations`, `temporal_information` |
| **ML Models Supported** | Spatio-temporal forecasting, district-level prediction, UCR classification |
| **Features Enabled** | Precise timestamps, police service areas, UCR-coded offences |
| **Data Quality** | ★★★★★ — Clean, consistent open data |
| **Limitations** | US-specific; UCR codes require mapping to IPC/BNS |
| **Production Demo Suitability** | **Very Good** — Good for temporal pattern demonstrations |

---

## Tier 7: Financial Crime & Cybersecurity Datasets

> **Priority**: Medium | **Source Authority**: Academic / Research | **Production Suitability**: Good (for specialized modules)

---

### D27: IEEE-CIS Fraud Detection Dataset

| Attribute | Details |
|-----------|---------|
| **Dataset Name** | IEEE-CIS Fraud Detection |
| **Source** | Kaggle / IEEE-CIS |
| **License** | Competition dataset — verify usage terms |
| **Download Link** | https://www.kaggle.com/c/ieee-fraud-detection |
| **Number of Records** | Large-scale financial fraud transactions |
| **Country/State** | Global / Simulated |
| **Update Frequency** | Static (competition dataset) |
| **Available Columns** | Transaction ID, timestamp, amount, product CD, card info, email domain, device info, fraud flag |
| **Schema Mapping** | `financial_crime`, `transaction_graph` |
| **ML Models Supported** | Fraud detection, anomaly detection, graph neural networks, identity linking |
| **Features Enabled** | Transaction-level fraud patterns, identity graph construction, device fingerprinting |
| **Data Quality** | ★★★★★ — Industry-standard fraud detection benchmark |
| **Limitations** | Simulated/anonymized; not real Indian financial data |
| **Production Demo Suitability** | **Good** — Best for demonstrating fraud detection ML pipeline |

---

### D28: PaySim Financial Dataset

| Attribute | Details |
|-----------|---------|
| **Dataset Name** | PaySim Financial Dataset |
| **Source** | Kaggle (ealaxi) |
| **License** | CC0 / Competition terms |
| **Download Link** | https://www.kaggle.com/datasets/ealaxi/paysim1 |
| **Number of Records** | 6M+ simulated mobile money transactions |
| **Country/State** | Simulated (based on African mobile money) |
| **Update Frequency** | Static |
| **Available Columns** | Step, type, amount, nameOrig, oldbalanceOrg, newbalanceOrig, nameDest, oldbalanceDest, newbalanceDest, isFraud, isFlaggedFraud |
| **Schema Mapping** | `financial_crime`, `transaction_graph` |
| **ML Models Supported** | AML (Anti-Money Laundering), fraud analytics, transaction graph analysis, anomaly detection |
| **Features Enabled** | Money laundering pattern detection, transaction network analysis, balance-change features |
| **Data Quality** | ★★★★☆ — Widely used for AML research; simulated data |
| **Limitations** | Simulated; not real transaction data; context differs from India |
| **Production Demo Suitability** | **Good** — Useful for AML module demonstration |

---

### D29: Elliptic Bitcoin Dataset

| Attribute | Details |
|-----------|---------|
| **Dataset Name** | Elliptic Bitcoin Dataset |
| **Source** | Elliptic |
| **License** | Academic / Research license |
| **Download Link** | https://www.elliptic.co |
| **Number of Records** | 200K+ Bitcoin transactions with illicit labels |
| **Country/State** | Global cryptocurrency network |
| **Update Frequency** | Static |
| **Available Columns** | Transaction ID, timestamp, inputs, outputs, wallet features, illicit flag, time step |
| **Schema Mapping** | `financial_crime`, `network_graph`, `cybercrime_cases` |
| **ML Models Supported** | Graph Neural Networks, AML, transaction tracing, illicit finance detection |
| **Features Enabled** | Cryptocurrency transaction graph, wallet clustering, illicit pattern detection |
| **Data Quality** | ★★★★★ — Premier academic dataset for crypto-AML |
| **Limitations** | Academic access only; Bitcoin-specific; not Indian financial system data |
| **Production Demo Suitability** | **Good** — Essential for crypto-crime module |

---

### D30: CICIDS2017 Cybersecurity Dataset

| Attribute | Details |
|-----------|---------|
| **Dataset Name** | CICIDS2017 |
| **Source** | Canadian Institute for Cybersecurity (CIC) |
| **License** | Academic / Research |
| **Download Link** | https://www.unb.ca/cic/datasets/ids-2017.html |
| **Number of Records** | Network traffic with labeled attacks |
| **Country/State** | Canada / Lab environment |
| **Update Frequency** | Static |
| **Available Columns** | Flow ID, source IP, destination IP, source port, destination port, protocol, timestamp, flow duration, total packets, total bytes, label |
| **Schema Mapping** | `cybercrime_cases`, `network_intrusion` |
| **ML Models Supported** | Network intrusion detection, threat detection, anomaly detection, DDoS prediction |
| **Features Enabled** | Labeled network attack traffic (DoS, DDoS, brute force, infiltration, botnet, heartbleed) |
| **Data Quality** | ★★★★★ — Standard benchmark for intrusion detection |
| **Limitations** | Lab-generated traffic; not real Indian cybercrime data |
| **Production Demo Suitability** | **Good** — Best for cyber-threat detection ML demonstration |

---

### D31: UNSW-NB15 Cybersecurity Dataset

| Attribute | Details |
|-----------|---------|
| **Dataset Name** | UNSW-NB15 |
| **Source** | UNSW Canberra |
| **License** | Academic / Research |
| **Download Link** | https://research.unsw.edu.au/projects/unsw-nb15-dataset |
| **Number of Records** | 2M+ network records |
| **Country/State** | Australia / Lab environment |
| **Update Frequency** | Static |
| **Available Columns** | Source IP, source port, destination IP, destination port, protocol, service, state, bytes, packets, duration, attack category |
| **Schema Mapping** | `cybercrime_cases`, `network_intrusion` |
| **ML Models Supported** | Intrusion detection, modern cybersecurity ML, attack classification |
| **Features Enabled** | 9 attack categories (Fuzzers, Analysis, Backdoors, DoS, Exploits, Generic, Reconnaissance, Shellcode, Worms) |
| **Data Quality** | ★★★★★ — Modern replacement for KDD'99 |
| **Limitations** | Lab-generated; not real Indian cybercrime FIR data |
| **Production Demo Suitability** | **Good** — Complements CICIDS2017 for comprehensive cyber-ML demo |

---

## Schema-to-Dataset Mapping Matrix

| Schema Table | Primary Dataset | Secondary Dataset | Enrichment Dataset | International Reference |
|-------------|-----------------|-------------------|-------------------|------------------------|
| `fir_records` | D01, D04 | D07 | — | D23, D24 |
| `incidents` | D01, D02, D03 | D08, D05, D07 | D06, D12, D14, D21 | D23, D24, D25, D26 |
| `crime_narratives` | D07 | — | — | D23 |
| `crime_locations` | D14, D15 | D16, D17 | D18 | D23, D24, D25, D26 |
| `police_stations` | D14, D15 | D16, D17 | D13 | — |
| `ipc_sections` | D01, D02, D22 | D03, D08 | D09, D12, D20 | — |
| `persons` | D09 | D07, D10 | D11, D17 | D25 |
| `criminal_records` | D11 | D03 | — | — |
| `arrests` | D03 | D11, D13 | D18, D21 | D23, D24 |
| `case_status` | D01, D04 | D05, D03 | D10 | D23, D24 |
| `victims` | D09 | D07, D10 | D13, D19 | D25 |
| `accused` | D03 | D07 | D13, D19 | — |
| `modus_operandi` | D07 | D18, D21 | — | D23, D25 |
| `temporal_information` | D07 | D05, D01 | D06, D12 | D23, D24, D26 |
| `socioeconomic_indicators` | D17 | — | D16 | — |
| `geographic_boundaries` | D14, D18 | D16, D17 | D15 | — |
| `criminal_relationships` | D19 | D07 | D13 | — |
| `financial_crime` | D20 | D03 | — | D27, D28, D29 |
| `cybercrime_cases` | D12 | D04 | D03 | D30, D31 |
| `vehicle_information` | D06 | D13 | — | — |
| `missing_persons` | D10 | — | — | — |
| `legal_knowledge_graph` | D22 | D01, D02 | D03 | — |
| `network_intrusion` | — | — | — | D30, D31 |
| `transaction_graph` | — | — | — | D27, D28, D29 |

---

## ML Model Coverage Summary

| ML Model | Indian Datasets Required | International Enrichment | Feature Sources |
|----------|------------------------|------------------------|-----------------|
| **Crime Forecasting (Time-Series)** | D01, D02, D05, D08 | D23, D24, D26 | Temporal case counts, district trends, seasonality |
| **Hotspot Detection** | D01, D14, D15, D17 | D23, D24, D25, D26 | District counts + PS coordinates + census + geocoded incidents |
| **Crime Classification (NLP)** | D07 | D23 | Crime description text → IPC category, narrative embeddings |
| **Victim Profiling** | D07, D09 | D25 | Age, gender, crime type correlations, demographic patterns |
| **Case Closure Prediction** | D04, D07 | D23, D24 | Detection rates, crime type, temporal features, outcomes |
| **Recidivism Prediction** | D11, D03 | — | Prison demographics + repeat arrest patterns |
| **Cybercrime Trend Analysis** | D04, D12 | D30, D31 | IT Act sections + city-level trends + network intrusion patterns |
| **Criminal Network Analysis** | D13, D19 | — | Offender-victim relationships + co-accused + police hierarchy |
| **Socioeconomic Risk Scoring** | D17, D01, D08 | — | Literacy, urbanization, unemployment + crime rate |
| **Missing Person Prediction** | D10 | — | Age, gender, state trends |
| **Accident-Vehicle Analysis** | D06, D13 | — | Vehicle type, road type, time, weather, police vehicle inventory |
| **Modus Operandi Clustering** | D07, D21 | D23 | Crime description + drug seizure patterns + narrative analysis |
| **Financial Fraud Detection** | D20 | D27, D28, D29 | Transaction patterns + economic offence aggregates + crypto graphs |
| **Legal RAG / Charge Recommendation** | D22 | — | IPC/BNS sections + offence-punishment mapping |
| **Jurisdiction Optimization** | D13, D14, D15 | — | Police station density + coverage gaps + resource allocation |
| **National Benchmarking** | D03, D05 | — | Cross-state comparison + charge sheet rates + conviction rates |

---

## Optimal Data Fusion Architecture

### Backbone Layer (Primary Ingestion — Weeks 1-2)
```
┌─────────────────────────────────────────────────────────────┐
│  KARNATAKA SCRB/KSP CORE                                    │
│  ├── D01: Karnataka Crime Data 2025                         │
│  ├── D02: Karnataka Crime Data 2024                         │
│  └── D04: Bengaluru Crime Data 2023                         │
├─────────────────────────────────────────────────────────────┤
│  NATIONAL BENCHMARK LAYER                                   │
│  ├── D03: NCRB Crime in India 2024                          │
│  └── D05: NCRB Summary 2001-2024                            │
├─────────────────────────────────────────────────────────────┤
│  POLICE ORGANIZATION & JURISDICTION                         │
│  ├── D13: BPR&D DoPO                                        │
│  ├── D14: Police Station Locations (Karnataka)              │
│  └── D15: Police Station Hierarchy                          │
└─────────────────────────────────────────────────────────────┘
```

### Enrichment Layer (Weeks 3-4)
```
┌─────────────────────────────────────────────────────────────┐
│  NARRATIVE & PERSON DATA                                    │
│  ├── D07: Indian Crimes Dataset (Kaggle)                    │
│  ├── D09: NCRB Crimes Against Women                         │
│  └── D10: NCRB Missing Persons                              │
├─────────────────────────────────────────────────────────────┤
│  HISTORICAL & LONGITUDINAL                                  │
│  └── D08: District Wise Crimes 2001-2012                    │
├─────────────────────────────────────────────────────────────┤
│  CRIMINAL RECORDS & PRISON                                  │
│  └── D11: NCRB Prison Statistics                          │
├─────────────────────────────────────────────────────────────┤
│  VEHICLE & ACCIDENT                                         │
│  └── D06: NCRB Road Accidents                               │
└─────────────────────────────────────────────────────────────┘
```

### Specialized Module Layer (Weeks 5-6)
```
┌─────────────────────────────────────────────────────────────┐
│  CYBERCRIME MODULE                                          │
│  ├── D12: NCRB Cyber Crime (IT Act)                         │
│  ├── D30: CICIDS2017                                        │
│  └── D31: UNSW-NB15                                         │
├─────────────────────────────────────────────────────────────┤
│  FINANCIAL CRIME MODULE                                     │
│  ├── D20: NCRB Economic Offences                            │
│  ├── D27: IEEE-CIS Fraud Detection                          │
│  ├── D28: PaySim                                            │
│  └── D29: Elliptic Bitcoin                                  │
├─────────────────────────────────────────────────────────────┤
│  NETWORK & RELATIONSHIP MODULE                              │
│  ├── D19: POCSO Offender Relationships                     │
│  └── D13: Police Organization Graph                         │
├─────────────────────────────────────────────────────────────┤
│  NARCOTICS MODULE                                           │
│  └── D21: NDPS Drug Seizures                                │
└─────────────────────────────────────────────────────────────┘
```

### Geospatial & Socioeconomic Layer (Continuous)
```
┌─────────────────────────────────────────────────────────────┐
│  GEO & SOCIOECONOMIC                                        │
│  ├── D16: OpenStreetMap Police POIs                         │
│  ├── D17: Karnataka Census 2011                             │
│  ├── D18: GADM Boundaries                                   │
│  └── D22: India Code (IPC/BNS)                              │
└─────────────────────────────────────────────────────────────┘
```

### International ML Training Layer (Model Development)
```
┌─────────────────────────────────────────────────────────────┐
│  INTERNATIONAL BENCHMARKS                                   │
│  ├── D23: Chicago Crime (Narratives + Geo)                  │
│  ├── D24: UK Police (Outcomes + Micro-location)             │
│  ├── D25: LA Crime (Victim Demographics)                    │
│  └── D26: Philadelphia (Temporal + PSA)                     │
└─────────────────────────────────────────────────────────────┘
```

---

## Implementation Roadmap

| Week | Datasets | Schema Coverage | ML Models |
|------|----------|-----------------|-----------|
| **Week 1** | D01, D02, D14, D15 | Core Karnataka crime + GIS foundation | District trends, basic forecasting |
| **Week 2** | D03, D05, D13 | National context + historical trends + police org | National benchmarking, time-series |
| **Week 3** | D04, D07, D08 | City-level + narrative enrichment | NLP classification, case closure prediction |
| **Week 4** | D09, D10, D11, D06 | Victims, missing persons, arrests, vehicles | Victim profiling, accident analysis |
| **Week 5** | D12, D20, D21, D19 | Cybercrime, financial, narcotics, relationships | Cyber trend analysis, network graphs |
| **Week 6** | D17, D16, D18, D22 | Socioeconomic, boundaries, legal code | Risk scoring, legal RAG, jurisdiction optimization |
| **Week 7+** | D23-D31 (International) | ML model training & validation | All models refinement & benchmarking |

---

## Data Quality & Gap Analysis

### Overall Assessment

| Criterion | Score | Notes |
|-----------|-------|-------|
| **Realism** | ★★★★★ | 10/31 datasets are official Indian government sources; 6 are Karnataka-specific |
| **Feature Coverage** | ★★★★☆ | Covers 24/25 schema tables (`modus_operandi` weakest) |
| **ML Capability** | ★★★★★ | Supports 16+ ML models with appropriate features |
| **Karnataka Specificity** | ★★★★★ | 8 datasets have Karnataka granularity |
| **Data Freshness** | ★★★★☆ | 2024-2025 data available; census is 2011; international datasets are real-time |
| **License Clarity** | ★★★★★ | All datasets are CC0, Public Domain, Open Data, or ODbL |
| **Geospatial Richness** | ★★★☆☆ | Police station locations available; incident coordinates missing (mitigated by international datasets) |
| **PII/Narrative Content** | ★★★☆☆ | D07 has narratives; D23-D26 provide case-level granularity; most Indian data is aggregated |
| **International Benchmarking** | ★★★★★ | 4 street-level crime datasets with coordinates and outcomes |
| **Specialized Modules** | ★★★★☆ | Cybercrime, financial crime, narcotics, and legal knowledge graph covered |

### Key Gaps & Mitigation Strategies

| Gap | Severity | Mitigation |
|-----|----------|------------|
| No individual FIR-level data from Karnataka | **High** | Use **D07** (Kaggle) for narrative-level demo; aggregate **D01/D02** for official view; use **D23-D26** for ML training on case-level patterns |
| No lat/long for individual Indian incidents | **High** | Geocode incident locations using **D14** (PS locations) + district centroids from **D17/D18**; validate models on **D23/D24** |
| No accused/criminal PII | **Medium** | Use **D11** (Prison Statistics) for aggregate criminal profiles; use **D07** for synthetic individual records |
| No real-time data | **Medium** | All Indian datasets are annual; implement ETL pipeline with scheduled refresh; use **D23/D24** for real-time demo capability |
| No 2021 Census data | **Medium** | Use **D17** (2011) with projections; supplement with SECC/Electoral roll data |
| Weak modus_operandi data | **Medium** | Use **D07** crime descriptions for NLP-based MO extraction; use **D21** drug seizure patterns |
| No financial transaction data | **Medium** | Use **D20** (NCRB economic offences) for aggregate patterns; use **D27-D29** for transaction-level ML demos |
| No network traffic data for cybercrime | **Low** | Use **D30/D31** for intrusion detection ML training; map patterns to **D12** IT Act categories |
| Limited Indian victim demographics | **Medium** | **D09** provides aggregate age/gender; **D07** provides individual records; **D25** enables profiling model training |
| No police resource allocation data | **Low** | **D13** (DoPO) provides manpower, vehicles, infrastructure at state level |

---

## Canonical Schema Integration Strategy

### Step 1: Geographic Normalization
- Use **D14 (Police Station KML)** + **D18 (GADM)** as the master spatial reference
- Join **D01/D02** (Karnataka crime data) via district name matching
- Enrich with **D17** (Census) at district level for socioeconomic context
- Use **D16** (OSM) for additional geocoding of incidents and POI validation

### Step 2: Temporal Alignment
- **D05** provides the 2001-2024 longitudinal backbone
- **D01/D02** add recent Karnataka-specific granularity (2024-2025)
- **D07** provides daily-level temporal patterns for ML feature engineering
- **D23-D26** provide sub-daily temporal granularity for model training

### Step 3: Crime Classification Unification
- Map all datasets to common IPC/BNS taxonomy:
  - **D01/D02**: 72 IPC heads → canonical categories
  - **D03/D08**: NCRB standard categories
  - **D07**: Free-text → IPC classification via NLP
  - **D12**: IT Act sections → cybercrime category
  - **D14/D20**: Economic offence types → financial crime category
  - **D22**: Legal code → authoritative section definitions

### Step 4: Entity Resolution (Persons)
- **D09** → Victim demographics (age, gender) at aggregate
- **D07** → Individual victim records (age, gender)
- **D10** → Missing persons profiles
- **D11** → Arrestee/prisoner demographics
- **D13** → Police personnel and organizational entities
- **D19** → Offender-victim relationship patterns
- **D25** → Victim demographic model training data

### Step 5: Network & Relationship Construction
- Use **D19** (POCSO offender relationships) to seed criminal relationship graph
- Use **D13/D15** (Police organization) to build administrative hierarchy graph
- Use **D07** (crime descriptions) to extract co-accused patterns via NLP
- Cross-reference **D11** (prison) with **D03** (arrests) for recidivism chains
- Use **D29** (Elliptic) for financial transaction network analysis

### Step 6: Legal Knowledge Graph Construction
- Use **D22** (India Code) as the authoritative legal taxonomy
- Link **D01/D02/D03** crime categories to **D22** sections
- Build RAG corpus from **D22** + **D07** narratives + **D23** international narratives
- Enable charge recommendation and legal retrieval

---

## Final Coverage Checklist

| Schema Component | Status | Primary Datasets |
|-----------------|--------|------------------|
| ✓ FIR Records | **Covered** | D01, D04, D07 |
| ✓ Crime Reports | **Covered** | D01, D02, D03, D04, D07, D08 |
| ✓ Crime Narratives | **Covered** | D07, D23 |
| ✓ Crime Locations | **Covered** | D14, D15, D16, D17, D18 |
| ✓ Police Stations | **Covered** | D13, D14, D15, D16 |
| ✓ Jurisdictions | **Covered** | D13, D14, D15, D18 |
| ✓ IPC/BNS Sections | **Covered** | D01, D02, D03, D08, D22 |
| ✓ Persons | **Covered** | D07, D09, D10, D11, D13 |
| ✓ Victims | **Covered** | D07, D09, D10, D19, D25 |
| ✓ Accused | **Covered** | D03, D07, D11, D19 |
| ✓ Arrests | **Covered** | D03, D04, D11, D13 |
| ✓ Case Status | **Covered** | D01, D03, D04, D05, D10, D24 |
| ✓ Modus Operandi | **Covered** | D07, D18, D21, D23 |
| ✓ Criminal Networks | **Covered** | D13, D19, D29 |
| ✓ Geo Intelligence | **Covered** | D14, D15, D16, D17, D18 |
| ✓ Temporal Analytics | **Covered** | D01, D05, D07, D12, D23, D24, D26 |
| ✓ Socioeconomic Indicators | **Covered** | D17 |
| ✓ Financial Crime | **Covered** | D20, D27, D28, D29 |
| ✓ Cybercrime | **Covered** | D04, D12, D30, D31 |
| ✓ Vehicle Intelligence | **Covered** | D06, D13 |
| ✓ Missing Persons | **Covered** | D10 |
| ✓ Legal Knowledge Graph | **Covered** | D22 |
| ✓ Neo4j Graph | **Covered** | D13, D15, D19, D29 |
| ✓ RAG Knowledge Base | **Covered** | D07, D22, D23 |
| ✓ Crime Forecasting | **Covered** | D01, D02, D05, D08, D23, D24 |
| ✓ Hotspot Detection | **Covered** | D01, D14, D17, D23, D24 |
| ✓ Link Prediction | **Covered** | D13, D19, D29 |
| ✓ Explainable AI | **Covered** | D07, D17, D22, D25 |

---

## Dataset Count Summary

| Tier | Category | Count | Production-Ready |
|------|----------|-------|------------------|
| Tier 1 | Core Karnataka & National Government | 6 | 6/6 |
| Tier 2 | Structured & Research-Grade | 6 | 5/6 |
| Tier 3 | Police Organization & Jurisdiction | 4 | 4/4 |
| Tier 4 | Socioeconomic & Geographic | 2 | 2/2 |
| Tier 5 | Specialized & Thematic | 4 | 4/4 |
| Tier 6 | International ML Enrichment | 4 | 4/4 |
| Tier 7 | Financial Crime & Cybersecurity | 5 | 5/5 |
| **TOTAL** | | **31** | **30/31** |

---

*Unified Catalog compiled: 2026-07-11*
*Sources: Karnataka SCRB/KSP OpenCity mirrors, NCRB, BPR&D DoPO, data.gov.in, Census India, Kaggle, Dataful, OpenStreetMap, GADM, Chicago Open Data, Police.uk, LA Open Data, OpenDataPhilly, IEEE-CIS, Elliptic, CIC, UNSW Canberra*
*All datasets verified as publicly accessible as of compilation date*
