# P3-C Implementation Readiness Resolver

APG's beginner-facing promise remains: **说出来一个想法，得到一个结果**.
P3-C is the deterministic offline decision stage between the P3-B project
blueprint and a later P3-D materialization-preview transaction. It answers one
bounded question: whether the exact accepted planning evidence is complete and
internally compatible enough to request a project-materialization preview.

P3-C does not materialize a project, modify the P3-B blueprint, or authorize
implementation. The established transaction date is `2026-08-09`, under Change
ID
`adaptive-project-governance-p3-c-implementation-readiness-resolver-v1-20260809`.

## Canonical source bindings

The resolver consumes closed, source-complete records and binds their canonical
bytes and SHA-256 digests. A readiness result must preserve enough source data
to reparse and recompute every derived field:

- the exact canonical P3-B `ProjectBlueprint`, including its embedded P3-A
  `IntentDecisionResult` and source digest;
- the exact canonical P2 `ProjectIntake`, rendered and parsed through the P2-A
  contract rather than reconstructed from blueprint prose;
- an explicit P3-A-to-P2 evidence binding that identifies shared evidence
  references; P3-A and P2 IDs are independent and identity is never inferred;
- the original P2-C `StackCandidate` records, including every dimension
  assessment and evidence reference, so `score_stack_candidates` can be rerun;
- the complete P2-D `DomainPackRegistry`, its nested test, performance, and
  professional-Gate records, and exact applicability evidence;
- the source inputs required to recompute P2-E guided-intake compatibility.

Architecture compatibility must be supported by explicit bound evidence. Code,
label, or prose similarity is not evidence and cannot establish compatibility.
The resolver does not discover a stack, infer a missing Domain Pack, repair
source records, or upgrade a recommendation into an owner decision.

## Deterministic recomputation

Generation derives the readiness result only from the validated canonical
sources. Parsing must reparse every embedded source, verify every source digest,
rerun the resolver, and require exact equality with the supplied result. In
particular, recomputation must:

1. verify the P3-B blueprint and its embedded P3-A source;
2. verify the canonical P2 intake and explicit P3-A-to-P2 evidence binding;
3. recompute P2 owner-gate and intake evidence sufficiency;
4. rerun `score_stack_candidates` from the original candidate records and
   compare the selected architecture and all derived scoring evidence;
5. recompute guided-intake route and stack compatibility from embedded source
   inputs rather than trusting a rendered view;
6. parse the complete Domain Pack registry and applicability evidence, then
   recompute applicable pack IDs and required professional Gates;
7. derive the first applicable readiness state, authority value, and preview
   flag from those recomputed facts.

Caller-authored readiness, selected stack, applicable pack IDs, required Gate
IDs, compatibility claims, or authority fields are rejected. Canonical JSON is
the normative form: bounded UTF-8, closed fields and enums, deterministic array
order, sorted object keys, compact separators, NFC strings, and one trailing
newline. Deterministic Markdown, when provided, is non-normative and is never a
source record.

## Seven closed readiness states

The resolver uses this exact first-match order:

1. `source-binding-required`: a required canonical source, digest, or explicit
   cross-stage evidence binding is absent or does not establish identity.
2. `owner-confirmation-required`: an applicable P2 owner-bound decision remains
   open or the bound source still requires explicit owner confirmation.
3. `intake-evidence-required`: the canonical intake lacks evidence required by
   its purpose, audience, risk, or need-evidence level.
4. `stack-evidence-required`: no supported stack decision can be recomputed
   from the original bounded candidates and their evidence.
5. `stack-correction-required`: recomputed stack scoring or guided-intake
   compatibility contradicts the blueprint architecture or selected candidate.
6. `domain-evidence-required`: applicability cannot be resolved, required
   Domain Pack evidence is missing, or applicable professional Gates cannot be
   derived completely.
7. `ready-for-materialization-preview`: every preceding requirement is
   satisfied and the exact source bundle is ready only for a later P3-D
   bounded preview.

`ready_for_materialization_preview` is `true` only for
`ready-for-materialization-preview`; it is `false` for every other state.
`implementation_authority` is always `not-authorized`, including in the final
state. P3-C never changes P3-B's `ready_for_implementation=false` value.

An unready state is a valid deterministic decision, not a partial success.
Malformed records, unknown fields, duplicate keys or IDs, non-canonical bytes,
unsafe locators, secret-shaped values, unsupported values, digest drift,
derived-field tampering, or exhausted bounds fail closed before a readiness
result is accepted. There is no force, approval, fallback-success, or
caller-supplied state override.

## Side-effect and authority boundary

Importing, resolving, parsing, and rendering are standard-library-only,
in-memory operations. They perform no filesystem discovery or write, project
materialization, subprocess execution, dependency discovery or installation,
Gate selection or execution, approval creation, provider or network call,
host/runtime launch, downstream mutation, Git operation, receipt write,
deployment, publication, global promotion, pilot, or release action.

P3-D, if separately proposed, must bind the exact canonical P3-C result and
blueprint digest and must declare its downstream root, changed paths, baseline,
approval, Gates, rollback, and acceptance before any preview. Preview is not
apply. A real downstream pilot remains blocked until its own later transaction
is authorized and accepted. Public publication, global promotion, host/runtime,
provider/network, downstream pilot, deployment, and release remain independent
facts with independent evidence.

## Gates and rollback

The P3-C repository transaction is limited to its approved implementation,
test, and documentation paths. Acceptance requires first-failure-stop execution
of `controller-focused`, `controller-compile`, and `controller-full`, followed
by Doctor and independent read-only review. Documentation does not convert a
planned or passing Gate into implementation, runtime, downstream, or release
authority.

Rollback removes only the new P3-C implementation, test, and reference files
and restores the three pre-existing documentation files to their captured
pre-transaction bytes. It must preserve the dirty baseline, P3-A and P3-B
sources, ChangeRecords, receipts, historical evidence, unmanaged files, and
unrelated user changes. Rollback does not rewrite or delete historical Gate or
Doctor evidence.
