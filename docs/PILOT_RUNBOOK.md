# Pilot Runbook

The Version 1 pilot validates read-only discovery, evidence-based levels, additive adoption, baseline ratcheting, configured gates, adapter drift detection, receipts, and rollback. It reduces regression risk but cannot promise zero bugs. It is not authorization for global activation, external enforcement, or a resident daemon.

## Preparation

- Confirm the target root, authorized write boundary, owner, and approval path.
- Identify native build, test, lint, type, package, release, and deployment commands; do not invent commands.
- Prepare an owner-reviewed canonical policy TOML for any G2, G3, or G4 initialization or adoption; include at least one project-native Gate.
- If the project maintains `.governance/architecture.graph.json`, review its ownership prefixes, dependency direction, Gate IDs, bounds, and rollback separately; absence is valid and preserves legacy behavior.
- If the project maintains `.governance/consistency.manifest.json`, review every declared relationship, member path, exact-byte expectation, bound, and rollback separately; absence is valid and preserves legacy behavior.
- Preserve an external receipt location for an unadopted target.
- Review existing governance files and conflicts.
- Confirm no global Codex, Claude Code, Cursor, launcher, daemon, or background configuration will change.

## Sequence

### 1. Audit

Run `audit`. It is strictly read-only and inventories architecture, contracts, commands, dependencies, release surfaces, governance files, Git state, licenses, open-source provenance, secret exposure, performance signals, and failures. It distinguishes evidence from inference and records missing evidence. For an unadopted target it must not create `.governance/`; retain the receipt in standard output or an explicit controller-owned location outside the target.

Classify each area as `Retain`, `Add`, `Decide`, `Measure`, or `Migrate`.

### 2. Use the B route for existing refactored projects

Audit the current shape, adapt policy to observed boundaries, preserve conflicts by surfacing them to `doctor`, approve only additive controls, record reproducible legacy baselines, verify adapters, and run relevant checks. Structural migration is separate: use an approved `plan-change` with impact, acceptance, rollout, telemetry, approval, and rollback. A large file alone is not migration evidence.

### 3. Preview

Preview initialization or adoption before apply. Pass the reviewed policy with `--policy-file POLICY_FILE` when required. Inspect planned files, level reasons, documents, adapters, gates, baseline treatment, approvals, and rollback. Confirm the policy does not lower the audit or embedded-policy floor or omit documents required by either authority. A G2, G3, or G4 policy with missing or empty Gates is rejected before any transaction. Owner-supplied and non-G1 embedded policies also need a command Gate for adapter projection; the controller does not invent one. Treat an empty adapter list as the Version 1 Codex default. Confirm all planned writes remain within the authorized root. Preview is not apply.

### 4. Approve and apply

`adopt` requires an approved audit receipt and project-specific approval. It applies approved additive controls, records the accepted baseline, verifies adapters, runs relevant checks, and emits a receipt. Review the receipt's policy digest, input status, Gate IDs, argument counts, planned documents, and adapters; raw argv values are intentionally absent from that summary. Do not treat `audit` as adoption approval. High and critical changes require configured approvals and explicit rollback.

### 5. Run gates

- **Fast:** scope, schema, adapter digest, secrets, configured lint/type/compile, unit, bug-reproducing, and affected contract checks.
- **Full:** fast plus broader/dependency-aware tests, integration/contract, build/package, baseline, dependency/license/security, migration, and relevant performance checks.
- **Release:** fast/full plus artifact, provenance/reproducibility, compatibility, security, performance, deployment, telemetry, staged rollout, rollback readiness, and approvals.

Record all five states: `pass`, `warn`, `fail`, `inconclusive`, `not-applicable`. Inconclusive never counts as pass.

Use `check --phase fast|full|release` for the legacy cumulative selector. For an
adopted project with one already applied canonical P1-D receipt, use the
alternative `check --plan-receipt .governance/receipts/RECEIPT.json` selector.
Never pass raw `planned_gate_ids`. Explicit phase and plan receipt are mutually
exclusive, and plan-bound execution cannot be combined with `--loop-run`.

For an adopted target, verify the canonical CLI receipt `policy_digest` matches
the SHA-256 of the canonical policy that supplied the Gates. Missing or mutated
policy authority must fail closed before Gate execution. A direct `run_check`
API call without a policy binding remains only a compatibility path for
unmanaged or internal callers; do not accept it as canonical adopted-project
evidence. Reject policy paths that traverse a symlink or reparse point or whose
opened final handle leaves the project root.

