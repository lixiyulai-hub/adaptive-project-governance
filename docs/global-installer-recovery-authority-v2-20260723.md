# APG Global Installer Recovery Authority V2

Change ID: `adaptive-project-governance-global-installer-recovery-authority-v2-20260723`

Risk and required phase: `high/full`

## Boundary

This change hardens only the non-packaged global installer and its isolated test
fixture. It does not modify the stable APG package, any Codex/Claude/Cursor target
or activation, Route B, Grill, P1-F/P1-E2, AniSpeak, dependencies, external
services, or Git state. It does not authorize a global promotion.

## Authority Contract

Install and recovery use the same complete argument set. Both operations require:

- the authorization path and SHA-256;
- the pre-state path and SHA-256;
- the exact change ID and owner approval ID;
- package, workspace, target, activation, alias, version, and manifest arguments;
- all three frozen activation pre-hashes.

The pre-state binds the exact approval object and scope projection, external write
scope projection, authorization path/hash, pre-state path, installer hash, stable
package identity, target tree projections, activation pre/post hashes, and alias
paths/resolution. A bare `--recover-backup` is invalid.

Recovery additionally requires that the requested backup is a non-linked direct
child of the approved backup parent. Journal paths never grant authority. Target,
activation, alias, stage, rollback, lock, and backup paths are re-derived from the
frozen inputs and transaction token. Unknown fields, unsafe tree entries, changed
lock ownership, unsupported phases, and completed transactions fail before any
recovery mutation.

## Transaction States

The installer durably creates `TRANSACTION.json` and an `initialized` STATE before
lock acquisition completes. The normal state sequence is:

1. `initialized`, `locked`, `prepared`, `staged`
2. `target-switch-<name>-before|renamed|after`
3. `activation-write-<name>-before|after`
4. `verified`, `cleanup-complete`, `commit-recorded`, `complete`

If interruption occurs after lock acquisition but before `PREINSTALL.json`,
authority-bound recovery proves that targets and activations still equal frozen
pre-state, verifies that no transaction siblings exist, and releases only the
matching lock. Later rollback uses frozen target maps and retained activation
preimages; it does not depend on the current stable tree remaining unchanged.

`commit-recorded` is the only recovery phase that may finalize the new state. It
requires both targets and all activations to match the frozen new state, cleanup
paths to be absent, aliases to resolve correctly, the stable package to match its
frozen tree, and the transaction lock to be matching or already absent. Recovery
of `complete`, `recovered`, or `rolled-back` is rejected.

## Concurrency And Success

Target switching validates the renamed rollback directory against the frozen old
tree before installing the staged tree. A change between validation and rename is
moved back intact and fails closed.

On Windows, activation compare/write/flush/post-verify occurs through one handle
that denies competing writes and deletes. The durable pre-write phase and retained
activation preimage provide recovery evidence for interruption or partial-write
disposition.

The stable package is revalidated before each staging/switch boundary and at the
final transaction boundary. Persistent `POSTINSTALL.json` reports
`PENDING_TRANSACTION_COMMIT`; it never independently claims success. The command
returns `DISK_PROMOTION_ACCEPTED` only after cleanup, durable `commit-recorded`,
verified lock release, and durable `complete`. Host state remains
`PENDING_HOST_RELOAD`.

## Recovery Invocation

Use the original install argument set and add:

```text
--recover-backup <approved-backup-root>
```

Do not omit or replace any frozen authority argument. Re-freezing or constructing
new authority for an existing transaction is not recovery and must be rejected.

## Compatibility

Install-mode arguments and successful JSON fields remain compatible. Recovery is
intentionally stricter: legacy bare recovery invocations and journals produced by
an installer with a different frozen installer hash require explicit disposition;
they are not silently upgraded or trusted.

## Rollback

The remediation preimages are:

- installer: `5002da9f69402d6151e4ffe56c36f1b0f976b94fdbcc17b6ca101ee88701abe6`
- test: `82ebfd10a870bacae43252ab7576a9e5c4f1caa160fb586bad0a8af79b5e9c39`

Restore those preimages only when the live files still equal this remediation's
recorded post-hashes. Remove this new document only when its live hash equals the
recorded post-hash. Preserve all old rejected evidence, this ChangeRecord and plan
receipt, new evidence, and any later drift. A mismatch stops rollback.

