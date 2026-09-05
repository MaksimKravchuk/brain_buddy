"""BrainBuddy-owned import stub for the Hermes gateway (spec 014 FR-017).

Not upstream code. The vendored Hermes A2A plugin beside this package imports
``gateway.platforms.base`` and ``gateway.config``; the real gateway is not
packaged and drags in a model runtime BrainBuddy has no business installing
(research.md Decision G). This package therefore provides *exactly* the import
surface ``plugins/platforms/a2a/adapter.py`` reaches for, and nothing else — the
same double Hermes' own plugin tests build.

Carries no provenance sha256 on purpose: it is the harness, not the runtime
under test. See ``../PROVENANCE.md``.
"""
