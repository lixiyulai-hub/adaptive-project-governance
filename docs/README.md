# Project Governance Operator Guide

This directory documents the approved Version 1 Adaptive Project Governance contract: repository-scoped, audit-first, evidence-producing, and reversible. Governance reduces regression risk, limits blast radius, preserves rollback, and retains evidence; it cannot promise zero bugs or prove the absence of defects.

## Scope and authority

- `.governance/project.toml` is the reviewed project profile.
- `.governance/policy.toml` is the canonical policy.
- `.governance/baseline.json` stores accepted finding fingerprints and measurements.
- `.governance/changes/<change-id>.json` stores intent, impact, approvals, rollout, telemetry, and rollback.
- `.governance/receipts/<timestamp>-<command>.json` stores immutable command evidence.
- `.governance/architecture.graph.json` is optional reviewed topology evidence, not a Gate execution plan.
- `.governance/consistency.manifest.json` is optional reviewed artifact-relationship evidence, not a generator or repair plan.
- `.governance/current-state.md` is generated, replaceable, and not authoritative.
- TOML is reviewed configuration; JSON is machine-produced evidence.
- Unknown schema major versions fail closed before writes.

The controller is technology-neutral, has no resident daemon, and does not dictate framework, language, architecture, or repository layout. Global activation for future projects or user-wide Codex, Claude Code, Cursor, or launcher configuration is outside Version 1 and requires separate authorization.

## Six operations

| Operation | Contract |
|---|---|
| `init` | Profile and initialize a new project with bounded, additive, idempotent writes. |
| `audit` | Strictly read-only inspection; does not create `.governance/` in an unadopted target. |
| `adopt` | Requires an approved audit receipt; applies approved additive controls, records baseline, verifies adapters, and runs relevant checks. |
| `plan-change` | Previews a consequential change by default; apply requires the applicable approval and rollback information. |
| `check` | Runs configured fast, full, or release gates. |
| `doctor` | Diagnoses policy, adapter, baseline, conflict, and evidence problems without silent replacement. |

`audit` is not adoption. Preview is not apply. Structural migration is a separate approved `plan-change` with acceptance tests, staged rollout, telemetry, and rollback. A large file is a review signal, not proof that it must be split.

## Five results and stable exits

Every gate returns exactly one state: `pass`, `warn`, `fail`, `inconclusive`, or `not-applicable`. `inconclusive` never counts as pass; timeout, crash, unavailable tool, and decode failure are inconclusive.

- `0`: pass
- `1`: deterministic failure
- `2`: invalid invocation or schema
- `3`: inconclusive required evidence
- `4`: authorization or scope violation
- `5`: partial-write recovery required

## Quality gates

- **Fast:** scope, schema, adapter digest, secret checks, configured lint/type/compile checks, unit tests, bug-reproducing tests, and affected public-contract checks.
- **Full:** fast plus broader and dependency-aware tests, integration and contract tests, build/package, baseline, dependency/license/security, migration, and relevant performance checks.
- **Release:** fast and full plus production artifact, provenance/reproducibility, compatibility, security, performance, deployment, telemetry, staged rollout, rollback readiness, and approvals. G4 may require independent verification and recovery rehearsal.

## Gate execution provenance

Canonical CLI `check` on an adopted project binds every check receipt to the
SHA-256 of the canonical `.governance/policy.toml` that supplied the executed
Gates. The CLI fails closed when that authority is missing or changes before
  execution, and rejects policy paths that contain a symlink, reparse point, or
  root-external final handle. The default selector remains phase: `fast`,
  cumulative `full`, or cumulative `release`. An adopted project with a valid
  P1-D plan may instead use the explicit, mutually exclusive `--plan-receipt`
  selector described below. Gate order and required/warning semantics are
  unchanged.

Normal and scope-violation check receipts include a closed Gate execution
evidence projection with schema version `1.0`. Each entry records the Gate
identity, phase, kind, required flag, result status, stable reason code, nullable
process exit code, SHA-256 of the full semantic Gate contract, SHA-256 values for
redacted stdout/stderr captures, observed and captured byte counts, truncation
flags, and duration. Contract hashing covers the complete declared Gate
semantics, while only the digest is persisted. Capture hashing occurs after
redaction and hashes only the capture's character-class shape, so unrecognized
literal values are not exposed through an exact-content verifier.

