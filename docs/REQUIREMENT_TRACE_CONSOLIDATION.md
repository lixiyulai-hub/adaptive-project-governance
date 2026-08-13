# P3-H Requirement Trace And Consolidation

P3-H turns the completed work record into one reviewable answer for an ordinary
user: the requested result is accepted, more evidence is needed, or a blocker
must be resolved. It does not ask the user to reconcile routine task output,
digest chains, or parallel-agent evidence.

## Source Chain

P3-H accepts only one exact canonical P3-G lifecycle JSON payload. It reparses
and rerenders that payload, then recomputes and binds:

```text
REQ-* -> P3-A digest -> P3-B section -> P3-F/P3-G task
      -> output artifact -> task consolidation -> phase evidence -> review
```

The controller obtains P3-A and P3-B from P3-G's embedded P3-F/P3-C source
chain. It never trusts a caller-supplied source digest, reconstructs a P3-B
section from RPD prose, or treats a task-level pass as compatibility of the
combined result.

Each trace records one stable `REQ-<three-digit>` identifier, exact P3-A and
P3-B SHA-256 digests, `P3B:<authoritative-section-id>` references, task IDs,
their transitive dependency IDs, exact output artifact references, exact P3-G
consolidation references, conflict and residual-gap links, next evidence
references, and the lifecycle's current phase evidence.

## Consolidation Result

Every P3-F/P3-G task must be claimed exactly once across the trace set. Unknown
tasks, missing task coverage, duplicate claims, artifact drift, consolidation
drift, checkpoint-chain loss, or a non-complete lifecycle return `BLOCK`.

P3-H compares every pair of P3-F task write paths. Any actual overlap requires
one explicit conflict record with the exact task pair, exact shared paths,
bounded evidence, and `resolved` state. A completed individual task does not
make an overlapping combined output safe by itself.

Residual gaps remain visible. An `open` gap returns `needs-evidence`; a
`blocking` gap returns `BLOCK`; a `closed` gap remains traceable without
blocking the result. Open and blocking gaps must name the next evidence needed.

`ACCEPT` requires all of the following:

- a complete P3-G lifecycle and intact checkpoint tip;
- exact one-to-one task coverage, artifact bindings, and consolidation bindings;
- all overlapping write paths explicitly resolved;
- no open or blocking residual gap;
- a post-`planned` lifecycle phase with its exact P3-G phase acceptance evidence;
- an `ACCEPT` consolidation review whose reviewer differs from the consolidator.

Missing review, a planned-only lifecycle phase, or an open gap is
`needs-evidence`. A blocked review, non-independent review, phase mismatch,
tampering, task overlap, unknown task, unresolved conflict, or blocking gap is
`BLOCK`.

## Canonical Safety And Boundaries

P3-H uses immutable records and closed canonical UTF-8 JSON: bounded input,
sorted unique arrays, sorted object keys, one trailing LF, duplicate-key
rejection, unknown-field rejection, unsupported-constant rejection, NFC text,
contained references, and full recomputation during parse and render.

It is standard-library-only and in memory. It performs no filesystem mutation,
subprocess, dependency, provider/network, credential, runtime, deployment,
publication, promotion, pilot, release, or Git action. A repository-validated
result cannot infer runtime, deployment, publication, pilot, or release
acceptance; those remain separate P3-G phase evidence and approval boundaries.

## User Result

`requirement_trace_user_result` exposes exactly `status`, `result`,
`next_step`, and `phase`. The full record keeps the requirement/task/artifact
trace and review evidence for operators without making a beginner relay routine
approvals or audit details.
