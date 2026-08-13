"""Pure P3-H requirement trace and consolidation controller.

P3-H consumes exact canonical P3-G lifecycle bytes and caller-supplied,
bounded trace metadata. It recomputes all upstream bindings, reconciles task
artifacts and consolidation references, records conflicts and residual gaps,
and requires phase-scoped independent review before returning ACCEPT.
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

from .autonomous_task_orchestration import ReviewVerdict
from .goal_delivery_lifecycle import (
    GoalDeliveryLifecycle,
    GoalDeliveryLifecycleError,
    LifecyclePhase,
    LifecycleState,
    parse_goal_delivery_lifecycle,
    render_goal_delivery_lifecycle,
)
from .intent_decision_router import render_intent_decision_result
from .project_blueprint import BlueprintSection, render_project_blueprint
from .storage import SchemaError, canonical_json_bytes


P3H_SCHEMA_VERSION = "1.0"
MAX_REQUIREMENT_TRACE_CONSOLIDATION_BYTES = 2 * 1024 * 1024
MAX_REQUIREMENTS = 128
MAX_CONFLICTS = 128
MAX_GAPS = 256
MAX_REFERENCES = 256

_CODE = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}\Z")
_REQ = re.compile(r"REQ-[0-9]{3}\Z")
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


class RequirementTraceConsolidationError(ValueError):
    """Raised when P3-H input or canonical state is malformed."""


class ConsolidationState(str, Enum):
    ACCEPT = "accept"
    NEEDS_EVIDENCE = "needs-evidence"
    BLOCK = "block"


class ConflictState(str, Enum):
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"


class GapState(str, Enum):
    OPEN = "open"
    BLOCKING = "blocking"
    CLOSED = "closed"


def _scalar(value: object, label: str, maximum: int = 240) -> str:
    if type(value) is not str or not value or len(value) > maximum:
        raise RequirementTraceConsolidationError(
            f"{label} must be bounded non-empty text"
        )
    if value != unicodedata.normalize("NFC", value):
        raise RequirementTraceConsolidationError(f"{label} must use NFC Unicode")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise RequirementTraceConsolidationError(
            f"{label} contains control characters"
        )
    if _SENSITIVE.search(value):
        raise RequirementTraceConsolidationError(
            f"{label} contains a sensitive-value pattern"
        )
    return value


def _code(value: object, label: str) -> str:
    text = _scalar(value, label, 128)
    if not _CODE.fullmatch(text):
        raise RequirementTraceConsolidationError(
            f"{label} must be a bounded stable code"
        )
    return text


def _requirement_id(value: object, label: str) -> str:
    text = _scalar(value, label, 7)
    if not _REQ.fullmatch(text):
        raise RequirementTraceConsolidationError(
            f"{label} must use the stable REQ-000 form"
        )
    return text


def _digest(value: object, label: str) -> str:
    if type(value) is not str or not _SHA256.fullmatch(value):
        raise RequirementTraceConsolidationError(
            f"{label} must be a lowercase SHA-256 digest"
        )
    return value


def _reference(value: object, label: str) -> str:
    text = _scalar(value, label, 240)
    if _CODE.fullmatch(text):
        return text
    if (
        "\\" not in text
        and not text.startswith("/")
        and not _WINDOWS_DRIVE.match(text)
        and "://" not in text
        and ":" not in text
        and "?" not in text
        and "#" not in text
    ):
        parts = text.split("/")
        if (
            all(part not in ("", ".", "..") for part in parts)
            and all(not part.endswith((".", " ")) for part in parts)
            and tuple(PurePosixPath(text).parts) == tuple(parts)
        ):
            return text
    raise RequirementTraceConsolidationError(
        f"{label} must be a stable code or contained relative path"
    )


def _tuple(value: object, label: str, maximum: int) -> tuple[object, ...]:
    if type(value) is not tuple or len(value) > maximum:
        raise RequirementTraceConsolidationError(
            f"{label} must be a bounded immutable tuple"
        )
    return value


def _canonical(
    value: object,
    label: str,
    validator,
    *,
    maximum: int = MAX_REFERENCES,
    allow_empty: bool = True,
) -> tuple[str, ...]:
    values = tuple(
        validator(item, f"{label}[{index}]")
        for index, item in enumerate(_tuple(value, label, maximum))
    )
    if not allow_empty and not values:
        raise RequirementTraceConsolidationError(f"{label} must not be empty")
    if values != tuple(sorted(set(values))):
        raise RequirementTraceConsolidationError(
            f"{label} must use canonical unique order"
        )
    return values


def _codes(
    value: object,
    label: str,
    *,
    maximum: int = MAX_REFERENCES,
    allow_empty: bool = True,
) -> tuple[str, ...]:
    return _canonical(
        value,
        label,
        _code,
        maximum=maximum,
        allow_empty=allow_empty,
    )


def _refs(
    value: object,
    label: str,
    *,
    maximum: int = MAX_REFERENCES,
    allow_empty: bool = True,
) -> tuple[str, ...]:
    return _canonical(
        value,
        label,
        _reference,
        maximum=maximum,
        allow_empty=allow_empty,
    )


def _sections(value: object, label: str) -> tuple[str, ...]:
    values = tuple(
        _scalar(item, f"{label}[{index}]", 32)
        for index, item in enumerate(_tuple(value, label, len(BlueprintSection)))
    )
    allowed = {f"P3B:{item.value}" for item in BlueprintSection}
    if not values:
        raise RequirementTraceConsolidationError(f"{label} must not be empty")
    if any(item not in allowed for item in values):
        raise RequirementTraceConsolidationError(
            f"{label} contains an unknown P3-B section reference"
        )
    if values != tuple(sorted(set(values))):
        raise RequirementTraceConsolidationError(
            f"{label} must use canonical unique order"
        )
    return values


def _enum(value: object, enum_type: type[Enum], label: str) -> Enum:
    if type(value) is not str:
        raise RequirementTraceConsolidationError(f"{label} must be a string enum")
    try:
        return enum_type(value)
    except ValueError as error:
        raise RequirementTraceConsolidationError(
            f"{label} has an unsupported value"
        ) from error


@dataclass(frozen=True)
class RequirementTraceInput:
    requirement_id: str
    blueprint_section_refs: tuple[str, ...]
    task_ids: tuple[str, ...]
    artifact_refs: tuple[str, ...]
    consolidation_refs: tuple[str, ...]
    conflict_resolution_ids: tuple[str, ...] = ()
    residual_gap_ids: tuple[str, ...] = ()
    next_evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self) is not RequirementTraceInput:
            raise RequirementTraceConsolidationError(
                "RequirementTraceInput subclasses are not accepted"
            )
        _requirement_id(self.requirement_id, "requirement.requirement_id")
        _sections(self.blueprint_section_refs, "requirement.blueprint_section_refs")
        _codes(self.task_ids, "requirement.task_ids", allow_empty=False)
        _refs(self.artifact_refs, "requirement.artifact_refs", allow_empty=False)
        _refs(
            self.consolidation_refs,
            "requirement.consolidation_refs",
            allow_empty=False,
        )
        _codes(self.conflict_resolution_ids, "requirement.conflict_resolution_ids")
        _codes(self.residual_gap_ids, "requirement.residual_gap_ids")
        _refs(self.next_evidence_refs, "requirement.next_evidence_refs")


@dataclass(frozen=True)
class ConflictResolution:
    conflict_id: str
    task_ids: tuple[str, ...]
    write_paths: tuple[str, ...]
    state: ConflictState
    resolution_code: str
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self) is not ConflictResolution:
            raise RequirementTraceConsolidationError(
                "ConflictResolution subclasses are not accepted"
            )
        _code(self.conflict_id, "conflict.conflict_id")
        task_ids = _codes(
            self.task_ids,
            "conflict.task_ids",
            maximum=2,
            allow_empty=False,
        )
        if len(task_ids) != 2:
            raise RequirementTraceConsolidationError(
                "conflict.task_ids must contain exactly two tasks"
            )
        _refs(self.write_paths, "conflict.write_paths", allow_empty=False)
        if type(self.state) is not ConflictState:
            raise RequirementTraceConsolidationError(
                "conflict.state must be an exact ConflictState"
            )
        _code(self.resolution_code, "conflict.resolution_code")
        _refs(self.evidence_refs, "conflict.evidence_refs", allow_empty=False)


@dataclass(frozen=True)
class ResidualGap:
    gap_id: str
    requirement_id: str
    state: GapState
    next_evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self) is not ResidualGap:
            raise RequirementTraceConsolidationError(
                "ResidualGap subclasses are not accepted"
            )
        _code(self.gap_id, "gap.gap_id")
        _requirement_id(self.requirement_id, "gap.requirement_id")
        if type(self.state) is not GapState:
            raise RequirementTraceConsolidationError(
                "gap.state must be an exact GapState"
            )
        refs = _refs(self.next_evidence_refs, "gap.next_evidence_refs")
        if self.state is not GapState.CLOSED and not refs:
            raise RequirementTraceConsolidationError(
                "open or blocking gaps require next evidence references"
            )


@dataclass(frozen=True)
class ConsolidationReview:
    review_id: str
    consolidator_id: str
    reviewer_id: str
    verdict: ReviewVerdict
    phase: LifecyclePhase
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self) is not ConsolidationReview:
            raise RequirementTraceConsolidationError(
                "ConsolidationReview subclasses are not accepted"
            )
        _code(self.review_id, "review.review_id")
        _code(self.consolidator_id, "review.consolidator_id")
        _code(self.reviewer_id, "review.reviewer_id")
        if type(self.verdict) is not ReviewVerdict:
            raise RequirementTraceConsolidationError(
                "review.verdict must be an exact ReviewVerdict"
            )
        if type(self.phase) is not LifecyclePhase:
            raise RequirementTraceConsolidationError(
                "review.phase must be an exact LifecyclePhase"
            )
        _refs(self.evidence_refs, "review.evidence_refs", allow_empty=False)


@dataclass(frozen=True)
class RequirementTrace:
    requirement_id: str
    p3a_intent_decision_sha256: str
    p3b_blueprint_sha256: str
    blueprint_section_refs: tuple[str, ...]
    task_ids: tuple[str, ...]
    dependency_task_ids: tuple[str, ...]
    artifact_refs: tuple[str, ...]
    consolidation_refs: tuple[str, ...]
    conflict_resolution_ids: tuple[str, ...]
    residual_gap_ids: tuple[str, ...]
    next_evidence_refs: tuple[str, ...]
    phase: LifecyclePhase
    phase_evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self) is not RequirementTrace:
            raise RequirementTraceConsolidationError(
                "RequirementTrace subclasses are not accepted"
            )
        _requirement_id(self.requirement_id, "trace.requirement_id")
        _digest(
            self.p3a_intent_decision_sha256,
            "trace.p3a_intent_decision_sha256",
        )
        _digest(self.p3b_blueprint_sha256, "trace.p3b_blueprint_sha256")
        _sections(self.blueprint_section_refs, "trace.blueprint_section_refs")
        _codes(self.task_ids, "trace.task_ids", allow_empty=False)
        _codes(self.dependency_task_ids, "trace.dependency_task_ids")
        _refs(self.artifact_refs, "trace.artifact_refs", allow_empty=False)
        _refs(
            self.consolidation_refs,
            "trace.consolidation_refs",
            allow_empty=False,
        )
        _codes(self.conflict_resolution_ids, "trace.conflict_resolution_ids")
        _codes(self.residual_gap_ids, "trace.residual_gap_ids")
        _refs(self.next_evidence_refs, "trace.next_evidence_refs")
        if type(self.phase) is not LifecyclePhase:
            raise RequirementTraceConsolidationError(
                "trace.phase must be an exact LifecyclePhase"
            )
        _refs(self.phase_evidence_refs, "trace.phase_evidence_refs")


@dataclass(frozen=True)
class ConsolidationUserResult:
    status_code: str
    result_code: str
    next_step_code: str
    phase: LifecyclePhase

    def __post_init__(self) -> None:
        if type(self) is not ConsolidationUserResult:
            raise RequirementTraceConsolidationError(
                "ConsolidationUserResult subclasses are not accepted"
            )
        _code(self.status_code, "user_result.status_code")
        _code(self.result_code, "user_result.result_code")
        _code(self.next_step_code, "user_result.next_step_code")
        if type(self.phase) is not LifecyclePhase:
            raise RequirementTraceConsolidationError(
                "user_result.phase must be an exact LifecyclePhase"
            )


@dataclass(frozen=True)
class RequirementTraceConsolidation:
    schema_version: str
    consolidation_id: str
    consolidator_id: str
    source_lifecycle_sha256: str
    source_lifecycle: GoalDeliveryLifecycle
    lifecycle_run_id: str
    plan_id: str
    plan_sha256: str
    checkpoint_tip_sha256: str | None
    p3a_intent_decision_sha256: str
    p3b_blueprint_sha256: str
    traces: tuple[RequirementTrace, ...]
    conflicts: tuple[ConflictResolution, ...]
    residual_gaps: tuple[ResidualGap, ...]
    review: ConsolidationReview | None
    phase: LifecyclePhase
    phase_evidence_refs: tuple[str, ...]
    state: ConsolidationState
    reason_codes: tuple[str, ...]
    user_result: ConsolidationUserResult
    execution_performed: bool

    def __post_init__(self) -> None:
        if type(self) is not RequirementTraceConsolidation:
            raise RequirementTraceConsolidationError(
                "RequirementTraceConsolidation subclasses are not accepted"
            )
        if self.schema_version != P3H_SCHEMA_VERSION:
            raise RequirementTraceConsolidationError(
                "unsupported requirement-trace schema_version"
            )
        _code(self.consolidation_id, "consolidation_id")
        _code(self.consolidator_id, "consolidator_id")
        _digest(self.source_lifecycle_sha256, "source_lifecycle_sha256")
        if type(self.source_lifecycle) is not GoalDeliveryLifecycle:
            raise RequirementTraceConsolidationError(
                "source_lifecycle must be an exact GoalDeliveryLifecycle"
            )
        lifecycle_bytes = render_goal_delivery_lifecycle(self.source_lifecycle)
        if hashlib.sha256(lifecycle_bytes).hexdigest() != self.source_lifecycle_sha256:
            raise RequirementTraceConsolidationError(
                "source_lifecycle_sha256 does not bind source_lifecycle"
            )
        _code(self.lifecycle_run_id, "lifecycle_run_id")
        _code(self.plan_id, "plan_id")
        _digest(self.plan_sha256, "plan_sha256")
        if self.checkpoint_tip_sha256 is not None:
            _digest(self.checkpoint_tip_sha256, "checkpoint_tip_sha256")
        _digest(
            self.p3a_intent_decision_sha256,
            "p3a_intent_decision_sha256",
        )
        _digest(self.p3b_blueprint_sha256, "p3b_blueprint_sha256")
        traces = _tuple(self.traces, "traces", MAX_REQUIREMENTS)
        if not traces or any(type(item) is not RequirementTrace for item in traces):
            raise RequirementTraceConsolidationError(
                "traces must contain exact RequirementTrace records"
            )
        trace_ids = tuple(item.requirement_id for item in traces)
        if trace_ids != tuple(sorted(set(trace_ids))):
            raise RequirementTraceConsolidationError(
                "traces must use canonical unique requirement order"
            )
        conflicts = _tuple(self.conflicts, "conflicts", MAX_CONFLICTS)
        if any(type(item) is not ConflictResolution for item in conflicts):
            raise RequirementTraceConsolidationError(
                "conflicts must contain exact ConflictResolution records"
            )
        conflict_ids = tuple(item.conflict_id for item in conflicts)
        if conflict_ids != tuple(sorted(set(conflict_ids))):
            raise RequirementTraceConsolidationError(
                "conflicts must use canonical unique conflict order"
            )
        gaps = _tuple(self.residual_gaps, "residual_gaps", MAX_GAPS)
        if any(type(item) is not ResidualGap for item in gaps):
            raise RequirementTraceConsolidationError(
                "residual_gaps must contain exact ResidualGap records"
            )
        gap_ids = tuple(item.gap_id for item in gaps)
        if gap_ids != tuple(sorted(set(gap_ids))):
            raise RequirementTraceConsolidationError(
                "residual_gaps must use canonical unique gap order"
            )
        if self.review is not None and type(self.review) is not ConsolidationReview:
            raise RequirementTraceConsolidationError(
                "review must be an exact ConsolidationReview or null"
            )
        if type(self.phase) is not LifecyclePhase:
            raise RequirementTraceConsolidationError(
                "phase must be an exact LifecyclePhase"
            )
        _refs(self.phase_evidence_refs, "phase_evidence_refs")
        if type(self.state) is not ConsolidationState:
            raise RequirementTraceConsolidationError(
                "state must be an exact ConsolidationState"
            )
        _codes(self.reason_codes, "reason_codes")
        if type(self.user_result) is not ConsolidationUserResult:
            raise RequirementTraceConsolidationError(
                "user_result must be an exact ConsolidationUserResult"
            )
        if self.execution_performed is not False:
            raise RequirementTraceConsolidationError(
                "P3-H cannot claim executor or external activity"
            )


def _transitive_dependencies(lifecycle: GoalDeliveryLifecycle, task_ids: set[str]) -> tuple[str, ...]:
    dependencies = {item.task_id: set(item.depends_on) for item in lifecycle.plan.routes}
    pending = list(task_ids)
    found: set[str] = set()
    while pending:
        task_id = pending.pop()
        for dependency in dependencies.get(task_id, set()):
            if dependency not in found:
                found.add(dependency)
                pending.append(dependency)
    return tuple(sorted(found))


def _overlapping_writes(lifecycle: GoalDeliveryLifecycle) -> dict[tuple[str, str], tuple[str, ...]]:
    routes = tuple(lifecycle.plan.routes)
    overlaps: dict[tuple[str, str], tuple[str, ...]] = {}
    for index, left in enumerate(routes):
        left_paths = set(left.context.write_paths)
        if not left_paths:
            continue
        for right in routes[index + 1 :]:
            shared = tuple(sorted(left_paths.intersection(right.context.write_paths)))
            if shared:
                overlaps[tuple(sorted((left.task_id, right.task_id)))] = shared
    return overlaps


def _phase_evidence(lifecycle: GoalDeliveryLifecycle) -> tuple[str, ...]:
    if lifecycle.phase is LifecyclePhase.PLANNED:
        return ()
    matching = tuple(
        item
        for item in lifecycle.phase_acceptances
        if item.phase is lifecycle.phase and item.evidence_domain is lifecycle.phase
    )
    if len(matching) != 1:
        return ()
    return matching[0].evidence_refs


def _state_and_reasons(
    *,
    lifecycle: GoalDeliveryLifecycle,
    requirements: tuple[RequirementTraceInput, ...],
    conflicts: tuple[ConflictResolution, ...],
    gaps: tuple[ResidualGap, ...],
    review: ConsolidationReview | None,
    consolidator_id: str,
    phase_evidence_refs: tuple[str, ...],
) -> tuple[ConsolidationState, tuple[str, ...]]:
    block: set[str] = set()
    needs: set[str] = set()
    route_ids = {item.task_id for item in lifecycle.plan.routes}
    accepted_ids = set(lifecycle.accepted_task_ids)
    claimed = [task_id for item in requirements for task_id in item.task_ids]
    claimed_set = set(claimed)
    if lifecycle.state is not LifecycleState.COMPLETE:
        block.add("lifecycle-not-complete")
    if not lifecycle.checkpoints:
        block.add("checkpoint-chain-missing")
    if claimed_set - route_ids:
        block.add("unknown-task")
    if len(claimed) != len(claimed_set):
        block.add("task-overlap")
    if claimed_set != route_ids or claimed_set != accepted_ids:
        block.add("task-coverage-mismatch")

    evidence_by_task = {item.task_id: item for item in lifecycle.task_evidence}
    consolidation_by_task = {
        item.task_id: item.consolidation_ref for item in lifecycle.consolidations
    }
    for item in requirements:
        known = set(item.task_ids).intersection(route_ids)
        expected_artifacts = {
            reference
            for task_id in known
            for reference in evidence_by_task.get(task_id, ()).output_refs
        } if all(task_id in evidence_by_task for task_id in known) else set()
        if set(item.artifact_refs) != expected_artifacts:
            block.add("artifact-binding-mismatch")
        expected_consolidations = {
            consolidation_by_task[task_id]
            for task_id in known
            if task_id in consolidation_by_task
        }
        if set(item.consolidation_refs) != expected_consolidations:
            block.add("consolidation-binding-mismatch")

    conflicts_by_pair = {item.task_ids: item for item in conflicts}
    overlaps = _overlapping_writes(lifecycle)
    if set(conflicts_by_pair) - set(overlaps):
        block.add("conflict-binding-mismatch")
    for pair, paths in overlaps.items():
        conflict = conflicts_by_pair.get(pair)
        if conflict is None:
            block.add("conflict-resolution-missing")
            continue
        if conflict.write_paths != paths:
            block.add("conflict-binding-mismatch")
        if conflict.state is not ConflictState.RESOLVED:
            block.add("conflict-unresolved")

    requirement_ids = {item.requirement_id for item in requirements}
    conflict_ids = {item.conflict_id for item in conflicts}
    gap_ids = {item.gap_id for item in gaps}
    for item in requirements:
        if not set(item.conflict_resolution_ids).issubset(conflict_ids):
            block.add("requirement-conflict-binding-mismatch")
        if not set(item.residual_gap_ids).issubset(gap_ids):
            block.add("requirement-gap-binding-mismatch")
    for item in conflicts:
        owners = {
            requirement.requirement_id
            for requirement in requirements
            if set(item.task_ids).intersection(requirement.task_ids)
        }
        declared = {
            requirement.requirement_id
            for requirement in requirements
            if item.conflict_id in requirement.conflict_resolution_ids
        }
        if declared != owners:
            block.add("requirement-conflict-binding-mismatch")
    for item in gaps:
        if item.requirement_id not in requirement_ids:
            block.add("gap-requirement-unknown")
        declared = next(
            (
                requirement
                for requirement in requirements
                if requirement.requirement_id == item.requirement_id
            ),
            None,
        )
        if declared is None or item.gap_id not in declared.residual_gap_ids:
            block.add("requirement-gap-binding-mismatch")
        if item.state is GapState.BLOCKING:
            block.add("blocking-gap")
        elif item.state is GapState.OPEN:
            needs.add("open-gap")
        if item.state is not GapState.CLOSED and declared is not None:
            if not set(item.next_evidence_refs).issubset(declared.next_evidence_refs):
                block.add("gap-next-evidence-mismatch")

    if lifecycle.phase is LifecyclePhase.PLANNED:
        needs.add("post-plan-phase-evidence-required")
    elif not phase_evidence_refs:
        block.add("phase-evidence-mismatch")
    if review is None:
        needs.add("independent-review-required")
    else:
        if review.phase is not lifecycle.phase:
            block.add("review-phase-mismatch")
        if review.consolidator_id != consolidator_id:
            block.add("review-consolidator-mismatch")
        if review.reviewer_id == consolidator_id:
            block.add("reviewer-not-independent")
        if review.verdict is ReviewVerdict.BLOCK:
            block.add("independent-review-blocked")

    if block:
        return ConsolidationState.BLOCK, tuple(sorted(block | needs))
    if needs:
        return ConsolidationState.NEEDS_EVIDENCE, tuple(sorted(needs))
    return ConsolidationState.ACCEPT, ()


def _user_result(
    state: ConsolidationState, phase: LifecyclePhase
) -> ConsolidationUserResult:
    if state is ConsolidationState.ACCEPT:
        return ConsolidationUserResult(
            status_code="accepted",
            result_code="requirements-consolidated",
            next_step_code="review-final-result",
            phase=phase,
        )
    if state is ConsolidationState.NEEDS_EVIDENCE:
        return ConsolidationUserResult(
            status_code="needs-evidence",
            result_code="consolidation-incomplete",
            next_step_code="collect-next-evidence",
            phase=phase,
        )
    return ConsolidationUserResult(
        status_code="blocked",
        result_code="consolidation-blocked",
        next_step_code="resolve-blockers",
        phase=phase,
    )


def build_requirement_trace_consolidation(
    lifecycle_payload: bytes | bytearray | memoryview,
    *,
    consolidation_id: str,
    consolidator_id: str,
    requirements: Sequence[RequirementTraceInput],
    conflicts: Sequence[ConflictResolution] = (),
    residual_gaps: Sequence[ResidualGap] = (),
    review: ConsolidationReview | None = None,
) -> RequirementTraceConsolidation:
    """Build a deterministic trace from exact canonical P3-G bytes."""

    try:
        lifecycle = parse_goal_delivery_lifecycle(lifecycle_payload)
    except (GoalDeliveryLifecycleError, TypeError, ValueError) as error:
        raise RequirementTraceConsolidationError(
            "P3-G lifecycle is invalid"
        ) from error
    identifier = _code(consolidation_id, "consolidation_id")
    owner = _code(consolidator_id, "consolidator_id")
    requirement_records = tuple(requirements)
    if (
        not requirement_records
        or len(requirement_records) > MAX_REQUIREMENTS
        or any(type(item) is not RequirementTraceInput for item in requirement_records)
    ):
        raise RequirementTraceConsolidationError(
            "requirements must contain bounded exact RequirementTraceInput records"
        )
    requirement_records = tuple(
        sorted(requirement_records, key=lambda item: item.requirement_id)
    )
    requirement_ids = tuple(item.requirement_id for item in requirement_records)
    if len(set(requirement_ids)) != len(requirement_ids):
        raise RequirementTraceConsolidationError(
            "requirements contain duplicate requirement IDs"
        )
    conflict_records = tuple(conflicts)
    if (
        len(conflict_records) > MAX_CONFLICTS
        or any(type(item) is not ConflictResolution for item in conflict_records)
    ):
        raise RequirementTraceConsolidationError(
            "conflicts must contain bounded exact ConflictResolution records"
        )
    conflict_records = tuple(sorted(conflict_records, key=lambda item: item.conflict_id))
    if len({item.conflict_id for item in conflict_records}) != len(conflict_records):
        raise RequirementTraceConsolidationError("conflicts contain duplicate IDs")
    if len({item.task_ids for item in conflict_records}) != len(conflict_records):
        raise RequirementTraceConsolidationError(
            "conflicts contain duplicate task-pair bindings"
        )
    gap_records = tuple(residual_gaps)
    if (
        len(gap_records) > MAX_GAPS
        or any(type(item) is not ResidualGap for item in gap_records)
    ):
        raise RequirementTraceConsolidationError(
            "residual_gaps must contain bounded exact ResidualGap records"
        )
    gap_records = tuple(sorted(gap_records, key=lambda item: item.gap_id))
    if len({item.gap_id for item in gap_records}) != len(gap_records):
        raise RequirementTraceConsolidationError(
            "residual_gaps contain duplicate IDs"
        )
    if review is not None and type(review) is not ConsolidationReview:
        raise RequirementTraceConsolidationError(
            "review must be an exact ConsolidationReview or null"
        )

    lifecycle_bytes = render_goal_delivery_lifecycle(lifecycle)
    readiness = lifecycle.plan.source.readiness
    blueprint = readiness.source.blueprint
    intent = blueprint.source.intent_decision
    p3a_sha256 = hashlib.sha256(render_intent_decision_result(intent)).hexdigest()
    p3b_sha256 = hashlib.sha256(render_project_blueprint(blueprint)).hexdigest()
    phase_evidence_refs = _phase_evidence(lifecycle)
    traces = tuple(
        RequirementTrace(
            requirement_id=item.requirement_id,
            p3a_intent_decision_sha256=p3a_sha256,
            p3b_blueprint_sha256=p3b_sha256,
            blueprint_section_refs=item.blueprint_section_refs,
            task_ids=item.task_ids,
            dependency_task_ids=_transitive_dependencies(
                lifecycle, set(item.task_ids)
            ),
            artifact_refs=item.artifact_refs,
            consolidation_refs=item.consolidation_refs,
            conflict_resolution_ids=item.conflict_resolution_ids,
            residual_gap_ids=item.residual_gap_ids,
            next_evidence_refs=item.next_evidence_refs,
            phase=lifecycle.phase,
            phase_evidence_refs=phase_evidence_refs,
        )
        for item in requirement_records
    )
    state, reason_codes = _state_and_reasons(
        lifecycle=lifecycle,
        requirements=requirement_records,
        conflicts=conflict_records,
        gaps=gap_records,
        review=review,
        consolidator_id=owner,
        phase_evidence_refs=phase_evidence_refs,
    )
    checkpoint_tip = (
        lifecycle.checkpoints[-1].checkpoint_sha256
        if lifecycle.checkpoints
        else None
    )
    return RequirementTraceConsolidation(
        schema_version=P3H_SCHEMA_VERSION,
        consolidation_id=identifier,
        consolidator_id=owner,
        source_lifecycle_sha256=hashlib.sha256(lifecycle_bytes).hexdigest(),
        source_lifecycle=lifecycle,
        lifecycle_run_id=lifecycle.lifecycle_run_id,
        plan_id=lifecycle.plan_id,
        plan_sha256=lifecycle.plan_sha256,
        checkpoint_tip_sha256=checkpoint_tip,
        p3a_intent_decision_sha256=p3a_sha256,
        p3b_blueprint_sha256=p3b_sha256,
        traces=traces,
        conflicts=conflict_records,
        residual_gaps=gap_records,
        review=review,
        phase=lifecycle.phase,
        phase_evidence_refs=phase_evidence_refs,
        state=state,
        reason_codes=reason_codes,
        user_result=_user_result(state, lifecycle.phase),
        execution_performed=False,
    )


def _trace_input(value: RequirementTrace) -> RequirementTraceInput:
    return RequirementTraceInput(
        requirement_id=value.requirement_id,
        blueprint_section_refs=value.blueprint_section_refs,
        task_ids=value.task_ids,
        artifact_refs=value.artifact_refs,
        consolidation_refs=value.consolidation_refs,
        conflict_resolution_ids=value.conflict_resolution_ids,
        residual_gap_ids=value.residual_gap_ids,
        next_evidence_refs=value.next_evidence_refs,
    )


def _recompute(value: RequirementTraceConsolidation) -> RequirementTraceConsolidation:
    return build_requirement_trace_consolidation(
        render_goal_delivery_lifecycle(value.source_lifecycle),
        consolidation_id=value.consolidation_id,
        consolidator_id=value.consolidator_id,
        requirements=tuple(_trace_input(item) for item in value.traces),
        conflicts=value.conflicts,
        residual_gaps=value.residual_gaps,
        review=value.review,
    )


def _requirement_mapping(value: RequirementTrace) -> dict[str, object]:
    return {
        "artifact_refs": list(value.artifact_refs),
        "blueprint_section_refs": list(value.blueprint_section_refs),
        "conflict_resolution_ids": list(value.conflict_resolution_ids),
        "consolidation_refs": list(value.consolidation_refs),
        "dependency_task_ids": list(value.dependency_task_ids),
        "next_evidence_refs": list(value.next_evidence_refs),
        "p3a_intent_decision_sha256": value.p3a_intent_decision_sha256,
        "p3b_blueprint_sha256": value.p3b_blueprint_sha256,
        "phase": value.phase.value,
        "phase_evidence_refs": list(value.phase_evidence_refs),
        "requirement_id": value.requirement_id,
        "residual_gap_ids": list(value.residual_gap_ids),
        "task_ids": list(value.task_ids),
    }


def _conflict_mapping(value: ConflictResolution) -> dict[str, object]:
    return {
        "conflict_id": value.conflict_id,
        "evidence_refs": list(value.evidence_refs),
        "resolution_code": value.resolution_code,
        "state": value.state.value,
        "task_ids": list(value.task_ids),
        "write_paths": list(value.write_paths),
    }


def _gap_mapping(value: ResidualGap) -> dict[str, object]:
    return {
        "gap_id": value.gap_id,
        "next_evidence_refs": list(value.next_evidence_refs),
        "requirement_id": value.requirement_id,
        "state": value.state.value,
    }


def _review_mapping(value: ConsolidationReview) -> dict[str, object]:
    return {
        "consolidator_id": value.consolidator_id,
        "evidence_refs": list(value.evidence_refs),
        "phase": value.phase.value,
        "review_id": value.review_id,
        "reviewer_id": value.reviewer_id,
        "verdict": value.verdict.value,
    }


def _mapping(value: RequirementTraceConsolidation) -> dict[str, object]:
    return {
        "checkpoint_tip_sha256": value.checkpoint_tip_sha256,
        "conflicts": [_conflict_mapping(item) for item in value.conflicts],
        "consolidation_id": value.consolidation_id,
        "consolidator_id": value.consolidator_id,
        "execution_performed": value.execution_performed,
        "lifecycle_run_id": value.lifecycle_run_id,
        "p3a_intent_decision_sha256": value.p3a_intent_decision_sha256,
        "p3b_blueprint_sha256": value.p3b_blueprint_sha256,
        "phase": value.phase.value,
        "phase_evidence_refs": list(value.phase_evidence_refs),
        "plan_id": value.plan_id,
        "plan_sha256": value.plan_sha256,
        "reason_codes": list(value.reason_codes),
        "residual_gaps": [_gap_mapping(item) for item in value.residual_gaps],
        "review": None if value.review is None else _review_mapping(value.review),
        "schema_version": value.schema_version,
        "source_lifecycle": json.loads(render_goal_delivery_lifecycle(value.source_lifecycle)),
        "source_lifecycle_sha256": value.source_lifecycle_sha256,
        "state": value.state.value,
        "traces": [_requirement_mapping(item) for item in value.traces],
        "user_result": {
            "next_step_code": value.user_result.next_step_code,
            "phase": value.user_result.phase.value,
            "result_code": value.user_result.result_code,
            "status_code": value.user_result.status_code,
        },
    }


def render_requirement_trace_consolidation(
    value: RequirementTraceConsolidation,
) -> bytes:
    """Render canonical JSON after full P3-H recomputation."""

    if type(value) is not RequirementTraceConsolidation:
        raise TypeError(
            "value must be an exact RequirementTraceConsolidation"
        )
    if _recompute(value) != value:
        raise RequirementTraceConsolidationError(
            "requirement trace does not match recomputed evidence"
        )
    try:
        rendered = canonical_json_bytes(_mapping(value))
    except SchemaError as error:
        raise RequirementTraceConsolidationError(
            f"requirement trace cannot be encoded: {error}"
        ) from error
    if len(rendered) > MAX_REQUIREMENT_TRACE_CONSOLIDATION_BYTES:
        raise RequirementTraceConsolidationError(
            "rendered requirement trace exceeds its byte bound"
        )
    return rendered


def requirement_trace_user_result(
    value: RequirementTraceConsolidation,
) -> dict[str, str]:
    """Return the compact ordinary-user projection without operator trace."""

    if type(value) is not RequirementTraceConsolidation:
        raise TypeError(
            "value must be an exact RequirementTraceConsolidation"
        )
    expected = _recompute(value)
    if expected != value:
        raise RequirementTraceConsolidationError(
            "requirement trace does not match recomputed evidence"
        )
    return {
        "status": value.user_result.status_code,
        "result": value.user_result.result_code,
        "next_step": value.user_result.next_step_code,
        "phase": value.user_result.phase.value,
    }


def _closed(value: object, fields: frozenset[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RequirementTraceConsolidationError(f"{label} must be an object")
    keys = set(value)
    if any(type(key) is not str for key in keys):
        raise RequirementTraceConsolidationError(f"{label} keys must be strings")
    unknown = sorted(keys - fields)
    missing = sorted(fields - keys)
    if unknown:
        raise RequirementTraceConsolidationError(
            f"{label} contains unknown fields: {', '.join(unknown)}"
        )
    if missing:
        raise RequirementTraceConsolidationError(
            f"{label} is missing fields: {', '.join(missing)}"
        )
    return value


def _array(value: object, label: str, maximum: int) -> tuple[object, ...]:
    if type(value) is not list or len(value) > maximum:
        raise RequirementTraceConsolidationError(
            f"{label} must be a bounded array"
        )
    return tuple(value)


def _parse_strings(value: object, label: str, validator, maximum: int) -> tuple[str, ...]:
    return tuple(
        validator(item, f"{label}[{index}]")
        for index, item in enumerate(_array(value, label, maximum))
    )


def _parse_trace(value: object, label: str) -> RequirementTrace:
    item = _closed(
        value,
        frozenset(
            {
                "artifact_refs",
                "blueprint_section_refs",
                "conflict_resolution_ids",
                "consolidation_refs",
                "dependency_task_ids",
                "next_evidence_refs",
                "p3a_intent_decision_sha256",
                "p3b_blueprint_sha256",
                "phase",
                "phase_evidence_refs",
                "requirement_id",
                "residual_gap_ids",
                "task_ids",
            }
        ),
        label,
    )
    return RequirementTrace(
        requirement_id=_requirement_id(item["requirement_id"], f"{label}.requirement_id"),
        p3a_intent_decision_sha256=_digest(
            item["p3a_intent_decision_sha256"],
            f"{label}.p3a_intent_decision_sha256",
        ),
        p3b_blueprint_sha256=_digest(
            item["p3b_blueprint_sha256"], f"{label}.p3b_blueprint_sha256"
        ),
        blueprint_section_refs=_parse_strings(
            item["blueprint_section_refs"],
            f"{label}.blueprint_section_refs",
            lambda value, nested: _scalar(value, nested, 32),
            len(BlueprintSection),
        ),
        task_ids=_parse_strings(item["task_ids"], f"{label}.task_ids", _code, MAX_REFERENCES),
        dependency_task_ids=_parse_strings(
            item["dependency_task_ids"],
            f"{label}.dependency_task_ids",
            _code,
            MAX_REFERENCES,
        ),
        artifact_refs=_parse_strings(
            item["artifact_refs"], f"{label}.artifact_refs", _reference, MAX_REFERENCES
        ),
        consolidation_refs=_parse_strings(
            item["consolidation_refs"],
            f"{label}.consolidation_refs",
            _reference,
            MAX_REFERENCES,
        ),
        conflict_resolution_ids=_parse_strings(
            item["conflict_resolution_ids"],
            f"{label}.conflict_resolution_ids",
            _code,
            MAX_REFERENCES,
        ),
        residual_gap_ids=_parse_strings(
            item["residual_gap_ids"],
            f"{label}.residual_gap_ids",
            _code,
            MAX_REFERENCES,
        ),
        next_evidence_refs=_parse_strings(
            item["next_evidence_refs"],
            f"{label}.next_evidence_refs",
            _reference,
            MAX_REFERENCES,
        ),
        phase=_enum(item["phase"], LifecyclePhase, f"{label}.phase"),
        phase_evidence_refs=_parse_strings(
            item["phase_evidence_refs"],
            f"{label}.phase_evidence_refs",
            _reference,
            MAX_REFERENCES,
        ),
    )


def _parse_conflict(value: object, label: str) -> ConflictResolution:
    item = _closed(
        value,
        frozenset(
            {
                "conflict_id",
                "evidence_refs",
                "resolution_code",
                "state",
                "task_ids",
                "write_paths",
            }
        ),
        label,
    )
    return ConflictResolution(
        conflict_id=_code(item["conflict_id"], f"{label}.conflict_id"),
        task_ids=_parse_strings(item["task_ids"], f"{label}.task_ids", _code, 2),
        write_paths=_parse_strings(
            item["write_paths"], f"{label}.write_paths", _reference, MAX_REFERENCES
        ),
        state=_enum(item["state"], ConflictState, f"{label}.state"),
        resolution_code=_code(item["resolution_code"], f"{label}.resolution_code"),
        evidence_refs=_parse_strings(
            item["evidence_refs"], f"{label}.evidence_refs", _reference, MAX_REFERENCES
        ),
    )


def _parse_gap(value: object, label: str) -> ResidualGap:
    item = _closed(
        value,
        frozenset(
            {"gap_id", "next_evidence_refs", "requirement_id", "state"}
        ),
        label,
    )
    return ResidualGap(
        gap_id=_code(item["gap_id"], f"{label}.gap_id"),
        requirement_id=_requirement_id(
            item["requirement_id"], f"{label}.requirement_id"
        ),
        state=_enum(item["state"], GapState, f"{label}.state"),
        next_evidence_refs=_parse_strings(
            item["next_evidence_refs"],
            f"{label}.next_evidence_refs",
            _reference,
            MAX_REFERENCES,
        ),
    )


def _parse_review(value: object, label: str) -> ConsolidationReview:
    item = _closed(
        value,
        frozenset(
            {
                "consolidator_id",
                "evidence_refs",
                "phase",
                "review_id",
                "reviewer_id",
                "verdict",
            }
        ),
        label,
    )
    return ConsolidationReview(
        review_id=_code(item["review_id"], f"{label}.review_id"),
        consolidator_id=_code(item["consolidator_id"], f"{label}.consolidator_id"),
        reviewer_id=_code(item["reviewer_id"], f"{label}.reviewer_id"),
        verdict=_enum(item["verdict"], ReviewVerdict, f"{label}.verdict"),
        phase=_enum(item["phase"], LifecyclePhase, f"{label}.phase"),
        evidence_refs=_parse_strings(
            item["evidence_refs"], f"{label}.evidence_refs", _reference, MAX_REFERENCES
        ),
    )


def _reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise RequirementTraceConsolidationError(
                "requirement trace contains duplicate object keys"
            )
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise RequirementTraceConsolidationError(
        f"requirement trace contains unsupported JSON constant: {value}"
    )


def parse_requirement_trace_consolidation(
    payload: bytes | bytearray | memoryview,
) -> RequirementTraceConsolidation:
    """Parse only bounded canonical UTF-8 JSON with full source recomputation."""

    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise RequirementTraceConsolidationError(
            "requirement-trace payload must be bytes"
        )
    raw = bytes(payload)
    if not raw or len(raw) > MAX_REQUIREMENT_TRACE_CONSOLIDATION_BYTES:
        raise RequirementTraceConsolidationError(
            "requirement-trace payload must use bounded non-empty bytes"
        )
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicates,
            parse_constant=_reject_constant,
        )
    except RequirementTraceConsolidationError:
        raise
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
        RecursionError,
    ) as error:
        raise RequirementTraceConsolidationError(
            "requirement trace is not valid UTF-8 JSON"
        ) from error
    item = _closed(
        value,
        frozenset(
            {
                "checkpoint_tip_sha256",
                "conflicts",
                "consolidation_id",
                "consolidator_id",
                "execution_performed",
                "lifecycle_run_id",
                "p3a_intent_decision_sha256",
                "p3b_blueprint_sha256",
                "phase",
                "phase_evidence_refs",
                "plan_id",
                "plan_sha256",
                "reason_codes",
                "residual_gaps",
                "review",
                "schema_version",
                "source_lifecycle",
                "source_lifecycle_sha256",
                "state",
                "traces",
                "user_result",
            }
        ),
        "requirement_trace",
    )
    try:
        lifecycle = parse_goal_delivery_lifecycle(
            canonical_json_bytes(item["source_lifecycle"])
        )
    except (GoalDeliveryLifecycleError, SchemaError, TypeError, ValueError) as error:
        raise RequirementTraceConsolidationError(
            "embedded P3-G lifecycle is invalid"
        ) from error
    review_value = item["review"]
    review = None if review_value is None else _parse_review(review_value, "review")
    user_item = _closed(
        item["user_result"],
        frozenset({"next_step_code", "phase", "result_code", "status_code"}),
        "user_result",
    )
    checkpoint_tip = item["checkpoint_tip_sha256"]
    if checkpoint_tip is not None:
        checkpoint_tip = _digest(checkpoint_tip, "checkpoint_tip_sha256")
    record = RequirementTraceConsolidation(
        schema_version=_scalar(item["schema_version"], "schema_version", 16),
        consolidation_id=_code(item["consolidation_id"], "consolidation_id"),
        consolidator_id=_code(item["consolidator_id"], "consolidator_id"),
        source_lifecycle_sha256=_digest(
            item["source_lifecycle_sha256"], "source_lifecycle_sha256"
        ),
        source_lifecycle=lifecycle,
        lifecycle_run_id=_code(item["lifecycle_run_id"], "lifecycle_run_id"),
        plan_id=_code(item["plan_id"], "plan_id"),
        plan_sha256=_digest(item["plan_sha256"], "plan_sha256"),
        checkpoint_tip_sha256=checkpoint_tip,
        p3a_intent_decision_sha256=_digest(
            item["p3a_intent_decision_sha256"], "p3a_intent_decision_sha256"
        ),
        p3b_blueprint_sha256=_digest(
            item["p3b_blueprint_sha256"], "p3b_blueprint_sha256"
        ),
        traces=tuple(
            _parse_trace(entry, f"traces[{index}]")
            for index, entry in enumerate(
                _array(item["traces"], "traces", MAX_REQUIREMENTS)
            )
        ),
        conflicts=tuple(
            _parse_conflict(entry, f"conflicts[{index}]")
            for index, entry in enumerate(
                _array(item["conflicts"], "conflicts", MAX_CONFLICTS)
            )
        ),
        residual_gaps=tuple(
            _parse_gap(entry, f"residual_gaps[{index}]")
            for index, entry in enumerate(
                _array(item["residual_gaps"], "residual_gaps", MAX_GAPS)
            )
        ),
        review=review,
        phase=_enum(item["phase"], LifecyclePhase, "phase"),
        phase_evidence_refs=_parse_strings(
            item["phase_evidence_refs"],
            "phase_evidence_refs",
            _reference,
            MAX_REFERENCES,
        ),
        state=_enum(item["state"], ConsolidationState, "state"),
        reason_codes=_parse_strings(
            item["reason_codes"], "reason_codes", _code, MAX_REFERENCES
        ),
        user_result=ConsolidationUserResult(
            status_code=_code(user_item["status_code"], "user_result.status_code"),
            result_code=_code(user_item["result_code"], "user_result.result_code"),
            next_step_code=_code(
                user_item["next_step_code"], "user_result.next_step_code"
            ),
            phase=_enum(user_item["phase"], LifecyclePhase, "user_result.phase"),
        ),
        execution_performed=item["execution_performed"],
    )
    if render_requirement_trace_consolidation(record) != raw:
        raise RequirementTraceConsolidationError(
            "requirement-trace JSON is not canonical"
        )
    return record


__all__ = [
    "P3H_SCHEMA_VERSION",
    "MAX_REQUIREMENT_TRACE_CONSOLIDATION_BYTES",
    "RequirementTraceConsolidationError",
    "ConsolidationState",
    "ConflictState",
    "GapState",
    "RequirementTraceInput",
    "ConflictResolution",
    "ResidualGap",
    "ConsolidationReview",
    "RequirementTrace",
    "ConsolidationUserResult",
    "RequirementTraceConsolidation",
    "build_requirement_trace_consolidation",
    "render_requirement_trace_consolidation",
    "parse_requirement_trace_consolidation",
    "requirement_trace_user_result",
]