Inspect `outputs.gate_execution_evidence` in both normal and scope-violation
receipts. Confirm its exact outer fields are `schema_version`, `selection_mode`,
`phase`, `policy_sha256`, `performed`, `entry_count`, and `entries`, with schema
`1.0`, `selection_mode = "phase"` or `"plan"`, and `policy_sha256` equal to the
top-level canonical CLI `policy_digest`. Confirm one ordered entry per check and
contiguous indexes. Every entry must have exactly `check_index`, `gate_id`,
`phase`, `kind`, `required`, `status`, `reason_code`, `process_exit_code`,
`gate_contract_sha256`, `stdout_capture_sha256`, `stdout_captured_bytes`,
`stdout_observed_bytes`, `stdout_truncated`, `stderr_capture_sha256`,
`stderr_captured_bytes`, `stderr_observed_bytes`, `stderr_truncated`, and
`duration_ms`.

Accept only reason codes `process_exited`, `process_timed_out`,
`process_spawn_failed`, `command_context_invalid`, `command_missing`, and
`builtin_evaluated`. Confirm the capture digests describe the character-class
shape of bounded redacted bytes and that byte counts agree with truncation. No receipt should contain argv,
commands, stdout/stderr text, environment values, option or working-directory
values, file contents, or secrets. Gate policy itself is public authority: do
not place credentials or low-entropy secrets in command arguments or options,
because the full semantic Gate contract digest is an equality verifier. Treat the nested shape as the P1-E0
producer/parser contract; the generic Receipt loader's acceptance of an
`outputs` mapping alone is not proof that every nested evidence field was
validated.

For an opt-in feedback loop, prepare a closed `loop_run` JSON object and pass it
with `check --loop-run LOOP_RUN`. The required fields are `change_id`, `loop_id`,
`cost_units`, and `input_evidence_refs`; use `previous_receipt_ref` only to name
the exact current chain tip. Optional `progress_evidence`, when present, must
contain all four fields: `metrics: [{id, value}]`, `acceptance: [{id, status}]`,
`incidents: [id]`, and `owner_decision_code`. Use only acceptance statuses
`pass`, `fail`, `inconclusive`, or `not_applicable`, and owner codes `none`,
`continue`, `revise`, `defer`, or `stop`. Metric values must be finite numbers;
`1`/`1.0` and `0`/`-0.0` intentionally hash identically. Duplicate IDs, unknown
fields, free-form statuses or decisions, and raw prose fail before any Gate runs.
Feedback loops remain phase-selected; do not combine `--loop-run` with
`--plan-receipt`.

### 6. Review optional architecture impact evidence

If `.governance/architecture.graph.json` exists, run Doctor before relying on its
evidence. Confirm the closed `1.0` schema, 1 MiB limit, no more than 256 nodes and
1,024 edges, no more than 32 prefixes/Gate IDs per node or 32 always-on Gates,
safe project-relative prefixes, unique ownership, declared edge endpoints, and
`depends_on` direction. Doctor is read-only: repair or graph creation requires a
separate bounded project change.

For plan-change, compare each changed path with the direct nodes selected by
longest prefix, then verify `affected_node_ids` includes the complete transitive
dependent closure. Review `candidate_gate_ids`, unmapped/ambiguous paths, cycles,
unknown Gate IDs, and traversal exhaustion. Any such uncertainty must set
`fallback_full = true`. Treat that value as a conservative review signal, not as
proof that a full phase ran.

Do not use the projection to select or skip Gates. P1-A plan-change only records
impact evidence and does not execute, reorder, or waive checks. It also does not
create or update the graph, infer one from source, or generate graphs or diagrams
for downstream projects. If the graph is absent, expect no Doctor warning/failure
and no `architecture_graph` member in plan-change impact; the legacy structure
must remain exact.

### 6a. Review optional declared consistency evidence

If `.governance/consistency.manifest.json` exists, run Doctor before relying on
its evidence. Confirm the closed `1.0` schema and review each relationship ID,
kind, comparison, and member. `source_generated` must declare one source and at
least one generated path; `cross_surface` members are symmetric. Version 1
supports only `exact_bytes`.