Raw argv, commands, command output, environment values, file contents, and
secrets are never persisted in this evidence. The full contract digest is an
exact equality verifier for the public policy semantics, so Gate policy must
never embed credentials or other low-entropy secrets; known credential-bearing
arguments, fields, and literals fail before execution. Treat policy and receipts
as governance evidence rather than a secret store. The public `run_gate` return type
and the top-level Receipt and CheckResult schemas remain unchanged. A direct
`run_check` API compatibility path may omit policy binding for unmanaged or
internal use, but canonical CLI checks of adopted projects may not opt out.

Phase mode records `selection_mode = "phase"`; plan-bound mode records
`selection_mode = "plan"` and uses the recomputed effective phase. Neither mode
accepts raw planned Gate IDs. A plan receipt can select execution only after the
controller authenticates and exactly recomputes the complete P1-D projection.

## Optional architecture impact graph

An adopted project may provide the optional canonical file
`.governance/architecture.graph.json`. Its closed `1.0` schema contains exactly
`schema_version`, `nodes`, `edges`, and `always_gate_ids`. Nodes declare a stable
ID, closed kind, project-relative path prefixes, owner, and Gate IDs. Directed
`depends_on` edges state that `dependent` uses `dependency`. The graph is bounded
to 1 MiB, 256 nodes, 1,024 edges, 32 path prefixes and 32 Gate IDs per node, and
32 always-on Gate IDs.

Changed paths map to one owner by deterministic longest path-prefix match.
Hierarchical prefixes are allowed; exact prefix ownership by multiple nodes is
invalid. Impact starts with directly matched nodes and follows the transitive
reverse dependent closure, so changing a dependency includes every bounded
dependent. The plan-change receipt preserves all legacy impact fields and, only
when the graph exists, adds `impact.architecture_graph` evidence with graph
digest/counts, direct and affected nodes, candidate Gate IDs, unmapped or
ambiguous paths, cycle information, unknown Gate IDs, traversal exhaustion, and
`fallback_full`.

`candidate_gate_ids` and `fallback_full` are evidence, not execution controls.
Plan-change does not select, skip, run, reorder, or waive a Gate. Unmapped or
ambiguous paths, unknown configured Gate IDs, cycles, or exhausted traversal set
`fallback_full = true`; they never produce an empty-success claim. If the graph
is absent, Doctor adds no warning or failure and plan-change retains its exact
legacy impact shape without an `architecture_graph` key. Doctor validates a
present graph read-only and reports rather than repairs it. The controller does
not infer the graph from source, generate it automatically, or create downstream
project graphs or diagrams.

## Optional declared consistency manifest

An adopted project may provide the optional canonical file
`.governance/consistency.manifest.json`. Its closed `1.0` schema declares
reviewed relationships rather than discovering them. A `source_generated`
relationship names one `source_path` and one or more `generated_paths`; a
`cross_surface` relationship names symmetric `paths`. Every relationship has a
stable `relationship_id`, its `kind`, and `comparison = "exact_bytes"`, the only
comparison supported in Version 1.

The manifest is bounded to 1 MiB, 128 relationships, 16 members per
relationship, 512 globally unique member paths, 256 Unicode characters per
path, 8 MiB per member file, and 64 MiB of aggregate declared member bytes per
evaluation. Members must be normal, root-contained project files. Unsafe,
aliased, duplicate, symlinked, governance-evidence, missing, oversized, or
otherwise unevaluable members fail validation; a declared mismatch is drift,
not equivalence.

If the manifest is absent, Doctor adds no diagnostic and plan-change preserves
its legacy impact shape. If it is present, Doctor evaluates it read-only and
reports valid matching relationships as pass or malformed, missing, or drifted
relationships as fail. Plan-change adds only nested
`impact.consistency_manifest` evidence for declared relationships touched by the
request. It may report the manifest digest, affected relationship IDs and member
    paths, omitted counterparts, and each affected relationship's current
    pass/drift/missing status, but it does
not add those counterparts to `changed_paths` and does not select, skip, run,
reorder, or waive a Gate.

The controller does not generate, repair, normalize, or infer a manifest or any
declared artifact. Exact-byte agreement does not prove generator correctness,
source authenticity, or build reproducibility; those claims require their own
configured evidence and Gates.

## Conservative affected-Gate planning

