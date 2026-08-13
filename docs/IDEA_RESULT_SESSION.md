# P3-I Idea-to-Result Session

P3-I is the unified session controller over the accepted P3-A through P3-H
contracts. Its ordinary-user promise is simple: provide an idea, then see the
current result, where the workflow is, and what happens next. Internal stage
digests and evidence remain available to operators without becoming a sequence
of routine approval requests for the user.

## Canonical Stage Chain

The session accepts only exact canonical bytes for these stages:

```text
P3-A intent decision
  -> P3-B project blueprint
  -> P3-C implementation readiness
  -> P3-F autonomous task plan
  -> P3-G goal-to-delivery lifecycle
  -> P3-H requirement trace and consolidation
```

P3-D and P3-E remain independent materialization transactions. P3-I does not
execute them, infer a physical root, or convert a logical plan into write
authority.

Every supplied stage is parsed by its existing canonical parser. P3-I records
the exact stage SHA-256 values and verifies every source relationship:

- P3-B binds the supplied P3-A digest;
- P3-C binds the supplied P3-B digest;
- P3-F binds the supplied P3-C digest;
- P3-G binds the supplied P3-F plan ID and digest;
- P3-H binds the supplied P3-G lifecycle run, plan, and digest.

A later stage without its predecessor, a changed digest, a changed plan ID, a
changed lifecycle run, noncanonical bytes, duplicate JSON fields, unknown
fields, or caller-authored derived state fails closed.

## Session States

| State | Meaning | User interruption |
| --- | --- | --- |
| `auto` | The next canonical local stage can be prepared without a consequential decision. | None. |
| `recommend` | A bounded recommendation is ready. | Review one actual choice. |
| `confirm` | The current source stage requires an explicit consequential decision or transaction approval. | Confirm that exact boundary. |
| `needs-evidence` | Required source, compatibility, review, or acceptance evidence is missing. | Supply or obtain the named evidence. |
| `block` | The source chain, authority, scope, or accepted result is unsafe or inconsistent. | Resolve the blocker before progress. |
| `complete` | P3-H accepted the exact combined result. | Review the final result. |

The first unresolved stage controls the session result. A P3-A record with
`recommended_decisions` remains `recommend` at the intent stage and requires
review; it is never silently upgraded to `auto`. A valid P3-A record with no
recommendation or confirmation automatically routes to blueprint generation.
An accepted readiness record routes to task planning. An accepted task plan
routes to the resumable P3-G
lifecycle. A completed lifecycle routes to P3-H consolidation. Only an exact
P3-H `accept` result returns session `complete`.

P3-I never invents approval, decision, requirement, task, artifact, evidence,
phase, runtime, deployment, publication, pilot, or release identifiers. Silence
and an earlier unrelated approval are not consent.

## Phase Isolation

The session phase is `planned` until an exact P3-G or P3-H phase record says
otherwise. Repository-local validation cannot infer runtime verification;
runtime cannot infer deployment; deployment cannot infer publication, pilot,
or release. Each later boundary retains its own ChangeRecord, authority,
evidence, rollback, and independent acceptance.

## Canonical And Side-Effect Boundary

P3-I is immutable, standard-library-only, and in memory. JSON is bounded,
closed, deterministic UTF-8 with sorted keys, canonical stage order, one
trailing LF, duplicate-key rejection, unsupported-constant rejection, and full
derived-state recomputation during render and parse.

The controller performs no filesystem mutation, subprocess, dependency
installation, provider/network call, credential access, Gate execution,
runtime launch, deployment, publication, promotion, pilot, release, or Git
operation. `execution_performed` is always `false`.

`idea_result_user_result` exposes only `status`, `result`, `next_step`, `stage`,
and `phase`. The canonical operator record retains the supplied stage records,
stage digests, reasons, and complete source chain.