Confirm the manifest is at most 1 MiB and declares at most 128 relationships, 16
total members per relationship, 512 globally unique member paths, and 256
Unicode characters per path. Each member must be a normal root-contained regular
file no larger than 8 MiB, and one evaluation must remain within 64 MiB of
aggregate declared member bytes. Stop on path aliases, duplicates, symlinks or
symlinked ancestors, governance-evidence paths, missing members, unsafe paths, or
exhausted bounds. Doctor is read-only: authoring or repairing a manifest or
member requires a separate bounded project change.

For plan-change, review nested `impact.consistency_manifest` only when a present
manifest declares relationships touched by the request. Confirm its manifest
    digest, affected relationship IDs and member paths, omitted counterpart members,
    and each affected relationship's current pass/drift/missing status. The projection must not add omitted
counterparts to `changed_paths`, widen authorization, or select, skip, run,
reorder, or waive Gates. If the manifest is absent, expect no Doctor diagnostic
and no `consistency_manifest` impact member.

Do not treat exact-byte agreement as proof of generator correctness, source
authenticity, or build reproducibility. The controller does not generate,
repair, normalize, or infer relationships or artifacts.

### 6b. Review conservative affected-Gate planning evidence

When a graph exists, inspect `impact.affected_gate_plan` after the sibling
architecture and consistency evidence. Confirm schema `1.0`, the graph, policy,
and optional manifest SHA-256 bindings, and `execution_performed = false`.
Verify that `changed_paths` remains the approved request scope. Any
`derived_consistency_paths` must come only from affected declared relationships;
their union may appear in `planning_paths` but nowhere in authorization or writes.

For `mode = "affected"`, confirm every planned Gate is an eligible graph
candidate, all eligible policy Gates are assigned to the graph, and effective
phase is not below either the risk phase or any candidate phase. For
`mode = "fallback_full"`, confirm effective phase is at least full and
`planned_gate_ids` equals the complete cumulative policy Gate set for that phase.
For `mode = "inconclusive"`, confirm no empty plan is represented as success.

Stop targeted planning on unmapped or ambiguous paths, cycles, unknown Gates,
traversal or projection exhaustion, empty candidates, unassigned eligible Gates,
and drifted, missing, or unevaluated affected consistency relationships. Do not
copy raw command arguments, options, environment values, file contents, or secret
labels into the plan.

Treat policy, architecture graph, consistency manifest, and ancestor-directory
changes as inconclusive authority changes, not full fallback. Apply such a change
only under its own approval, then rerun planning against the new authority before
using any affected-Gate recommendation. Reject an empty changed-path request.
Reject guard-resolved path aliases, including Windows short-name and
symlink/reparse forms; mixed-case authority paths must still be classified as
authority changes through NFC plus casefold comparison.

Treat the projection as review evidence until the plan-change is explicitly
applied and its resulting canonical receipt is selected through the bounded
interface below. Do not copy IDs into another input, modify Gate order, mark
omitted Gates not applicable, or claim planning itself ran a Gate. With no graph,
expect no `affected_gate_plan` member, no plan-bound execution, and the exact
legacy impact structure.

### 6c. Run and review one plan-bound check

Select only a project-local canonical plan-change receipt whose ChangeRecord and
approval scope have already been reviewed. Before execution, confirm the
controller accepted canonical bytes and filename digest, matching ChangeRecord,
policy, architecture graph, optional consistency manifest, approval/risk/phase
fields, and an exact recomputation of `impact.affected_gate_plan`. Missing,
changed, aliased, incomplete, or unsafe authority must stop before any Gate runs.

After the two stable selected-plan reads, require a complete pre-execution
receipt-ledger inventory. Confirm no more than 10,000 entries, no receipt larger
than 1 MiB, and no more than 64 MiB of aggregate receipt input. Every entry must
be a root-contained regular canonical Receipt 1.x file with stable reads and no
link, reparse point, or hardlink. Invalid, unreadable, unsafe, or exhausted input
must return exit `2`, run zero Gates, and persist no check receipt. Do not reject
a canonical historical receipt because of age or re-evaluate it under current
policy or approval rules. Only the selected plan-change receipt is revalidated
against its ChangeRecord and current authority.

For `affected`, verify the executed Gate IDs equal the exact planned set. For
`fallback_full`, verify every cumulative eligible Gate executes. For
`inconclusive`, verify no Gate executes, both Gate evidence and checks are empty,
and exit `3` is retained. In every executable mode, compare the ordered checks
one-for-one with P1-E0 provenance. Treat `omitted_gate_ids` only as unexecuted;
do not record them as pass, waived, or not applicable.