Plan-change adds the closed
`impact.affected_gate_plan` schema `1.0`. This is an execution-free recommendation
bound to the canonical policy plus optional graph and consistency-manifest SHA-256
values. A missing graph is represented by `architecture_graph_sha256 = null`; it
deterministically uses `mode = "fallback_full"`, promotes the effective phase to at
least `full`, and plans every cumulative eligible policy Gate without omissions.
The plan reports the risk-required and effective phases, declared and derived
planning paths, direct and affected nodes, candidate, eligible, planned, omitted,
unassigned, and unsafe Gate IDs, stable fallback reasons, and
`execution_performed = false`. Gate commands, options, environment values, file
contents, and secrets are not projected.

Consistency endpoints may extend `planning_paths`, but never the ChangeRecord
`changed_paths`, approval scope, authorized writes, or P1-A architecture impact
evidence. Effective phase is monotonic: it cannot be lower than the risk-required
phase and rises to a higher candidate phase. Unmapped or ambiguous paths, cycles,
unknown Gates, exhausted bounds, empty candidates, unassigned eligible policy
Gates, or non-passing consistency relationships use `mode = "fallback_full"`
and recommend the complete cumulative Gate set for at least the full phase.
Missing policy authority, no eligible Gate, unsafe Gate identity, or an output
bound that prevents a complete recommendation uses `mode = "inconclusive"`,
never empty success. Proven bounded coverage uses `mode = "affected"`.
Changing `.governance/policy.toml`, `.governance/architecture.graph.json`,
`.governance/consistency.manifest.json`, or an ancestor path is also
inconclusive: the pre-change authorities cannot prove the post-change Gate set,
so plan-change must be rerun after the authority change is applied.

Planning itself remains execution-free: it does not select a live check, run,
reorder, waive, or mark a Gate not applicable. Only an applied canonical plan
receipt can later enter the separately explicit plan-bound check path. Graphless
plan-bound execution authenticates and recomputes the same policy-bound fallback,
records a null graph digest, and retains stale-policy, receipt-ledger, scope, and
first-failure-stop checks.

## Plan-bound Gate execution

`check TARGET --plan-receipt .governance/receipts/RECEIPT.json` is available
only for adopted projects. The reference must name one canonical, regular,
non-linked, non-hardlinked in-project `plan-change` receipt whose filename and
canonical receipt digest agree. Before any Gate runs, the controller verifies
the receipt envelope and closed plan shape; the matching canonical
ChangeRecord; input, evidence, authorization, risk, phase, and approval fields;
and the current policy, architecture graph, and optional consistency manifest
digests. It then recomputes P1-D planning from those current authorities and
requires exact equality with the stored projection. The stable plan selection is
read twice before execution. After those reads and before any Gate, the
controller inventories the complete `.governance/receipts` ledger. The bounded
inventory accepts at most 10,000 entries, at most 1 MiB per receipt, and at most
64 MiB of aggregate receipt bytes. Every entry must be one root-contained,
regular, non-linked, non-reparse, non-hardlinked, stably read canonical Receipt
1.x file. An invalid, unreadable, unsafe, or exhausted ledger fails with exit
`2`, before Gate execution, and persists no check receipt.

Canonical historical receipts remain valid regardless of age. The ledger
inventory validates their persisted Receipt envelope and bytes; it does not
reinterpret historical approvals or outputs against current policy. Only the
selected plan-change receipt is revalidated with its matching ChangeRecord and
the current plan authority.

`mode = "affected"` executes exactly the recomputed planned Gate set.
`mode = "fallback_full"` executes the complete cumulative eligible set.
`mode = "inconclusive"` executes no Gate and returns exit `3`. Selected Gates
remain in canonical phase and Gate order and each produces one normal CheckResult
and one P1-E0 provenance entry. Omitted Gate IDs are recorded only as not
executed; they are never represented as pass, waived, or not applicable.

The receipt adds a closed `plan_bound_execution` object with the plan receipt
reference and hashes, ChangeRecord hash, change ID, mode, effective phase,
policy/graph/manifest hashes, planned/executed/omitted Gate IDs, fallback reason
codes, `execution_performed`, and `authority_status`. After execution the
controller reloads policy and recomputes the complete selection. It also
re-inventories the ledger and compares its in-memory fingerprint with the
pre-execution inventory. An invalid post-run ledger or any fingerprint drift is
a receipt-ledger scope violation even when the selected plan authority is still
stable. Any concurrent plan, ChangeRecord, receipt-ledger, authority, or
workspace change returns exit `4` with scope-violation evidence and does not
persist a successful check receipt. This bounded before/after guard detects
drift; it does not provide locking, leases, or atomic replacement, which remain
P1-E2 work. `--plan-receipt` is mutually exclusive with explicit `--phase` and
cannot be combined with `--loop-run`. Legacy phase and feedback-loop behavior is
unchanged and does not acquire this new ledger precondition.

