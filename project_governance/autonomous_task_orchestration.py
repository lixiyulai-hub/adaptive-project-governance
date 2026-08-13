"""Deterministic P3-F task routing and acceptance evaluation.

P3-F turns exact P3-C readiness evidence into a bounded recommended task path.
It classifies each task with the P3-E authorization policy, serializes unsafe
parallel ownership, and evaluates independently reviewed evidence. It performs
no task execution or external action itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from pathlib import PurePosixPath
import re
from typing import Any, Mapping, Sequence
import unicodedata

from .implementation_readiness import (
    ImplementationReadiness,
    ImplementationReadinessError,
    ReadinessState,
    parse_implementation_readiness,
    render_implementation_readiness,
)
from .project_blueprint import BlueprintTask
from .project_materialization_apply import (
    ActionContext,
    AuthorizationClass,
    MaterializationApplyError,
    assess_action,
)
from .storage import SchemaError, canonical_json_bytes


P3F_SCHEMA_VERSION = "1.0"
MAX_AUTONOMOUS_TASK_PLAN_BYTES = 512 * 1024
MAX_AUTONOMOUS_TASK_ACCEPTANCE_BYTES = 256 * 1024
MAX_TASKS = 32
MAX_PATHS_PER_TASK = 64
MAX_REFERENCES_PER_TASK = 64

_CODE = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_WINDOWS_DRIVE = re.compile(r"[A-Za-z]:")
_SENSITIVE = re.compile(
    r"(?:\bsk-[A-Za-z0-9_-]{8,}|\bghp_[A-Za-z0-9]{8,}|"
    r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.|"
    r"\bbearer\s+[A-Za-z0-9._~+/-]{8,}|"
    r"\b(?:api[_-]?key|token|password|secret)\s*[:=]|"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----)",
    re.IGNORECASE,
)


class AutonomousTaskOrchestrationError(ValueError):
    """Raised when P3-F input or canonical evidence is malformed."""


class OrchestrationState(str, Enum):
    AUTO_READY = "auto-ready"
    RECOMMENDATION_READY = "recommendation-ready"
    PENDING_USER_INPUT = "pending-user-input"
    BLOCK = "block"


class TaskResultStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"


class ReviewVerdict(str, Enum):
    ACCEPT = "accept"
    BLOCK = "block"


class FinalAcceptanceState(str, Enum):
    ACCEPT = "accept"
    INCOMPLETE = "incomplete"
    BLOCK = "block"


def _scalar(value: object, label: str, maximum: int = 240) -> str:
    if type(value) is not str or not value or len(value) > maximum:
        raise AutonomousTaskOrchestrationError(
            f"{label} must be bounded non-empty text"
        )
    if value != unicodedata.normalize("NFC", value):
        raise AutonomousTaskOrchestrationError(f"{label} must use NFC Unicode")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise AutonomousTaskOrchestrationError(f"{label} contains control characters")
    if _SENSITIVE.search(value):
        raise AutonomousTaskOrchestrationError(
            f"{label} contains a sensitive-value pattern"
        )
    return value


def _code(value: object, label: str) -> str:
    text = _scalar(value, label, 128)
    if not _CODE.fullmatch(text):
        raise AutonomousTaskOrchestrationError(
            f"{label} must be a bounded stable code"
        )
    return text


def _digest(value: object, label: str) -> str:
    if type(value) is not str or not _SHA256.fullmatch(value):
        raise AutonomousTaskOrchestrationError(
            f"{label} must be a lowercase SHA-256 digest"
        )
    return value


def _safe_relative_path(value: str) -> bool:
    if "\\" in value or value.startswith("/") or _WINDOWS_DRIVE.match(value):
        return False
    if "://" in value or ":" in value or "?" in value or "#" in value:
        return False
    parts = value.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return False
    if any(part.endswith((".", " ")) for part in parts):
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and tuple(path.parts) == tuple(parts)


def _portable_path_key(value: str) -> str:
    return unicodedata.normalize("NFC", value.replace("\\", "/")).casefold()


def _path(value: object, label: str) -> str:
    text = _scalar(value, label, 240)
    if not _safe_relative_path(text):
        raise AutonomousTaskOrchestrationError(
            f"{label} must be a contained relative slash path"
        )
    return text


def _reference(value: object, label: str) -> str:
    text = _scalar(value, label, 240)
    if _CODE.fullmatch(text) or _safe_relative_path(text):
        return text
    raise AutonomousTaskOrchestrationError(
        f"{label} must be a stable code or contained relative path"
    )


def _exact_enum(value: object, enum_type: type[Enum], label: str) -> None:
    if type(value) is not enum_type:
        raise AutonomousTaskOrchestrationError(
            f"{label} must be an exact {enum_type.__name__}"
        )


def _enum_value(enum_type: type[Enum], value: object, label: str) -> Enum:
    if type(value) is not str:
        raise AutonomousTaskOrchestrationError(f"{label} must be a string enum")
    try:
        return enum_type(value)
    except ValueError as error:
        raise AutonomousTaskOrchestrationError(
            f"{label} has an unsupported value"
        ) from error


def _tuple(value: object, label: str, maximum: int) -> tuple[object, ...]:
    if type(value) is not tuple or len(value) > maximum:
        raise AutonomousTaskOrchestrationError(
            f"{label} must be a bounded immutable tuple"
        )
    return value


def _canonical_codes(
    value: object,
    label: str,
    maximum: int = MAX_REFERENCES_PER_TASK,
    *,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    items = _tuple(value, label, maximum)
    if not allow_empty and not items:
        raise AutonomousTaskOrchestrationError(f"{label} must not be empty")
    normalized = tuple(_code(item, f"{label}[{index}]") for index, item in enumerate(items))
    if normalized != tuple(sorted(set(normalized))):
        raise AutonomousTaskOrchestrationError(
            f"{label} must use canonical unique order"
        )
    return normalized


def _semantic_codes(
    value: object,
    label: str,
    maximum: int = MAX_REFERENCES_PER_TASK,
    *,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    items = _tuple(value, label, maximum)
    if not allow_empty and not items:
        raise AutonomousTaskOrchestrationError(f"{label} must not be empty")
    normalized = tuple(_code(item, f"{label}[{index}]") for index, item in enumerate(items))
    if len(set(normalized)) != len(normalized):
        raise AutonomousTaskOrchestrationError(f"{label} must contain unique codes")
    return normalized


def _canonical_paths(
    value: object,
    label: str,
    *,
    allow_empty: bool = True,
) -> tuple[str, ...]:
    items = _tuple(value, label, MAX_PATHS_PER_TASK)
    if not allow_empty and not items:
        raise AutonomousTaskOrchestrationError(f"{label} must not be empty")
    normalized = tuple(_path(item, f"{label}[{index}]") for index, item in enumerate(items))
    if normalized != tuple(sorted(set(normalized))):
        raise AutonomousTaskOrchestrationError(
            f"{label} must use canonical unique order"
        )
    portable = tuple(_portable_path_key(item) for item in normalized)
    if len(set(portable)) != len(portable):
        raise AutonomousTaskOrchestrationError(
            f"{label} contains portable path aliases"
        )
    return normalized


def _canonical_refs(
    value: object,
    label: str,
    *,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    items = _tuple(value, label, MAX_REFERENCES_PER_TASK)
    if not allow_empty and not items:
        raise AutonomousTaskOrchestrationError(f"{label} must not be empty")
    normalized = tuple(
        _reference(item, f"{label}[{index}]") for index, item in enumerate(items)
    )
    if normalized != tuple(sorted(set(normalized))):
        raise AutonomousTaskOrchestrationError(
            f"{label} must use canonical unique order"
        )
    return normalized


@dataclass(frozen=True)
class TaskExecutionContext:
    task_id: str
    executor_id: str
    read_paths: tuple[str, ...]
    write_paths: tuple[str, ...]
    gate_ids: tuple[str, ...]
    acceptance_refs: tuple[str, ...]
    rollback_ref: str
    action_context: ActionContext
    git_operation: bool = False
    release: bool = False

    def __post_init__(self) -> None:
        if type(self) is not TaskExecutionContext:
            raise AutonomousTaskOrchestrationError(
                "TaskExecutionContext subclasses are not accepted"
            )
        _code(self.task_id, "task_context.task_id")
        _code(self.executor_id, "task_context.executor_id")
        reads = _canonical_paths(self.read_paths, "task_context.read_paths")
        writes = _canonical_paths(self.write_paths, "task_context.write_paths")
        if not reads and not writes:
            raise AutonomousTaskOrchestrationError(
                "task context must declare a read or write scope"
            )
        by_portable_key: dict[str, set[str]] = {}
        for path in reads + writes:
            by_portable_key.setdefault(_portable_path_key(path), set()).add(path)
        if any(len(values) > 1 for values in by_portable_key.values()):
            raise AutonomousTaskOrchestrationError(
                "task context contains portable path aliases"
            )
        _canonical_codes(self.gate_ids, "task_context.gate_ids")
        _canonical_refs(self.acceptance_refs, "task_context.acceptance_refs")
        _reference(self.rollback_ref, "task_context.rollback_ref")
        if type(self.action_context) is not ActionContext:
            raise AutonomousTaskOrchestrationError(
                "task_context.action_context must be an exact ActionContext"
            )
        if type(self.git_operation) is not bool or type(self.release) is not bool:
            raise AutonomousTaskOrchestrationError(
                "task context Git and release flags must be booleans"
            )


@dataclass(frozen=True)
class OrchestrationSource:
    readiness_sha256: str
    readiness: ImplementationReadiness
    task_contexts: tuple[TaskExecutionContext, ...]

    def __post_init__(self) -> None:
        if type(self) is not OrchestrationSource:
            raise AutonomousTaskOrchestrationError(
                "OrchestrationSource subclasses are not accepted"
            )
        _digest(self.readiness_sha256, "source.readiness_sha256")
        if type(self.readiness) is not ImplementationReadiness:
            raise AutonomousTaskOrchestrationError(
                "source.readiness must be an exact ImplementationReadiness"
            )
        rendered = render_implementation_readiness(self.readiness)
        if hashlib.sha256(rendered).hexdigest() != self.readiness_sha256:
            raise AutonomousTaskOrchestrationError(
                "source readiness digest does not bind readiness bytes"
            )
        contexts = _tuple(self.task_contexts, "source.task_contexts", MAX_TASKS)
        if any(type(item) is not TaskExecutionContext for item in contexts):
            raise AutonomousTaskOrchestrationError(
                "source.task_contexts must contain exact TaskExecutionContext records"
            )
        identifiers = tuple(item.task_id for item in contexts)
        if identifiers != tuple(sorted(set(identifiers))):
            raise AutonomousTaskOrchestrationError(
                "source.task_contexts must use canonical unique task ID order"
            )


@dataclass(frozen=True)
class TaskRoute:
    task_id: str
    phase: str
    action_code: str
    output_code: str
    depends_on: tuple[str, ...]
    wave_index: int
    context: TaskExecutionContext
    classification: AuthorizationClass
    reason_codes: tuple[str, ...]
    auto_authorized: bool

    def __post_init__(self) -> None:
        if type(self) is not TaskRoute:
            raise AutonomousTaskOrchestrationError("TaskRoute subclasses are not accepted")
        _code(self.task_id, "task_route.task_id")
        _code(self.phase, "task_route.phase")
        _code(self.action_code, "task_route.action_code")
        _code(self.output_code, "task_route.output_code")
        _canonical_codes(
            self.depends_on,
            "task_route.depends_on",
            maximum=MAX_TASKS,
            allow_empty=True,
        )
        if type(self.wave_index) is not int or self.wave_index < 0:
            raise AutonomousTaskOrchestrationError(
                "task_route.wave_index must be a non-negative integer"
            )
        if type(self.context) is not TaskExecutionContext or self.context.task_id != self.task_id:
            raise AutonomousTaskOrchestrationError("task route context does not bind task")
        _exact_enum(self.classification, AuthorizationClass, "task_route.classification")
        _canonical_codes(
            self.reason_codes,
            "task_route.reason_codes",
            allow_empty=True,
        )
        if type(self.auto_authorized) is not bool:
            raise AutonomousTaskOrchestrationError(
                "task_route.auto_authorized must be boolean"
            )
        if self.auto_authorized != (self.classification is AuthorizationClass.AUTO):
            raise AutonomousTaskOrchestrationError(
                "task_route auto authorization does not match classification"
            )


@dataclass(frozen=True)
class ExecutionWave:
    wave_index: int
    task_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self) is not ExecutionWave:
            raise AutonomousTaskOrchestrationError(
                "ExecutionWave subclasses are not accepted"
            )
        if type(self.wave_index) is not int or self.wave_index < 0:
            raise AutonomousTaskOrchestrationError(
                "wave_index must be a non-negative integer"
            )
        _canonical_codes(self.task_ids, "wave.task_ids", maximum=MAX_TASKS)


@dataclass(frozen=True)
class AutonomousTaskPlan:
    schema_version: str
    plan_id: str
    source: OrchestrationSource
    policy_sha256: str
    routes: tuple[TaskRoute, ...]
    waves: tuple[ExecutionWave, ...]
    recommended_task_ids: tuple[str, ...]
    next_task_ids: tuple[str, ...]
    auto_authorized_task_ids: tuple[str, ...]
    recommendation_task_ids: tuple[str, ...]
    confirmation_task_ids: tuple[str, ...]
    blocked_task_ids: tuple[str, ...]
    self_check_codes: tuple[str, ...]
    blocker_codes: tuple[str, ...]
    state: OrchestrationState
    user_summary_code: str
    execution_performed: bool

    def __post_init__(self) -> None:
        if type(self) is not AutonomousTaskPlan:
            raise AutonomousTaskOrchestrationError(
                "AutonomousTaskPlan subclasses are not accepted"
            )
        if self.schema_version != P3F_SCHEMA_VERSION:
            raise AutonomousTaskOrchestrationError(
                "unsupported autonomous-task-plan schema_version"
            )
        _code(self.plan_id, "plan_id")
        if type(self.source) is not OrchestrationSource:
            raise AutonomousTaskOrchestrationError(
                "source must be an exact OrchestrationSource"
            )
        _digest(self.policy_sha256, "policy_sha256")
        routes = _tuple(self.routes, "routes", MAX_TASKS)
        if not routes or any(type(item) is not TaskRoute for item in routes):
            raise AutonomousTaskOrchestrationError(
                "routes must contain exact TaskRoute records"
            )
        waves = _tuple(self.waves, "waves", MAX_TASKS)
        if not waves or any(type(item) is not ExecutionWave for item in waves):
            raise AutonomousTaskOrchestrationError(
                "waves must contain exact ExecutionWave records"
            )
        _semantic_codes(
            self.recommended_task_ids,
            "recommended_task_ids",
            maximum=MAX_TASKS,
            allow_empty=True,
        )
        _semantic_codes(
            self.next_task_ids,
            "next_task_ids",
            maximum=MAX_TASKS,
            allow_empty=True,
        )
        for label, value in (
            ("auto_authorized_task_ids", self.auto_authorized_task_ids),
            ("recommendation_task_ids", self.recommendation_task_ids),
            ("confirmation_task_ids", self.confirmation_task_ids),
            ("blocked_task_ids", self.blocked_task_ids),
            ("self_check_codes", self.self_check_codes),
            ("blocker_codes", self.blocker_codes),
        ):
            _canonical_codes(value, label, maximum=MAX_TASKS * 4, allow_empty=True)
        _exact_enum(self.state, OrchestrationState, "state")
        _code(self.user_summary_code, "user_summary_code")
        if self.execution_performed is not False:
            raise AutonomousTaskOrchestrationError(
                "P3-F planning cannot claim task execution"
            )


@dataclass(frozen=True)
class TaskExecutionEvidence:
    task_id: str
    executor_id: str
    status: TaskResultStatus
    output_refs: tuple[str, ...]
    gate_refs: tuple[str, ...]
    acceptance_refs: tuple[str, ...]
    rollback_ref: str
    reviewer_id: str
    review_verdict: ReviewVerdict
    decision_ref: str | None = None
    authorization_ref: str | None = None

    def __post_init__(self) -> None:
        if type(self) is not TaskExecutionEvidence:
            raise AutonomousTaskOrchestrationError(
                "TaskExecutionEvidence subclasses are not accepted"
            )
        _code(self.task_id, "task_evidence.task_id")
        _code(self.executor_id, "task_evidence.executor_id")
        _exact_enum(self.status, TaskResultStatus, "task_evidence.status")
        _canonical_refs(self.output_refs, "task_evidence.output_refs")
        _canonical_refs(self.gate_refs, "task_evidence.gate_refs", allow_empty=True)
        _canonical_refs(self.acceptance_refs, "task_evidence.acceptance_refs")
        _reference(self.rollback_ref, "task_evidence.rollback_ref")
        _code(self.reviewer_id, "task_evidence.reviewer_id")
        _exact_enum(self.review_verdict, ReviewVerdict, "task_evidence.review_verdict")
        if self.decision_ref is not None:
            _reference(self.decision_ref, "task_evidence.decision_ref")
        if self.authorization_ref is not None:
            _reference(self.authorization_ref, "task_evidence.authorization_ref")


@dataclass(frozen=True)
class AutonomousTaskAcceptance:
    schema_version: str
    plan_id: str
    plan_sha256: str
    plan: AutonomousTaskPlan
    task_evidence: tuple[TaskExecutionEvidence, ...]
    state: FinalAcceptanceState
    accepted_task_ids: tuple[str, ...]
    pending_task_ids: tuple[str, ...]
    blocked_task_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    user_summary_code: str

    def __post_init__(self) -> None:
        if type(self) is not AutonomousTaskAcceptance:
            raise AutonomousTaskOrchestrationError(
                "AutonomousTaskAcceptance subclasses are not accepted"
            )
        if self.schema_version != P3F_SCHEMA_VERSION:
            raise AutonomousTaskOrchestrationError(
                "unsupported autonomous-task-acceptance schema_version"
            )
        _code(self.plan_id, "acceptance.plan_id")
        _digest(self.plan_sha256, "acceptance.plan_sha256")
        if type(self.plan) is not AutonomousTaskPlan:
            raise AutonomousTaskOrchestrationError(
                "acceptance.plan must be an exact AutonomousTaskPlan"
            )
        if self.plan_id != self.plan.plan_id:
            raise AutonomousTaskOrchestrationError(
                "acceptance plan ID does not bind the plan"
            )
        if hashlib.sha256(render_autonomous_task_plan(self.plan)).hexdigest() != self.plan_sha256:
            raise AutonomousTaskOrchestrationError(
                "acceptance plan digest does not bind the plan"
            )
        evidence = _tuple(self.task_evidence, "acceptance.task_evidence", MAX_TASKS)
        if any(type(item) is not TaskExecutionEvidence for item in evidence):
            raise AutonomousTaskOrchestrationError(
                "acceptance evidence must contain exact TaskExecutionEvidence records"
            )
        identifiers = tuple(item.task_id for item in evidence)
        if identifiers != tuple(sorted(set(identifiers))):
            raise AutonomousTaskOrchestrationError(
                "acceptance evidence must use canonical unique task ID order"
            )
        _exact_enum(self.state, FinalAcceptanceState, "acceptance.state")
        for label, value in (
            ("accepted_task_ids", self.accepted_task_ids),
            ("pending_task_ids", self.pending_task_ids),
            ("blocked_task_ids", self.blocked_task_ids),
            ("reason_codes", self.reason_codes),
        ):
            _canonical_codes(value, label, maximum=MAX_TASKS * 4, allow_empty=True)
        _code(self.user_summary_code, "acceptance.user_summary_code")


def _paths_overlap(left: str, right: str) -> bool:
    left = _portable_path_key(left)
    right = _portable_path_key(right)
    return (
        left == right
        or left.startswith(right.rstrip("/") + "/")
        or right.startswith(left.rstrip("/") + "/")
    )


def _contexts_conflict(left: TaskExecutionContext, right: TaskExecutionContext) -> bool:
    left_touched = left.read_paths + left.write_paths
    right_touched = right.read_paths + right.write_paths
    return any(
        _paths_overlap(write_path, other_path)
        for write_path in left.write_paths
        for other_path in right_touched
    ) or any(
        _paths_overlap(write_path, other_path)
        for write_path in right.write_paths
        for other_path in left_touched
    )


def _derive_waves(
    tasks: tuple[BlueprintTask, ...],
    contexts: Mapping[str, TaskExecutionContext],
) -> tuple[dict[str, int], frozenset[str]]:
    task_wave: dict[str, int] = {}
    wave_tasks: dict[int, list[str]] = {}
    serialized: set[str] = set()
    for task in tasks:
        candidate = (
            max(task_wave[item] for item in task.depends_on) + 1
            if task.depends_on
            else 0
        )
        while any(
            _contexts_conflict(contexts[task.task_id], contexts[other])
            for other in wave_tasks.get(candidate, ())
        ):
            candidate += 1
            serialized.add(task.task_id)
        task_wave[task.task_id] = candidate
        wave_tasks.setdefault(candidate, []).append(task.task_id)
    return task_wave, frozenset(serialized)


def _build_plan(
    readiness: ImplementationReadiness,
    contexts: tuple[TaskExecutionContext, ...],
    *,
    plan_id: str,
) -> AutonomousTaskPlan:
    if (
        readiness.state is not ReadinessState.READY_FOR_MATERIALIZATION_PREVIEW
        or not readiness.ready_for_materialization_preview
        or readiness.blocker_codes
    ):
        raise AutonomousTaskOrchestrationError(
            "implementation readiness is not ready for autonomous task routing"
        )
    tasks = readiness.source.blueprint.task_graph.tasks
    expected_ids = tuple(sorted(task.task_id for task in tasks))
    context_ids = tuple(item.task_id for item in contexts)
    if context_ids != expected_ids:
        raise AutonomousTaskOrchestrationError(
            "task contexts must exactly cover the blueprint task graph"
        )
    policies = {item.action_context.policy_sha256 for item in contexts}
    if len(policies) != 1:
        raise AutonomousTaskOrchestrationError(
            "task contexts must bind one policy digest"
        )
    policy_sha256 = next(iter(policies))
    by_id = {item.task_id: item for item in contexts}
    seen_paths: dict[str, str] = {}
    for context in contexts:
        for path in context.read_paths + context.write_paths:
            key = _portable_path_key(path)
            prior = seen_paths.get(key)
            if prior is not None and prior != path:
                raise AutonomousTaskOrchestrationError(
                    "task contexts contain portable path aliases"
                )
            seen_paths[key] = path
    task_wave, serialized = _derive_waves(tasks, by_id)
    readiness_refs = set(readiness.evidence_refs)

    declared_gates = {gate for item in contexts for gate in item.gate_ids}
    required_gates = {
        item.gate_id for item in readiness.professional_gate_requirements if item.required
    }
    missing_gates = tuple(sorted(required_gates - declared_gates))

    routes: list[TaskRoute] = []
    blocker_codes: set[str] = set()
    for task in tasks:
        context = by_id[task.task_id]
        assessment = assess_action(context.action_context)
        classification = assessment.classification
        reasons = set(assessment.reason_codes)
        if context.git_operation:
            classification = AuthorizationClass.CONFIRM
            reasons.add("git-operation")
        if context.release:
            classification = AuthorizationClass.CONFIRM
            reasons.add("release")
        if not set(context.action_context.evidence_refs).issubset(readiness_refs):
            classification = AuthorizationClass.BLOCK
            reasons.add("evidence-not-bound-to-readiness")
        if task.task_id in serialized:
            reasons.add("ownership-overlap-serialized")
        if missing_gates:
            classification = AuthorizationClass.BLOCK
            reasons.update(f"required-gate-missing.{item}" for item in missing_gates)
        if classification is AuthorizationClass.BLOCK:
            blocker_codes.update(reasons)
        routes.append(
            TaskRoute(
                task_id=task.task_id,
                phase=task.phase.value,
                action_code=task.action_code,
                output_code=task.output_code,
                depends_on=task.depends_on,
                wave_index=task_wave[task.task_id],
                context=context,
                classification=classification,
                reason_codes=tuple(sorted(reasons)),
                auto_authorized=classification is AuthorizationClass.AUTO,
            )
        )

    if missing_gates:
        blocker_codes.update(f"required-gate-missing.{item}" for item in missing_gates)

    waves = tuple(
        ExecutionWave(
            wave_index=index,
            task_ids=tuple(
                sorted(item.task_id for item in routes if item.wave_index == index)
            ),
        )
        for index in sorted({item.wave_index for item in routes})
    )
    auto_ids = tuple(sorted(item.task_id for item in routes if item.classification is AuthorizationClass.AUTO))
    recommend_ids = tuple(sorted(item.task_id for item in routes if item.classification is AuthorizationClass.RECOMMEND))
    confirm_ids = tuple(sorted(item.task_id for item in routes if item.classification is AuthorizationClass.CONFIRM))
    blocked_ids = tuple(sorted(item.task_id for item in routes if item.classification is AuthorizationClass.BLOCK))
    if blocker_codes:
        state = OrchestrationState.BLOCK
        summary = "summary.goal-path-blocked"
    elif confirm_ids:
        state = OrchestrationState.PENDING_USER_INPUT
        summary = "summary.consequential-confirmation-required"
    elif recommend_ids:
        state = OrchestrationState.RECOMMENDATION_READY
        summary = "summary.recommended-goal-path-ready"
    else:
        state = OrchestrationState.AUTO_READY
        summary = "summary.automatic-goal-path-ready"

    first_wave = (
        tuple(
            task_id
            for task_id in waves[0].task_ids
            if next(item for item in routes if item.task_id == task_id).classification
            is not AuthorizationClass.BLOCK
        )
        if waves
        else ()
    )
    recommended = tuple(item.task_id for item in routes if item.classification is not AuthorizationClass.BLOCK)
    self_checks = [
        "check.acceptance-bound",
        "check.dependencies-closed",
        "check.policy-bound",
        "check.readiness-recomputed",
        "check.rollback-bound",
        "check.scope-bounded",
        "check.write-ownership-serialized",
    ]
    if not missing_gates:
        self_checks.append("check.gates-covered")
    readiness_bytes = render_implementation_readiness(readiness)
    return AutonomousTaskPlan(
        schema_version=P3F_SCHEMA_VERSION,
        plan_id=_code(plan_id, "plan_id"),
        source=OrchestrationSource(
            readiness_sha256=hashlib.sha256(readiness_bytes).hexdigest(),
            readiness=readiness,
            task_contexts=contexts,
        ),
        policy_sha256=policy_sha256,
        routes=tuple(routes),
        waves=waves,
        recommended_task_ids=recommended,
        next_task_ids=first_wave,
        auto_authorized_task_ids=auto_ids,
        recommendation_task_ids=recommend_ids,
        confirmation_task_ids=confirm_ids,
        blocked_task_ids=blocked_ids,
        self_check_codes=tuple(sorted(self_checks)),
        blocker_codes=tuple(sorted(blocker_codes)),
        state=state,
        user_summary_code=summary,
        execution_performed=False,
    )


def build_autonomous_task_plan(
    readiness_payload: bytes | bytearray | memoryview,
    contexts: Sequence[TaskExecutionContext],
    *,
    plan_id: str | None = None,
) -> AutonomousTaskPlan:
    """Build a deterministic goal path without executing any task."""

    try:
        readiness = parse_implementation_readiness(readiness_payload)
    except (ImplementationReadinessError, TypeError, ValueError) as error:
        raise AutonomousTaskOrchestrationError(
            "P3-C implementation readiness is invalid"
        ) from error
    if not isinstance(contexts, (tuple, list)) or len(contexts) > MAX_TASKS:
        raise AutonomousTaskOrchestrationError("contexts must be a bounded sequence")
    values = tuple(contexts)
    if any(type(item) is not TaskExecutionContext for item in values):
        raise AutonomousTaskOrchestrationError(
            "contexts must contain exact TaskExecutionContext records"
        )
    identifiers = tuple(item.task_id for item in values)
    if identifiers != tuple(sorted(set(identifiers))):
        raise AutonomousTaskOrchestrationError(
            "contexts must use canonical unique task ID order"
        )
    readiness_sha256 = hashlib.sha256(render_implementation_readiness(readiness)).hexdigest()
    identifier = plan_id or f"orchestration.{readiness.readiness_id}.{readiness_sha256[:12]}"
    return _build_plan(readiness, values, plan_id=identifier)


def _action_context_mapping(value: ActionContext) -> dict[str, object]:
    return {
        "bounded_scope": value.bounded_scope,
        "deployment": value.deployment,
        "evidence_refs": list(value.evidence_refs),
        "irreversible": value.irreversible,
        "materially_ambiguous": value.materially_ambiguous,
        "no_cost": value.no_cost,
        "no_credentials": value.no_credentials,
        "no_network": value.no_network,
        "no_real_data": value.no_real_data,
        "no_secret_values": value.no_secret_values,
        "policy_sha256": value.policy_sha256,
        "privacy_change": value.privacy_change,
        "public_delivery": value.public_delivery,
        "recommendation_only": value.recommendation_only,
        "reversible": value.reversible,
        "runtime_launch": value.runtime_launch,
        "security_change": value.security_change,
    }


def _context_mapping(value: TaskExecutionContext) -> dict[str, object]:
    return {
        "acceptance_refs": list(value.acceptance_refs),
        "action_context": _action_context_mapping(value.action_context),
        "executor_id": value.executor_id,
        "gate_ids": list(value.gate_ids),
        "git_operation": value.git_operation,
        "read_paths": list(value.read_paths),
        "release": value.release,
        "rollback_ref": value.rollback_ref,
        "task_id": value.task_id,
        "write_paths": list(value.write_paths),
    }


def _route_mapping(value: TaskRoute) -> dict[str, object]:
    return {
        "action_code": value.action_code,
        "auto_authorized": value.auto_authorized,
        "classification": value.classification.value,
        "context": _context_mapping(value.context),
        "depends_on": list(value.depends_on),
        "output_code": value.output_code,
        "phase": value.phase,
        "reason_codes": list(value.reason_codes),
        "task_id": value.task_id,
        "wave_index": value.wave_index,
    }


def _plan_mapping(value: AutonomousTaskPlan) -> dict[str, object]:
    return {
        "auto_authorized_task_ids": list(value.auto_authorized_task_ids),
        "blocked_task_ids": list(value.blocked_task_ids),
        "blocker_codes": list(value.blocker_codes),
        "confirmation_task_ids": list(value.confirmation_task_ids),
        "execution_performed": value.execution_performed,
        "next_task_ids": list(value.next_task_ids),
        "plan_id": value.plan_id,
        "policy_sha256": value.policy_sha256,
        "recommendation_task_ids": list(value.recommendation_task_ids),
        "recommended_task_ids": list(value.recommended_task_ids),
        "routes": [_route_mapping(item) for item in value.routes],
        "schema_version": value.schema_version,
        "self_check_codes": list(value.self_check_codes),
        "source": {
            "readiness": json.loads(render_implementation_readiness(value.source.readiness)),
            "readiness_sha256": value.source.readiness_sha256,
            "task_contexts": [_context_mapping(item) for item in value.source.task_contexts],
        },
        "state": value.state.value,
        "user_summary_code": value.user_summary_code,
        "waves": [
            {"task_ids": list(item.task_ids), "wave_index": item.wave_index}
            for item in value.waves
        ],
    }


def render_autonomous_task_plan(value: AutonomousTaskPlan) -> bytes:
    """Render a closed canonical P3-F plan after full recomputation."""

    if type(value) is not AutonomousTaskPlan:
        raise TypeError("value must be an exact AutonomousTaskPlan")
    expected = _build_plan(
        value.source.readiness,
        value.source.task_contexts,
        plan_id=value.plan_id,
    )
    if expected != value:
        raise AutonomousTaskOrchestrationError(
            "autonomous task plan does not match recomputed source evidence"
        )
    try:
        rendered = canonical_json_bytes(_plan_mapping(value))
    except SchemaError as error:
        raise AutonomousTaskOrchestrationError(
            f"autonomous task plan cannot be encoded: {error}"
        ) from error
    if len(rendered) > MAX_AUTONOMOUS_TASK_PLAN_BYTES:
        raise AutonomousTaskOrchestrationError(
            "rendered autonomous task plan exceeds its byte bound"
        )
    return rendered


def _closed(value: object, fields: frozenset[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AutonomousTaskOrchestrationError(f"{label} must be an object")
    keys = set(value)
    if any(type(key) is not str for key in keys):
        raise AutonomousTaskOrchestrationError(f"{label} keys must be strings")
    unknown = sorted(keys - fields)
    missing = sorted(fields - keys)
    if unknown:
        raise AutonomousTaskOrchestrationError(
            f"{label} contains unknown fields: {', '.join(unknown)}"
        )
    if missing:
        raise AutonomousTaskOrchestrationError(
            f"{label} is missing fields: {', '.join(missing)}"
        )
    return value


def _sequence(value: object, label: str, maximum: int) -> tuple[object, ...]:
    if type(value) is not list or len(value) > maximum:
        raise AutonomousTaskOrchestrationError(f"{label} must be a bounded array")
    return tuple(value)


def _parse_codes(value: object, label: str, maximum: int, *, allow_empty: bool = False) -> tuple[str, ...]:
    items = tuple(
        _code(item, f"{label}[{index}]")
        for index, item in enumerate(_sequence(value, label, maximum))
    )
    if not allow_empty and not items:
        raise AutonomousTaskOrchestrationError(f"{label} must not be empty")
    return items


def _parse_paths(value: object, label: str) -> tuple[str, ...]:
    return tuple(
        _path(item, f"{label}[{index}]")
        for index, item in enumerate(_sequence(value, label, MAX_PATHS_PER_TASK))
    )


def _parse_refs(value: object, label: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    items = tuple(
        _reference(item, f"{label}[{index}]")
        for index, item in enumerate(
            _sequence(value, label, MAX_REFERENCES_PER_TASK)
        )
    )
    if not allow_empty and not items:
        raise AutonomousTaskOrchestrationError(f"{label} must not be empty")
    return items


def _parse_action_context(value: object, label: str) -> ActionContext:
    item = _closed(
        value,
        frozenset(
            {
                "bounded_scope",
                "deployment",
                "evidence_refs",
                "irreversible",
                "materially_ambiguous",
                "no_cost",
                "no_credentials",
                "no_network",
                "no_real_data",
                "no_secret_values",
                "policy_sha256",
                "privacy_change",
                "public_delivery",
                "recommendation_only",
                "reversible",
                "runtime_launch",
                "security_change",
            }
        ),
        label,
    )
    bool_fields = {
        key: item[key]
        for key in item
        if key not in ("policy_sha256", "evidence_refs")
    }
    if any(type(value) is not bool for value in bool_fields.values()):
        raise AutonomousTaskOrchestrationError(
            f"{label} action flags must be booleans"
        )
    try:
        return ActionContext(
            policy_sha256=_digest(item["policy_sha256"], f"{label}.policy_sha256"),
            evidence_refs=_parse_codes(
                item["evidence_refs"], f"{label}.evidence_refs", MAX_REFERENCES_PER_TASK
            ),
            **bool_fields,
        )
    except MaterializationApplyError as error:
        raise AutonomousTaskOrchestrationError(
            f"{label} is not a valid P3-E action context"
        ) from error


def _parse_context(value: object, label: str) -> TaskExecutionContext:
    item = _closed(
        value,
        frozenset(
            {
                "acceptance_refs",
                "action_context",
                "executor_id",
                "gate_ids",
                "git_operation",
                "read_paths",
                "release",
                "rollback_ref",
                "task_id",
                "write_paths",
            }
        ),
        label,
    )
    return TaskExecutionContext(
        task_id=_code(item["task_id"], f"{label}.task_id"),
        executor_id=_code(item["executor_id"], f"{label}.executor_id"),
        read_paths=_parse_paths(item["read_paths"], f"{label}.read_paths"),
        write_paths=_parse_paths(item["write_paths"], f"{label}.write_paths"),
        gate_ids=_parse_codes(item["gate_ids"], f"{label}.gate_ids", MAX_REFERENCES_PER_TASK),
        acceptance_refs=_parse_refs(item["acceptance_refs"], f"{label}.acceptance_refs"),
        rollback_ref=_reference(item["rollback_ref"], f"{label}.rollback_ref"),
        action_context=_parse_action_context(item["action_context"], f"{label}.action_context"),
        git_operation=item["git_operation"],
        release=item["release"],
    )


def _reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise AutonomousTaskOrchestrationError(
                "autonomous task plan contains duplicate object keys"
            )
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise AutonomousTaskOrchestrationError(
        f"autonomous task plan contains unsupported JSON constant: {value}"
    )


def parse_autonomous_task_plan(
    payload: bytes | bytearray | memoryview,
) -> AutonomousTaskPlan:
    """Parse only bounded canonical P3-F JSON and recompute all derived fields."""

    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise AutonomousTaskOrchestrationError("autonomous task plan must be bytes")
    raw = bytes(payload)
    if not raw or len(raw) > MAX_AUTONOMOUS_TASK_PLAN_BYTES:
        raise AutonomousTaskOrchestrationError(
            "autonomous task plan must use bounded non-empty bytes"
        )
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicates,
            parse_constant=_reject_constant,
        )
    except AutonomousTaskOrchestrationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError, RecursionError) as error:
        raise AutonomousTaskOrchestrationError(
            "autonomous task plan is not valid UTF-8 JSON"
        ) from error
    item = _closed(
        value,
        frozenset(
            {
                "auto_authorized_task_ids",
                "blocked_task_ids",
                "blocker_codes",
                "confirmation_task_ids",
                "execution_performed",
                "next_task_ids",
                "plan_id",
                "policy_sha256",
                "recommendation_task_ids",
                "recommended_task_ids",
                "routes",
                "schema_version",
                "self_check_codes",
                "source",
                "state",
                "user_summary_code",
                "waves",
            }
        ),
        "plan",
    )
    source = _closed(
        item["source"],
        frozenset({"readiness", "readiness_sha256", "task_contexts"}),
        "plan.source",
    )
    try:
        readiness = parse_implementation_readiness(
            canonical_json_bytes(source["readiness"])
        )
    except (ImplementationReadinessError, SchemaError, TypeError, ValueError) as error:
        raise AutonomousTaskOrchestrationError(
            "embedded implementation readiness is invalid"
        ) from error
    contexts = tuple(
        _parse_context(record, f"plan.source.task_contexts[{index}]")
        for index, record in enumerate(
            _sequence(source["task_contexts"], "plan.source.task_contexts", MAX_TASKS)
        )
    )
    rebuilt = _build_plan(
        readiness,
        contexts,
        plan_id=_code(item["plan_id"], "plan.plan_id"),
    )
    if render_autonomous_task_plan(rebuilt) != raw:
        raise AutonomousTaskOrchestrationError(
            "autonomous task plan JSON is not canonical or was tampered"
        )
    return rebuilt


def evaluate_autonomous_task_plan(
    plan: AutonomousTaskPlan,
    task_evidence: Sequence[TaskExecutionEvidence],
) -> AutonomousTaskAcceptance:
    """Evaluate exact task evidence into one final user-facing result."""

    if type(plan) is not AutonomousTaskPlan:
        raise TypeError("plan must be an exact AutonomousTaskPlan")
    plan_bytes = render_autonomous_task_plan(plan)
    if not isinstance(task_evidence, (tuple, list)) or len(task_evidence) > MAX_TASKS:
        raise AutonomousTaskOrchestrationError(
            "task_evidence must be a bounded sequence"
        )
    evidence = tuple(task_evidence)
    if any(type(item) is not TaskExecutionEvidence for item in evidence):
        raise AutonomousTaskOrchestrationError(
            "task_evidence must contain exact TaskExecutionEvidence records"
        )
    evidence = tuple(sorted(evidence, key=lambda item: item.task_id))
    identifiers = tuple(item.task_id for item in evidence)
    if len(set(identifiers)) != len(identifiers):
        raise AutonomousTaskOrchestrationError(
            "task_evidence contains duplicate task IDs"
        )
    route_by_id = {item.task_id: item for item in plan.routes}
    unknown = tuple(sorted(set(identifiers) - set(route_by_id)))
    if unknown:
        raise AutonomousTaskOrchestrationError(
            "task_evidence contains tasks outside the plan"
        )
    evidence_by_id = {item.task_id: item for item in evidence}

    accepted: set[str] = set()
    pending: set[str] = set()
    blocked: set[str] = set()
    reasons: set[str] = set(plan.blocker_codes)
    for route in plan.routes:
        item = evidence_by_id.get(route.task_id)
        if route.classification is AuthorizationClass.BLOCK:
            blocked.add(route.task_id)
            reasons.add(f"task-blocked.{route.task_id}")
            continue
        if item is not None:
            context = route.context
            task_reasons: set[str] = set()
            if item.executor_id != context.executor_id:
                task_reasons.add("executor-binding-mismatch")
            if item.rollback_ref != context.rollback_ref:
                task_reasons.add("rollback-binding-mismatch")
            if not set(context.gate_ids).issubset(item.gate_refs):
                task_reasons.add("gate-evidence-missing")
            if not set(context.acceptance_refs).issubset(item.acceptance_refs):
                task_reasons.add("acceptance-evidence-missing")
            if item.reviewer_id == item.executor_id:
                task_reasons.add("independent-review-required")
            if item.status is TaskResultStatus.FAIL:
                task_reasons.add("task-result-failed")
            if item.review_verdict is ReviewVerdict.BLOCK:
                task_reasons.add("independent-review-blocked")
            if task_reasons:
                blocked.add(route.task_id)
                reasons.update(
                    f"{reason}.{route.task_id}" for reason in task_reasons
                )
                continue
        blocked_dependencies = tuple(
            dependency for dependency in route.depends_on if dependency in blocked
        )
        if blocked_dependencies:
            blocked.add(route.task_id)
            reasons.add(f"dependency-blocked.{route.task_id}")
            continue
        pending_dependencies = tuple(
            dependency for dependency in route.depends_on if dependency not in accepted
        )
        if pending_dependencies:
            pending.add(route.task_id)
            reasons.add(f"dependency-evidence-pending.{route.task_id}")
            continue
        if item is None:
            pending.add(route.task_id)
            reasons.add(f"task-evidence-pending.{route.task_id}")
            continue
        if route.classification is AuthorizationClass.CONFIRM and item.authorization_ref is None:
            pending.add(route.task_id)
            reasons.add(f"owner-authorization-pending.{route.task_id}")
            continue
        if route.classification is AuthorizationClass.RECOMMEND and item.decision_ref is None:
            pending.add(route.task_id)
            reasons.add(f"recommendation-decision-pending.{route.task_id}")
            continue
        accepted.add(route.task_id)

    if blocked or plan.state is OrchestrationState.BLOCK:
        state = FinalAcceptanceState.BLOCK
        summary = "summary.final-result-blocked"
    elif pending:
        state = FinalAcceptanceState.INCOMPLETE
        summary = "summary.final-result-incomplete"
    else:
        state = FinalAcceptanceState.ACCEPT
        summary = "summary.final-result-accepted"
    return AutonomousTaskAcceptance(
        schema_version=P3F_SCHEMA_VERSION,
        plan_id=plan.plan_id,
        plan_sha256=hashlib.sha256(plan_bytes).hexdigest(),
        plan=plan,
        task_evidence=evidence,
        state=state,
        accepted_task_ids=tuple(sorted(accepted)),
        pending_task_ids=tuple(sorted(pending)),
        blocked_task_ids=tuple(sorted(blocked)),
        reason_codes=tuple(sorted(reasons)),
        user_summary_code=summary,
    )


def _task_evidence_mapping(value: TaskExecutionEvidence) -> dict[str, object]:
    return {
        "acceptance_refs": list(value.acceptance_refs),
        "authorization_ref": value.authorization_ref,
        "decision_ref": value.decision_ref,
        "executor_id": value.executor_id,
        "gate_refs": list(value.gate_refs),
        "output_refs": list(value.output_refs),
        "review_verdict": value.review_verdict.value,
        "reviewer_id": value.reviewer_id,
        "rollback_ref": value.rollback_ref,
        "status": value.status.value,
        "task_id": value.task_id,
    }


def render_autonomous_task_acceptance(value: AutonomousTaskAcceptance) -> bytes:
    """Render receipt-safe final P3-F evidence without claiming external acceptance."""

    if type(value) is not AutonomousTaskAcceptance:
        raise TypeError("value must be an exact AutonomousTaskAcceptance")
    expected = evaluate_autonomous_task_plan(value.plan, value.task_evidence)
    if expected != value:
        raise AutonomousTaskOrchestrationError(
            "autonomous task acceptance does not match recomputed evidence"
        )
    try:
        rendered = canonical_json_bytes(
            {
                "accepted_task_ids": list(value.accepted_task_ids),
                "blocked_task_ids": list(value.blocked_task_ids),
                "pending_task_ids": list(value.pending_task_ids),
                "plan_id": value.plan_id,
                "plan_sha256": value.plan_sha256,
                "reason_codes": list(value.reason_codes),
                "schema_version": value.schema_version,
                "state": value.state.value,
                "task_evidence": [
                    _task_evidence_mapping(item) for item in value.task_evidence
                ],
                "user_summary_code": value.user_summary_code,
            }
        )
    except SchemaError as error:
        raise AutonomousTaskOrchestrationError(
            f"autonomous task acceptance cannot be encoded: {error}"
        ) from error
    if len(rendered) > MAX_AUTONOMOUS_TASK_ACCEPTANCE_BYTES:
        raise AutonomousTaskOrchestrationError(
            "rendered autonomous task acceptance exceeds its byte bound"
        )
    return rendered


__all__ = [
    "P3F_SCHEMA_VERSION",
    "MAX_AUTONOMOUS_TASK_PLAN_BYTES",
    "MAX_AUTONOMOUS_TASK_ACCEPTANCE_BYTES",
    "AutonomousTaskOrchestrationError",
    "OrchestrationState",
    "TaskResultStatus",
    "ReviewVerdict",
    "FinalAcceptanceState",
    "TaskExecutionContext",
    "OrchestrationSource",
    "TaskRoute",
    "ExecutionWave",
    "AutonomousTaskPlan",
    "TaskExecutionEvidence",
    "AutonomousTaskAcceptance",
    "build_autonomous_task_plan",
    "render_autonomous_task_plan",
    "parse_autonomous_task_plan",
    "evaluate_autonomous_task_plan",
    "render_autonomous_task_acceptance",
]
