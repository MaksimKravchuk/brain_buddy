# The unmodified Hermes A2A plugin, behind a scripted brain, as a Compose
# fixture.
#
# The plugin under `plugins/platforms/a2a/` is upstream Hermes byte-for-byte
# (see `backend/vendor/hermes_a2a/PROVENANCE.md`). `gateway/` and `run_stub.py`
# are the BrainBuddy-owned harness: `gateway/` provides exactly the imports the
# adapter needs, and `run_stub.py` replaces the agent brain with a deterministic
# one-line reply so the fixture needs no model and spends no provider money.
#
# The plugin depends only on the standard library, so this image installs
# nothing: whatever the E2E stack observes here is Hermes' own code paths.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    A2A_HOST=0.0.0.0 \
    A2A_PORT=9900 \
    A2A_STUB_HOME=/tmp/hermes-a2a

WORKDIR /app
COPY backend/vendor/hermes_a2a/run_stub.py ./
COPY backend/vendor/hermes_a2a/LICENSE backend/vendor/hermes_a2a/PROVENANCE.md ./
COPY backend/vendor/hermes_a2a/gateway ./gateway
COPY backend/vendor/hermes_a2a/plugins ./plugins

RUN find /app -name '__pycache__' -type d -prune -exec rm -rf {} + \
    && useradd --create-home --uid 10002 hermes \
    && mkdir -p /tmp/hermes-a2a \
    && chown -R hermes /app /tmp/hermes-a2a
USER hermes

EXPOSE 9900
# `A2A_BEARER_TOKEN` and `A2A_PUBLIC_URL` are supplied by Compose: the token
# because the adapter binds to loopback only when no token is set, and the
# public URL because the card must advertise the address the *backend* can
# reach the fixture on, which is the Compose service name and not this
# container's bind host.
CMD ["python", "run_stub.py"]
