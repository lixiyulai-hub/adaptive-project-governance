# RPD: Requirements Planning, Orchestration, and Delivery

## Document Control

| Field | Value |
| --- | --- |
| Document ID | `APG-RPD-001` |
| Canonical name | Requirements Planning, Orchestration, and Delivery (RPD) |
| Familiar alias | Product Requirements Document (PRD); RPD is canonical because it also binds orchestration, evidence, and delivery traceability. |
| Version | `0.2.0` |
| Effective date | `2026-08-13` |
| Change ID | `adaptive-project-governance-rpd-p3-d-j-completion-alignment-v1-20260813` |
| Approved write scope | Root-level `RPD.md` only. |
| Pre-state | `RPD.md` version `0.1.0`, SHA-256 `add0682c1ad5872388f6166f90726ac6cbfba100839004c8cde7d394886c53e7`; the existing dirty baseline remains outside this document's ownership. |
| Approval state | The owner authorized this one-path alignment on `2026-08-13`; no formal Approval ID was supplied or invented. |
| Product state | P3-A through P3-J repository capabilities are implemented and repository-validated. The P3 repository-capability milestone is closed; P4 is not started. Host integration, concrete target execution, runtime, deployment, publication, promotion, pilot, and release remain separate. |
| Normative language | ASCII identifiers and field values are preferred. The product promise below is retained verbatim. |

## Product Promise

APG begins with a simple user promise: **"说出来一个想法，得到一个结果"**.

The user describes an intended outcome. APG aligns questions, turns the
result into reviewable requirements, plans work, selects evidence-bound
decisions, coordinates implementation, validates results, and prepares a
delivery path. Governance is a backend safeguard; it does not replace the
user-facing outcome.

This RPD is the single requirements truth source for that flow. It does not
replace canonical P3-A through P3-J records. Instead, it binds their
requirements, tasks, artifacts, decisions, orchestration state, and evidence
to one reviewable requirement registry.

## Scope

This RPD defines:

- one stable `REQ-*` registry for ordinary users and ordinary programmers;
- GUIDED and ENGINEERING interaction modes over the same requirement truth;
- requirement-to-plan-to-evidence traceability;
- question-led alignment, requirements-before-code, task decomposition,
  parallel execution, consolidation, gap closure, and observable acceptance;
- the authority boundary for configuration, secrets, providers, network,
  real data, cost, deployment, publication, promotion, pilot, and release;
- separate acceptance states for repository-local validation, runtime,
  deployment, publication, pilot, and release.

## Non-Goals

This RPD does not:

- create a second PRD or a second canonical requirement truth source;
- repeat or redefine the eight P3-B blueprint sections, which remain
  authoritative in `docs/project-governance/PROJECT_BLUEPRINT.md`;
- execute a plan, create a downstream project, select or install a dependency,
  configure a provider, access a network, or perform a runtime action;
- contain raw ideas, raw conversations, raw media, transcripts, prompts, PII,
  customer records, credentials, secret values, callback material, or real
  production data;
- convert a recommendation, a generated artifact, a passing local check, or a
  dashboard into owner approval or product acceptance;
- authorize a concrete P3-D/P3-E target transaction, plugin or host action,
  runtime, deployment, publication, promotion, downstream pilot, release,
  source-control action, or external irreversible action.

## One Truth Source, Two Modes

GUIDED and ENGINEERING are interaction modes, not separate products and not
separate registries. Both write and review the same stable `REQ-*` identity,
statement, decision state, acceptance criterion, phase binding, and evidence
reference. A mode can change how information is collected; it cannot bypass
owner confirmation, canonical source binding, or acceptance evidence.

