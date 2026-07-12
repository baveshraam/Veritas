# Veritas — 90-second demo script

Pre-flight (before the judges arrive): `docker compose up -d`, API on :8000, `npm run dev`
on :3000, one browser tab on `http://localhost:3000`, signed out. Timings assume the
deterministic engine (no LLM latency).

| # | Do | Say | ~sec |
|---|----|-----|------|
| 1 | Click **DSP · Shivakumar Shetty** on the sign-in card | "Officers sign in by role — watch what that changes later." | 5 |
| 2 | Sweep a hand over the **Case Index** (3,000 cases, facet chips) | "Every FIR this officer is cleared to see — searchable, faceted. Nothing here is hidden behind a prompt." | 10 |
| 3 | Type `Summarise the criminal history of Ravi Gowda` → **Ask** | "Every sentence carries a numbered citation." | 10 |
| 4 | Click citation chip **[2]** in the answer | "The chip opens the exact record — including the SQL that fetched it. Nothing is asserted without a source." | 10 |
| 5 | Click **reasoning trace** above the answer | "The agent's plan is inspectable, not just logged: retrieval, evaluation, synthesis, timings." | 8 |
| 6 | Type `Who are the associates of Ravi Gowda and who runs that network?` | "The centre pane switches itself — this is the co-accusal network from the knowledge graph, ranked by PageRank." | 12 |
| 7 | Type `Trace the money trail for accounts linked to Ravi Gowda` | "Financial flows as a Sankey — rupee amounts, hop counts, every edge a graph traversal." | 10 |
| 8 | Type `What is the criminal history of Vikram Batra?` | "No such person exists. It says so — **it will not guess**. For law enforcement that refusal is the most important answer in the product." | 10 |
| 9 | Type `How many cases should Bengaluru Urban expect next month?` | "Prophet forecast, MinT-reconciled, with a confidence band — and the evidence item says 'projection, not a record'." | 10 |
| 10 | Click **PDF** (top of chat pane) | "The whole conversation exports as a signed-off case-diary PDF on KSP letterhead." | 5 |

Total ≈ 90s. If asked about RBAC: sign out, sign in as **IO · Lakshmi Rao** — the same
index collapses from 3,000 cases to her station's 22, and `/person` responses mask
victim identity below DSP rank (403 on foreign-PS FIRs).
