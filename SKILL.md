---
name: adaptive-project-governance
description: Audit-first governance controller for new and existing software, application, web, automation, and imported open-source projects. Use when starting a project, adopting an existing or previously refactored project, planning risky changes, running quality gates, diagnosing governance drift, or preventing regression as a codebase grows.
---

# Adaptive Project Governance

Use this skill only for an explicitly authorized project.

## Required workflow

1. Run a read-only `audit` first and review its evidence and receipt.
2. Obtain explicit project authorization for any write or adoption operation.
3. Use preview mode first; write operations require the explicit `--apply` flag.
4. Keep all writes inside the authorized project boundary and preserve rollback evidence.

The controller supports `audit`, `init`, `adopt`, `plan-change`, `check`, and `doctor`.
Do not perform global installation, global activation, user-wide configuration changes,
or writes to unrelated projects. This package is a local installable framework, not a
resident daemon and not a promise of zero bugs.