## Existing refactored projects: B route

1. **Audit** the architecture, contracts, commands, dependencies, release surfaces, governance files, Git state, licenses, provenance, secret exposure, performance signals, and failures; distinguish evidence from inference.
2. **Classify** each area as `Retain`, `Add`, `Decide`, `Measure`, or `Migrate`.
3. **Adapt** policy to observed boundaries and add only approved controls.
4. **Preserve conflicts:** surface conflicting rules to `doctor`; never silently merge, replace, or downgrade them.
5. **Approve adoption** from the audit receipt, record reproducible legacy baselines, verify adapters, and run relevant checks.
6. **Migrate separately** through an approved `plan-change` when concrete coupling, reliability, performance, security, or maintainability evidence supports it.

The quality ratchet permits known reproducible legacy failures but blocks new or worsened failures. Baselines cannot waive secret leakage, unauthorized writes, data-integrity corruption, or another configured non-baselinable rule.

See `POLICY_REFERENCE.md` for every canonical field and `PILOT_RUNBOOK.md` for the pilot sequence.

## Prerequisites and command use

Run the standard-library controller from the repository with Python:

```powershell
python -X utf8 -m project_governance --help
```

Before a write, confirm the target root, authorized scope, owner, approval path, and native project commands. The controller does not invent build, test, lint, type, package, release, deployment, or performance commands. The public commands and their documented flags are:

```text
project_governance audit TARGET [--receipt-dir RECEIPT_DIR] [--json]
project_governance init TARGET [--policy-file POLICY_FILE] [--apply] [--json]
project_governance adopt TARGET --audit-receipt AUDIT_RECEIPT --audit-digest AUDIT_DIGEST --approval APPROVAL [--policy-file POLICY_FILE] [--apply] [--json]
project_governance plan-change TARGET --request REQUEST [--apply] [--json]
project_governance check TARGET [--phase {fast,full,release}] [--loop-run LOOP_RUN] [--json]
project_governance check TARGET --plan-receipt PLAN_RECEIPT [--json]
project_governance doctor TARGET [--json]
```

`init`, `adopt`, and `plan-change` preview by default; `--apply` is the explicit write switch for those commands. `audit` is read-only and does not create `.governance/` in an unadopted target. `--json` emits one canonical JSON receipt. `init` and `adopt` accept an owner-reviewed canonical TOML policy through `--policy-file`. The supplied policy cannot lower the audit or embedded-policy governance floor or omit any document selected by those authorities. A `G2`, `G3`, or `G4` policy must contain at least one valid canonical Gate; owner-supplied policies and non-G1 embedded policies must also contain a command Gate for adapter projection, so the controller never invents a project command. Rejection occurs before a transaction is created. An empty adapter list retains the Version 1 Codex default used by Doctor. `adopt` additionally requires an approved audit receipt, its expected digest, and structured project approval. G1 retains the legacy generated or embedded-policy path. Preview is not apply, and audit is not adoption.

## Receipts and adapters

Receipts retain command inputs and outputs, policy and target digests, authorized scope, findings, checks, approvals, classifications, and evidence references. Receipt 1.x has one strict loader shared by CLI adoption and Doctor: the envelope and nested finding/check fields are closed, commands and UTC timestamps are validated, duplicate JSON keys fail, and persisted receipt bytes must equal canonical JSON. A canonical historical receipt remains immutable evidence regardless of age; age alone never makes it invalid, and Doctor does not delete, archive, rewrite, or migrate receipt history. An operation may still require fresh audit evidence before a new adoption without invalidating the older receipt. Init/adopt receipts also record policy input status, Gate IDs, Gate kind/phase and argument counts, planned documents, and configured adapters; raw command arguments are not copied into this summary. After adoption, receipts live under `.governance/receipts/`; for an unadopted audit, use standard output or `--receipt-dir` outside the target.

