---
name: adaptive-project-governance
description: Route software-project governance by project state and risk before repository writes or external actions. Use for governance diagnosis, adoption, structural planning, quality gates, global or host changes, target-project mutation, runtime, deployment, publication, pilot, or release work. Skip ordinary chat, translation, and unrelated informational requests.
---

# Adaptive Project Governance

Use this skill only for an explicitly authorized project. The global router decides
when to invoke it; project `AGENTS.md` files own project-specific commands and Gates.

## Adaptive route

| Level | Use when | Required action |
| --- | --- | --- |
| `NONE` | Non-project chat, translation, or unrelated informational work. | Skip APG. |
| `ROUTINE` | An adopted project has a bounded local write with no shared contract, dependency, external state, or delivery effect. | Read local rules and Git state, run `doctor`, then the fast or affected check. |
| `MODERATE` | Work changes multiple modules, shared behavior, a contract, dependency, architecture, or durable requirement. | Run `doctor`, prepare `plan-change`, obtain approval before `--apply`, then run focused or affected checks. |
| `HIGH` | Work touches a global directory, host or plugin, provider or network, target-project mutation, runtime, deployment, publication, pilot, or release. | Use a separate exact-scope transaction with owner approval, preimage evidence, CAS or equivalent drift guard, rollback, and independent review. |
| `CRITICAL` | Work is destructive or irreversible, or touches production data, secrets, identity, payment, or an uncontrolled external effect. | Apply the `HIGH` route plus a distinct independent verifier and fail closed on any ambiguity or drift. |

For an adopted project, enter through `doctor`; do not run `audit` again unless adoption
or a fresh audit was explicitly requested. For an unadopted project, run read-only
`audit`, then prepare `init` or additive Route B `adopt` preview as appropriate.

Preview is not authorization. Keep writes inside the approved scope, preserve unrelated
state, and never infer host, provider, runtime, deployment, publication, pilot, or release
acceptance from repository checks. This skill does not itself authorize any global or
external action. It is a local installable framework, not a resident daemon or a promise
of zero bugs.
