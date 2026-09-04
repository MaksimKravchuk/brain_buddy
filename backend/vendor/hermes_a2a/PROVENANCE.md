# Provenance: Hermes A2A platform plugin

Vendored **unmodified** so BrainBuddy's hand-written A2A client (spec 014
FR-017, 014-SC-001) is proved against the second real third-party runtime — the
one whose quirks research.md documents as facts F1–F5 (blocking `SendMessage`,
a new task per message, a legacy card security shape, `-32050/-32051/-32052`).
`backend/tests/test_vendor_provenance.py` re-hashes every recorded file on each
run; `backend/tests/test_agent_a2a_reference_hermes.py` drives the plugin
through the harness described below.

| field | value |
|---|---|
| Upstream project | [`NousResearch/hermes-agent`](https://github.com/NousResearch/hermes-agent) |
| Upstream path | `plugins/platforms/a2a/` |
| Upstream commit | `63279301bcbdc185c1b07b98a9312eb0c862f26d` |
| Licence | MIT (`LICENSE`, copied verbatim from the repository root) |
| Vendored on | 2026-09-04 |

## Files and sha256

| file | sha256 |
|---|---|
| `plugins/platforms/a2a/__init__.py` | `c417888896bdc4114805997fe492c4027e8c0a15e091bf19a5f03f22d693f4e1` |
| `plugins/platforms/a2a/adapter.py` | `f13b690ef6fc4dc9c44118f4485962e0e511a488d94a07a5b85e710d4a9463aa` |
| `plugins/platforms/a2a/protocol.py` | `79d22629b6c95df38a3b28250b9211cba7190690a2e306e10527d049e4f3efe3` |
| `plugins/platforms/a2a/security.py` | `fd1f3ec3dc2ead5aff3604001516b3ab0b3320f0a49d77191dad758f9c92530c` |
| `LICENSE` | `821556e6336796450ab852d375117b48a4887e71d255794fd6318d99982a5ab6` |

## What is *not* upstream

`gateway/` and `run_stub.py` are **BrainBuddy-owned** and deliberately carry no
sha256 above: they are the harness, not the runtime under test. The plugin
imports `gateway.platforms.base` and `gateway.config` from the full Hermes
gateway, which is not packaged and pulls a model runtime BrainBuddy has no
business installing (research.md Decision G). `gateway/` therefore provides
exactly the import surface `adapter.py` needs — the same double Hermes' own
tests use — and `run_stub.py` runs the real, unmodified adapter over it with a
scripted reply handler and no model.

`plugins/` and `plugins/platforms/` are PEP 420 namespace packages here: their
upstream `__init__.py` files import the rest of the Hermes tree and are
deliberately not vendored.

`backend/tests/test_vendor_provenance.py` excludes those two paths **by name**,
so an accidental edit to any *plugin* file still fails the provenance test.

## Modification policy

**None** for the recorded files above — not formatting, not an import, not a
port. `backend/vendor/` is excluded from black, `ruff --fix` and mypy
(`.pre-commit-config.yaml` `exclude`, `backend/pyproject.toml` ruff
`extend-exclude`) precisely so no tool can silently invalidate this record.

To refresh: re-copy from the upstream commit, recompute the hashes with
`sha256sum`, and update the commit and the table together in one commit.
