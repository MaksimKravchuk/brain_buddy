# The official a2a-sdk `helloworld` sample, unmodified, as a Compose fixture.
#
# It is copied from `backend/vendor/a2a_helloworld/` rather than fetched, so the
# image is built from the same bytes the provenance record hashes and the E2E
# stack has no network dependency at build time beyond PyPI.
#
# The sample hard-codes `127.0.0.1:9999`. That is why the Compose service joins
# the backend's network namespace instead of getting its own: an agent that only
# listens on loopback is only reachable from inside that namespace, and patching
# the bind address would make this a fixture of our own rather than the
# reference runtime FR-017 asks for.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/tmp/helloworld

# Pinned to the same version the backend's dev extra installs, so the runtime
# the E2E stack exercises is the one the pytest conformance suite exercises.
RUN pip install --no-cache-dir "a2a-sdk[http-server]==1.1.2" "uvicorn==0.34.0"

WORKDIR /app
COPY backend/vendor/a2a_helloworld/__main__.py backend/vendor/a2a_helloworld/agent_executor.py ./
COPY backend/vendor/a2a_helloworld/LICENSE backend/vendor/a2a_helloworld/PROVENANCE.md ./

RUN useradd --create-home --uid 10001 helloworld \
    && mkdir -p /tmp/helloworld \
    && chown -R helloworld /app /tmp/helloworld
USER helloworld

EXPOSE 9999
CMD ["python", "__main__.py"]
