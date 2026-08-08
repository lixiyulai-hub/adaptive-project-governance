# Adaptive Project Governance 0.3.0

Adaptive Project Governance is a repository-scoped, audit-first controller
that produces evidence, bounds changes, and preserves rollback information.

This release is the accepted 0.3.0 package. The package manifest contains the
canonical file set and is independently hashable through `MANIFEST.json`.

## Scope

This repository publishes the local APG package only. It does not claim global
installation, host/runtime activation, provider or network acceptance, or
downstream pilot acceptance. Those stages require separate authorization and
evidence.

## Contents

- `project_governance/`: controller implementation
- `scripts/`: command entry points and offline evaluators
- `docs/`: operator, policy, and pilot references
- `examples/` and `fixtures/`: bounded offline examples and catalogs

See `docs/README.md` for the operator guide and `SKILL.md` for the skill
contract.