| Concern | GUIDED mode | ENGINEERING mode | Shared truth rule |
| --- | --- | --- | --- |
| Starting point | One natural-language idea and desired result. | A product goal plus repository, interface, architecture, stack, compatibility, test, performance, operational, or delivery constraints. | Normalize to bounded requirement statements and evidence references; do not retain raw input as the durable record. |
| Questions | Ask only questions that could change outcome, risk, scope, or acceptance. Explain defaults in plain language. | Accept concise constraints and request only missing facts that block a decision or evidence binding. | Record each resolved fact against the same `REQ-*` item and source reference. |
| Defaults | May propose safe defaults as `RECOMMEND`. | May compare alternatives as `RECOMMEND`. | A recommendation never becomes an owner decision without required confirmation. |
| Consequential action | Stop at `CONFIRM` and explain the impact. | Stop at `CONFIRM` with the relevant technical scope and evidence need. | Cost, external access, security, data, and delivery boundaries are identical in both modes. |
| Output | A reviewable outcome, requirements, and next decision. | A reviewable constraint set, requirements, and next decision. | The canonical output is the registry plus bound P3 records, not a mode-specific document. |

### Question-Led Alignment

1. Identify the outcome, user, success signal, and material constraints.
2. Ask only the smallest set of questions that can change the result,
   acceptance criterion, risk, or required confirmation.
3. State assumptions as `RECOMMEND`, unresolved facts as `needs-evidence`, and
   consequential decisions as `CONFIRM`.
4. Freeze the reviewable requirement set before implementation work is planned.
5. Treat later discoveries as explicit requirement updates or gap records, not
   as silent changes to an accepted requirement.

## Stable REQ Registry

The registry below is normative for this RPD. New requirements receive a new
ASCII `REQ-<three-digit>` identifier. IDs are never reused, renumbered, or
silently deleted. A superseded item remains traceable to its successor.

Each requirement has these required fields:

| Field | Meaning |
| --- | --- |
| `id` | Stable ASCII `REQ-*` identifier. |
| `category` | Bounded grouping such as product, interaction, plan, quality, security, operation, delivery, or boundary. |
| `statement` | Bounded, reviewable requirement statement; not raw user input. |
| `user_modes` | `GUIDED`, `ENGINEERING`, or both. |
| `source` | Canonical source record or bounded evidence reference; never a secret value or raw transcript. |
| `decision` | Exactly `AUTO`, `RECOMMEND`, or `CONFIRM`. |
| `priority` | `P0`, `P1`, `P2`, or `P3`. |
| `acceptance` | Observable condition that an independent reviewer can evaluate. |
| `phase_binding` | P3-A through P3-J, an independent execution phase, configured Gate, runtime acceptance, or explicit unresolved state. |
| `evidence` | Required evidence reference or `needs-evidence`; evidence does not imply acceptance outside its phase. |
| `status` | One of the Acceptance and Evidence States defined below. |

