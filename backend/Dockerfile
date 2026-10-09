FROM python:3.14-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

COPY backend /app

RUN pip install --upgrade pip

# Spec 026 (T004): the backend wheel carries the PyO3 core bridge (``bb_core``)
# built from rust/, so it is compiled once here and the later stages install the
# wheel and never hold a compiler. The build context is the repository root, so
# ``rust`` and ``backend`` are siblings exactly as pyproject.toml expects
# (``manifest-path = "../rust/..."``).
#
# The toolchain is copied from the official image whose tag is the version in
# rust/rust-toolchain.toml (a backend test keeps the two equal). RUSTUP_TOOLCHAIN
# selects it explicitly: maturin runs cargo from /app, outside rust/, so the
# toolchain file would not apply, and this also stops rustup from fetching the
# file's extra rustfmt/clippy components during an image build.
FROM base AS core-build

RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libc6-dev && \
    rm -rf /var/lib/apt/lists/*
COPY --from=rust:1.99.0-slim /usr/local/rustup /usr/local/rustup
COPY --from=rust:1.99.0-slim /usr/local/cargo /usr/local/cargo
ENV RUSTUP_HOME=/usr/local/rustup \
    CARGO_HOME=/usr/local/cargo \
    RUSTUP_TOOLCHAIN=1.99.0 \
    PATH=/usr/local/cargo/bin:$PATH
COPY rust /rust
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /wheels /app

FROM base AS tests

COPY --from=core-build /wheels /wheels
RUN pip install --no-cache-dir "$(ls /wheels/*.whl)[dev]"

ENV BRAIN_BUDDY_ENV=test \
    BRAIN_BUDDY_DATA_DIR=/app/data \
    BRAIN_BUDDY_API_PREFIX=/api

CMD ["pytest"]

FROM base AS runtime

COPY --from=core-build /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels

ENV BRAIN_BUDDY_ENV=production \
    BRAIN_BUDDY_DATA_DIR=/app/data \
    BRAIN_BUDDY_API_PREFIX=/api

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