Inspect the closed `outputs.plan_bound_execution` object. Confirm the plan
receipt reference plus file and canonical digests, ChangeRecord hash, authority
hashes, mode, effective phase, planned/executed/omitted sets, fallback reasons,
execution flag, and authority status. After execution, require a stable authority
re-read and a second complete ledger inventory. Compare the second ledger
fingerprint with the retained pre-execution fingerprint. An invalid post-run
ledger or fingerprint drift must produce exit `4` scope-violation evidence even
when selected plan authority remains stable; set `authority_status = "changed"`
only when that selected authority changed. Plan, ChangeRecord, receipt-ledger,
policy, graph, manifest, or workspace drift must persist no successful check
receipt. Retain the plan receipt and check receipt as distinct evidence. Treat
this as bounded drift detection, not locking: leases, inter-process locks, and
atomic replacement remain P1-E2 work. Legacy phase checks do not acquire this
plan-bound ledger precondition.

### 7. Handle exits and rollback

- `0` pass: retain evidence.
- `1` deterministic failure: fix or plan it; do not waive informally.
- `2` invalid invocation/schema: correct before retry.
- `3` required evidence inconclusive: collect or restore evidence; never convert to pass.
- `4` authorization/scope violation: stop; do not widen scope implicitly.
- `5` partial-write recovery required: stop normal work, follow recovery/rollback evidence, and preserve the receipt.

Required G4 controls that cannot be evaluated block the affected operation. Optional or non-critical uncertainty becomes a visible warning with an owner and evidence task. Timeouts and tool crashes are inconclusive.

### 8. Verify and hand off

Run `doctor` after adoption, adapter generation, policy changes, baseline changes, or recovery. Confirm policy digest, adapter version/digest/scope, conflict status, baseline validity, receipt linkage, exception expiry, and rollback history. Receipt age is not a failure: retain every canonical historical receipt and investigate only non-canonical bytes, invalid schemas, broken fields, or unsupported commands. If `.governance/current-state.md` is absent, continue; it is optional. If present, confirm it names the latest canonical receipt, matches that receipt's SHA-256, and lists exact hashes for the current project, policy, and baseline authority files. Treat projection drift as a warning and receipt corruption as a failure. Doctor remains read-only and never regenerates either artifact. Hand off audit/adoption receipts, level reasons, changed paths, gate evidence, baseline owners/dates, approvals, rollback evidence, and unresolved `Decide`, `Measure`, and `Migrate` items.

### 9. Verify feedback-loop evidence and chain integrity

Inspect the emitted canonical check receipt rather than retaining raw feedback.
Confirm its feedback-loop input contains only normalized coded metrics,
acceptance, incidents, and owner decision evidence. Do not place raw feedback,
logs, prompts, summaries, PII, credentials, tokens, or secrets in `loop_run`.
An empty/default progress object may be omitted from the receipt; historical
receipts that lack `progress_evidence` are interpreted as empty evidence with
owner code `none`.

Before continuing the chain, verify that the controller accepted every canonical
receipt, recomputed each stored progress fingerprint from that receipt's own
checks and feedback-loop inputs, and selected one unbroken, unbranched, acyclic
tip. A mismatch is invalid evidence, not a reason to copy or repair a stored
fingerprint. `owner_decision_code` grants no approval and does not change or
override `stop_state` or `next_gate`; follow the emitted decision and the normal
approval path. Progress evidence may change the progress fingerprint, but it does
not change proposed regression symptom codes, `candidate_id`, or either ledger
identity.

### 10. Promote recurring defects deliberately

When an opt-in feedback-loop check proposes a regression delta, inspect the
canonical check receipt. New receipts retain legacy `symptom_codes` and add
`candidate_schema_version = "2.0"` plus a closed `candidates` array. For each
candidate, verify that `candidate_id` binds its symptom code, safe Gate contract
digest, and receipt-safe evidence digest. Confirm the receipt has an independent
closed `regression_gate_contracts` snapshot, each failed or inconclusive check
has exactly one candidate, and each candidate matches that snapshot. Confirm the
proposal has no more than 64 candidates and the snapshot no more than 256
contracts. The visible Gate contract must contain only Gate ID, phase, kind,
required flag, timeout, warning codes, argv count, and option-key names. Stop if it exposes command
arguments, option or environment values, or if evidence identity contains
messages, stdout/stderr, logs, prompts, feedback, PII, secrets, or file content.
Bounded UTF-8 project paths, common filename punctuation, and spaces are valid;
scope paths may include a bare directory with spaces. Privacy-redacted references
must appear only as deterministic count-based sentinels such as
`redacted/evidence-001.ref`. With no evidence references, expect the empty
evidence projection digest.