| ID | Category | Statement | User modes | Source | Decision | Priority | Acceptance | Phase binding | Evidence | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `REQ-001` | product | Preserve the APG idea-to-result promise while making the intended outcome reviewable. | GUIDED, ENGINEERING | `RPD-DOC-CTRL` | AUTO | P0 | A reviewer can locate the promise and one bounded outcome statement in the shared registry. | P3-A, P3-B, P3-I. | Canonical P3-A/P3-B bindings and P3-I session contract. | repository-validated |
| `REQ-002` | interaction | Provide GUIDED and ENGINEERING modes over the same stable requirement identities and decision states. | GUIDED, ENGINEERING | `RPD-MODES` | AUTO | P0 | Mode-specific collection produces equivalent registry fields for equivalent facts. | P2-E guided intake; P3-A/P3-C compatibility. | GUIDED evidence exists; explicit named-mode equivalence and a persisted shared registry still need evidence. | needs-evidence |
| `REQ-003` | plan | Complete requirement alignment and owner decisions before code or downstream materialization is proposed. | GUIDED, ENGINEERING | `RPD-ALIGNMENT` | CONFIRM | P0 | No implementation task is eligible while a bound P3-A decision requires owner confirmation. | P3-A, P3-B, P3-C. | Canonical decision, blueprint, and readiness contracts. | repository-validated |
| `REQ-004` | plan | Decompose accepted requirements into bounded, dependency-aware `TASK-*` records. | GUIDED, ENGINEERING | `RPD-TASKS` | RECOMMEND | P0 | Every planned task names its requirement, input digest, owner, dependency set, output artifact, and verification need. | P3-B, P3-F. | Canonical task graph, execution context, route, and wave records. | repository-validated |
| `REQ-005` | orchestration | Permit parallel agents only with disjoint write ownership, bounded inputs, and a defined consolidation owner. | GUIDED, ENGINEERING | `RPD-PARALLEL` | CONFIRM | P1 | Parallel tasks have no overlapping write path unless a consolidation record resolves the overlap. | P3-F, P3-H, P3-J. | Ownership serialization, conflict records, component lanes, and consolidation contracts. | repository-validated |
| `REQ-006` | quality | Consolidate planned outputs deterministically and register gaps rather than silently accepting incomplete work. | GUIDED, ENGINEERING | `RPD-CONSOLIDATION` | AUTO | P0 | Consolidation links each input artifact to a result, conflict decision, residual gap, and next evidence requirement. | P3-G, P3-H. | Lifecycle consolidation, conflict resolution, residual gaps, and independent review. | repository-validated |
| `REQ-007` | quality | Separate repository-local validation, runtime verification, deployment preparation, and observability evidence. | GUIDED, ENGINEERING | `RPD-VALIDATION` | CONFIRM | P0 | Evidence labels identify their phase; no later-phase claim is accepted from an earlier-phase artifact. | P3-G, P3-H, P3-I. | Phase enum, phase-scoped acceptance, and no-inference contracts; only repository validation has current execution evidence. | repository-validated |
| `REQ-008` | security | Require explicit confirmation and no-secret handling for consequential external, sensitive, or costly work. | GUIDED, ENGINEERING | `RPD-BOUNDARY` | CONFIRM | P0 | Any such action remains blocked until an independent approval binds scope, risk, evidence, and rollback. | P3-D, P3-E, P3-F, P3-G. | Authorization classification and bounded approval contracts; concrete external actions remain independently gated. | repository-validated |
| `REQ-009` | delivery | Hand P3-D materialization and downstream project creation to an independent, exact-root transaction. | GUIDED, ENGINEERING | `RPD-P3D` | CONFIRM | P0 | A P3-D proposal binds exact P3-C and blueprint digests, root, manifest, baseline, changed paths, Gates, rollback, and acceptance. | P3-D preview; P3-E apply controller. | Repository-validated preview and bounded apply-controller contracts; no concrete target transaction was run in this completion audit. | repository-validated |
| `REQ-010` | delivery | Keep runtime, deployment, publication, promotion, downstream pilot, and release as separate evidence and approval boundaries. | GUIDED, ENGINEERING | `RPD-DELIVERY-BOUNDARIES` | CONFIRM | P0 | Each boundary has its own authority, execution record, rollback, and acceptance evidence. | P3-G, P3-H, P3-I, P3-J. | Repository-validated phase-isolation contracts; later execution phases are not performed or accepted. | repository-validated |
| `REQ-011` | acceptance | Require observable acceptance evidence and independent review; reject self-assertion as final proof. | GUIDED, ENGINEERING | `RPD-EVIDENCE` | AUTO | P0 | An independent reviewer can return `ACCEPT` or `BLOCK` against the requirement and cited evidence. | P3-F, P3-G, P3-H, P3-J; configured Gates. | Independent-review contracts, plan-bound Gate receipt, and independent read-only review. | repository-validated |

`repository-validated` in this registry means that the APG contract and its
repository tests passed their bounded acceptance. It does not mean that a
plugin host loaded the capability, a target project executed it, or a later
runtime, deployment, publication, pilot, or release boundary passed.

