"""BrainBuddy's A2A v1.0 client surface (spec 014).

BrainBuddy is an A2A **client only** — it never serves the protocol. The package
is deliberately small and hand-written rather than built on ``a2a-sdk``: every
outbound byte has to travel through ``egress.pinned_request`` (one pinned
address, hostname TLS, no redirects, bounded body, absolute deadline), and the
distinct failure categories FR-002 and SC-009 require cannot be recovered from
an SDK that collapses 401/403/429/5xx into one error string. See research.md
Decision A for the full trade-off; ``a2a-sdk`` stays a *test-only* dependency
providing the reference runtime the client is proved against.

Modules:

* ``types``   — the protocol subset, as Pydantic models
* ``card``    — discovery, interface selection, security schemes, guarantee tier
* ``client``  — the six JSON-RPC operations, over pinned egress
* ``mapping`` — the pure projection from an A2A task onto BrainBuddy's run state
"""
