# Implementation record

The true state of the project, maintained as work lands. Read this before the code.

`CLAUDE.md` is the *architecture* (what we intend and why). This folder is the
*implementation* (what actually exists, what's verified, what's deferred, and the
precise reason anything is blocked). Where the two disagree, this folder is right.

| Doc | Covers |
|---|---|
| [`01-causal-layer.md`](./01-causal-layer.md) | Census 2011 ground truth (D17) + the DoWhy causal layer, and the generator defect it exposed |
| [`02-llm-resilience.md`](./02-llm-resilience.md) | Gemini is live; degrading correctly when its quota isn't |
| [`03-kannada-and-voice.md`](./03-kannada-and-voice.md) | Self-hosted translation/ASR/TTS, and the Console's push-to-talk UI |
| [`STATUS.md`](./STATUS.md) | Current state at a glance: what runs, what's blocked, and on what |

## How to verify everything yourself

```bash
docker compose up -d
pip install -e data -e packages/policy -e packages/ml_models -e packages/rag_agent -e apps/api
cd data && python -m data.generator.run --firs 3000 && cd ..
pytest                     # 76 tests
```

**Run Python from a package directory, never the repo root.** The repo has a
top-level `data/` folder and the package inside it is also called `data`, so from the
root `import data` resolves to the folder as a namespace package and `from data import
SessionFocus` fails with "unknown location". `conftest.py` strips the root from
`sys.path` so pytest is unaffected, and every entrypoint `cd`s into its own package.