## Traceability Contract

The required trace is:

```text
REQ-* -> P3-A -> P3-B section -> P3-C -> P3-F/P3-G task evidence
      -> P3-H consolidation -> P3-I session -> P3-J target plan
      -> phase-scoped acceptance evidence
```

P3-D preview and P3-E bounded materialization are a separate exact-root branch
from P3-C. They are not silently inserted into the in-memory P3-F through P3-J
chain and do not receive execution authority from that chain.

`P3-B section` is an authoritative section reference emitted by P3-B. This
RPD records the reference but deliberately does not copy, list, or redefine
P3-B's eight blueprint sections. The P3-B document remains the source for
their names, order, and semantics.

| Trace stage | Required binding | Invalid shortcut |
| --- | --- | --- |
| `REQ-*` | Stable requirement ID, versioned statement, decision state, and acceptance condition. | A prose request without a stable ID. |
| P3-A | Exact canonical `IntentDecisionResult` and digest, including unresolved owner decisions. | Treating an unconfirmed recommendation as accepted intent. |
| P3-B section | `P3B:<authoritative-section-id>` reference plus the blueprint digest. | Reconstructing a section from RPD prose or copying the P3-B schema here. |
| `TASK-*` | Task ID, parent `REQ-*`, bound source digest, inputs, output artifact, owner, dependency set, and verification target. | An agent assignment with no requirement or ownership binding. |
| Implementation artifact | Declared path or artifact ID produced only in a separately authorized execution transaction. | A generated file, agent statement, or local process treated as accepted work. |
| Consolidation | Deterministic record of inputs, conflicts, resolved outputs, residual gaps, and changed trace links. | Assuming parallel output is compatible because each agent reported success. |
| Acceptance evidence | Phase-scoped `EVID-*` reference evaluated against the `REQ-*` acceptance criterion. | A dashboard, token availability, one successful request, or deployment result alone. |

### Trace Record Shape

The following is a documentation schema, not a new runtime format:

```text
trace_id: TRACE-<id>
requirement_id: REQ-<id>
p3_a_digest: <canonical-digest-or-needs-evidence>
p3_b_blueprint_digest: <canonical-digest-or-needs-evidence>
p3_b_section_refs: [P3B:<authoritative-section-id>]
task_ids: [TASK-<id>]
artifact_refs: [ART-<id>]
consolidation_ref: CONSOLIDATION-<id>
acceptance_evidence_refs: [EVID-<id>]
status: <acceptance-and-evidence-state>
```

A trace is incomplete when any required binding is absent, digest-drifted,
unconfirmed, out of scope, or claimed by the wrong phase. Incomplete traces
remain `needs-evidence`, `pending-confirmation`, or `BLOCK`; they do not fall
back to inferred success.

## Workflow Requirements

The following workflow requirements capture the accepted product practices as
requirements. They do not authorize execution.

1. **Question alignment:** `REQ-001` through `REQ-003` require outcome-led
   questions, explicit defaults, and owner confirmation before a plan can be
   treated as ready.
2. **RPD before code:** `REQ-003` requires the canonical RPD/PRD requirement
   set and P3-A decision state before P3-B planning or later execution.
3. **Bounded plan split:** `REQ-004` requires each `TASK-*` item to have a
   bounded deliverable, dependencies, owner, acceptance target, and no implied
   execution authority.
4. **Parallel agents:** `REQ-005` permits independent tasks to proceed in
   parallel only where input scope and write ownership are disjoint.
5. **Consolidation:** `REQ-006` requires one accountable consolidator to
   reconcile artifacts, conflicts, assumptions, quality results, and trace
   links before a combined result is evaluated.
6. **Iterative gap closure:** gaps become explicit `REQ-*`, `TASK-*`, or
   `needs-evidence` entries. A later iteration cannot silently change accepted
   scope or delete prior evidence.
