# Security boundaries

Only synthetic cases belong in public packs. Never include customer tickets, personal data, tokens, account identifiers, private knowledge, or credentials in the repository or a publicly distributed bundle.

Bundle SHA-256 hashes and a private local registry detect changed bytes; they do not prove who authored a pack. `maintainer` is an unverified label. Review all knowledge and source URLs before activation. The manifest's engine commit is checked against the supplied checkout at build time, but consumers must independently pin and inspect the engine they install. Keep the registry directory owned by its operating-system user with mode `0700`. Protect any LiveOps and Resolution Engine databases separately.

The prototype has no remote registry, publisher signatures, revocation, per-tenant identity, or automatic upgrades. Treat each activation as a deliberate local administrative choice. Report vulnerabilities privately to the repository owner without customer data.