`.governance/current-state.md` is optional, replaceable, and non-authoritative. When present it is TOML-compatible Markdown containing a canonical source receipt reference and SHA-256 plus exact SHA-256 entries for the projected governance files. Doctor accepts absence, passes a current projection, warns on stale links or digest drift, and fails only when the underlying receipt evidence is invalid. It never creates or repairs this projection. Managed projections are adapters, not independent policy sources. Configured adapters may project controls to Codex `AGENTS.md`, Claude Code `CLAUDE.md`, Cursor scoped `.cursor/rules/`, Git fast-check hooks, or GitHub integration/release checks. Each projection records policy/source digests, generator version, and scope; `doctor` detects missing, stale, manually edited, duplicated, or divergent projections.

Feedback-loop checks remain opt-in and write only normal check receipts. The
optional `check --loop-run LOOP_RUN` path accepts the closed loop-run fields plus
optional `progress_evidence`.
When present, progress evidence contains exactly `metrics: [{id, value}]`,
`acceptance: [{id, status}]`, `incidents: [id]`, and `owner_decision_code`. The
acceptance statuses are `pass`, `fail`, `inconclusive`, and `not_applicable`; owner
decision codes are `none`, `continue`, `revise`, `defer`, and `stop`. IDs are
bounded code tokens, metric values are finite numbers, duplicate IDs and unknown
fields fail before any Gate runs, and free-form feedback is not accepted. Numeric
canonicalization makes `1` equivalent to `1.0` and `0` equivalent to `-0.0` for
the progress fingerprint.

Historical loop receipts without `progress_evidence` are read as empty metrics,
acceptance, and incidents with owner code `none`. For every canonical receipt in
the selected chain, the controller recomputes the stored progress fingerprint from
that receipt's checks and feedback-loop input; mismatches, broken links, branches,
and cycles fail closed. Owner decision codes are fingerprint evidence only: they
grant no approval and do not change or override `stop_state` or `next_gate`. Raw
feedback, logs, prompts, PII, and secrets are not persisted. The progress
fingerprint is separate from regression identity: P0-E metrics, acceptance,
incidents, and owner decision codes never enter a regression `candidate_id`.

New check receipts retain legacy `symptom_codes` and also emit
`candidate_schema_version = "2.0"` with a closed `candidates` array. Each
`candidate_id` binds the symptom code to a safe Gate contract digest and a
receipt-safe evidence digest. The receipt also stores an independent closed
`regression_gate_contracts` snapshot. Source validation requires each failed or
inconclusive check to have exactly one candidate and requires that candidate's
contract to match the independent snapshot. A proposal contains at most 64
candidates and a snapshot at most 256 contracts; generation and parsing enforce
the same limits before Receipt persistence. The Gate projection contains only
Gate ID, phase, kind, required flag, timeout, warning codes, argv count, and
option-key names; it never copies command arguments, option values, or
environment values. Evidence identity accepts normalized, bounded UTF-8 project
locators, including common filename punctuation and spaces. Scope-normalized
changed paths may also include single-segment directory paths. Backslashes
normalize to `/`; a root locator `.` becomes `project.root`.
References redacted by the receipt boundary become deterministic count-based
sentinels such as `redacted/evidence-001.ref` before hashing. Candidate evidence
never copies a check message, stdout, stderr, logs, prompts, feedback, PII,
secrets, or file content. When a Gate supplies no evidence references, the
evidence projection remains empty.

Persisting any proposed regression remains a separate approved
`plan-change --apply`. Legacy Ledger/Update `1.0` continues to select a
`symptom_code` and use
the legacy symptom fingerprint. Ledger/Update `1.1` selects the exact
`candidate_id` from the source check receipt and stores it as the record
fingerprint and filename. Existing `1.0` records are not migrated or rewritten,
and updates cannot cross versions. `doctor` validates canonical record bytes,
filename/fingerprint agreement, the source candidate, and Gate/evidence digests;
it reports drift without repairing it. Regression records otherwise retain only
constrained codes, receipt references, recurrence count, owner/status/next gate,
and typed project-relative permanent assets. Closing a record requires an
existing permanent asset.

Profiles are discovered and written as `.governance/project.toml`; the canonical policy is `.governance/policy.toml`. Profile evidence selects level `G1`–`G4`, conditional required documents, adapters, gates, and non-baselinable rules. Conditional documents are selected from the observed project type, lifecycle, exposure, data risk, release model, and test burden; do not assume every project needs every document.

For large AI, media, or monorepo targets, read-only audit hashes normal source and
governance files while representing dependency, model, VCS-object, and generated
subtrees with bounded directory metadata. The receipt names this proof mode and
lists every pruned directory name. Those generated subtrees are outside content
inspection; initialization, adoption, and all transactions continue to use exact
write scopes and full rollback checks.

