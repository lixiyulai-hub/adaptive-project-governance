# P3-F Autonomous Task Orchestration

P3-F is the deterministic repository-local controller after P3-C readiness and
the P3-E authorization policy. It turns the exact P3-B task graph embedded in a
ready P3-C record into a recommended execution path. It does not execute the
tasks.

The ordinary user contract is compact: show the recommended path, interrupt
only for a consequential boundary, and return one final result. The complete
scope, dependency, Gate, rollback, authorization, and review evidence remains
available for operators and independent acceptance.

## Exact Source Binding

`build_autonomous_task_plan` accepts canonical P3-C bytes and reparses and
recomputes the complete readiness record. The source must be
`ready-for-materialization-preview`, have no blocker code, and bind the exact
embedded P3-B blueprint and task graph.

Every blueprint task must have exactly one `TaskExecutionContext`. Extra,
missing, duplicate, unsafe, or drifted contexts fail closed. A context binds:

- one task and executor identity;
- canonical read and write scopes;
- declared Gate IDs and acceptance references;
- one rollback reference;
- one P3-E `ActionContext` and policy digest;
- explicit Git-operation and release flags.

All task contexts use one policy digest. Their planning evidence must be bound
to the P3-C evidence set. Required professional Gates emitted by P3-C must be
covered by the task contexts.

## Recommended Path and Waves

P3-F retains the P3-B topological order and derives deterministic execution
waves. A task enters a wave only after every dependency is in an earlier wave.

Parallel work is not handed to the user to reconcile. If one task writes a
path that overlaps another task's read or write scope, P3-F moves the later
task into a later wave and records `ownership-overlap-serialized`. It never
silently permits overlapping write ownership.

The plan exposes:

- the complete recommended task path;
- the next material task IDs;
- deterministic execution waves;
- automatic, recommended, confirmation, and blocked task sets;
- self-check and blocker codes;
- one compact user summary code.

## Authorization Policy

P3-F calls the P3-E `assess_action` policy for every task and only tightens its
result.

| Class | P3-F behavior |
| --- | --- |
| `AUTO` | The task may proceed in a later exact-scope executor without another routine owner interruption. |
| `RECOMMEND` | Present the preferred safe path; no write authority is inferred until decision evidence exists. |
| `CONFIRM` | Pause only for consequential boundaries, including the P3-E triggers, Git mutation, or release. |
| `BLOCK` | Stop on unsafe, incomplete, unbound, drifted, or policy-inconsistent facts. |

`auto_authorized_task_ids` is bounded no-interruption eligibility. It is not a
filesystem write, P3-E materialization result, provider permission, runtime
authority, deployment authority, publication authority, Git authority, pilot
acceptance, or release acceptance.

## Final Acceptance

`evaluate_autonomous_task_plan` accepts bounded evidence for any completed task.
Missing task evidence produces `INCOMPLETE`; it is not inferred success.

For one task to be accepted, its evidence must bind the declared executor,
rollback reference, Gate IDs, acceptance references, and output references.
The reviewer identity must differ from the executor identity and the review
verdict must be `ACCEPT`. Every dependency must already be accepted; missing
upstream evidence keeps dependent work `INCOMPLETE`, and a blocked dependency
blocks its dependents. A `RECOMMEND` task also needs decision evidence. A
`CONFIRM` task also needs authorization evidence.

The final state is exactly one of:

| State | Meaning |
| --- | --- |
| `ACCEPT` | Every task has complete independently accepted evidence. |
| `INCOMPLETE` | Admissible task, decision, or authorization evidence is still pending. |
| `BLOCK` | A task failed, review blocked, evidence drifted, the plan was blocked, or a binding was inconsistent. |

The receipt-safe final result binds the exact plan digest and retains accepted,
pending, and blocked task IDs plus stable reason codes. It remains
repository-local orchestration evidence.

## Side-Effect Boundary

P3-F is standard-library-only and in-memory. Planning, parsing, rendering, and
acceptance evaluation perform no filesystem mutation, subprocess execution,
dependency installation, provider or network call, credential access, runtime
launch, deployment, publication, promotion, pilot, release, or Git action.

A later executor must bind its own exact root, paths, pre-state, authorized
operation set, Gates, evidence capture, and rollback. P3-E remains the bounded
materialization transaction controller when physical project files are written.

## Repository Rollback

The P3-F repository implementation transaction may remove only the new P3-F
module, test, and reference document and restore only the three declared dirty
documentation paths from byte-exact preimages. Rollback is permitted only
while live post-state hashes match the accepted transaction. Any drift is
`BLOCK` and must preserve unrelated dirty state and historical evidence.
