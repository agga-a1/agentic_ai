# # syntax=docker/dockerfile:1.4
# FROM python:3.10-slim-bookworm

# WORKDIR /app

# COPY requirements.txt ./

# RUN apt-get update && apt-get install -y --no-install-recommends \
#     build-essential \
#     pkg-config \
#     libcairo2-dev \
#     poppler-utils \
#     graphviz \
#     tesseract-ocr \
#     && rm -rf /var/lib/apt/lists/*

# RUN python -m pip install --no-cache-dir keyring keyrings.google-artifactregistry-auth

# RUN --mount=type=secret,id=gcp_adc,target=/tmp/gcp_adc.json \
#     test -f /tmp/gcp_adc.json && \
#     export GOOGLE_APPLICATION_CREDENTIALS=/tmp/gcp_adc.json && \
#     python -m pip install --no-cache-dir \
#       --index-url=https://pypi.org/simple \
#       --extra-index-url=https://europe-west1-python.pkg.dev/vf-grp-aib-dev-hk09-sbx-alpha/pypi-repository/simple \
#       -r requirements.txt

# COPY . .

# EXPOSE 8000

# ARG RUN_ENV
# ENV RUN_ENV=${RUN_ENV}

# CMD ["sh", "-c", "uvicorn agent_api:app --host 0.0.0.0 --port ${PORT:-8000}"]

# =========================================================
# Builder stage
# =========================================================
FROM python:3.10-slim-bookworm AS builder
 
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    VENV_PATH=/opt/venv
 
WORKDIR /app
 
COPY requirements.txt ./
 
# Build dependencies only needed during install/compile
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    pkg-config \
    libcairo2-dev \
    poppler-utils \
    graphviz \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*
 
# Create isolated virtualenv for all Python deps
RUN python -m venv ${VENV_PATH}
ENV PATH="${VENV_PATH}/bin:${PATH}"
 
# Install helper packages used for Artifact Registry auth
RUN python -m pip install --no-cache-dir --upgrade pip setuptools wheel && \
    python -m pip install --no-cache-dir keyring keyrings.google-artifactregistry-auth
 
# Install application dependencies using the ADC secret
RUN --mount=type=secret,id=gcp_adc,target=/tmp/gcp_adc.json \
    test -f /tmp/gcp_adc.json && \
    export GOOGLE_APPLICATION_CREDENTIALS=/tmp/gcp_adc.json && \
    python -m pip install --no-cache-dir \
      --index-url=https://pypi.org/simple \
      --extra-index-url=https://europe-west1-python.pkg.dev/vf-grp-aib-dev-hk09-sbx-alpha/pypi-repository/simple \
      -r requirements.txt
 
# =========================================================
# Runtime stage
# =========================================================
FROM python:3.10-slim-bookworm AS runtime
 
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    VENV_PATH=/opt/venv \
    PATH="/opt/venv/bin:${PATH}"
 
WORKDIR /app
 
# Runtime-only OS packages
# NOTE:
# - libcairo2 is needed at runtime if pycairo/reportlab/svg rendering uses Cairo
# - poppler-utils, graphviz, tesseract-ocr are kept because your app appears to use them at runtime
# - libgomp1 is commonly needed by numpy/scikit/onnxruntime/torch wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    libcairo2 \
    poppler-utils \
    graphviz \
    tesseract-ocr \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*
 
# Copy only the built virtualenv from the builder stage
COPY --from=builder /opt/venv /opt/venv
 
# Copy application code
COPY . .
 
EXPOSE 8000
 
ARG RUN_ENV
ENV RUN_ENV=${RUN_ENV}
 
CMD ["sh", "-c", "uvicorn agent_api:app --host 0.0.0.0 --port ${PORT:-8000}"]