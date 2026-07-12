# Veritas backend — Catalyst AppSail custom (OCI) runtime.
#
# The whole monorepo is the build context: apps/api imports data, policy, rag_agent
# and ml_models as local editable packages, so a per-app Dockerfile cannot see them.
#
# Catalyst only runs linux/amd64 images — build with:
#   docker build --platform linux/amd64 -t veritas-api:latest .
FROM --platform=linux/amd64 python:3.11-slim

# ponytail: single stage. The wheel set (torch, prophet, xgboost) dominates the image;
# a builder stage would save tens of MB of apt packages against ~3GB of wheels.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential git \
    && rm -rf /var/lib/apt/lists/*

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
    pip install --index-url https://download.pytorch.org/whl/cpu torch==2.5.1+cpu

# Order matters: the leaves resolve `veritas-data` etc. from the local paths above.
# Cache mount: the wheel set is ~3GB, so a failed resolve must not cost a re-download.
RUN --mount=type=cache,target=/root/.cache/pip pip install \
        "./packages/policy" \
        "./data[embeddings,translation,voice,generator]" \
        "./packages/ml_models[forecasting,risk,financial,causal,fairness]" \
        "./packages/rag_agent" \
        "./apps/api"

# fastembed's ONNX cache and HF weights must land somewhere writable at runtime.
ENV VERITAS_FASTEMBED_CACHE=/tmp/fastembed \
    HF_HOME=/tmp/hf

# AppSail injects $X_ZOHO_CATALYST_LISTEN_PORT; fall back to 8000 for local runs.
EXPOSE 8000
CMD uvicorn api.main:app --host 0.0.0.0 --port ${X_ZOHO_CATALYST_LISTEN_PORT:-8000}
