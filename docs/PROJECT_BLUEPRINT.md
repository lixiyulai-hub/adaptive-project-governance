# P3-B Project Blueprint Generator

APG's beginner-facing promise remains: **说出来一个想法，得到一个结果**.
P3-B advances that workflow by turning an accepted P3-A decision route into a
bounded project blueprint. The result is planning evidence for later project
materialization, implementation, verification, and delivery phases; it is not
yet a runnable project.

## Contract

`generate_project_blueprint` accepts one exact `IntentDecisionResult`. It first
renders the P3-A source canonically, embeds that source, records its SHA-256
digest, and derives exactly these sections in order:

1. `PROJECT_BRIEF`
2. `PRODUCT_PLAN`
3. `UX_FLOW`
4. `ARCHITECTURE`
5. `STACK_DECISION`
6. `TASK_GRAPH`
7. `QUALITY_PLAN`
8. `DEPLOYMENT_PLAN`

The normative representation is closed canonical UTF-8 JSON. Markdown is a
deterministic, human-readable projection and is not a second source format.
Parsing reparses the embedded P3-A record and recomputes the complete blueprint;
edited or caller-authored derived sections fail closed.

## Source gate

P3-B returns no partial blueprint when the source requires owner confirmation.
Both conditions are mandatory:

- `ready_for_blueprint` is `true`;
- `confirmation_required_decisions` is empty.

There is no `force`, `approved`, or missing-answer override. P2-enriched routes
also fail closed while P3-A cannot canonically serialize and recompute their
complete P2 source context. P3-B does not strip those decisions or reconstruct
missing stack evidence.

## Eight sections

| Section | Declarative content | What it does not claim |
|---|---|---|
| `PROJECT_BRIEF` | normalized project type, target, persona, goals, constraints, assumptions | complete requirements or owner acceptance |
| `PRODUCT_PLAN` | bounded outcomes, capabilities, and planning milestones | shipped features or market validation |
| `UX_FLOW` | coded actor, entry, steps, exit, and accessibility requirement | implemented screens, routes, or usability results |
| `ARCHITECTURE` | proposed logical components, boundaries, and data-flow codes | physical files, deployed resources, or running services |
| `STACK_DECISION` | architecture requirements and missing-evidence state | a selected framework, provider, database, package, or version |
| `TASK_GRAPH` | deterministic planned tasks and dependencies | task execution or downstream project mutation |
| `QUALITY_PLAN` | required checks and acceptance evidence | a Gate run, pass result, or release acceptance |
| `DEPLOYMENT_PLAN` | delivery prerequisites, artifacts, rollback, and verification requirements | deployment authority, endpoint existence, publication, or runtime acceptance |

`RECOMMEND` decisions remain explicit assumptions. Unknown facts remain
`unknown` or `needs-evidence`. P3-B v1 is always
`ready_for_implementation=false`; quality execution remains `not-run`, and
deployment authority remains `not-authorized`.

## Canonical and security rules

- Records are immutable and use closed enums, exact tuple fields, unique IDs,
  deterministic ordering, bounded codes, and bounded evidence references.
- JSON uses sorted keys, compact separators, NFC strings, and one trailing LF.
- Duplicate keys, unknown fields, unsupported values, non-canonical bytes,
  oversized payloads, unsafe locators, and secret-shaped values are rejected.
- No field retains a raw idea, prompt, transcript, model message, credential,
  customer record, or unbounded free-form text.
- The task graph is deterministic, acyclic, topologically ordered, and contains
  planned actions only.

## Side-effect boundary

Generation, parsing, and rendering are standard-library-only and in-memory.
They perform no project file creation, filesystem discovery or write, subprocess
execution, provider or network call, dependency discovery or installation,
approval creation, Gate selection or execution, deployment, publication,
promotion, host/runtime launch, downstream mutation, Git operation, or release.

Public publication, global promotion, host/runtime activation, provider/network
acceptance, downstream pilot acceptance, deployment, and release remain
separate transactions with separate authority, evidence, Gates, rollback, and
acceptance.

## Later handoff

P3-B provides the closed plan/evidence bundle that a later project-materializer
phase may consume. That later phase must have its own ChangeRecord and must bind
the exact blueprint digest, downstream root, changed paths, baseline, approval,
Gates, and rollback before it writes or runs anything.
