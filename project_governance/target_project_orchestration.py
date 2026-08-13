"""Pure P3-J non-invasive target-project orchestration controller.

P3-J binds one exact canonical P3-I COMPLETE session to a caller-supplied,
redacted target snapshot. It derives requirement, component, task, capability,
review, and acceptance records without accessing or changing a target project.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
import hashlib
import json
import re
from typing import Any, Mapping, Sequence
import unicodedata

from .autonomous_task_orchestration import (
    AutonomousTaskPlan,
    render_autonomous_task_plan,
)
from .goal_delivery_lifecycle import (
    LifecyclePhase,
    LifecycleState,
    render_goal_delivery_lifecycle,
)
from .idea_result_session import (
    IdeaResultSession,
    IdeaResultSessionError,
    SessionStage,
    SessionState,
    parse_idea_result_session,
    render_idea_result_session,
)
from .project_blueprint import BlueprintSection
from .requirement_trace_consolidation import (
    ConsolidationState,
    RequirementTrace,
    render_requirement_trace_consolidation,
)
from .storage import SchemaError, canonical_json_bytes


P3J_SCHEMA_VERSION = "1.0"
MAX_TARGET_PROJECT_ORCHESTRATION_BYTES = 8 * 1024 * 1024
MAX_ITEMS = 128

_CODE = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}\Z")
_REQUIREMENT = re.compile(r"REQ-[0-9]{3}\Z")
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


class TargetProjectOrchestrationError(ValueError):
    """Raised when P3-J input or canonical state is malformed."""


class CapabilityDisposition(str, Enum):
    PRESERVE = "preserve"
    CHANGE_PROPOSED = "change-proposed"


class PreservationState(str, Enum):
    VERIFIED = "verified"
    MISSING = "missing"
    DRIFT = "drift"


class OrchestrationReviewVerdict(str, Enum):
    ACCEPT = "accept"
    BLOCK = "block"


class TargetOrchestrationState(str, Enum):
    PLAN_READY = "plan-ready"
    NEEDS_EVIDENCE = "needs-evidence"
    BLOCK = "block"
    ORCHESTRATION_ACCEPTED = "orchestration-accepted"


def _scalar(value: object, label: str, maximum: int = 240) -> str:
    if type(value) is not str or not value or len(value) > maximum:
        raise TargetProjectOrchestrationError(
            f"{label} must be bounded non-empty text"
        )
    if value != unicodedata.normalize("NFC", value):
        raise TargetProjectOrchestrationError(f"{label} must use NFC Unicode")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise TargetProjectOrchestrationError(f"{label} contains control characters")
    if _SENSITIVE.search(value):
        raise TargetProjectOrchestrationError(
            f"{label} contains a sensitive-value pattern"
        )
    return value


def _code(value: object, label: str) -> str:
    text = _scalar(value, label, 128)
    if not _CODE.fullmatch(text):
        raise TargetProjectOrchestrationError(
            f"{label} must be a bounded stable logical code"
        )
    return text


def _requirement(value: object, label: str) -> str:
    if type(value) is not str or not _REQUIREMENT.fullmatch(value):
        raise TargetProjectOrchestrationError(
            f"{label} must be a canonical REQ-three-digit identifier"
        )
    return value


def _reference(value: object, label: str) -> str:
    text = _scalar(value, label, 240)
    if _CODE.fullmatch(text):
        return text
    if (
        "\\" in text
        or text.startswith("/")
        or _WINDOWS_DRIVE.match(text)
        or "://" in text
        or ":" in text
        or "?" in text
        or "#" in text
    ):
        raise TargetProjectOrchestrationError(
            f"{label} must be a stable code or contained project-relative path"
        )
    parts = text.split("/")
    if len(parts) < 2 or any(part in ("", ".", "..") for part in parts):
        raise TargetProjectOrchestrationError(
            f"{label} must be a stable code or contained project-relative path"
        )
    return text


def _digest(value: object, label: str) -> str:
    if type(value) is not str or not _SHA256.fullmatch(value):
        raise TargetProjectOrchestrationError(
            f"{label} must be a lowercase SHA-256 digest"
        )
    return value


def _tuple(value: object, label: str, maximum: int = MAX_ITEMS) -> tuple[object, ...]:
    if type(value) is not tuple or len(value) > maximum:
        raise TargetProjectOrchestrationError(
            f"{label} must be a bounded immutable tuple"
        )
    return value


def _codes(
    value: object,
    label: str,
    *,
    allow_empty: bool = True,
    semantic_order: bool = False,
) -> tuple[str, ...]:
    items = _tuple(value, label)
    if not allow_empty and not items:
        raise TargetProjectOrchestrationError(f"{label} must not be empty")
    normalized = tuple(
        _code(item, f"{label}[{index}]") for index, item in enumerate(items)
    )
    if len(normalized) != len(set(normalized)):
        raise TargetProjectOrchestrationError(f"{label} must contain unique codes")
    if not semantic_order and normalized != tuple(sorted(normalized)):
        raise TargetProjectOrchestrationError(f"{label} must use canonical order")
    return normalized


def _requirements(value: object, label: str) -> tuple[str, ...]:
    items = _tuple(value, label)
    normalized = tuple(
        _requirement(item, f"{label}[{index}]")
        for index, item in enumerate(items)
    )
    if normalized != tuple(sorted(set(normalized))):
        raise TargetProjectOrchestrationError(
            f"{label} must use canonical unique order"
        )
    return normalized


def _sections(value: object, label: str) -> tuple[str, ...]:
    items = _tuple(value, label, len(BlueprintSection))
    values = tuple(
        _scalar(item, f"{label}[{index}]", 32)
        for index, item in enumerate(items)
    )
    allowed = {f"P3B:{section.value}" for section in BlueprintSection}
    if not values or any(item not in allowed for item in values):
        raise TargetProjectOrchestrationError(
            f"{label} must contain canonical P3-B section references"
        )
    if values != tuple(sorted(set(values))):
        raise TargetProjectOrchestrationError(
            f"{label} must use canonical unique order"
        )
    return values


def _references(value: object, label: str) -> tuple[str, ...]:
    items = _tuple(value, label)
    normalized = tuple(
        _reference(item, f"{label}[{index}]")
        for index, item in enumerate(items)
    )
    if normalized != tuple(sorted(set(normalized))):
        raise TargetProjectOrchestrationError(
            f"{label} must use canonical unique order"
        )
    return normalized


def _enum(value: object, enum_type: type[Enum], label: str) -> Enum:
    if type(value) is not str:
        raise TargetProjectOrchestrationError(f"{label} must be a string enum")
    try:
        return enum_type(value)
    except ValueError as error:
        raise TargetProjectOrchestrationError(
            f"{label} has an unsupported value"
        ) from error


@dataclass(frozen=True)
class TargetCapabilitySnapshot:
    capability_id: str
    baseline_sha256: str
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self) is not TargetCapabilitySnapshot:
            raise TargetProjectOrchestrationError(
                "TargetCapabilitySnapshot subclasses are not accepted"
            )
        _code(self.capability_id, "capability.capability_id")
        _digest(self.baseline_sha256, "capability.baseline_sha256")
        _references(self.evidence_refs, "capability.evidence_refs")
        if not self.evidence_refs:
            raise TargetProjectOrchestrationError(
                "capability.evidence_refs must not be empty"
            )


@dataclass(frozen=True)
class TargetComponentSnapshot:
    component_id: str
    baseline_sha256: str
    capability_ids: tuple[str, ...]
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self) is not TargetComponentSnapshot:
            raise TargetProjectOrchestrationError(
                "TargetComponentSnapshot subclasses are not accepted"
            )
        _code(self.component_id, "component.component_id")
        _digest(self.baseline_sha256, "component.baseline_sha256")
        _codes(self.capability_ids, "component.capability_ids", allow_empty=False)
        _references(self.evidence_refs, "component.evidence_refs")
        if not self.evidence_refs:
            raise TargetProjectOrchestrationError(
                "component.evidence_refs must not be empty"
            )


@dataclass(frozen=True)
class TargetProjectSnapshot:
    target_id: str
    capabilities: tuple[TargetCapabilitySnapshot, ...]
    components: tuple[TargetComponentSnapshot, ...]
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self) is not TargetProjectSnapshot:
            raise TargetProjectOrchestrationError(
                "TargetProjectSnapshot subclasses are not accepted"
            )
        _code(self.target_id, "target_id")
        capabilities = _tuple(self.capabilities, "target.capabilities")
        if not capabilities or any(
            type(item) is not TargetCapabilitySnapshot for item in capabilities
        ):
            raise TargetProjectOrchestrationError(
                "target.capabilities must contain exact snapshot records"
            )
        capability_ids = tuple(item.capability_id for item in capabilities)
        if capability_ids != tuple(sorted(set(capability_ids))):
            raise TargetProjectOrchestrationError(
                "target.capabilities must use canonical unique capability order"
            )
        components = _tuple(self.components, "target.components")
        if not components or any(
            type(item) is not TargetComponentSnapshot for item in components
        ):
            raise TargetProjectOrchestrationError(
                "target.components must contain exact snapshot records"
            )
        component_ids = tuple(item.component_id for item in components)
        if component_ids != tuple(sorted(set(component_ids))):
            raise TargetProjectOrchestrationError(
                "target.components must use canonical unique component order"
            )
        known_capabilities = set(capability_ids)
        if any(
            set(component.capability_ids) - known_capabilities
            for component in components
        ):
            raise TargetProjectOrchestrationError(
                "target component references an unknown capability"
            )
        represented_capabilities = {
            capability_id
            for component in components
            for capability_id in component.capability_ids
        }
        if represented_capabilities != known_capabilities:
            raise TargetProjectOrchestrationError(
                "target components must completely represent target capabilities"
            )
        _references(self.evidence_refs, "target.evidence_refs")
        if not self.evidence_refs:
            raise TargetProjectOrchestrationError(
                "target.evidence_refs must not be empty"
            )


@dataclass(frozen=True)
class ComponentTaskBinding:
    component_id: str
    task_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self) is not ComponentTaskBinding:
            raise TargetProjectOrchestrationError(
                "ComponentTaskBinding subclasses are not accepted"
            )
        _code(self.component_id, "component_binding.component_id")
        _codes(self.task_ids, "component_binding.task_ids")


@dataclass(frozen=True)
class CapabilityChangeRequest:
    capability_id: str
    requirement_id: str
    change_code: str

    def __post_init__(self) -> None:
        if type(self) is not CapabilityChangeRequest:
            raise TargetProjectOrchestrationError(
                "CapabilityChangeRequest subclasses are not accepted"
            )
        _code(self.capability_id, "capability_change.capability_id")
        _requirement(self.requirement_id, "capability_change.requirement_id")
        _code(self.change_code, "capability_change.change_code")


@dataclass(frozen=True)
class CapabilityPreservationEvidence:
    capability_id: str
    observed_sha256: str
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self) is not CapabilityPreservationEvidence:
            raise TargetProjectOrchestrationError(
                "CapabilityPreservationEvidence subclasses are not accepted"
            )
        _code(self.capability_id, "preservation_evidence.capability_id")
        _digest(self.observed_sha256, "preservation_evidence.observed_sha256")
        _references(
            self.evidence_refs,
            "preservation_evidence.evidence_refs",
        )
        if not self.evidence_refs:
            raise TargetProjectOrchestrationError(
                "preservation_evidence.evidence_refs must not be empty"
            )


@dataclass(frozen=True)
class TargetOrchestrationReview:
    review_id: str
    orchestrator_id: str
    reviewer_id: str
    verdict: OrchestrationReviewVerdict
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self) is not TargetOrchestrationReview:
            raise TargetProjectOrchestrationError(
                "TargetOrchestrationReview subclasses are not accepted"
            )
        _code(self.review_id, "review.review_id")
        _code(self.orchestrator_id, "review.orchestrator_id")
        _code(self.reviewer_id, "review.reviewer_id")
        if type(self.verdict) is not OrchestrationReviewVerdict:
            raise TargetProjectOrchestrationError(
                "review.verdict must be an exact OrchestrationReviewVerdict"
            )
        _references(self.evidence_refs, "review.evidence_refs")
        if not self.evidence_refs:
            raise TargetProjectOrchestrationError(
                "review.evidence_refs must not be empty"
            )


@dataclass(frozen=True)
class SourceBindings:
    session_sha256: str
    consolidation_sha256: str
    lifecycle_sha256: str
    plan_sha256: str

    def __post_init__(self) -> None:
        if type(self) is not SourceBindings:
            raise TargetProjectOrchestrationError(
                "SourceBindings subclasses are not accepted"
            )
        for label, value in (
            ("session_sha256", self.session_sha256),
            ("consolidation_sha256", self.consolidation_sha256),
            ("lifecycle_sha256", self.lifecycle_sha256),
            ("plan_sha256", self.plan_sha256),
        ):
            _digest(value, f"source_bindings.{label}")


@dataclass(frozen=True)
class TargetRequirementTrace:
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
        if type(self) is not TargetRequirementTrace:
            raise TargetProjectOrchestrationError(
                "TargetRequirementTrace subclasses are not accepted"
            )
        _requirement(self.requirement_id, "requirement_trace.requirement_id")
        _digest(
            self.p3a_intent_decision_sha256,
            "requirement_trace.p3a_intent_decision_sha256",
        )
        _digest(
            self.p3b_blueprint_sha256,
            "requirement_trace.p3b_blueprint_sha256",
        )
        _sections(
            self.blueprint_section_refs,
            "requirement_trace.blueprint_section_refs",
        )
        _codes(self.task_ids, "requirement_trace.task_ids")
        _codes(
            self.dependency_task_ids,
            "requirement_trace.dependency_task_ids",
        )
        _references(self.artifact_refs, "requirement_trace.artifact_refs")
        _references(
            self.consolidation_refs,
            "requirement_trace.consolidation_refs",
        )
        _codes(
            self.conflict_resolution_ids,
            "requirement_trace.conflict_resolution_ids",
        )
        _codes(self.residual_gap_ids, "requirement_trace.residual_gap_ids")
        _references(
            self.next_evidence_refs,
            "requirement_trace.next_evidence_refs",
        )
        if type(self.phase) is not LifecyclePhase:
            raise TargetProjectOrchestrationError(
                "requirement_trace.phase must be an exact LifecyclePhase"
            )
        _references(
            self.phase_evidence_refs,
            "requirement_trace.phase_evidence_refs",
        )


@dataclass(frozen=True)
class TargetComponentPlan:
    component_id: str
    baseline_sha256: str
    capability_ids: tuple[str, ...]
    task_ids: tuple[str, ...]
    requirement_ids: tuple[str, ...]
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self) is not TargetComponentPlan:
            raise TargetProjectOrchestrationError(
                "TargetComponentPlan subclasses are not accepted"
            )
        _code(self.component_id, "component_plan.component_id")
        _digest(self.baseline_sha256, "component_plan.baseline_sha256")
        _codes(self.capability_ids, "component_plan.capability_ids", allow_empty=False)
        _codes(self.task_ids, "component_plan.task_ids")
        _requirements(self.requirement_ids, "component_plan.requirement_ids")
        _references(self.evidence_refs, "component_plan.evidence_refs")
        if not self.evidence_refs:
            raise TargetProjectOrchestrationError(
                "component_plan.evidence_refs must not be empty"
            )


@dataclass(frozen=True)
class TargetTaskLane:
    task_id: str
    component_id: str
    requirement_ids: tuple[str, ...]
    phase: str
    action_code: str
    output_code: str
    depends_on: tuple[str, ...]
    wave_index: int
    read_paths: tuple[str, ...]
    write_paths: tuple[str, ...]
    gate_ids: tuple[str, ...]
    acceptance_refs: tuple[str, ...]
    rollback_ref: str

    def __post_init__(self) -> None:
        if type(self) is not TargetTaskLane:
            raise TargetProjectOrchestrationError(
                "TargetTaskLane subclasses are not accepted"
            )
        _code(self.task_id, "task_lane.task_id")
        _code(self.component_id, "task_lane.component_id")
        _requirements(self.requirement_ids, "task_lane.requirement_ids")
        _code(self.phase, "task_lane.phase")
        _code(self.action_code, "task_lane.action_code")
        _code(self.output_code, "task_lane.output_code")
        _codes(self.depends_on, "task_lane.depends_on")
        if type(self.wave_index) is not int or self.wave_index < 0:
            raise TargetProjectOrchestrationError(
                "task_lane.wave_index must be a non-negative integer"
            )
        _references(self.read_paths, "task_lane.read_paths")
        _references(self.write_paths, "task_lane.write_paths")
        _codes(self.gate_ids, "task_lane.gate_ids")
        _references(self.acceptance_refs, "task_lane.acceptance_refs")
        _reference(self.rollback_ref, "task_lane.rollback_ref")


@dataclass(frozen=True)
class TargetExecutionWave:
    wave_index: int
    task_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self) is not TargetExecutionWave:
            raise TargetProjectOrchestrationError(
                "TargetExecutionWave subclasses are not accepted"
            )
        if type(self.wave_index) is not int or self.wave_index < 0:
            raise TargetProjectOrchestrationError(
                "target wave index must be a non-negative integer"
            )
        _codes(self.task_ids, "target_wave.task_ids", allow_empty=False)


@dataclass(frozen=True)
class CapabilityPlan:
    capability_id: str
    baseline_sha256: str
    disposition: CapabilityDisposition
    requirement_ids: tuple[str, ...]
    change_code: str | None
    observed_sha256: str | None
    snapshot_evidence_refs: tuple[str, ...]
    preservation_evidence_refs: tuple[str, ...]
    preservation_state: PreservationState
    downstream_transaction_required: bool

    def __post_init__(self) -> None:
        if type(self) is not CapabilityPlan:
            raise TargetProjectOrchestrationError(
                "CapabilityPlan subclasses are not accepted"
            )
        _code(self.capability_id, "capability_plan.capability_id")
        _digest(self.baseline_sha256, "capability_plan.baseline_sha256")
        if type(self.disposition) is not CapabilityDisposition:
            raise TargetProjectOrchestrationError(
                "capability_plan.disposition must be exact"
            )
        _requirements(self.requirement_ids, "capability_plan.requirement_ids")
        if self.change_code is not None:
            _code(self.change_code, "capability_plan.change_code")
        if self.observed_sha256 is not None:
            _digest(self.observed_sha256, "capability_plan.observed_sha256")
        _references(
            self.snapshot_evidence_refs,
            "capability_plan.snapshot_evidence_refs",
        )
        if not self.snapshot_evidence_refs:
            raise TargetProjectOrchestrationError(
                "capability_plan.snapshot_evidence_refs must not be empty"
            )
        _references(
            self.preservation_evidence_refs,
            "capability_plan.preservation_evidence_refs",
        )
        if type(self.preservation_state) is not PreservationState:
            raise TargetProjectOrchestrationError(
                "capability_plan.preservation_state must be exact"
            )
        if type(self.downstream_transaction_required) is not bool:
            raise TargetProjectOrchestrationError(
                "capability_plan downstream flag must be boolean"
            )
        if self.disposition is CapabilityDisposition.PRESERVE:
            if self.requirement_ids or self.change_code is not None:
                raise TargetProjectOrchestrationError(
                    "preserved capability cannot claim a change request"
                )
            if self.downstream_transaction_required:
                raise TargetProjectOrchestrationError(
                    "preserved capability cannot require a change transaction"
                )
        else:
            if len(self.requirement_ids) != 1 or self.change_code is None:
                raise TargetProjectOrchestrationError(
                    "proposed capability change requires one requirement and change code"
                )
            if not self.downstream_transaction_required:
                raise TargetProjectOrchestrationError(
                    "proposed capability change must remain a downstream transaction"
                )


@dataclass(frozen=True)
class IndependentReviewRequirement:
    scope_code: str
    required_verdict: OrchestrationReviewVerdict
    reviewer_must_differ: bool
    evidence_required: bool

    def __post_init__(self) -> None:
        if type(self) is not IndependentReviewRequirement:
            raise TargetProjectOrchestrationError(
                "IndependentReviewRequirement subclasses are not accepted"
            )
        _code(self.scope_code, "review_requirement.scope_code")
        if type(self.required_verdict) is not OrchestrationReviewVerdict:
            raise TargetProjectOrchestrationError(
                "review_requirement.required_verdict must be exact"
            )
        if self.reviewer_must_differ is not True or self.evidence_required is not True:
            raise TargetProjectOrchestrationError(
                "independent review requirements cannot be weakened"
            )


@dataclass(frozen=True)
class TargetOrchestrationAcceptance:
    state: TargetOrchestrationState
    accepted: bool
    scope_code: str
    review_id: str | None
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self) is not TargetOrchestrationAcceptance:
            raise TargetProjectOrchestrationError(
                "TargetOrchestrationAcceptance subclasses are not accepted"
            )
        if type(self.state) is not TargetOrchestrationState:
            raise TargetProjectOrchestrationError(
                "acceptance.state must be exact"
            )
        if type(self.accepted) is not bool:
            raise TargetProjectOrchestrationError(
                "acceptance.accepted must be boolean"
            )
        _code(self.scope_code, "acceptance.scope_code")
        if self.review_id is not None:
            _code(self.review_id, "acceptance.review_id")
        _codes(self.reason_codes, "acceptance.reason_codes")
        if self.accepted != (
            self.state is TargetOrchestrationState.ORCHESTRATION_ACCEPTED
        ):
            raise TargetProjectOrchestrationError(
                "acceptance flag does not match orchestration state"
            )


@dataclass(frozen=True)
class TargetOrchestrationUserResult:
    status_code: str
    result_code: str
    next_step_code: str
    phase: LifecyclePhase

    def __post_init__(self) -> None:
        if type(self) is not TargetOrchestrationUserResult:
            raise TargetProjectOrchestrationError(
                "TargetOrchestrationUserResult subclasses are not accepted"
            )
        _code(self.status_code, "user_result.status_code")
        _code(self.result_code, "user_result.result_code")
        _code(self.next_step_code, "user_result.next_step_code")
        if type(self.phase) is not LifecyclePhase:
            raise TargetProjectOrchestrationError(
                "user_result.phase must be an exact LifecyclePhase"
            )


@dataclass(frozen=True)
class TargetProjectOrchestration:
    schema_version: str
    orchestration_id: str
    orchestrator_id: str
    source_session: IdeaResultSession
    source_bindings: SourceBindings
    target_snapshot: TargetProjectSnapshot
    component_task_bindings: tuple[ComponentTaskBinding, ...]
    capability_changes: tuple[CapabilityChangeRequest, ...]
    preservation_evidence: tuple[CapabilityPreservationEvidence, ...]
    review: TargetOrchestrationReview | None
    requirement_traces: tuple[TargetRequirementTrace, ...]
    component_plans: tuple[TargetComponentPlan, ...]
    task_lanes: tuple[TargetTaskLane, ...]
    waves: tuple[TargetExecutionWave, ...]
    capability_plans: tuple[CapabilityPlan, ...]
    review_requirement: IndependentReviewRequirement
    self_check_codes: tuple[str, ...]
    reason_codes: tuple[str, ...]
    state: TargetOrchestrationState
    acceptance: TargetOrchestrationAcceptance
    user_result: TargetOrchestrationUserResult
    execution_authority: bool
    target_mutation_performed: bool
    execution_performed: bool

    def __post_init__(self) -> None:
        if type(self) is not TargetProjectOrchestration:
            raise TargetProjectOrchestrationError(
                "TargetProjectOrchestration subclasses are not accepted"
            )
        if self.schema_version != P3J_SCHEMA_VERSION:
            raise TargetProjectOrchestrationError(
                "unsupported target-project-orchestration schema_version"
            )
        _code(self.orchestration_id, "orchestration_id")
        _code(self.orchestrator_id, "orchestrator_id")
        if type(self.source_session) is not IdeaResultSession:
            raise TargetProjectOrchestrationError(
                "source_session must be an exact IdeaResultSession"
            )
        if type(self.source_bindings) is not SourceBindings:
            raise TargetProjectOrchestrationError(
                "source_bindings must be exact"
            )
        if type(self.target_snapshot) is not TargetProjectSnapshot:
            raise TargetProjectOrchestrationError(
                "target_snapshot must be exact"
            )
        for label, values, record_type in (
            ("component_task_bindings", self.component_task_bindings, ComponentTaskBinding),
            ("capability_changes", self.capability_changes, CapabilityChangeRequest),
            ("preservation_evidence", self.preservation_evidence, CapabilityPreservationEvidence),
            ("requirement_traces", self.requirement_traces, TargetRequirementTrace),
            ("component_plans", self.component_plans, TargetComponentPlan),
            ("task_lanes", self.task_lanes, TargetTaskLane),
            ("waves", self.waves, TargetExecutionWave),
            ("capability_plans", self.capability_plans, CapabilityPlan),
        ):
            items = _tuple(values, label)
            if any(type(item) is not record_type for item in items):
                raise TargetProjectOrchestrationError(
                    f"{label} contains an invalid record"
                )
        if self.review is not None and type(self.review) is not TargetOrchestrationReview:
            raise TargetProjectOrchestrationError("review must be exact or null")
        if type(self.review_requirement) is not IndependentReviewRequirement:
            raise TargetProjectOrchestrationError(
                "review_requirement must be exact"
            )
        _codes(self.self_check_codes, "self_check_codes")
        _codes(self.reason_codes, "reason_codes")
        if type(self.state) is not TargetOrchestrationState:
            raise TargetProjectOrchestrationError("state must be exact")
        if type(self.acceptance) is not TargetOrchestrationAcceptance:
            raise TargetProjectOrchestrationError("acceptance must be exact")
        if type(self.user_result) is not TargetOrchestrationUserResult:
            raise TargetProjectOrchestrationError("user_result must be exact")
        if (
            self.execution_authority is not False
            or self.target_mutation_performed is not False
            or self.execution_performed is not False
        ):
            raise TargetProjectOrchestrationError(
                "P3-J cannot claim target authority, mutation, or execution"
            )


def _source_records(
    session: IdeaResultSession,
) -> tuple[AutonomousTaskPlan, object, object]:
    if session.state is not SessionState.COMPLETE:
        raise TargetProjectOrchestrationError(
            "P3-J requires an exact canonical P3-I COMPLETE session"
        )
    if session.current_stage is not SessionStage.COMPLETE:
        raise TargetProjectOrchestrationError(
            "P3-J requires the P3-I current stage to be COMPLETE"
        )
    if session.task_plan is None or session.lifecycle is None or session.consolidation is None:
        raise TargetProjectOrchestrationError(
            "P3-I COMPLETE session is missing required source records"
        )
    if session.consolidation.state is not ConsolidationState.ACCEPT:
        raise TargetProjectOrchestrationError(
            "P3-J requires an accepted P3-H consolidation"
        )
    if session.lifecycle.state is not LifecycleState.COMPLETE:
        raise TargetProjectOrchestrationError(
            "P3-J requires a completed P3-G lifecycle"
        )
    return session.task_plan, session.lifecycle, session.consolidation


def _canonical_input_records(
    values: Sequence[object], record_type: type, key_name: str, label: str
) -> tuple[object, ...]:
    if not isinstance(values, (tuple, list)) or len(values) > MAX_ITEMS:
        raise TargetProjectOrchestrationError(f"{label} must be a bounded sequence")
    records = tuple(values)
    if any(type(item) is not record_type for item in records):
        raise TargetProjectOrchestrationError(
            f"{label} must contain exact {record_type.__name__} records"
        )
    records = tuple(sorted(records, key=lambda item: getattr(item, key_name)))
    identifiers = tuple(getattr(item, key_name) for item in records)
    if len(identifiers) != len(set(identifiers)):
        raise TargetProjectOrchestrationError(f"{label} contains duplicate identifiers")
    return records


def _actual_source_bindings(session: IdeaResultSession) -> SourceBindings:
    plan, lifecycle, consolidation = _source_records(session)
    return SourceBindings(
        session_sha256=hashlib.sha256(_render_session(session)).hexdigest(),
        consolidation_sha256=hashlib.sha256(
            _render_consolidation(consolidation)
        ).hexdigest(),
        lifecycle_sha256=hashlib.sha256(
            _render_lifecycle(lifecycle)
        ).hexdigest(),
        plan_sha256=hashlib.sha256(_render_plan(plan)).hexdigest(),
    )


@lru_cache(maxsize=8)
def _render_session(value: IdeaResultSession) -> bytes:
    return render_idea_result_session(value)


@lru_cache(maxsize=8)
def _render_plan(value: AutonomousTaskPlan) -> bytes:
    return render_autonomous_task_plan(value)


@lru_cache(maxsize=8)
def _render_lifecycle(value: object) -> bytes:
    return render_goal_delivery_lifecycle(value)  # type: ignore[arg-type]


@lru_cache(maxsize=8)
def _render_consolidation(value: object) -> bytes:
    return render_requirement_trace_consolidation(value)  # type: ignore[arg-type]


def _trace_plan(trace: RequirementTrace) -> TargetRequirementTrace:
    return TargetRequirementTrace(
        requirement_id=trace.requirement_id,
        p3a_intent_decision_sha256=trace.p3a_intent_decision_sha256,
        p3b_blueprint_sha256=trace.p3b_blueprint_sha256,
        blueprint_section_refs=trace.blueprint_section_refs,
        task_ids=trace.task_ids,
        dependency_task_ids=trace.dependency_task_ids,
        artifact_refs=trace.artifact_refs,
        consolidation_refs=trace.consolidation_refs,
        conflict_resolution_ids=trace.conflict_resolution_ids,
        residual_gap_ids=trace.residual_gap_ids,
        next_evidence_refs=trace.next_evidence_refs,
        phase=trace.phase,
        phase_evidence_refs=trace.phase_evidence_refs,
    )


def _task_requirement_map(
    traces: tuple[TargetRequirementTrace, ...]
) -> dict[str, tuple[str, ...]]:
    result: dict[str, list[str]] = {}
    for trace in traces:
        for task_id in trace.task_ids:
            result.setdefault(task_id, []).append(trace.requirement_id)
    return {key: tuple(sorted(value)) for key, value in result.items()}


def _state_and_reasons(
    *,
    plan: AutonomousTaskPlan,
    snapshot: TargetProjectSnapshot,
    bindings: tuple[ComponentTaskBinding, ...],
    changes: tuple[CapabilityChangeRequest, ...],
    evidence: tuple[CapabilityPreservationEvidence, ...],
    review: TargetOrchestrationReview | None,
    orchestrator_id: str,
    requirements: set[str],
) -> tuple[TargetOrchestrationState, tuple[str, ...]]:
    block: set[str] = set()
    needs: set[str] = set()
    route_ids = {route.task_id for route in plan.routes}
    snapshot_components = {item.component_id for item in snapshot.components}
    binding_components = {item.component_id for item in bindings}
    claimed = [task_id for item in bindings for task_id in item.task_ids]
    if binding_components != snapshot_components:
        block.add("component-binding-coverage-mismatch")
    if set(claimed) != route_ids:
        block.add("task-coverage-mismatch")
    if len(claimed) != len(set(claimed)):
        block.add("task-claimed-multiple-times")
    if set(claimed) - route_ids:
        block.add("unknown-task-claim")

    capability_by_id = {item.capability_id: item for item in snapshot.capabilities}
    for change in changes:
        if change.capability_id not in capability_by_id:
            block.add("unknown-capability-change")
        if change.requirement_id not in requirements:
            block.add("capability-change-requirement-mismatch")
    evidence_by_id = {item.capability_id: item for item in evidence}
    if set(evidence_by_id) - set(capability_by_id):
        block.add("unknown-capability-evidence")
    for capability_id, capability in capability_by_id.items():
        item = evidence_by_id.get(capability_id)
        if item is None:
            needs.add("capability-preservation-evidence-missing")
        elif item.observed_sha256 != capability.baseline_sha256:
            block.add("capability-contract-drift")

    if review is not None:
        if review.orchestrator_id != orchestrator_id:
            block.add("review-orchestrator-binding-mismatch")
        if review.reviewer_id == orchestrator_id:
            block.add("reviewer-not-independent")
        if review.verdict is OrchestrationReviewVerdict.BLOCK:
            block.add("independent-review-blocked")
    if block:
        return TargetOrchestrationState.BLOCK, tuple(sorted(block | needs))
    if needs:
        return TargetOrchestrationState.NEEDS_EVIDENCE, tuple(sorted(needs))
    if review is None:
        return TargetOrchestrationState.PLAN_READY, ()
    return TargetOrchestrationState.ORCHESTRATION_ACCEPTED, ()


def _user_result(
    state: TargetOrchestrationState, phase: LifecyclePhase
) -> TargetOrchestrationUserResult:
    result_code, next_step = {
        TargetOrchestrationState.PLAN_READY: (
            "target-orchestration-plan-ready",
            "obtain-independent-review",
        ),
        TargetOrchestrationState.NEEDS_EVIDENCE: (
            "target-preservation-evidence-required",
            "collect-capability-preservation-evidence",
        ),
        TargetOrchestrationState.BLOCK: (
            "target-orchestration-blocked",
            "resolve-target-orchestration-blockers",
        ),
        TargetOrchestrationState.ORCHESTRATION_ACCEPTED: (
            "target-orchestration-accepted",
            "start-separate-target-transaction",
        ),
    }[state]
    return TargetOrchestrationUserResult(
        status_code=state.value,
        result_code=result_code,
        next_step_code=next_step,
        phase=phase,
    )


def _build(
    *,
    session: IdeaResultSession,
    orchestration_id: str,
    orchestrator_id: str,
    target_snapshot: TargetProjectSnapshot,
    component_task_bindings: tuple[ComponentTaskBinding, ...],
    capability_changes: tuple[CapabilityChangeRequest, ...],
    preservation_evidence: tuple[CapabilityPreservationEvidence, ...],
    review: TargetOrchestrationReview | None,
) -> TargetProjectOrchestration:
    plan, _, consolidation = _source_records(session)
    traces = tuple(_trace_plan(item) for item in consolidation.traces)
    requirements = {item.requirement_id for item in traces}
    task_requirements = _task_requirement_map(traces)
    task_component = {
        task_id: binding.component_id
        for binding in component_task_bindings
        for task_id in binding.task_ids
    }
    snapshot_components = {
        item.component_id: item for item in target_snapshot.components
    }
    component_plans = tuple(
        TargetComponentPlan(
            component_id=item.component_id,
            baseline_sha256=item.baseline_sha256,
            capability_ids=item.capability_ids,
            task_ids=next(
                (
                    binding.task_ids
                    for binding in component_task_bindings
                    if binding.component_id == item.component_id
                ),
                (),
            ),
            requirement_ids=tuple(
                sorted(
                    {
                        requirement
                        for binding in component_task_bindings
                        if binding.component_id == item.component_id
                        for task_id in binding.task_ids
                        for requirement in task_requirements.get(task_id, ())
                    }
                )
            ),
            evidence_refs=item.evidence_refs,
        )
        for item in target_snapshot.components
    )
    task_lanes = tuple(
        TargetTaskLane(
            task_id=route.task_id,
            component_id=task_component.get(route.task_id, "component.unassigned"),
            requirement_ids=task_requirements.get(route.task_id, ()),
            phase=route.phase,
            action_code=route.action_code,
            output_code=route.output_code,
            depends_on=route.depends_on,
            wave_index=route.wave_index,
            read_paths=route.context.read_paths,
            write_paths=route.context.write_paths,
            gate_ids=route.context.gate_ids,
            acceptance_refs=route.context.acceptance_refs,
            rollback_ref=route.context.rollback_ref,
        )
        for route in plan.routes
    )
    waves = tuple(
        TargetExecutionWave(wave_index=item.wave_index, task_ids=item.task_ids)
        for item in plan.waves
    )
    changes_by_id = {item.capability_id: item for item in capability_changes}
    evidence_by_id = {
        item.capability_id: item for item in preservation_evidence
    }
    capability_plans: list[CapabilityPlan] = []
    for capability in target_snapshot.capabilities:
        change = changes_by_id.get(capability.capability_id)
        evidence = evidence_by_id.get(capability.capability_id)
        preservation_state = (
            PreservationState.MISSING
            if evidence is None
            else PreservationState.VERIFIED
            if evidence.observed_sha256 == capability.baseline_sha256
            else PreservationState.DRIFT
        )
        capability_plans.append(
            CapabilityPlan(
                capability_id=capability.capability_id,
                baseline_sha256=capability.baseline_sha256,
                disposition=(
                    CapabilityDisposition.PRESERVE
                    if change is None
                    else CapabilityDisposition.CHANGE_PROPOSED
                ),
                requirement_ids=() if change is None else (change.requirement_id,),
                change_code=None if change is None else change.change_code,
                observed_sha256=None if evidence is None else evidence.observed_sha256,
                snapshot_evidence_refs=capability.evidence_refs,
                preservation_evidence_refs=(
                    () if evidence is None else evidence.evidence_refs
                ),
                preservation_state=preservation_state,
                downstream_transaction_required=change is not None,
            )
        )
    state, reasons = _state_and_reasons(
        plan=plan,
        snapshot=target_snapshot,
        bindings=component_task_bindings,
        changes=capability_changes,
        evidence=preservation_evidence,
        review=review,
        orchestrator_id=orchestrator_id,
        requirements=requirements,
    )
    self_checks = {
        "check.canonical-p3i-complete",
        "check.capability-inventory-complete",
        "check.execution-authority-absent",
        "check.source-bindings-recomputed",
        "check.target-snapshot-redacted",
    }
    if not any(reason.startswith("component-") or reason.startswith("task-") for reason in reasons):
        self_checks.add("check.task-partition-complete")
    if all(item.preservation_state is PreservationState.VERIFIED for item in capability_plans):
        self_checks.add("check.capabilities-preserved")
    if all(
        item.disposition is CapabilityDisposition.PRESERVE
        or item.requirement_ids[0] in requirements
        for item in capability_plans
    ):
        self_checks.add("check.capability-changes-traceable")
    if review is not None and review.reviewer_id != orchestrator_id:
        self_checks.add("check.independent-review-present")
    acceptance = TargetOrchestrationAcceptance(
        state=state,
        accepted=state is TargetOrchestrationState.ORCHESTRATION_ACCEPTED,
        scope_code="scope.orchestration-plan-and-preservation-only",
        review_id=None if review is None else review.review_id,
        reason_codes=reasons,
    )
    return TargetProjectOrchestration(
        schema_version=P3J_SCHEMA_VERSION,
        orchestration_id=orchestration_id,
        orchestrator_id=orchestrator_id,
        source_session=session,
        source_bindings=_actual_source_bindings(session),
        target_snapshot=target_snapshot,
        component_task_bindings=component_task_bindings,
        capability_changes=capability_changes,
        preservation_evidence=preservation_evidence,
        review=review,
        requirement_traces=traces,
        component_plans=component_plans,
        task_lanes=task_lanes,
        waves=waves,
        capability_plans=tuple(capability_plans),
        review_requirement=IndependentReviewRequirement(
            scope_code="scope.orchestration-plan-and-preservation-only",
            required_verdict=OrchestrationReviewVerdict.ACCEPT,
            reviewer_must_differ=True,
            evidence_required=True,
        ),
        self_check_codes=tuple(sorted(self_checks)),
        reason_codes=reasons,
        state=state,
        acceptance=acceptance,
        user_result=_user_result(state, consolidation.phase),
        execution_authority=False,
        target_mutation_performed=False,
        execution_performed=False,
    )


def build_target_project_orchestration(
    session_payload: bytes | bytearray | memoryview,
    *,
    orchestration_id: str,
    orchestrator_id: str,
    target_snapshot: TargetProjectSnapshot,
    component_task_bindings: Sequence[ComponentTaskBinding],
    capability_changes: Sequence[CapabilityChangeRequest] = (),
    preservation_evidence: Sequence[CapabilityPreservationEvidence] = (),
    review: TargetOrchestrationReview | None = None,
) -> TargetProjectOrchestration:
    """Build a deterministic target plan without target-project access."""

    if not isinstance(session_payload, (bytes, bytearray, memoryview)):
        raise TargetProjectOrchestrationError(
            "P3-I idea-result session payload must be bytes"
        )
    try:
        session = _parse_canonical_session(bytes(session_payload))
    except (IdeaResultSessionError, TypeError, ValueError) as error:
        raise TargetProjectOrchestrationError(
            "P3-I idea-result session is invalid or noncanonical"
        ) from error
    if type(target_snapshot) is not TargetProjectSnapshot:
        raise TargetProjectOrchestrationError(
            "target_snapshot must be an exact TargetProjectSnapshot"
        )
    if review is not None and type(review) is not TargetOrchestrationReview:
        raise TargetProjectOrchestrationError(
            "review must be an exact TargetOrchestrationReview or null"
        )
    bindings = _canonical_input_records(
        component_task_bindings,
        ComponentTaskBinding,
        "component_id",
        "component_task_bindings",
    )
    changes = _canonical_input_records(
        capability_changes,
        CapabilityChangeRequest,
        "capability_id",
        "capability_changes",
    )
    evidence = _canonical_input_records(
        preservation_evidence,
        CapabilityPreservationEvidence,
        "capability_id",
        "preservation_evidence",
    )
    return _build(
        session=session,
        orchestration_id=_code(orchestration_id, "orchestration_id"),
        orchestrator_id=_code(orchestrator_id, "orchestrator_id"),
        target_snapshot=target_snapshot,
        component_task_bindings=bindings,  # type: ignore[arg-type]
        capability_changes=changes,  # type: ignore[arg-type]
        preservation_evidence=evidence,  # type: ignore[arg-type]
        review=review,
    )


@lru_cache(maxsize=8)
def _parse_canonical_session(raw: bytes) -> IdeaResultSession:
    return parse_idea_result_session(raw)


def _capability_snapshot_mapping(value: TargetCapabilitySnapshot) -> dict[str, object]:
    return {
        "baseline_sha256": value.baseline_sha256,
        "capability_id": value.capability_id,
        "evidence_refs": list(value.evidence_refs),
    }


def _component_snapshot_mapping(value: TargetComponentSnapshot) -> dict[str, object]:
    return {
        "baseline_sha256": value.baseline_sha256,
        "capability_ids": list(value.capability_ids),
        "component_id": value.component_id,
        "evidence_refs": list(value.evidence_refs),
    }


def _mapping(value: TargetProjectOrchestration) -> dict[str, object]:
    return {
        "acceptance": {
            "accepted": value.acceptance.accepted,
            "reason_codes": list(value.acceptance.reason_codes),
            "review_id": value.acceptance.review_id,
            "scope_code": value.acceptance.scope_code,
            "state": value.acceptance.state.value,
        },
        "capability_changes": [
            {
                "capability_id": item.capability_id,
                "change_code": item.change_code,
                "requirement_id": item.requirement_id,
            }
            for item in value.capability_changes
        ],
        "capability_plans": [
            {
                "baseline_sha256": item.baseline_sha256,
                "capability_id": item.capability_id,
                "change_code": item.change_code,
                "disposition": item.disposition.value,
                "downstream_transaction_required": item.downstream_transaction_required,
                "observed_sha256": item.observed_sha256,
                "preservation_evidence_refs": list(item.preservation_evidence_refs),
                "preservation_state": item.preservation_state.value,
                "requirement_ids": list(item.requirement_ids),
                "snapshot_evidence_refs": list(item.snapshot_evidence_refs),
            }
            for item in value.capability_plans
        ],
        "component_plans": [
            {
                "baseline_sha256": item.baseline_sha256,
                "capability_ids": list(item.capability_ids),
                "component_id": item.component_id,
                "evidence_refs": list(item.evidence_refs),
                "requirement_ids": list(item.requirement_ids),
                "task_ids": list(item.task_ids),
            }
            for item in value.component_plans
        ],
        "component_task_bindings": [
            {"component_id": item.component_id, "task_ids": list(item.task_ids)}
            for item in value.component_task_bindings
        ],
        "execution_authority": value.execution_authority,
        "execution_performed": value.execution_performed,
        "orchestration_id": value.orchestration_id,
        "orchestrator_id": value.orchestrator_id,
        "preservation_evidence": [
            {
                "capability_id": item.capability_id,
                "evidence_refs": list(item.evidence_refs),
                "observed_sha256": item.observed_sha256,
            }
            for item in value.preservation_evidence
        ],
        "reason_codes": list(value.reason_codes),
        "requirement_traces": [
            {
                "artifact_refs": list(item.artifact_refs),
                "blueprint_section_refs": list(item.blueprint_section_refs),
                "consolidation_refs": list(item.consolidation_refs),
                "conflict_resolution_ids": list(item.conflict_resolution_ids),
                "dependency_task_ids": list(item.dependency_task_ids),
                "next_evidence_refs": list(item.next_evidence_refs),
                "p3a_intent_decision_sha256": item.p3a_intent_decision_sha256,
                "p3b_blueprint_sha256": item.p3b_blueprint_sha256,
                "phase": item.phase.value,
                "phase_evidence_refs": list(item.phase_evidence_refs),
                "requirement_id": item.requirement_id,
                "residual_gap_ids": list(item.residual_gap_ids),
                "task_ids": list(item.task_ids),
            }
            for item in value.requirement_traces
        ],
        "review": None
        if value.review is None
        else {
            "evidence_refs": list(value.review.evidence_refs),
            "orchestrator_id": value.review.orchestrator_id,
            "review_id": value.review.review_id,
            "reviewer_id": value.review.reviewer_id,
            "verdict": value.review.verdict.value,
        },
        "review_requirement": {
            "evidence_required": value.review_requirement.evidence_required,
            "required_verdict": value.review_requirement.required_verdict.value,
            "reviewer_must_differ": value.review_requirement.reviewer_must_differ,
            "scope_code": value.review_requirement.scope_code,
        },
        "schema_version": value.schema_version,
        "self_check_codes": list(value.self_check_codes),
        "source_bindings": {
            "consolidation_sha256": value.source_bindings.consolidation_sha256,
            "lifecycle_sha256": value.source_bindings.lifecycle_sha256,
            "plan_sha256": value.source_bindings.plan_sha256,
            "session_sha256": value.source_bindings.session_sha256,
        },
        "source_session": json.loads(_render_session(value.source_session)),
        "state": value.state.value,
        "target_mutation_performed": value.target_mutation_performed,
        "target_snapshot": {
            "capabilities": [
                _capability_snapshot_mapping(item)
                for item in value.target_snapshot.capabilities
            ],
            "components": [
                _component_snapshot_mapping(item)
                for item in value.target_snapshot.components
            ],
            "evidence_refs": list(value.target_snapshot.evidence_refs),
            "target_id": value.target_snapshot.target_id,
        },
        "task_lanes": [
            {
                "acceptance_refs": list(item.acceptance_refs),
                "action_code": item.action_code,
                "component_id": item.component_id,
                "depends_on": list(item.depends_on),
                "gate_ids": list(item.gate_ids),
                "output_code": item.output_code,
                "phase": item.phase,
                "read_paths": list(item.read_paths),
                "requirement_ids": list(item.requirement_ids),
                "rollback_ref": item.rollback_ref,
                "task_id": item.task_id,
                "wave_index": item.wave_index,
                "write_paths": list(item.write_paths),
            }
            for item in value.task_lanes
        ],
        "user_result": {
            "next_step_code": value.user_result.next_step_code,
            "phase": value.user_result.phase.value,
            "result_code": value.user_result.result_code,
            "status_code": value.user_result.status_code,
        },
        "waves": [
            {"task_ids": list(item.task_ids), "wave_index": item.wave_index}
            for item in value.waves
        ],
    }


def _recompute(value: TargetProjectOrchestration) -> TargetProjectOrchestration:
    return _build(
        session=value.source_session,
        orchestration_id=value.orchestration_id,
        orchestrator_id=value.orchestrator_id,
        target_snapshot=value.target_snapshot,
        component_task_bindings=value.component_task_bindings,
        capability_changes=value.capability_changes,
        preservation_evidence=value.preservation_evidence,
        review=value.review,
    )


def render_target_project_orchestration(value: TargetProjectOrchestration) -> bytes:
    """Render closed canonical P3-J JSON after full recomputation."""

    if type(value) is not TargetProjectOrchestration:
        raise TypeError("value must be an exact TargetProjectOrchestration")
    if _recompute(value) != value:
        raise TargetProjectOrchestrationError(
            "target-project orchestration does not match recomputed inputs"
        )
    try:
        rendered = canonical_json_bytes(_mapping(value))
    except SchemaError as error:
        raise TargetProjectOrchestrationError(
            f"target-project orchestration cannot be encoded: {error}"
        ) from error
    if len(rendered) > MAX_TARGET_PROJECT_ORCHESTRATION_BYTES:
        raise TargetProjectOrchestrationError(
            "rendered target-project orchestration exceeds its byte bound"
        )
    return rendered


def target_project_user_result(value: TargetProjectOrchestration) -> dict[str, str]:
    """Return the compact result intended for an ordinary project owner."""

    if type(value) is not TargetProjectOrchestration:
        raise TypeError("value must be an exact TargetProjectOrchestration")
    if _recompute(value) != value:
        raise TargetProjectOrchestrationError(
            "target-project orchestration does not match recomputed inputs"
        )
    return {
        "status": value.user_result.status_code,
        "result": value.user_result.result_code,
        "next_step": value.user_result.next_step_code,
        "phase": value.user_result.phase.value,
    }


def _closed(value: object, fields: frozenset[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TargetProjectOrchestrationError(f"{label} must be an object")
    keys = set(value)
    if any(type(key) is not str for key in keys):
        raise TargetProjectOrchestrationError(f"{label} keys must be strings")
    unknown = sorted(keys - fields)
    missing = sorted(fields - keys)
    if unknown:
        raise TargetProjectOrchestrationError(
            f"{label} contains unknown fields: {', '.join(unknown)}"
        )
    if missing:
        raise TargetProjectOrchestrationError(
            f"{label} is missing fields: {', '.join(missing)}"
        )
    return value


def _array(value: object, label: str) -> tuple[object, ...]:
    if type(value) is not list or len(value) > MAX_ITEMS:
        raise TargetProjectOrchestrationError(f"{label} must be a bounded array")
    return tuple(value)


def _parse_codes(value: object, label: str) -> tuple[str, ...]:
    return tuple(
        _code(item, f"{label}[{index}]")
        for index, item in enumerate(_array(value, label))
    )


def _parse_requirements(value: object, label: str) -> tuple[str, ...]:
    return tuple(
        _requirement(item, f"{label}[{index}]")
        for index, item in enumerate(_array(value, label))
    )


def _parse_references(value: object, label: str) -> tuple[str, ...]:
    return tuple(
        _reference(item, f"{label}[{index}]")
        for index, item in enumerate(_array(value, label))
    )


def _reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise TargetProjectOrchestrationError(
                "target-project orchestration contains duplicate object keys"
            )
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise TargetProjectOrchestrationError(
        f"target-project orchestration contains unsupported JSON constant: {value}"
    )


def parse_target_project_orchestration(
    payload: bytes | bytearray | memoryview,
) -> TargetProjectOrchestration:
    """Parse canonical P3-J JSON and recompute every derived field."""

    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise TargetProjectOrchestrationError(
            "target-project-orchestration payload must be bytes"
        )
    raw = bytes(payload)
    if not raw or len(raw) > MAX_TARGET_PROJECT_ORCHESTRATION_BYTES:
        raise TargetProjectOrchestrationError(
            "target-project-orchestration payload must use bounded non-empty bytes"
        )
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicates,
            parse_constant=_reject_constant,
        )
    except TargetProjectOrchestrationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError, RecursionError) as error:
        raise TargetProjectOrchestrationError(
            "target-project orchestration is not valid UTF-8 JSON"
        ) from error
    top_fields = frozenset(
        {
            "acceptance",
            "capability_changes",
            "capability_plans",
            "component_plans",
            "component_task_bindings",
            "execution_authority",
            "execution_performed",
            "orchestration_id",
            "orchestrator_id",
            "preservation_evidence",
            "reason_codes",
            "requirement_traces",
            "review",
            "review_requirement",
            "schema_version",
            "self_check_codes",
            "source_bindings",
            "source_session",
            "state",
            "target_mutation_performed",
            "target_snapshot",
            "task_lanes",
            "user_result",
            "waves",
        }
    )
    item = _closed(value, top_fields, "target_project_orchestration")
    try:
        session_payload = canonical_json_bytes(item["source_session"])
        session = _parse_canonical_session(session_payload)
    except (SchemaError, IdeaResultSessionError, TypeError, ValueError) as error:
        raise TargetProjectOrchestrationError("embedded P3-I session is invalid") from error
    target_item = _closed(
        item["target_snapshot"],
        frozenset({"capabilities", "components", "evidence_refs", "target_id"}),
        "target_snapshot",
    )
    capabilities = tuple(
        TargetCapabilitySnapshot(
            capability_id=_code(
                _closed(
                    entry,
                    frozenset({"baseline_sha256", "capability_id", "evidence_refs"}),
                    f"target_snapshot.capabilities[{index}]",
                )["capability_id"],
                f"target_snapshot.capabilities[{index}].capability_id",
            ),
            baseline_sha256=_digest(
                _closed(
                    entry,
                    frozenset({"baseline_sha256", "capability_id", "evidence_refs"}),
                    f"target_snapshot.capabilities[{index}]",
                )["baseline_sha256"],
                f"target_snapshot.capabilities[{index}].baseline_sha256",
            ),
            evidence_refs=_parse_references(
                _closed(
                    entry,
                    frozenset({"baseline_sha256", "capability_id", "evidence_refs"}),
                    f"target_snapshot.capabilities[{index}]",
                )["evidence_refs"],
                f"target_snapshot.capabilities[{index}].evidence_refs",
            ),
        )
        for index, entry in enumerate(_array(target_item["capabilities"], "target_snapshot.capabilities"))
    )
    components = tuple(
        TargetComponentSnapshot(
            component_id=_code(
                _closed(
                    entry,
                    frozenset({"baseline_sha256", "capability_ids", "component_id", "evidence_refs"}),
                    f"target_snapshot.components[{index}]",
                )["component_id"],
                f"target_snapshot.components[{index}].component_id",
            ),
            baseline_sha256=_digest(
                _closed(
                    entry,
                    frozenset({"baseline_sha256", "capability_ids", "component_id", "evidence_refs"}),
                    f"target_snapshot.components[{index}]",
                )["baseline_sha256"],
                f"target_snapshot.components[{index}].baseline_sha256",
            ),
            capability_ids=_parse_codes(
                _closed(
                    entry,
                    frozenset({"baseline_sha256", "capability_ids", "component_id", "evidence_refs"}),
                    f"target_snapshot.components[{index}]",
                )["capability_ids"],
                f"target_snapshot.components[{index}].capability_ids",
            ),
            evidence_refs=_parse_references(
                _closed(
                    entry,
                    frozenset({"baseline_sha256", "capability_ids", "component_id", "evidence_refs"}),
                    f"target_snapshot.components[{index}]",
                )["evidence_refs"],
                f"target_snapshot.components[{index}].evidence_refs",
            ),
        )
        for index, entry in enumerate(_array(target_item["components"], "target_snapshot.components"))
    )
    snapshot = TargetProjectSnapshot(
        target_id=_code(target_item["target_id"], "target_snapshot.target_id"),
        capabilities=capabilities,
        components=components,
        evidence_refs=_parse_references(target_item["evidence_refs"], "target_snapshot.evidence_refs"),
    )
    bindings = tuple(
        ComponentTaskBinding(
            component_id=_code(
                _closed(entry, frozenset({"component_id", "task_ids"}), f"component_task_bindings[{index}]")["component_id"],
                f"component_task_bindings[{index}].component_id",
            ),
            task_ids=_parse_codes(
                _closed(entry, frozenset({"component_id", "task_ids"}), f"component_task_bindings[{index}]")["task_ids"],
                f"component_task_bindings[{index}].task_ids",
            ),
        )
        for index, entry in enumerate(_array(item["component_task_bindings"], "component_task_bindings"))
    )
    changes = tuple(
        CapabilityChangeRequest(
            capability_id=_code(
                _closed(entry, frozenset({"capability_id", "change_code", "requirement_id"}), f"capability_changes[{index}]")["capability_id"],
                f"capability_changes[{index}].capability_id",
            ),
            requirement_id=_requirement(
                _closed(entry, frozenset({"capability_id", "change_code", "requirement_id"}), f"capability_changes[{index}]")["requirement_id"],
                f"capability_changes[{index}].requirement_id",
            ),
            change_code=_code(
                _closed(entry, frozenset({"capability_id", "change_code", "requirement_id"}), f"capability_changes[{index}]")["change_code"],
                f"capability_changes[{index}].change_code",
            ),
        )
        for index, entry in enumerate(_array(item["capability_changes"], "capability_changes"))
    )
    evidence = tuple(
        CapabilityPreservationEvidence(
            capability_id=_code(
                _closed(entry, frozenset({"capability_id", "evidence_refs", "observed_sha256"}), f"preservation_evidence[{index}]")["capability_id"],
                f"preservation_evidence[{index}].capability_id",
            ),
            observed_sha256=_digest(
                _closed(entry, frozenset({"capability_id", "evidence_refs", "observed_sha256"}), f"preservation_evidence[{index}]")["observed_sha256"],
                f"preservation_evidence[{index}].observed_sha256",
            ),
            evidence_refs=_parse_references(
                _closed(entry, frozenset({"capability_id", "evidence_refs", "observed_sha256"}), f"preservation_evidence[{index}]")["evidence_refs"],
                f"preservation_evidence[{index}].evidence_refs",
            ),
        )
        for index, entry in enumerate(_array(item["preservation_evidence"], "preservation_evidence"))
    )
    review_item = item["review"]
    review = None
    if review_item is not None:
        review_map = _closed(
            review_item,
            frozenset({"evidence_refs", "orchestrator_id", "review_id", "reviewer_id", "verdict"}),
            "review",
        )
        review = TargetOrchestrationReview(
            review_id=_code(review_map["review_id"], "review.review_id"),
            orchestrator_id=_code(review_map["orchestrator_id"], "review.orchestrator_id"),
            reviewer_id=_code(review_map["reviewer_id"], "review.reviewer_id"),
            verdict=_enum(review_map["verdict"], OrchestrationReviewVerdict, "review.verdict"),  # type: ignore[arg-type]
            evidence_refs=_parse_references(review_map["evidence_refs"], "review.evidence_refs"),
        )
    record = _build(
        session=session,
        orchestration_id=_code(item["orchestration_id"], "orchestration_id"),
        orchestrator_id=_code(item["orchestrator_id"], "orchestrator_id"),
        target_snapshot=snapshot,
        component_task_bindings=bindings,
        capability_changes=changes,
        preservation_evidence=evidence,
        review=review,
    )
    if render_target_project_orchestration(record) != raw:
        raise TargetProjectOrchestrationError(
            "target-project-orchestration JSON is not canonical"
        )
    return record


__all__ = [
    "P3J_SCHEMA_VERSION",
    "MAX_TARGET_PROJECT_ORCHESTRATION_BYTES",
    "TargetProjectOrchestrationError",
    "CapabilityDisposition",
    "PreservationState",
    "OrchestrationReviewVerdict",
    "TargetOrchestrationState",
    "TargetCapabilitySnapshot",
    "TargetComponentSnapshot",
    "TargetProjectSnapshot",
    "ComponentTaskBinding",
    "CapabilityChangeRequest",
    "CapabilityPreservationEvidence",
    "TargetOrchestrationReview",
    "SourceBindings",
    "TargetRequirementTrace",
    "TargetComponentPlan",
    "TargetTaskLane",
    "TargetExecutionWave",
    "CapabilityPlan",
    "IndependentReviewRequirement",
    "TargetOrchestrationAcceptance",
    "TargetOrchestrationUserResult",
    "TargetProjectOrchestration",
    "build_target_project_orchestration",
    "render_target_project_orchestration",
    "parse_target_project_orchestration",
    "target_project_user_result",
]
