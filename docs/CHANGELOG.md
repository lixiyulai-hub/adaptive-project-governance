# Changelog

## 0.3.0 - 2026-08-08

### Added

- Accepted P2-D Domain Packs and P2-E guided-intake source contracts are now
  included in the repository-local installable package.
- The package now carries the canonical Domain Pack catalog, six frozen
  guided-intake examples, and the offline evaluator used for source-bound
  route, stack, question, Gate, and stop verification.

### Changed

- The source CLI, package `VERSION`, and package manifest report `0.3.0`.
- The deterministic builder collects only the approved catalog, P2-E example
  tree, and evaluator script; unrelated workspace fixtures and examples remain
  outside the package.

### Compatibility

- The six-command CLI and the top-level workspace `VERSION=1.0.003` remain
  unchanged at their respective boundaries.
- This is a repository-local package release. It does not publish to GitHub,
  promote global Codex/Claude/Cursor installations, reload a host, claim
  provider/runtime acceptance, or roll out to downstream projects.

### Verification

- P2-E source-bound independent acceptance passed all six route, stack, and
  stop cases, including the P2-C wrong-stack recommendation.
- P2-F requires byte-identical dual builds, exact manifest membership and
  SHA-256 verification, packaged CLI/evaluator smoke, a fresh 0.2.1 rollback
  tree, full Gates, Doctor, independent acceptance, and rollback rehearsal.

## 0.2.1 - 2026-07-23

### Added

- Canonical adapter dialect, Gate-contract, explicit-policy, receipt-state,
  automated-review progress, and evidence-bound regression identity controls.
- Bounded architecture graphs, source/generated cross-surface consistency,
  conservative affected-Gate planning, and Gate execution provenance.
- Plan-bound Gate execution authenticates the selected plan receipt,
  ChangeRecord, policy, architecture graph, consistency manifest, and Gate
  provenance before execution.
- Shared receipt-ledger inventory accepts at most 10,000 receipts, 1 MiB per
  receipt, and 64 MiB aggregate input, and rejects malformed, noncanonical,
  linked, hardlinked, unreadable, unstable, or oversized records.

### Changed

- A pre-existing invalid receipt ledger now fails plan-bound execution before
  any Gate and without a new receipt; ledger drift after execution starts
  retains exit `4` scope-violation and rollback semantics.
- The installable package includes six post-0.2.0 modules and all accepted P0
  and P1 controller and documentation updates.

### Compatibility

- The CLI remains the same six commands: `audit`, `init`, `adopt`,
  `plan-change`, `check`, and `doctor`.
- Legacy phase mode, absent optional architecture/consistency inputs, historical
  canonical receipts, Receipt 1.0, ChangeRecord, and evidence schemas retain
  their prior behavior.
- The workspace top-level `VERSION=1.0.003` remains a separate boundary.
- This stable-package release does not promote Codex, Claude, or Cursor, apply
  downstream Route B, install Grill, operate AniSpeak, change dependencies, or
  change Git state.

### Verification

- P1-E1.1 source acceptance completed with 356 controller tests run, 355
  passed, one existing conditional skip, and an independent `ACCEPT` verdict.
- Release promotion requires byte-identical dual builds, exact manifest
  membership and SHA-256 verification, packaged runtime smoke, stable-tree
  backup verification, and independent acceptance.

## 0.2.0 - 2026-07-17

### Added

- Optional change-scoped feedback loops for agentic coding, developer review,
  and external feedback.
- Deterministic iteration, elapsed-time, cost, failure, and no-progress budgets.
- Immutable feedback-loop sidecars and append-only receipt-chain validation.
- Proposed regression deltas in loop-aware check receipts without direct ledger
  writes.
- Approved recurring-defect persistence at
  `.governance/regressions/<fingerprint>.json` through `plan-change --apply`.
- Read-only doctor diagnostics for malformed, unsupported, missing-link, stale,
  inconsistent, and drifted regression records.

### Changed

- Route B adoption now renders substantive canonical documents and projects
  configured command gates into managed adapters.
- Managed adapter blocks can refresh across canonical policy revisions while
  preserving manual content and rejecting body drift.
- Command gates enforce project-relative working directories and isolated
  runtime environments.
- Governance contract paths and `AGENTS.md` changes require high-risk full
  verification.
- Canonical policy command argv survives receipt projection after per-scalar
  redaction while generic command and capture payloads remain opaque.

### Compatibility

- The CLI remains the same six commands: `audit`, `init`, `adopt`,
  `plan-change`, `check`, and `doctor`.
- Receipt 1.0 and ChangeRecord top-level schemas and golden canonical bytes are
  unchanged.
- Feedback loops and the regression ledger remain opt-in; unconfigured legacy
  projects keep their prior behavior.
- The workspace top-level `VERSION=1.0.003` is a separate workspace boundary
  and is unchanged by this package release.

### Verification

- Historical full-suite failures were reduced from `11 failures / 3 errors` to
  a green baseline before feature completion.
- Slice B source verification completed with `239` controller tests passing.
- Release artifacts require byte-identical dual builds and full manifest
  membership and SHA-256 verification before installation.

## 0.1.9 - 2026-07-16

- Unified bounded snapshot behavior across `init`, `plan-change`, `check`, and
  `doctor` for large repositories.
- Retained deterministic packaging and the repository-local six-command
  governance controller.
