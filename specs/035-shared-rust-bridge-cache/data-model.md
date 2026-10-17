# Data and contracts
No application data or API contract changes. Cache identities, path sets, platform variants and cold-build semantics match the existing Apple consumers. Only compiler artifacts and generated bindings are retained by GitHub Actions caching.

Cache retention inherits the existing platform-managed inactivity/quota eviction unchanged. The two artifacts contain source-derived build output only; no user data or secrets. They are excluded from account export, unaffected by account purge and may survive purge. Normal delivery deletes no cache; demonstrated corrupt entries need separately scoped owner-authorized deletion and cold rebuild.
