# Screenshots — conversational architecture pass, 2026-08-26

Captured live against the deployed console
(`https://veritas-60077763394.development.catalystserverless.in/app/index.html?as=IG`)
via headless Chrome driven over CDP, per `[[veritas-console-verification]]`. This is the
first screenshot set committed to the repo — prior passes kept screenshots in the
session scratchpad only (see `docs/QA_FUNCTIONALITY_MATRIX.md`'s older entries); this
pass's mega-prompt asked for them to live here instead, as current evidence for the next
session rather than something to re-derive.

One continuous session (`?as=IG`, Shivakumar Kamath), one FIR (`100222201202600022`,
Mandya, Hurt), driven turn by turn:

| File | Turn | What it shows |
|---|---|---|
| `01-signed-in.png` | — | Console loaded and signed in via the `?as=IG` shortcut |
| `02-fir-lookup.png` | "What is the status of FIR 100222201202600022?" | Exact FIR lookup (pre-existing capability, baseline) |
| `03-case-context-what-happened.png` | "What happened?" | **New**: `CASE_CONTEXT` — answers about the open case from `SessionFocus.active_fir`, no FIR number restated |
| `04-case-people-network.png` | "Who are the key people in this case?" | **New**: `CASE_PEOPLE` — lists the case's accused, switches the centre pane to the network view (node size = real PageRank) |
| `05-similar-cases-structured.png` | "Are there similar cases?" | **New**: case-scoped `SIMILAR_CASES` — reuses the Investigation Copilot's structurally-explained similarity (crime type / IPC section / district / MO), not a fresh literal-text search |
| `06-case-locations-map.png` | "Where are those cases concentrated?" | **New**: `CASE_LOCATIONS` — tallies districts over the PREVIOUS turn's cited FIRs and renders the map pane with those specific points |
| `07-next-steps-leads.png` | "What should I investigate next?" | **New**: `NEXT_STEPS` — reuses the Copilot's own lead-generation (direct co-accused only, PageRank/community-cited) |
| `08-explain-reasoning.png` | "Why are you showing me these people?" | **New**: `EXPLAIN_REASONING` — re-describes the PREVIOUS turn's own agent trace and citations, not a fresh retrieval |

Not screenshotted this pass (curl-only, see `docs/QA_FUNCTIONALITY_MATRIX.md` RAG-29/31 and
`docs/VERITAS_HANDOFF.md`): `EVIDENCE_FOR`, `BRIEFING`, the Kannada round-trip on
`CASE_CONTEXT`, and the RBAC-boundary refusal (an IO asking about a case outside their
station). All four were verified live via curl/SSE against the same deployment; the
visual rendering of those specific turns was not additionally captured.
