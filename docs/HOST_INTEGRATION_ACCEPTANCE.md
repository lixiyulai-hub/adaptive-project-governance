# P4-1 Host Integration Contract and Acceptance Plan

## Status and Authority

P4-1 defines the evidence and approval contract for integrating one exact APG
build with one exact plugin host. This document is repository planning evidence
only. Its status is `planned`; it does not select a host or authorize
installation, promotion, reload, invocation, provider or network access,
target-project execution, runtime launch, deployment, publication, pilot, or
release.

Repository validation is a prerequisite for a later host transaction. It is
not host acceptance. Installed files are not reload evidence, reload is not
invocation evidence, and invocation is not target-project or runtime
acceptance.

## Transaction Boundaries

Host integration uses separate, ordered transactions. No transaction inherits
authority or acceptance from an earlier transaction.

| Transaction | Required authority | Required result |
| --- | --- | --- |
| Host selection | Owner-approved host identity and scope | One exact host product, version, installation class, and acceptance target |
| Installation or promotion | Exact source and destination manifest plus bounded write approval | Installed-byte evidence and compare-and-swap rollback evidence |
| Host reload | Current process or window binding and explicit reload approval | Pre-state, reload action, post-state, and cleanup evidence |
| APG invocation | Exact reloaded host session and bounded invocation approval | One observable APG entry-point result with redacted evidence |
| Provider or network use | Separate owner confirmation when required | Phase-scoped provider result without secret values |
| Host acceptance | Independent review of all required evidence | `ACCEPT` or `BLOCK` for host integration only |

Target-project execution, runtime verification, deployment, publication,
promotion, pilot, and release remain later independent transactions.

## Host Identity Record

A later host transaction MUST bind these facts before any action:

- stable host product identifier and exact version;
- installation class and exact installed-root locator;
- process identity and executable digest when a process is involved;
- window identity and binding evidence when reload or invocation depends on a
  visible host window;
- transaction owner, allowed actions, timestamps, and rollback owner;
- explicit acceptance target and independent reviewer identity.

Missing, stale, ambiguous, or multiply matching host identity is `BLOCK`. A
process name alone, a previous process ID, a prior window handle, or an
unrelated historical reload receipt is not sufficient current identity.

## Source and Installed-Byte Evidence

The installation transaction MUST bind one exact APG source artifact and one
exact destination manifest. Evidence MUST include:

- source version, source locator, source manifest digest, and artifact digest;
- destination installed-root locator and ownership evidence;
- every transaction-owned relative path with expected pre-state and expected
  post-state SHA-256 values;
- byte comparison between the approved source manifest and installed files;
- explicit treatment of destination-only, missing, drifted, or aliased paths;
- confirmation that unrelated host files and user data are outside the write
  set.

Source or installed-byte drift is `BLOCK`. Package version text, directory
presence, an installer exit code, or a subset hash does not prove the complete
installed state.

## Reload Evidence

Reload is a separate action after installed-byte verification. A reload record
MUST contain:

- current host process and window pre-state, captured immediately before the
  action;
- exact approved reload method and action authority;
- action start and completion timestamps;
- post-action process, window, version, and installed-byte binding;
- listener or child-process ownership when relevant;
- cleanup result and remaining-process disposition;
- a no-action result when the required process or window cannot be uniquely
  bound.

Missing current identity, an absent or ambiguous window, incomplete action,
unexpected process ownership, post-state drift, timeout, or cleanup failure is
`BLOCK`. Terminating or restarting a process without proving the bound host
post-state is not reload acceptance.

## Invocation Evidence

Invocation acceptance requires one bounded APG entry-point exercise in the
exact reloaded host session. The evidence MUST bind:

- host session identity and reload evidence reference;
- APG entry-point identifier and installed manifest digest;
- bounded, non-secret invocation input and expected observable behavior;
- start and completion timestamps, status, and redacted output evidence;
- proof that the invoked capability came from the approved installed bytes;
- cleanup and retained-state disposition.

A command listing, menu presence, skill discovery, self-report, log message, or
successful provider call alone is not invocation evidence. Successful
invocation proves only the approved host-integration criterion; it does not
prove target execution, runtime, deployment, publication, promotion, pilot, or
release acceptance.

## Provider, Network, Secrets, and Data

Provider and network use default to `false`. A host transaction that can be
accepted with an offline invocation MUST remain offline. When provider or
network access is necessary, a separate owner confirmation MUST bind provider
class, network scope, cost or quota posture, expected request count, timeout,
retry limit, evidence, and rollback or cleanup.

Secret values, tokens, account data, callback payloads, machine identifiers,
and production data MUST NOT appear in ChangeRecords, receipts, logs, prompts,
or review notes. Secret availability is not provider or host acceptance.

## First-Failure-Stop States

The transaction MUST stop without widening scope when any of these conditions
occurs:

- source manifest, installed manifest, pre-state, or post-state drift;
- missing or ambiguous host, process, window, or installation ownership;
- unapproved path, action, provider, network, cost, credential, or data use;
- incomplete reload, timeout, unexpected process ownership, or cleanup failure;
- missing, unbound, or non-observable invocation evidence;
- provider failure or exhausted bounded retry allowance;
- rollback precondition or live post-state mismatch;
- reviewer identity conflict, evidence mismatch, or blocking verdict.

Timeout and inconclusive evidence never count as pass. Failed evidence is
retained and may be followed only by a new bounded disposition.

## Acceptance Review

The reviewer MUST be distinct from the transaction executor and MUST evaluate
the exact host, source, installed bytes, reload, invocation, cleanup, and
rollback bindings. The verdict is exactly `ACCEPT` or `BLOCK`.

`ACCEPT` means only that one approved APG build was installed, reloaded, and
invoked in one approved host scope with complete evidence. Any missing binding,
phase inference, self-review, or unresolved failure is `BLOCK`.

## Rollback

Rollback is compare-and-swap bounded. It MAY restore only captured preimages or
delete paths proven absent before installation, and only while every live
transaction-owned post-state still matches. Host-state rollback MUST use the
approved host method and record final process, window, installed-byte, and
cleanup state.

Rollback MUST NOT delete unrelated host data, rewrite accounts or tokens,
change network or security settings, alter machine identity, normalize the APG
repository, or touch a target project. Any live drift is `BLOCK` and requires a
new recovery transaction.

## Excluded Historical Test Carrier

`CursorVIP_Dev` remains a completed historical test carrier. It is not a P4
host, target, pilot, or dependency and MUST NOT be read, written, started,
configured, installed into, invoked, deployed, released, or otherwise changed
by this plan or its successors unless a future owner explicitly reverses that
exclusion in a separately reviewed transaction.
