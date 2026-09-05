# Provenance: a2a-samples `helloworld` agent

Vendored **unmodified** so BrainBuddy's hand-written A2A client (spec 014
FR-017, 014-SC-001) can be proved against a real third-party runtime instead of
against a fake written by the same hand. `backend/tests/test_vendor_provenance.py`
re-hashes every file below on each run; `backend/tests/test_agent_a2a_reference_helloworld.py`
starts this sample as a subprocess and drives connect → test → preview →
dispatch against it.

| field | value |
|---|---|
| Upstream project | [`a2aproject/a2a-samples`](https://github.com/a2aproject/a2a-samples) |
| Upstream path | `samples/python/agents/helloworld/` |
| Upstream commit | `6603ba3f2c31a7ef33e70b9d8b5b5f8be42ac9a3` |
| Licence | Apache-2.0 (`LICENSE`, copied verbatim from the repository root) |
| Vendored on | 2026-09-04 |
| Runtime dependency | `a2a-sdk[http-server]==1.1.2`, in the backend **dev** extra only — never a runtime dependency (research.md Decision A). Upstream's own `requirements.txt` pins `a2a-sdk==1.1.0`; 1.1.2 is the version this repository resolves and tests against. |

## Files and sha256

| file | sha256 |
|---|---|
| `__main__.py` | `d32cadcdd9ee146258902534e70a283795051d46c89c0ca7af50bf39aee4de71` |
| `agent_executor.py` | `4ca9015d8a626fb141c619e6dd81027550b2d154eeeb993106c972d627e71ae6` |
| `LICENSE` | `cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30` |

## Modification policy

**None.** No BrainBuddy edit is permitted to any file above — not formatting, not
an import, not a port. `backend/vendor/` is excluded from black, `ruff --fix`
and mypy (`.pre-commit-config.yaml` `exclude`, `backend/pyproject.toml` ruff
`extend-exclude`) precisely so no tool can silently invalidate this record. The
sample hard-codes `127.0.0.1:9999`; the reference test works around that with a
pre-bind availability check rather than by patching the sample.

To refresh: re-copy from the upstream commit, recompute the hashes with
`sha256sum`, and update the commit and the table together in one commit.