7. **Deployment preparation:** a plan may state prerequisites, validation
   strategy, rollback needs, and owner confirmations. Preparation is not
   deployment authority.
8. **Runtime verification:** runtime behavior is separately exercised and
   evidenced after repository-local validation, under its own approved scope.
9. **Observability:** observable signals must be named with their measurement
   scope, expected behavior, and evidence reference. Observability supplements
   product acceptance; it cannot replace it.

## Decision and External-Action Policy

### Decision Values

| Value | Allowed meaning | Prohibited meaning |
| --- | --- | --- |
| `AUTO` | Normalize bounded inputs, detect missing evidence, render traceability, and route a non-consequential next step. | Approve, spend, call a provider, access a network, mutate data, deploy, publish, or release. |
| `RECOMMEND` | Present a default, option, or bounded tradeoff with its assumptions and evidence needs. | Convert a recommendation into an owner decision or a final acceptance result. |
| `CONFIRM` | Pause for an explicit owner decision with scope, consequence, evidence need, and rollback expectation. | Infer consent from silence, a prior unrelated approval, a token, or a local success. |

### Mandatory CONFIRM Boundaries

`CONFIRM` is mandatory before any of the following, in either mode:

- cost, paid service, quota consumption, or budget commitment;
- configuration that changes external behavior or security posture;
- credentials, secret provisioning, provider access, or network access;
- authentication, authorization, privacy, personal data, production data, or
  real customer data;
- database mutation, destructive change, irreversible external action, or
  materially ambiguous product direction;
- runtime launch, deployment, public publication, promotion, downstream pilot,
  release, source-control push, merge, or other public delivery action.

### No-Secret and Data Rules

- Secret values are forbidden in this RPD, a requirement statement, task,
  evidence reference, log excerpt, prompt, receipt summary, or review note.
- A record may contain only a redacted secret name, a secret capability state,
  a bounded evidence reference, `needs-evidence`, or `PENDING_USER_INPUT`.
- A secret availability claim is not provider, network, runtime, deployment, or
  product acceptance evidence.
- Configuration is represented as a decision and evidence need, never as a
  copied live configuration value.
- Real, production, personal, or customer data requires an independent
  `CONFIRM` decision and its own bounded handling plan before use.

## Independent Delivery Boundaries

The boundaries below are intentionally independent. Passing an earlier row
does not satisfy a later row.

| Boundary | Required transaction | Minimum binding | Current state |
| --- | --- | --- | --- |
| P3-D materialization-preview capability | Completed P3-D repository ChangeRecord. Preview remains distinct from apply. | Exact P3-C result and blueprint digests, logical root, manifest, baseline, changed paths, approvals, Gates, rollback, and acceptance. | `repository-validated` |
| P3-E bounded apply-controller capability | Completed P3-E repository ChangeRecord. | Exact P3-D preview, manifest bytes, physical-root fingerprint, pre-state, authorization class, snapshot, post-state, and rollback. | `repository-validated`; no concrete target transaction was run in this completion audit. |
| P3-F through P3-J orchestration capability | Completed independent repository ChangeRecords. | Canonical source chain, task ownership, lifecycle evidence, consolidation, session state, capability preservation, and independent review. | `repository-validated` |
| Plugin host integration | New owner request and bounded host-integration ChangeRecord. | Exact plugin build, installed bytes, host identity, reload state, provider availability, invocation evidence, rollback, and host acceptance. | `not-performed`; repository completion does not require it. |
| Concrete target-project execution | Independent exact-root ChangeRecord. | Target identity, approved scope, pre-state, transaction evidence, Gates, rollback, and target acceptance. | `not-performed`; no target project is selected for follow-up. |
| Runtime verification | Independent runtime ChangeRecord. | Runtime scope, process ownership, configuration evidence, bounded interaction, observability, rollback, and runtime acceptance. | `not-authorized` |
| Deployment | Independent deployment ChangeRecord. | Target class, manifest, approvals, rollback, deployment evidence, and deployment acceptance. | `not-authorized` |
| Publication | Independent publication ChangeRecord. | Public surface, content scope, confirmation, publication evidence, and rollback or takedown plan. | `not-authorized` |
| Promotion | Independent promotion ChangeRecord. | Source version, target population, eligibility evidence, rollback, and promotion acceptance. | `not-authorized` |
| Downstream pilot | Independent pilot ChangeRecord. | Exact downstream root, pilot cohort, real-data decision, runtime evidence, observability, rollback, and pilot acceptance. | `not-authorized` |
| Release | Independent release ChangeRecord. | Version, release scope, evidence closure, rollback, downstream status, and release acceptance. | `not-authorized` |

