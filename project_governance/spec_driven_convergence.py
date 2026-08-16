"""Deterministic specification convergence and beginner prompt routing."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath
import re
from typing import Sequence

from .project_materialization_apply import (
    ActionContext,
    AuthorizationClass,
    assess_action,
)
from .storage import canonical_json_bytes


SPEC_DRIVEN_CONVERGENCE_SCHEMA_VERSION = "1.0"
MAX_REQUIREMENTS = 128
MAX_TASKS = 256
MAX_CODES = 32
MAX_REFERENCES = 32
MAX_QUESTIONS = 5
MAX_FINDINGS = 512
MAX_CONVERGENCE_ITERATIONS = 8

_CODE = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}\Z")
_WINDOWS_DRIVE = re.compile(r"[A-Za-z]:")


class SpecDrivenConvergenceError(ValueError):
    """Raised when a specification convergence record is unsafe or malformed."""


class PromptCommand(str, Enum):
    PLAN = "/plan"
    IMPLEMENT = "/implement"
    CLARIFY = "/clarify"
    CHECKLIST = "/checklist"
    ANALYZE = "/analyze"
    CONVERGE = "/converge"


class PromptAuthority(str, Enum):
    AUTO = "auto"
    CONFIRM = "confirm"
    BLOCK = "block"


class ClarificationCategory(str, Enum):
    ACCEPTANCE = "acceptance"
    SCOPE = "scope"
    BOUNDARY = "boundary"
    DEPENDENCY = "dependency"
    DATA = "data"
    INTEGRATION = "integration"
    UX = "ux"
    ERROR = "error"
    PERFORMANCE = "performance"
    TERMINOLOGY = "terminology"
    EVIDENCE = "evidence"
    OTHER = "other"


class RequirementChecklistState(str, Enum):
    PASS = "pass"
    NEEDS_CLARIFICATION = "needs-clarification"


class PlanningAnalysisState(str, Enum):
    PASS = "pass"
    NEEDS_REVISION = "needs-revision"
    BLOCK = "block"


class FindingSeverity(str, Enum):
    REVISE = "revise"
    BLOCK = "block"


class ConvergenceState(str, Enum):
    COMPLETE = "complete"
    CONTINUE = "continue"
    CONFIRM = "confirm"
    BLOCK = "block"


def _code(value: object, label: str) -> str:
    if type(value) is not str or not _CODE.fullmatch(value):
        raise SpecDrivenConvergenceError(f"{label} must be a bounded stable code")
    return value


def _safe_relative_path(value: str) -> bool:
    if "\\" in value or value.startswith("/") or _WINDOWS_DRIVE.match(value):
        return False
    if "://" in value or ":" in value or "?" in value or "#" in value:
        return False
    parts = value.split("/")
    if len(parts) < 2 or any(part in ("", ".", "..") for part in parts):
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and tuple(path.parts) == tuple(parts)


def _reference(value: object, label: str) -> str:
    if type(value) is not str:
        raise SpecDrivenConvergenceError(
            f"{label} must be a stable code or contained relative path"
        )
    if _CODE.fullmatch(value) or _safe_relative_path(value):
        return value
    raise SpecDrivenConvergenceError(
        f"{label} must be a stable code or contained relative path"
    )


def _codes(
    values: object,
    label: str,
    maximum: int = MAX_CODES,
    *,
    allow_empty: bool = True,
) -> tuple[str, ...]:
    if type(values) is not tuple or len(values) > maximum:
        raise SpecDrivenConvergenceError(f"{label} must be a bounded tuple")
    if not allow_empty and not values:
        raise SpecDrivenConvergenceError(f"{label} must not be empty")
    normalized = tuple(_code(item, f"{label}[{index}]") for index, item in enumerate(values))
    if normalized != tuple(sorted(set(normalized))):
        raise SpecDrivenConvergenceError(f"{label} must use canonical unique order")
    return normalized


def _references(
    values: object,
    label: str,
    maximum: int = MAX_REFERENCES,
    *,
    allow_empty: bool = True,
) -> tuple[str, ...]:
    if type(values) is not tuple or len(values) > maximum:
        raise SpecDrivenConvergenceError(f"{label} must be a bounded tuple")
    if not allow_empty and not values:
        raise SpecDrivenConvergenceError(f"{label} must not be empty")
    normalized = tuple(
        _reference(item, f"{label}[{index}]") for index, item in enumerate(values)
    )
    if normalized != tuple(sorted(set(normalized))):
        raise SpecDrivenConvergenceError(f"{label} must use canonical unique order")
    return normalized


def _paths(values: object, label: str) -> tuple[str, ...]:
    if type(values) is not tuple or len(values) > MAX_REFERENCES:
        raise SpecDrivenConvergenceError(f"{label} must be a bounded tuple")
    normalized: list[str] = []
    for index, item in enumerate(values):
        if type(item) is not str or not _safe_relative_path(item):
            raise SpecDrivenConvergenceError(
                f"{label}[{index}] must be a contained relative path"
            )
        normalized.append(item)
    result = tuple(normalized)
    if result != tuple(sorted(set(result))):
        raise SpecDrivenConvergenceError(f"{label} must use canonical unique order")
    return result


@dataclass(frozen=True)
class SpecRequirement:
    requirement_id: str
    statement_code: str
    acceptance_codes: tuple[str, ...]
    dependency_ids: tuple[str, ...]
    ambiguity_codes: tuple[str, ...]
    boundary_codes: tuple[str, ...]
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self) is not SpecRequirement:
            raise SpecDrivenConvergenceError("SpecRequirement subclasses are not accepted")
        _code(self.requirement_id, "requirement_id")
        _code(self.statement_code, "statement_code")
        _codes(self.acceptance_codes, "acceptance_codes")
        dependencies = _codes(self.dependency_ids, "dependency_ids")
        if self.requirement_id in dependencies:
            raise SpecDrivenConvergenceError("a requirement cannot depend on itself")
        _codes(self.ambiguity_codes, "ambiguity_codes")
        _codes(self.boundary_codes, "boundary_codes")
        _references(self.evidence_refs, "evidence_refs")


@dataclass(frozen=True)
class SpecTask:
    task_id: str
    requirement_ids: tuple[str, ...]
    dependency_ids: tuple[str, ...]
    output_paths: tuple[str, ...]
    gate_ids: tuple[str, ...]
    rollback_ref: str | None

    def __post_init__(self) -> None:
        if type(self) is not SpecTask:
            raise SpecDrivenConvergenceError("SpecTask subclasses are not accepted")
        _code(self.task_id, "task_id")
        _codes(self.requirement_ids, "requirement_ids")
        dependencies = _codes(self.dependency_ids, "dependency_ids")
        if self.task_id in dependencies:
            raise SpecDrivenConvergenceError("a task cannot depend on itself")
        _paths(self.output_paths, "output_paths")
        _codes(self.gate_ids, "gate_ids")
        if self.rollback_ref is not None:
            _reference(self.rollback_ref, "rollback_ref")


def _canonical_requirements(values: Sequence[SpecRequirement]) -> tuple[SpecRequirement, ...]:
    if not isinstance(values, (tuple, list)) or len(values) > MAX_REQUIREMENTS:
        raise SpecDrivenConvergenceError("requirements must be a bounded sequence")
    records = tuple(values)
    if any(type(item) is not SpecRequirement for item in records):
        raise SpecDrivenConvergenceError("requirements must contain exact records")
    identifiers = tuple(item.requirement_id for item in records)
    if identifiers != tuple(sorted(set(identifiers))):
        raise SpecDrivenConvergenceError("requirements must use canonical unique order")
    return records


def _canonical_tasks(values: Sequence[SpecTask]) -> tuple[SpecTask, ...]:
    if not isinstance(values, (tuple, list)) or len(values) > MAX_TASKS:
        raise SpecDrivenConvergenceError("tasks must be a bounded sequence")
    records = tuple(values)
    if any(type(item) is not SpecTask for item in records):
        raise SpecDrivenConvergenceError("tasks must contain exact records")
    identifiers = tuple(item.task_id for item in records)
    if identifiers != tuple(sorted(set(identifiers))):
        raise SpecDrivenConvergenceError("tasks must use canonical unique order")
    return records


@dataclass(frozen=True)
class ClarificationQuestion:
    question_id: str
    requirement_id: str
    category: ClarificationCategory
    reason_code: str
    impact_code: str
    recommendation_code: str

    def __post_init__(self) -> None:
        if type(self) is not ClarificationQuestion:
            raise SpecDrivenConvergenceError(
                "ClarificationQuestion subclasses are not accepted"
            )
        _code(self.question_id, "question_id")
        _code(self.requirement_id, "requirement_id")
        if type(self.category) is not ClarificationCategory:
            raise SpecDrivenConvergenceError("category must be a ClarificationCategory")
        _code(self.reason_code, "reason_code")
        _code(self.impact_code, "impact_code")
        _code(self.recommendation_code, "recommendation_code")


@dataclass(frozen=True)
class ClarificationAssessment:
    schema_version: str
    questions: tuple[ClarificationQuestion, ...]
    unresolved_requirement_ids: tuple[str, ...]
    ready_for_plan: bool

    def __post_init__(self) -> None:
        if self.schema_version != SPEC_DRIVEN_CONVERGENCE_SCHEMA_VERSION:
            raise SpecDrivenConvergenceError("unsupported clarification schema_version")
        if type(self.questions) is not tuple or len(self.questions) > MAX_QUESTIONS:
            raise SpecDrivenConvergenceError("questions exceed the five-question bound")
        if any(type(item) is not ClarificationQuestion for item in self.questions):
            raise SpecDrivenConvergenceError("questions contain invalid records")
        question_ids = tuple(item.question_id for item in self.questions)
        if len(set(question_ids)) != len(question_ids):
            raise SpecDrivenConvergenceError("questions contain duplicate IDs")
        unresolved = _codes(
            self.unresolved_requirement_ids,
            "unresolved_requirement_ids",
            MAX_REQUIREMENTS,
        )
        expected = tuple(sorted({item.requirement_id for item in self.questions}))
        if unresolved != expected:
            raise SpecDrivenConvergenceError(
                "unresolved requirements must match the selected questions"
            )
        if type(self.ready_for_plan) is not bool or self.ready_for_plan != (not self.questions):
            raise SpecDrivenConvergenceError("ready_for_plan is inconsistent")


_CATEGORY_PRIORITY = {
    ClarificationCategory.ACCEPTANCE: 0,
    ClarificationCategory.SCOPE: 1,
    ClarificationCategory.BOUNDARY: 2,
    ClarificationCategory.DEPENDENCY: 3,
    ClarificationCategory.DATA: 4,
    ClarificationCategory.INTEGRATION: 5,
    ClarificationCategory.UX: 6,
    ClarificationCategory.ERROR: 7,
    ClarificationCategory.PERFORMANCE: 8,
    ClarificationCategory.TERMINOLOGY: 9,
    ClarificationCategory.EVIDENCE: 10,
    ClarificationCategory.OTHER: 11,
}


def _category(code: str) -> ClarificationCategory:
    for token, category in (
        ("acceptance", ClarificationCategory.ACCEPTANCE),
        ("scope", ClarificationCategory.SCOPE),
        ("boundary", ClarificationCategory.BOUNDARY),
        ("dependency", ClarificationCategory.DEPENDENCY),
        ("data", ClarificationCategory.DATA),
        ("integration", ClarificationCategory.INTEGRATION),
        ("ux", ClarificationCategory.UX),
        ("error", ClarificationCategory.ERROR),
        ("performance", ClarificationCategory.PERFORMANCE),
        ("terminology", ClarificationCategory.TERMINOLOGY),
        ("evidence", ClarificationCategory.EVIDENCE),
    ):
        if token in code:
            return category
    return ClarificationCategory.OTHER


def _question(
    requirement: SpecRequirement,
    category: ClarificationCategory,
    reason: str,
) -> ClarificationQuestion:
    suffix = reason.replace("ambiguity.", "").replace("missing-", "")
    return ClarificationQuestion(
        question_id=f"question.{requirement.requirement_id}.{category.value}.{suffix}",
        requirement_id=requirement.requirement_id,
        category=category,
        reason_code=reason,
        impact_code=f"impact.{category.value}",
        recommendation_code=f"recommendation.resolve-{category.value}",
    )


def clarify_requirements(
    requirements: Sequence[SpecRequirement],
) -> ClarificationAssessment:
    records = _canonical_requirements(requirements)
    known = {item.requirement_id for item in records}
    candidates: dict[str, ClarificationQuestion] = {}
    for requirement in records:
        if not requirement.acceptance_codes:
            item = _question(
                requirement,
                ClarificationCategory.ACCEPTANCE,
                "missing-acceptance",
            )
            candidates[item.question_id] = item
        if not requirement.evidence_refs:
            item = _question(
                requirement,
                ClarificationCategory.EVIDENCE,
                "missing-evidence",
            )
            candidates[item.question_id] = item
        for dependency in requirement.dependency_ids:
            if dependency not in known:
                item = _question(
                    requirement,
                    ClarificationCategory.DEPENDENCY,
                    "missing-dependency",
                )
                candidates[item.question_id] = item
        for ambiguity in requirement.ambiguity_codes:
            category = _category(ambiguity)
            item = _question(requirement, category, ambiguity)
            candidates[item.question_id] = item
    ordered = tuple(
        sorted(
            candidates.values(),
            key=lambda item: (
                _CATEGORY_PRIORITY[item.category],
                item.requirement_id,
                item.question_id,
            ),
        )[:MAX_QUESTIONS]
    )
    return ClarificationAssessment(
        schema_version=SPEC_DRIVEN_CONVERGENCE_SCHEMA_VERSION,
        questions=ordered,
        unresolved_requirement_ids=tuple(
            sorted({item.requirement_id for item in ordered})
        ),
        ready_for_plan=not ordered,
    )


@dataclass(frozen=True)
class RequirementChecklistFinding:
    finding_id: str
    requirement_id: str
    check_code: str
    reason_code: str

    def __post_init__(self) -> None:
        if type(self) is not RequirementChecklistFinding:
            raise SpecDrivenConvergenceError(
                "RequirementChecklistFinding subclasses are not accepted"
            )
        _code(self.finding_id, "finding_id")
        _code(self.requirement_id, "requirement_id")
        _code(self.check_code, "check_code")
        _code(self.reason_code, "reason_code")


@dataclass(frozen=True)
class RequirementChecklist:
    schema_version: str
    state: RequirementChecklistState
    evaluated_requirement_ids: tuple[str, ...]
    findings: tuple[RequirementChecklistFinding, ...]

    def __post_init__(self) -> None:
        if self.schema_version != SPEC_DRIVEN_CONVERGENCE_SCHEMA_VERSION:
            raise SpecDrivenConvergenceError("unsupported checklist schema_version")
        if type(self.state) is not RequirementChecklistState:
            raise SpecDrivenConvergenceError("state must be a RequirementChecklistState")
        _codes(
            self.evaluated_requirement_ids,
            "evaluated_requirement_ids",
            MAX_REQUIREMENTS,
        )
        if type(self.findings) is not tuple or len(self.findings) > MAX_FINDINGS:
            raise SpecDrivenConvergenceError("findings must be bounded")
        if any(type(item) is not RequirementChecklistFinding for item in self.findings):
            raise SpecDrivenConvergenceError("findings contain invalid records")
        identifiers = tuple(item.finding_id for item in self.findings)
        if identifiers != tuple(sorted(set(identifiers))):
            raise SpecDrivenConvergenceError("findings must use canonical unique order")
        expected = (
            RequirementChecklistState.PASS
            if not self.findings
            else RequirementChecklistState.NEEDS_CLARIFICATION
        )
        if self.state is not expected:
            raise SpecDrivenConvergenceError("checklist state is inconsistent")


def evaluate_requirement_checklist(
    requirements: Sequence[SpecRequirement],
) -> RequirementChecklist:
    records = _canonical_requirements(requirements)
    known = {item.requirement_id for item in records}
    findings: list[RequirementChecklistFinding] = []

    def add(requirement: SpecRequirement, check: str, reason: str) -> None:
        findings.append(
            RequirementChecklistFinding(
                finding_id=f"finding.{requirement.requirement_id}.{check}",
                requirement_id=requirement.requirement_id,
                check_code=check,
                reason_code=reason,
            )
        )

    for requirement in records:
        if not requirement.acceptance_codes:
            add(requirement, "acceptance", "acceptance-missing")
        if not requirement.evidence_refs:
            add(requirement, "evidence", "evidence-missing")
        if requirement.ambiguity_codes:
            add(requirement, "ambiguity", "ambiguity-unresolved")
        if any(item not in known for item in requirement.dependency_ids):
            add(requirement, "dependency", "dependency-unknown")
        if "boundary.unknown" in requirement.boundary_codes:
            add(requirement, "boundary", "boundary-unresolved")

    ordered = tuple(sorted(findings, key=lambda item: item.finding_id))
    return RequirementChecklist(
        schema_version=SPEC_DRIVEN_CONVERGENCE_SCHEMA_VERSION,
        state=(
            RequirementChecklistState.PASS
            if not ordered
            else RequirementChecklistState.NEEDS_CLARIFICATION
        ),
        evaluated_requirement_ids=tuple(item.requirement_id for item in records),
        findings=ordered,
    )


@dataclass(frozen=True)
class PlanningFinding:
    finding_id: str
    severity: FindingSeverity
    reason_code: str
    subject_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self) is not PlanningFinding:
            raise SpecDrivenConvergenceError("PlanningFinding subclasses are not accepted")
        _code(self.finding_id, "finding_id")
        if type(self.severity) is not FindingSeverity:
            raise SpecDrivenConvergenceError("severity must be a FindingSeverity")
        _code(self.reason_code, "reason_code")
        _codes(self.subject_ids, "subject_ids", MAX_TASKS, allow_empty=False)


@dataclass(frozen=True)
class PlanningConsistencyAnalysis:
    schema_version: str
    state: PlanningAnalysisState
    requirement_ids: tuple[str, ...]
    task_ids: tuple[str, ...]
    findings: tuple[PlanningFinding, ...]
    ready_for_implementation: bool

    def __post_init__(self) -> None:
        if self.schema_version != SPEC_DRIVEN_CONVERGENCE_SCHEMA_VERSION:
            raise SpecDrivenConvergenceError("unsupported planning schema_version")
        if type(self.state) is not PlanningAnalysisState:
            raise SpecDrivenConvergenceError("state must be a PlanningAnalysisState")
        _codes(self.requirement_ids, "requirement_ids", MAX_REQUIREMENTS)
        _codes(self.task_ids, "task_ids", MAX_TASKS)
        if type(self.findings) is not tuple or len(self.findings) > MAX_FINDINGS:
            raise SpecDrivenConvergenceError("findings must be bounded")
        if any(type(item) is not PlanningFinding for item in self.findings):
            raise SpecDrivenConvergenceError("findings contain invalid records")
        identifiers = tuple(item.finding_id for item in self.findings)
        if identifiers != tuple(sorted(set(identifiers))):
            raise SpecDrivenConvergenceError("findings must use canonical unique order")
        if any(item.severity is FindingSeverity.BLOCK for item in self.findings):
            expected = PlanningAnalysisState.BLOCK
        elif self.findings:
            expected = PlanningAnalysisState.NEEDS_REVISION
        else:
            expected = PlanningAnalysisState.PASS
        if self.state is not expected:
            raise SpecDrivenConvergenceError("planning state is inconsistent")
        if type(self.ready_for_implementation) is not bool:
            raise SpecDrivenConvergenceError("ready_for_implementation must be boolean")
        if self.ready_for_implementation != (self.state is PlanningAnalysisState.PASS):
            raise SpecDrivenConvergenceError("implementation readiness is inconsistent")


def _paths_overlap(left: str, right: str) -> bool:
    left_key = left.casefold().rstrip("/")
    right_key = right.casefold().rstrip("/")
    return (
        left_key == right_key
        or left_key.startswith(right_key + "/")
        or right_key.startswith(left_key + "/")
    )


def _cycle_task_ids(tasks: tuple[SpecTask, ...]) -> tuple[str, ...]:
    known = {item.task_id for item in tasks}
    indegree = {item.task_id: 0 for item in tasks}
    dependents = {item.task_id: [] for item in tasks}
    for task in tasks:
        for dependency in task.dependency_ids:
            if dependency in known:
                indegree[task.task_id] += 1
                dependents[dependency].append(task.task_id)
    ready = sorted(item for item, count in indegree.items() if count == 0)
    visited: list[str] = []
    while ready:
        current = ready.pop(0)
        visited.append(current)
        for dependent in sorted(dependents[current]):
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                ready.append(dependent)
                ready.sort()
    if len(visited) == len(tasks):
        return ()
    return tuple(sorted(set(known) - set(visited)))


def analyze_planning_consistency(
    requirements: Sequence[SpecRequirement],
    tasks: Sequence[SpecTask],
) -> PlanningConsistencyAnalysis:
    requirement_records = _canonical_requirements(requirements)
    task_records = _canonical_tasks(tasks)
    requirement_ids = {item.requirement_id for item in requirement_records}
    task_ids = {item.task_id for item in task_records}
    findings: list[PlanningFinding] = []

    def add(
        identifier: str,
        severity: FindingSeverity,
        reason: str,
        subjects: tuple[str, ...],
    ) -> None:
        findings.append(
            PlanningFinding(identifier, severity, reason, tuple(sorted(set(subjects))))
        )

    covered = {item for task in task_records for item in task.requirement_ids}
    for requirement_id in sorted(requirement_ids - covered):
        add(
            f"finding.requirement.{requirement_id}.uncovered",
            FindingSeverity.REVISE,
            "requirement-uncovered",
            (requirement_id,),
        )
    for task in task_records:
        if not task.requirement_ids:
            add(
                f"finding.task.{task.task_id}.orphan",
                FindingSeverity.REVISE,
                "task-orphan",
                (task.task_id,),
            )
        unknown_requirements = tuple(
            sorted(set(task.requirement_ids) - requirement_ids)
        )
        if unknown_requirements:
            add(
                f"finding.task.{task.task_id}.unknown-requirement",
                FindingSeverity.BLOCK,
                "task-requirement-unknown",
                (task.task_id,) + unknown_requirements,
            )
        unknown_dependencies = tuple(sorted(set(task.dependency_ids) - task_ids))
        if unknown_dependencies:
            add(
                f"finding.task.{task.task_id}.unknown-dependency",
                FindingSeverity.BLOCK,
                "task-dependency-unknown",
                (task.task_id,) + unknown_dependencies,
            )
        if not task.gate_ids:
            add(
                f"finding.task.{task.task_id}.gates",
                FindingSeverity.REVISE,
                "task-gates-missing",
                (task.task_id,),
            )
        if task.rollback_ref is None:
            add(
                f"finding.task.{task.task_id}.rollback",
                FindingSeverity.REVISE,
                "task-rollback-missing",
                (task.task_id,),
            )
        if not task.output_paths:
            add(
                f"finding.task.{task.task_id}.outputs",
                FindingSeverity.REVISE,
                "task-outputs-missing",
                (task.task_id,),
            )

    cycle_ids = _cycle_task_ids(task_records)
    if cycle_ids:
        add(
            "finding.task-graph.cycle",
            FindingSeverity.BLOCK,
            "task-dependency-cycle",
            cycle_ids,
        )

    for left_index, left in enumerate(task_records):
        for right in task_records[left_index + 1 :]:
            if any(
                _paths_overlap(left_path, right_path)
                for left_path in left.output_paths
                for right_path in right.output_paths
            ):
                add(
                    f"finding.output-ownership.{left.task_id}.{right.task_id}",
                    FindingSeverity.REVISE,
                    "output-ownership-overlap",
                    (left.task_id, right.task_id),
                )

    ordered = tuple(sorted(findings, key=lambda item: item.finding_id))
    if any(item.severity is FindingSeverity.BLOCK for item in ordered):
        state = PlanningAnalysisState.BLOCK
    elif ordered:
        state = PlanningAnalysisState.NEEDS_REVISION
    else:
        state = PlanningAnalysisState.PASS
    return PlanningConsistencyAnalysis(
        schema_version=SPEC_DRIVEN_CONVERGENCE_SCHEMA_VERSION,
        state=state,
        requirement_ids=tuple(item.requirement_id for item in requirement_records),
        task_ids=tuple(item.task_id for item in task_records),
        findings=ordered,
        ready_for_implementation=state is PlanningAnalysisState.PASS,
    )


@dataclass(frozen=True)
class PromptExecutionContext:
    command: PromptCommand
    action_context: ActionContext
    implementation_ready: bool = False
    exact_root_bound: bool = False
    write_scope_bound: bool = False
    gates_bound: bool = False
    rollback_bound: bool = False
    git_mutation: bool = False
    release: bool = False

    def __post_init__(self) -> None:
        if type(self) is not PromptExecutionContext:
            raise SpecDrivenConvergenceError(
                "PromptExecutionContext subclasses are not accepted"
            )
        if type(self.command) is not PromptCommand:
            raise SpecDrivenConvergenceError("command must be a PromptCommand")
        if type(self.action_context) is not ActionContext:
            raise SpecDrivenConvergenceError("action_context must be an ActionContext")
        for name, value in vars(self).items():
            if name in ("command", "action_context"):
                continue
            if type(value) is not bool:
                raise SpecDrivenConvergenceError(f"{name} must be a boolean")


@dataclass(frozen=True)
class PromptExecutionRoute:
    schema_version: str
    command: PromptCommand
    authority: PromptAuthority
    planning_authority: bool
    execution_authority: bool
    requires_owner_input: bool
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != SPEC_DRIVEN_CONVERGENCE_SCHEMA_VERSION:
            raise SpecDrivenConvergenceError("unsupported route schema_version")
        if type(self.command) is not PromptCommand:
            raise SpecDrivenConvergenceError("command must be a PromptCommand")
        if type(self.authority) is not PromptAuthority:
            raise SpecDrivenConvergenceError("authority must be a PromptAuthority")
        for name in (
            "planning_authority",
            "execution_authority",
            "requires_owner_input",
        ):
            if type(getattr(self, name)) is not bool:
                raise SpecDrivenConvergenceError(f"{name} must be a boolean")
        _codes(self.reason_codes, "reason_codes", MAX_CODES, allow_empty=False)
        if self.authority is PromptAuthority.AUTO and self.requires_owner_input:
            raise SpecDrivenConvergenceError("AUTO cannot require owner input")
        if self.authority is PromptAuthority.CONFIRM and not self.requires_owner_input:
            raise SpecDrivenConvergenceError("CONFIRM must require owner input")
        if self.authority is PromptAuthority.BLOCK and (
            self.planning_authority or self.execution_authority
        ):
            raise SpecDrivenConvergenceError("BLOCK cannot grant authority")
        if self.command is not PromptCommand.IMPLEMENT and self.execution_authority:
            raise SpecDrivenConvergenceError("only /implement may grant execution authority")


_PLANNING_COMMANDS = frozenset(
    {
        PromptCommand.PLAN,
        PromptCommand.CLARIFY,
        PromptCommand.CHECKLIST,
        PromptCommand.ANALYZE,
        PromptCommand.CONVERGE,
    }
)


def route_prompt_execution(context: PromptExecutionContext) -> PromptExecutionRoute:
    if type(context) is not PromptExecutionContext:
        raise SpecDrivenConvergenceError("context must be an exact PromptExecutionContext")
    if context.command in _PLANNING_COMMANDS:
        return PromptExecutionRoute(
            schema_version=SPEC_DRIVEN_CONVERGENCE_SCHEMA_VERSION,
            command=context.command,
            authority=PromptAuthority.AUTO,
            planning_authority=True,
            execution_authority=False,
            requires_owner_input=False,
            reason_codes=("explicit-beginner-planning-command",),
        )

    blockers: list[str] = []
    if not context.implementation_ready:
        blockers.append("implementation-not-ready")
    if not context.exact_root_bound:
        blockers.append("exact-root-required")
    if not context.write_scope_bound:
        blockers.append("write-scope-required")
    if not context.gates_bound:
        blockers.append("gates-required")
    if not context.rollback_bound:
        blockers.append("rollback-required")
    assessment = assess_action(context.action_context)
    if assessment.classification is AuthorizationClass.BLOCK:
        blockers.extend(assessment.reason_codes)
    if blockers:
        return PromptExecutionRoute(
            schema_version=SPEC_DRIVEN_CONVERGENCE_SCHEMA_VERSION,
            command=context.command,
            authority=PromptAuthority.BLOCK,
            planning_authority=False,
            execution_authority=False,
            requires_owner_input=False,
            reason_codes=tuple(sorted(set(blockers))),
        )

    confirmation = list(
        assessment.reason_codes
        if assessment.classification is AuthorizationClass.CONFIRM
        else ()
    )
    if context.git_mutation:
        confirmation.append("git-mutation")
    if context.release:
        confirmation.append("release")
    if confirmation:
        return PromptExecutionRoute(
            schema_version=SPEC_DRIVEN_CONVERGENCE_SCHEMA_VERSION,
            command=context.command,
            authority=PromptAuthority.CONFIRM,
            planning_authority=True,
            execution_authority=False,
            requires_owner_input=True,
            reason_codes=tuple(sorted(set(confirmation))),
        )

    reasons = ["explicit-beginner-implement-command", "bounded-safe-local-path"]
    if assessment.classification is AuthorizationClass.RECOMMEND:
        reasons.append("safe-default-selected")
    return PromptExecutionRoute(
        schema_version=SPEC_DRIVEN_CONVERGENCE_SCHEMA_VERSION,
        command=context.command,
        authority=PromptAuthority.AUTO,
        planning_authority=True,
        execution_authority=True,
        requires_owner_input=False,
        reason_codes=tuple(sorted(reasons)),
    )


@dataclass(frozen=True)
class ConvergenceInput:
    iteration: int
    max_iterations: int
    failed_acceptance_ids: tuple[str, ...]
    inconclusive_gate_ids: tuple[str, ...]
    blocking_codes: tuple[str, ...]
    consequential_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self) is not ConvergenceInput:
            raise SpecDrivenConvergenceError("ConvergenceInput subclasses are not accepted")
        if type(self.iteration) is not int or self.iteration < 0:
            raise SpecDrivenConvergenceError("iteration must be a non-negative integer")
        if (
            type(self.max_iterations) is not int
            or self.max_iterations < 1
            or self.max_iterations > MAX_CONVERGENCE_ITERATIONS
        ):
            raise SpecDrivenConvergenceError("max_iterations is outside its bound")
        _codes(self.failed_acceptance_ids, "failed_acceptance_ids", MAX_REQUIREMENTS)
        _codes(self.inconclusive_gate_ids, "inconclusive_gate_ids", MAX_CODES)
        _codes(self.blocking_codes, "blocking_codes", MAX_CODES)
        _codes(self.consequential_codes, "consequential_codes", MAX_CODES)


@dataclass(frozen=True)
class ConvergencePlan:
    schema_version: str
    state: ConvergenceState
    iteration: int
    max_iterations: int
    auto_continue: bool
    next_action_codes: tuple[str, ...]
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != SPEC_DRIVEN_CONVERGENCE_SCHEMA_VERSION:
            raise SpecDrivenConvergenceError("unsupported convergence schema_version")
        if type(self.state) is not ConvergenceState:
            raise SpecDrivenConvergenceError("state must be a ConvergenceState")
        if type(self.iteration) is not int or type(self.max_iterations) is not int:
            raise SpecDrivenConvergenceError("iteration values must be integers")
        if type(self.auto_continue) is not bool:
            raise SpecDrivenConvergenceError("auto_continue must be boolean")
        _codes(self.next_action_codes, "next_action_codes", MAX_CODES)
        _codes(self.reason_codes, "reason_codes", MAX_CODES, allow_empty=False)
        if self.auto_continue != (self.state is ConvergenceState.CONTINUE):
            raise SpecDrivenConvergenceError("auto_continue is inconsistent")


def build_convergence_plan(value: ConvergenceInput) -> ConvergencePlan:
    if type(value) is not ConvergenceInput:
        raise SpecDrivenConvergenceError("value must be an exact ConvergenceInput")
    if value.blocking_codes:
        state = ConvergenceState.BLOCK
        reasons = value.blocking_codes
        actions: tuple[str, ...] = ()
    elif not value.failed_acceptance_ids and not value.inconclusive_gate_ids:
        state = ConvergenceState.COMPLETE
        reasons = ("all-acceptance-and-gates-pass",)
        actions = ()
    elif value.consequential_codes:
        state = ConvergenceState.CONFIRM
        reasons = value.consequential_codes
        actions = ()
    elif value.iteration >= value.max_iterations:
        state = ConvergenceState.BLOCK
        reasons = ("convergence-budget-exhausted",)
        actions = ()
    else:
        state = ConvergenceState.CONTINUE
        reasons = ("bounded-remediation-available",)
        actions = tuple(
            sorted(
                {f"resolve.{item}" for item in value.failed_acceptance_ids}
                | {f"measure.{item}" for item in value.inconclusive_gate_ids}
            )
        )
    return ConvergencePlan(
        schema_version=SPEC_DRIVEN_CONVERGENCE_SCHEMA_VERSION,
        state=state,
        iteration=value.iteration,
        max_iterations=value.max_iterations,
        auto_continue=state is ConvergenceState.CONTINUE,
        next_action_codes=actions,
        reason_codes=tuple(sorted(set(reasons))),
    )


def render_clarification_assessment(value: ClarificationAssessment) -> bytes:
    if type(value) is not ClarificationAssessment:
        raise SpecDrivenConvergenceError("value must be a ClarificationAssessment")
    return canonical_json_bytes(value)


def render_requirement_checklist(value: RequirementChecklist) -> bytes:
    if type(value) is not RequirementChecklist:
        raise SpecDrivenConvergenceError("value must be a RequirementChecklist")
    return canonical_json_bytes(value)


def render_planning_consistency(value: PlanningConsistencyAnalysis) -> bytes:
    if type(value) is not PlanningConsistencyAnalysis:
        raise SpecDrivenConvergenceError("value must be a PlanningConsistencyAnalysis")
    return canonical_json_bytes(value)


def render_prompt_execution_route(value: PromptExecutionRoute) -> bytes:
    if type(value) is not PromptExecutionRoute:
        raise SpecDrivenConvergenceError("value must be a PromptExecutionRoute")
    return canonical_json_bytes(value)


def render_convergence_plan(value: ConvergencePlan) -> bytes:
    if type(value) is not ConvergencePlan:
        raise SpecDrivenConvergenceError("value must be a ConvergencePlan")
    return canonical_json_bytes(value)


__all__ = [
    "SPEC_DRIVEN_CONVERGENCE_SCHEMA_VERSION",
    "SpecDrivenConvergenceError",
    "PromptCommand",
    "PromptAuthority",
    "ClarificationCategory",
    "RequirementChecklistState",
    "PlanningAnalysisState",
    "FindingSeverity",
    "ConvergenceState",
    "SpecRequirement",
    "SpecTask",
    "ClarificationQuestion",
    "ClarificationAssessment",
    "RequirementChecklistFinding",
    "RequirementChecklist",
    "PlanningFinding",
    "PlanningConsistencyAnalysis",
    "PromptExecutionContext",
    "PromptExecutionRoute",
    "ConvergenceInput",
    "ConvergencePlan",
    "clarify_requirements",
    "evaluate_requirement_checklist",
    "analyze_planning_consistency",
    "route_prompt_execution",
    "build_convergence_plan",
    "render_clarification_assessment",
    "render_requirement_checklist",
    "render_planning_consistency",
    "render_prompt_execution_route",
    "render_convergence_plan",
]
