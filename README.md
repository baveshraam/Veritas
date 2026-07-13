# Veritas — KSP Datathon 2026, Challenge 01

Conversational crime intelligence for the Karnataka State Police. Ask in English or Kannada;
every claim in the answer traces to a specific record.

Built on Zoho Catalyst. Schema is the organizers' `Police_FIR_ER_Diagram.pdf`, verbatim.

```bash
python -m pytest                                      # 185 tests, no stack needed
cd data && python -m data.generator.run --cases 10000
cd apps/api && uvicorn api.main:app --reload
cd apps/web && npm run dev
```

**All design, architecture and rationale lives in [CLAUDE.md](./CLAUDE.md).** It is the single
source of truth for this repo — there are no other design docs, by intent.
