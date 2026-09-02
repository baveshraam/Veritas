# Veritas — Cost Breakdown

## Monthly Platform Costs (Catalyst)

| Service | Purpose | Monthly Cost |
|---------|---------|--------------|
| **AppSail** | API runtime (FastAPI, agents, policy) | ₹500–1,500 |
| **Data Store** | 37 ZCQL tables, 10k FIRs, queries | ₹1,000–2,500 |
| **Web Client Hosting** | Static console export (Slate) | ₹200–400 |
| **Cache** | Session focus, read-through | ₹100–300 |
| **File Store** | Model weights (~760MB, streamed) | ₹200–500 |
| **QuickML LLM** | GLM-4.7-Flash inference, per-call | ₹500–2,000 |
| **Cron** | veritas_refresh (6h) + audit_verify (12h) | ₹50–200 |
| | | |
| **Total Monthly** | | **₹2,550–7,400** |
| **Annual** | | **₹30,600–88,800** |

---

## One-Time Setup Costs

| Item | Cost |
|------|------|
| Data provisioning (Admin API) | ~₹0 (scripted) |
| Schema migration (27 tables + 10 vx_* tables) | ~₹0 (API-based) |
| Model weights ingestion (File Store) | ~₹500–1,000 |
| **Total One-Time** | **~₹500–1,000** |

---

## Cost Drivers (What Scales)

- **Query volume** → Data Store (`ZCQL` page reads, filters, joins)
- **LLM calls** → QuickML (one call per `/chat` turn; deterministic queries bypass it)
- **File Store** → Only if models added (currently static ~760MB)
- **Compute** → AppSail memory tier fixed at 2048MB (floor for this workload)

---

## Comparison to Alternatives

| Stack | Monthly | Notes |
|-------|---------|-------|
| **Veritas (Catalyst)** | ₹2.5–7.4k | Identity resolution in-process; all ML local |
| **PostgreSQL + PostGIS + Neo4j + pgvector + Gemini** | ₹10–25k+ | AWS/Heroku/GCP; external LLM; 4 stateful services |
| **AWS Lambda + RDS + Bedrock** | ₹8–20k+ | Cold-start latency; vector search separate tool |
| **GCP Firestore + Vertex AI** | ₹12–22k+ | No graph native; higher data egress |

---

## Notes

1. **Target**: This project launched at **~₹0/month** (Catalyst startup pricing during competition)
2. **Scale**: Costs are linear to 100k+ FIRs; identity resolution cost is fixed (batch preprocessing)
3. **Degrades gracefully**: If QuickML unavailable, 5 deterministic branches (FIR lookup, statistics, offender ranking, priors, hotspots) answer without it
4. **No vendor lock**: Graph, vectors, ML models all portable to self-hosted; only Data Store is Catalyst-specific