`CursorVIP_Dev` was used only as a test carrier for APG requirement and safety
evidence. Those tests are complete for this milestone. It is not a delivery
target or a continuing dependency, and APG will not read, write, start,
configure, deploy, release, or otherwise change it under this closeout.

The following do not independently prove product acceptance: one-round
generation, an agent self-report, a passing localhost interaction, deployment
completion, secret availability, provider availability, or an observability
dashboard. Each can be a bounded evidence input only when the appropriate
future phase defines and evaluates it.

## Acceptance and Evidence States

| State | Meaning | Minimum evidence |
| --- | --- | --- |
| `specified` | Requirement is defined in the registry with an observable acceptance criterion. | RPD registry row. |
| `PENDING_USER_INPUT` | An owner decision or missing bounded fact is required. | Explicit question, impact, and required decision. |
| `pending-confirmation` | A `CONFIRM` action is known but not authorized. | Scoped confirmation request. |
| `needs-evidence` | A decision or acceptance claim lacks required evidence. | Missing-evidence statement and next evidence requirement. |
| `planned` | Bound P3-A/P3-B/P3-C evidence supports a later proposal only. | Canonical source digests and task trace. |
| `repository-validated` | Configured repository-local Gates passed in the approved transaction. | Gate receipts and independent review. |
| `not-performed` | A capability boundary exists, but no execution instance was attempted for this milestone. | Explicit scope decision and absence of execution authority or result. |
| `not-authorized` | A later action has not received transaction-specific authority. | New owner request and bounded ChangeRecord are required before execution. |
| `runtime-verified` | Approved runtime acceptance criteria passed. | Runtime evidence scoped to the approved runtime transaction. |
| `deployment-verified` | Approved deployment criteria passed. | Deployment evidence scoped to the deployment transaction. |
| `publication-verified` | Approved public publication criteria passed. | Publication evidence scoped to the publication transaction. |
| `pilot-accepted` | Approved downstream pilot acceptance passed. | Pilot evidence, observability, and independent acceptance. |
| `release-accepted` | Approved release acceptance passed. | Release evidence and independent acceptance. |
| `BLOCK` | Work is prohibited or cannot proceed because authority, evidence, scope, or safety conditions are missing. | Blocking reason and required successor transaction. |

Evidence is valid only for the phase and scope it names. Every acceptance claim
must connect a `REQ-*` acceptance criterion to a phase-scoped `EVID-*` record
and an independent `ACCEPT` or `BLOCK` review result. A failed or incomplete
check is retained as evidence; it is not silently reclassified as a baseline.

## Open Decisions

