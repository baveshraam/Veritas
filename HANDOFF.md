# HANDOFF.md — start here if you're new to this repo

Read this first, then [CLAUDE.md](CLAUDE.md) (design truth — architecture, why every
Catalyst-vs-third-party call was made) and [CONTEXT.md](CONTEXT.md) (operational truth —
live URLs, deploy pipeline, every measured platform gotcha). If any of the three disagree,
CONTEXT.md is newest, CLAUDE.md is deepest, this file is "how do I get moving."

## What this project is

Veritas: a conversational crime-intelligence platform for the Karnataka State Police, built
for KSP Datathon 2026 Challenge 01. Ask a question in English or Kannada, get an answer where
every claim traces to a specific record. It runs entirely on Zoho Catalyst (mandatory for the
competition) except for four things with no Catalyst equivalent — Kannada speech/translation,
the vector index, the knowledge graph, and audit-log hash-chaining — each justified in
[CLAUDE.md §2](CLAUDE.md).

The one fact that explains most of the design: the organizers' ER schema has no `Person`
table — accused rows belong to one case each with no cross-case identity. Everything about
"does this person have priors / who are their known associates / is this account linked to a
person" is *inferred* (Fellegi-Sunter record linkage, F1 0.989), not read off the schema. See
[CLAUDE.md §0](CLAUDE.md).

## Get it running locally

```bash
python -m pytest                                     # 189 tests, no DB/Docker needed
cd data && python -m data.generator.run --cases 10000 # synthetic FIRs, sqlite backend
cd apps/api && uvicorn api.main:app --reload
cd apps/web && npm run dev
```

Nothing above needs Catalyst credentials — the `sqlite` backend in `data/data/ds.py` runs the
exact same ZCQL strings the live Data Store accepts, so this is a real dev loop, not a mock.

## Live deployment

- API: `https://veritas-api-50043864344.development.catalystappsail.in`
- Console: `https://veritas-60077763394.development.catalystserverless.in/app/index.html`
- Deploying is *not* `catalyst deploy` for the API — the image has to be patched inside a
  running container and relayed through GitHub Actions because a home uplink can't beat the
  signed-upload URL's 30-minute TTL. Full recipe in [CONTEXT.md § Deploy pipeline](CONTEXT.md).
  Don't attempt a deploy without reading that section first — steps 60–66 of CONTEXT.md list
  approaches that were already tried and failed.

## Repo map

| Folder | Owns |
|---|---|
| `apps/web/` | Command Console UI (Next.js, static export via Slate) |
| `apps/api/` | FastAPI, auth, policy enforcement, transport, audit |
| `packages/rag_agent/` | LangGraph orchestration, HippoRAG/ToG retrieval, evidence chain |
| `packages/ml_models/` | Entity resolution, predictive analytics, AML, fairness audit |
| `packages/policy/` | RBAC rules (shared — enforced in both API middleware and query construction) |
| `data/` | Schema, Data Store client (`ds.py`), synthetic generator, graph, vectors, Kannada NLP |

`apps/api` is the one deployable service; the packages are imports it makes, not
microservices. Full detail: [CLAUDE.md §10](CLAUDE.md).

## Standing rules for anyone working on this

- **Cost**: target is ~₹0/month on limited Catalyst credits. Flag anything that adds a
  service, raises AppSail memory above the 2048MB floor, or adds an always-on worker *before*
  making the change, not after.
- **No LLM text-to-SQL / text-to-Cypher.** ZCQL has no bind parameters, so model-authored
  queries against the evidence store are a deliberately closed door — see
  [CLAUDE.md §5](CLAUDE.md) for why Think-on-Graph exists instead.
- **No protected attributes reach a model.** `CasteID`/`ReligionID` are stored (schema
  conformance is required) but never read by a model. Don't wire them into a feature vector.
- **Detector output never becomes generator input.** The AML training labels live in a file,
  never in the column the fraud detector scores — don't "simplify" this by writing them back.
- **Git history stays append-only in the normal course of work.** Commit and push as work
  lands; don't rewrite pushed history. (This session force-pushed once, with the repo owner's
  explicit sign-off, purely to undo two accidental junk commits — that was a one-off
  correction, not a standing workflow. See "What happened this session" below.)

## What happened this session (2026-07-23)

Two accidental commits (`chore: refresh repository metadata`, `nothing lol`) landed junk in
`README.md` (a stray trailing `#` line) and `.gitignore` on `origin/main`. The repo owner had
already run `git reset --hard` locally to undo them, but that only rewound the local branch —
`origin/main` was still two commits ahead with the broken state. Diagnosed the divergence,
confirmed with the owner, and force-pushed the clean local `main` (commit `110db34`) back over
`origin/main` to restore the correct README.

Also investigated a `claude` account showing up in the GitHub repo's Contributors sidebar.
`git log --all` across every branch (checked before any branch deletion or `gc`) shows zero
commits ever authored or committed by anything matching "Claude" or an anthropic.com address —
only `Bavesh Raam S` / `baveshraam`. So there is nothing in this repo's git history to fix.
That sidebar is GitHub's own cached contributor-stats table, which can lag behind actual
history (especially after force-pushes / history rewrites) and isn't correctable via git.
**Unresolved, not actionable from this environment** — no `gh` CLI or API token was available
to query GitHub's side further. Next step for whoever picks this up: check
**Settings → Collaborators** on the GitHub repo (rule out a literal collaborator invite, which
*is* removable) and, if the Contributors widget still shows it after a few days, it's a
GitHub Support ticket, not a code fix.

## Where to look when something breaks

- Test failures: `python -m pytest -x` locally reproduces everything except the 9 platform
  quirks in [CONTEXT.md § Measured platform constraints](CONTEXT.md) that only exist live
  (JOIN restrictions, pagination duplication, string-typed reads, etc.) — those are already
  worked around in `data/data/ds.py`, don't rediscover them.
- Deploy failures: bundle-creator logs via `GET .../appsail/{id}/deployment/{depid}/logs`,
  documented in CONTEXT.md.
- "Why does X in CLAUDE.md say Y but the code does Z": CLAUDE.md is meant to be kept current —
  if you find drift, fix the doc in the same PR as the code change, and append the delta to
  its changelog rather than rewriting past entries.
