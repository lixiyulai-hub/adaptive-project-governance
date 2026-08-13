# Non-Invasive Target Project Orchestration

P3-J turns one completed idea-to-result session into a reviewable target-project
work package. It organizes requirements, components, tasks, preservation checks,
review, and orchestration acceptance without reading, running, or changing the
target project.

## Source And Redacted Target Snapshot

The source is one exact canonical P3-I payload whose state and current stage are
both `complete`. P3-J reparses it and binds canonical P3-I, P3-H, P3-G, and P3-F
SHA-256 digests. The caller supplies only a bounded redacted snapshot with a
stable logical `target_id`, existing capability baselines, component membership,
and evidence references. Physical paths, URLs, raw source, credentials, tokens,
account data, machine identifiers, provider responses, and production data are
outside the contract.

## Derived Orchestration Package

P3-J derives requirement traces, component plans, exact P3-F task lanes and
waves, capability-preservation checks, an independent-review requirement, and an
orchestration-scoped acceptance result. Component bindings must exactly partition
the complete P3-F/P3-H task set. Lanes reuse upstream task order, waves,
dependencies, read/write paths, Gates, acceptance references, and rollback
references without reinterpretation.

## Capability Preservation

Every existing target capability defaults to `preserve`. An explicit
`change-proposed` capability must bind one existing capability, one P3-H `REQ-*`
reference, and one stable change code. It remains a separately governed
downstream target transaction; P3-J never executes it. Missing preservation
evidence is `needs-evidence`; a baseline mismatch is `block`.

## States And Independent Review

The closed states are `plan-ready`, `needs-evidence`, `block`, and
`orchestration-accepted`. A reviewer must differ from the P3-J orchestrator.
Self-review, review binding mismatch, or a blocking verdict is `block`.

## Canonical Safety And Authority Boundary

Records are immutable bounded canonical UTF-8 JSON with duplicate-key and
unknown-field rejection, deterministic arrays, one trailing LF, and full
derived-state recomputation. P3-J is standard-library-only and in memory. It
performs no filesystem, subprocess, dependency, network, credential, runtime,
deployment, publication, pilot, release, or Git action. These flags are always
false:

```text
execution_authority=false
target_mutation_performed=false
execution_performed=false
```

`orchestration-accepted` is not implementation, runtime, deployment,
publication, pilot, release, or product acceptance.

## User Result

The ordinary-user projection contains only `status`, `result`, `next_step`, and
`phase`; the complete trace remains in the operator record.