| ID | Decision | State | Required successor |
| --- | --- | --- | --- |
| `OD-001` | Canonical persisted representation for future RPD registry instances. | `PENDING_USER_INPUT` | Separate design and ChangeRecord; this document introduces no runtime format. |
| `OD-002` | Concrete downstream root, manifest, write set, and P3-E transaction. | `not-performed` | No successor is required for P3 closeout. A future target request requires its own exact-root ChangeRecord. |
| `OD-003` | Provider, network, configuration, credential, and cost posture. | `PENDING_USER_INPUT` | Independent scoped confirmation; no secret values belong in this RPD. |
| `OD-004` | Runtime, deployment, publication, promotion, pilot, and release success criteria. | `not-authorized` | One independent ChangeRecord per selected boundary with phase-specific acceptance evidence. |
| `OD-005` | Product success metrics and observability thresholds for a concrete downstream project. | `needs-evidence` | Later requirement update with measured baseline and owner confirmation. |
| `OD-006` | Explicit named GUIDED/ENGINEERING mode equivalence and persisted shared registry. | `needs-evidence` | A future product requirement and bounded design ChangeRecord only if this capability is requested. |
| `OD-007` | Plugin host integration or real target execution after P3. | `not-performed` | P4 is not started. A new owner request must define the desired outcome before any preview. |

## P3 Completion Evidence

P3-A through P3-J repository capabilities are closed as of `2026-08-13`.
The completion decision is bounded to the repository capability milestone and
uses the following evidence:

- the prior full-suite result supplied at handoff: `665 passed, 1 skipped`;
- the prior source-compilation result supplied at handoff: 57 Python sources;
- the prior independent read-only review verdict supplied at handoff: `ACCEPT`;
- P3-J plan-bound Gate receipt
  `.governance/receipts/20260813T021223993194Z-check-f18af3762258.json`,
  SHA-256
  `d30cf961bba8b5e65b425f22afaae9c6e9548908d7292fb6591ad0abb914851e`;
- the `2026-08-13` pre-alignment Doctor result: 216 canonical receipts,
  0 invalid, with only the existing `.governance/previews` warning.

The full suite, compilation, and independent review above were not rerun during
the read-only completion audit. This alignment transaction has its own
plan-bound validation and receipt. No evidence in either transaction implies
plugin-host, target-project, runtime, deployment, publication, promotion,
pilot, release, or product acceptance.

## Milestone Decision

The P3 repository-capability milestone is closed. P4 is not started and is not
required to close P3. No automatic continuation is authorized.

A future owner may request a separately named milestone for plugin-host
integration, a real target-project execution, runtime acceptance, deployment,
pilot, or release. Such a request must begin with a new bounded ChangeRecord
and cannot reuse this closeout as execution authority.

## Approval State

The approved ChangeRecord authorizes only this root-level `RPD.md` alignment.
It does not authorize a concrete P3-D/P3-E target transaction, implementation
outside this document, dependency changes, plugin installation or host reload,
provider or network access, credentials, runtime activity, deployment,
publication, promotion, pilot, release, push, merge, or any other external
action. It authorizes no action against `CursorVIP_Dev`.

No independent Approval ID was supplied for those later actions. Their state is
therefore `PENDING_USER_INPUT` or `BLOCK`, never an inferred approval.

## Change History

| Version | Date | Change | Scope |
| --- | --- | --- | --- |
| `0.2.0` | `2026-08-13` | Align P3-D through P3-J repository completion, close the P3 repository-capability milestone, record `REQ-002` residual evidence needs, preserve independent delivery boundaries, exclude further `CursorVIP_Dev` action, and leave P4 not started. | `RPD.md` only. |
| `0.1.0` | `2026-08-10` | Initial canonical RPD for dual-mode requirements, orchestration, traceability, and delivery boundaries. | `RPD.md` only. |

## Rollback

The recorded pre-state for this transaction is `RPD.md` version `0.1.0` with
SHA-256 `add0682c1ad5872388f6166f90726ac6cbfba100839004c8cde7d394886c53e7`.
Rollback may restore only that exact preimage and only when the live RPD hash
equals the post-apply SHA-256 recorded by this transaction. Any hash drift
requires a new bounded disposition.

Rollback must not restore, normalize, rewrite, delete, baseline, or otherwise
modify unrelated dirty files, prior ChangeRecords, receipts, historical
evidence, generated outputs, P3-A through P3-J records, plugins,
`CursorVIP_Dev`, target projects, or external artifacts.