The `.git` directory uses a stable presence sentinel because read-only Git status
may refresh index locks and timestamps. Worktree content remains fingerprinted;
the audit receipt records this narrower VCS metadata boundary explicitly.

Adoption replays the snapshot mode declared by the audit receipt before comparing
the target fingerprint. Receipts from the earlier full-snapshot proof remain
loadable when they do not declare a proof mode; unknown or drifted proof contracts
are rejected.

## Pilot boundary and limitation

Pilot work is audit-first: retain the read-only receipt, review evidence, classify `Retain`/`Add`/`Decide`/`Measure`/`Migrate`, preview adoption, obtain explicit approval, apply only additive controls, verify adapters and gates, and retain rollback/recovery evidence. Do not change Git state or global Codex, Claude Code, Cursor, launcher, daemon, or background settings as part of Version 1. Structural migration is a separate approved change. The framework reduces regressions and improves prevention, detection, containment, and recovery, but it cannot promise zero bugs.

## P2-A structured project intake

P2-A adds the standard-library-only `project_governance.intake` module. It is an
in-memory evidence contract for the later Grill and routing slices; importing,
parsing, and rendering it performs no filesystem writes, network calls,
dependency discovery, approval creation, or target mutation. The public API is
`parse_intake(payload: bytes) -> ProjectIntake` and
`render_intake(record: ProjectIntake) -> bytes`.

The extension is closed at `extension_schema_version = "1.0"`. A top-level
record contains only `intake_id`, `project_mode`,
`project_mode_evidence_refs`, `purpose`, `user_context`, `remediation_level`,
`stack_fitness`, `need_evidence_level`, `slice_complexity`, `decisions`,
`evidence`, and `stop_state`. Nested records are frozen dataclasses and their
collections are tuples. Unknown fields, duplicate object keys, duplicate
record IDs, unsupported enum values, non-canonical array order, and mutable
record shapes are rejected before a record is returned.

The routing enums are deliberately small:

| Dimension | Values |
|---|---|
| Project mode | `new`, `existing`, `ambiguous` |
| Purpose | `personal-learning`, `real-audience` |
| Decision disposition | `D` (default), `V` (verify), `B` (human-bound) |
| Remediation | `L0` through `L4` |
| Stack fitness | `S0` through `S4` |
| Need evidence | `T0`, `T1`, `T2` |
| Stop state | `continue`, `ready-for-preview`, `owner-gate` |

`user_context` is limited to project relationship, self-declared domain
experience, self-declared technical experience, and audience mode. Each field
uses a closed vocabulary with an explicit `unknown` value where appropriate;
names, email addresses, account identifiers, credentials, customer records,
and unbounded conversation text are outside this contract.

Each decision has a stable ID, topic code, disposition, resolution state,
recommendation code, evidence references, bounded confidence, and user-impact
code. `ai-resolved` is valid only for `D` and `V`; a `B` item remains open or is
marked `user-confirmed`. Human-bound decisions consume a budget of three for a
simple slice or five for a complex current slice. AI-resolved `D`/`V` decisions
are reported separately by `ai_resolved_count` and do not consume that budget.

Evidence references are either bounded stable IDs or contained
project-relative paths. Traversal, absolute paths, query-bearing URLs, secret
patterns, control characters, oversized scalars, and excessive records are
rejected. Evidence kinds distinguish `hypothesis`, `public-research`,
`real-user-evidence`, `technical-viability`, `user-confirmation`, and
`project-evidence`. `T0` represents personal learning, `T1` requires public
research for a real-audience hypothesis, and `T2` requires real-user evidence.
These labels describe evidence quality; they do not assert that a hypothesis
is a product fact.

The stop state is derived and checked against unresolved decisions:

- `continue` means unresolved `D`/`V` items remain and no open `B` item exists.
- `owner-gate` means at least one open `B` item remains.
- `ready-for-preview` means all decisions are resolved.

An intake record is evidence only. It does not grant APG approval, authorize a
write, select a Gate, persist `.governance/intake/`, or replace an owner,
domain, or independent acceptance decision. APG `plan-change`, approvals,
bounded apply, Gate receipts, Doctor, and rollback remain separate authorities.
P2-A also leaves CLI commands, agent prompts, research execution, candidate
scoring, Domain Packs, packaging, global installation, promotion, host reload,
downstream projects, external services, dependencies, and Git operations to
later Change IDs.
