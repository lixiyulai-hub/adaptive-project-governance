# Domain Packs

P2-D adds a bounded, evidence-only Domain Pack layer above the APG governance
kernel. A pack describes a domain's applicability, test intent, measured
performance profile, and professional review evidence. It does not execute a
Gate, install a dependency, call a provider, persist intake state, or authorize
an apply.

## Contract

`project_governance.domain_pack` uses frozen dataclasses, closed enums, stable
ASCII identifiers, immutable tuples, canonical ordering, and explicit limits.
Pack versions use `major.minor.patch`; source references and evidence locators
are bounded stable codes. Applicability is an intersection of project mode,
purpose, and risk level. A pack that cannot prove applicability is omitted from
the evidence result rather than guessed.

The registry accepts a bounded set of unique packs and composable dependency
references. It rejects duplicate IDs, missing dependencies, version conflicts,
cycles, non-canonical order, and bound exhaustion. Composition is deterministic
and side-effect free.

## Professional Gates

Professional routing returns stable `professional_gate_ids`, reasons, and an
explicit `owner_gate` or `needs-evidence` status. The route contains no command,
environment, executable, approval, or GateDefinition. APG policy remains the
only authority that selects and executes actual Gates.

## Test And Performance Profiles

Test profiles state a bounded contract ID and evidence references. Performance
profiles require a measured baseline reference and preserve metric, unit,
workload, environment, comparator, threshold, tolerance, and variance policy.
No threshold is invented from a recommendation or an unmeasured estimate.

The canonical catalog at `fixtures/domain-packs/catalog-v1.json` contains the
twelve bounded domains: game, three-d, ecommerce, payments, privacy, security,
ai-content, copyright, medical, finance, industrial-control, and accessibility.

P2-D remains offline and local. UX, examples, evaluation, packaging, promotion,
runtime, public release, and downstream rollout are separate P2-E/P2-F work.