Choose one compatible update path and preview it before apply:

- **Ledger/Update 1.0:** select one legacy `symptom_code`; use the legacy symptom
  fingerprint and exact `.governance/regressions/<fingerprint>.json` path.
- **Ledger/Update 1.1:** select the exact `candidate_id` present in the source
  receipt; use `.governance/regressions/<candidate_id>.json` and retain the source
  Gate/evidence digests.

Do not translate a historical `1.0` record into `1.1`, rename its file, or use a
`1.1` update against it; the reverse cross-version update is also invalid.
`check` itself does not write the ledger. Apply records the first or latest
occurrence transactionally. Keep the record open until an existing project-local
test, eval, static rule, runtime probe, or incident fingerprint is linked. Close
only with `next_gate = "closed"`, then run `doctor` and retain both receipts.

Confirm Doctor accepted canonical record bytes, filename/fingerprint agreement,
the exact source candidate, and recomputed Gate contract/evidence digests. Treat
any mismatch as failed evidence. Doctor reports the problem and never repairs,
migrates, or renames the record.

## Stop conditions

Stop when the root is ambiguous, a write crosses the boundary, approval is missing, a required critical control is inconclusive, an adapter is divergent, a non-baselinable finding is proposed as debt, or partial-write recovery is unsafe.

## Pilot checklist

| Check | Evidence |
|---|---|
| Read-only audit | Target unchanged; receipt retained outside unadopted target |
| Adoption | Approved audit receipt, additive scope, baseline, adapter verification, receipt |
| Preview/apply | Distinct plan and applied paths |
| Gates | Five-state results; inconclusive never pass |
| Plan-bound check | Canonical applied plan; exact recomputation; executed equals planned; omitted remains unexecuted; post-run authority stable |
| Architecture graph | Optional closed 1.0 graph; longest-prefix ownership; dependent closure; conservative fallback; Doctor read-only |
| Consistency manifest | Optional closed 1.0 relationships; exact bytes only; bounded normal files; Doctor read-only; impact is evidence only |
| Feedback-loop evidence | Closed coded input; canonical chain fingerprints recomputed; no raw feedback or sensitive data |
| Regression candidate | Schema 2.0 candidate; safe Gate/evidence digests; progress evidence excluded from identity |
| Regression ledger | Version-compatible 1.0 or 1.1 update; exact filename and source candidate; Doctor read-only |
| Baseline | Stable fingerprints, owners, dates, review, source receipt, exclusions |
| Receipt history | Canonical bytes retained regardless of age; invalid evidence fails |
| Current state | Optional digest-linked projection; drift warns and never replaces receipts |
| Rollback | Explicit path and recovery/rollback receipt |
| Global boundary | No global activation, daemon, or user-wide configuration |

## Explicit pilot boundaries

- Confirm Git state will remain unchanged by the pilot; Git hooks or integrations may be planned as scoped adapters, but global activation is excluded.
- For the P1-C source slice, do not create `.governance/consistency.manifest.json` in AniSpeak; downstream authoring remains a separate approved project change. Do not package, release, or globally install the source controller in this slice.
- Preview initialization or adoption before apply. Inspect planned files, level reasons, conditional documents, adapters, gates, baseline treatment, approvals, and rollback. Use the controller's explicit `--apply` only after the preview and approval review.
- The adoption decision must state whether the pilot will retain, add, decide, measure, or migrate each material finding. Retain only evidence-backed controls and reproducible legacy debt; add only bounded additive controls; leave `Decide` and `Measure` items visible with owners; and use a separate approved `plan-change` for `Migrate` items.
- If a write is partial, stop normal work, preserve the receipt, inspect changed paths, and follow the recorded rollback or recovery path. Do not retry with a wider scope. If the adapter projection, baseline, or required document set is divergent, stop adoption and return to `doctor`/preview rather than silently replacing project files.

## Pilot exit and adoption review

At pilot close, review the audit and adoption receipts, planned versus changed paths, level reasons, selected documents, adapter digests, gate states, baseline fingerprints, owners and review dates, unresolved classifications, approvals, and rollback evidence. Adopt only when the evidence is reproducible and the project owner explicitly approves the bounded scope. Otherwise retain the audit receipt, record the decision, and do not apply.
