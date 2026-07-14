# Veritas backend — Catalyst AppSail custom (OCI) runtime.
#
# The whole monorepo is the build context: apps/api imports data, policy, rag_agent
# and ml_models as local editable packages, so a per-app Dockerfile cannot see them.
#
# Catalyst only runs linux/amd64 images — build with:
#   docker build --platform linux/amd64 -t veritas-api:latest .
FROM --platform=linux/amd64 python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1

# Copy manifests first so a code-only edit doesn't re-resolve the dependency tree.
COPY data/pyproject.toml               data/pyproject.toml
COPY packages/policy/pyproject.toml    packages/policy/pyproject.toml
COPY packages/ml_models/pyproject.toml packages/ml_models/pyproject.toml
COPY packages/rag_agent/pyproject.toml packages/rag_agent/pyproject.toml
COPY apps/api/pyproject.toml           apps/api/pyproject.toml

COPY data/            data/
COPY packages/        packages/
COPY apps/api/        apps/api/

# Two isolated resolves, one index each:
#
#   step 1: torch, pinned, from the CPU index as the SOLE index.
#   step 2: everything else from PyPI as the SOLE index. constraints.txt keeps torch
#           pinned so `torch>=2.2` (data[translation]) is already satisfied by step 1
#           and pip never reaches for PyPI's CUDA build (nvidia-cudnn + triton, ~2GB,
#           on a container with no GPU).
#
# Keeping the PyTorch index out of step 2 is not cosmetic: as an --extra-index-url it
# is searched for EVERY name, not just torch, which widens the resolve for no benefit.
COPY constraints.txt constraints.txt
ENV PIP_CONSTRAINT=/app/constraints.txt

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --index-url https://download.pytorch.org/whl/cpu torch==2.6.0+cpu

# Order matters: the leaves resolve `veritas-data` etc. from the local paths above.
# Cache mount: the wheel set is ~3GB, so a failed resolve must not cost a re-download.
RUN --mount=type=cache,target=/root/.cache/pip pip install \
        "./packages/policy" \
        "./data[embeddings,translation,voice,generator]" \
        "./packages/ml_models[forecasting,risk,financial,causal,fairness]" \
        "./packages/rag_agent" \
        "./apps/api"

# Model weights are BAKED IN, not fetched at runtime.
#
# Three reasons, in order of how much they matter:
#   1. A running container that reaches out to huggingface.co is a third-party dependency at
#      request time — exactly what the competition rule is about, and exactly what "self-
#      hosted so FIR text never leaves the network" is supposed to prevent. Downloading the
#      *model* is not the same as sending it data, but it is still an egress dependency the
#      deployment does not control.
#   2. A cold AppSail container would otherwise spend its first Kannada request downloading
#      2.4GB of NLLB. That is not a slow answer, it is a timeout.
#   3. If the download fails — rate limit, network policy, a renamed repo — the failure lands
#      on an officer's query instead of on a build.
ENV VERITAS_FASTEMBED_CACHE=/opt/models/fastembed \
    HF_HOME=/opt/models/hf \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

RUN --mount=type=cache,target=/root/.cache/pip \
    HF_HUB_OFFLINE=0 TRANSFORMERS_OFFLINE=0 python - <<'PY'
import glob, os
# The retrieval embedder: every single query goes through it.
from fastembed import TextEmbedding
TextEmbedding(model_name="BAAI/bge-small-en-v1.5",
              cache_dir=os.environ["VERITAS_FASTEMBED_CACHE"])

# Kannada translation. Kept self-hosted because Catalyst Zia has no translation service at
# all — see CLAUDE.md. NLLB-200 rather than IndicTrans2 only because IndicTrans2's weights
# are gated behind a click-through, which a build cannot do.
#
# Converted to CTranslate2 int8 rather than baked as a raw fp32 checkpoint: ~2.4GB raw vs.
# ~650MB int8 — the same technique already used for Whisper below, and the single biggest
# saving available, since the deploy pipeline has a real disk quota on the pull/unpack step.
from ctranslate2.converters import TransformersConverter
TransformersConverter("facebook/nllb-200-distilled-600M").convert(
    "/opt/models/nllb-ct2", quantization="int8", force=True)

from transformers import AutoTokenizer
AutoTokenizer.from_pretrained("facebook/nllb-200-distilled-600M")

# The converter downloaded the raw fp32 checkpoint into the HF cache to convert from —
# it is dead weight now that /opt/models/nllb-ct2 exists. Only the tokenizer/config files
# above (a few MB) are needed at runtime, so drop any cached blob bigger than a tokenizer
# could plausibly be, rather than the whole repo cache (which would take the tokenizer
# with it).
for blob in glob.glob("/opt/models/hf/hub/models--facebook--nllb*/blobs/*"):
    if os.path.getsize(blob) > 100 * 1024 * 1024:
        os.remove(blob)

# ASR. Zia has no speech-to-text either. `base.en` for English, multilingual `small` for
# Kannada — both are what data.nlp.speech loads by default, so they must both be here.
# Already CTranslate2 int8 checkpoints straight from the HF hub — no conversion needed.
from faster_whisper import WhisperModel
WhisperModel("base.en", device="cpu", compute_type="int8")
WhisperModel("small", device="cpu", compute_type="int8")
PY

# AppSail injects $X_ZOHO_CATALYST_LISTEN_PORT; fall back to 8000 for local runs.
EXPOSE 8000
CMD uvicorn api.main:app --host 0.0.0.0 --port ${X_ZOHO_CATALYST_LISTEN_PORT:-8000}
