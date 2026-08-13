"""Pure P3-I idea-to-result session controller.

P3-I composes exact canonical P3-A, P3-B, P3-C, P3-F, P3-G, and P3-H
records into one resumable stage result. It derives the next safe stage and
the smallest genuine interruption without executing any project action.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import re
from typing import Any, Mapping, Sequence
import unicodedata

from .autonomous_task_orchestration import (
    AutonomousTaskOrchestrationError,
    AutonomousTaskPlan,
    OrchestrationState,
    parse_autonomous_task_plan,
    render_autonomous_task_plan,
)
from .goal_delivery_lifecycle import (
    GoalDeliveryLifecycle,
    GoalDeliveryLifecycleError,
    LifecyclePhase,
    LifecycleState,
    parse_goal_delivery_lifecycle,
    render_goal_delivery_lifecycle,
)
from .implementation_readiness import (
    ImplementationReadiness,
    ImplementationReadinessError,
    ReadinessState,
    parse_implementation_readiness,
    render_implementation_readiness,
)
from .intent_decision_router import (
    IntentDecisionError,
    IntentDecisionResult,
    parse_intent_decision_result,
    render_intent_decision_result,
)
from .project_blueprint import (
    ProjectBlueprint,
    ProjectBlueprintError,
    parse_project_blueprint,
    render_project_blueprint,
)
from .requirement_trace_consolidation import (
    ConsolidationState,
    RequirementTraceConsolidation,
    RequirementTraceConsolidationError,
    parse_requirement_trace_consolidation,
    render_requirement_trace_consolidation,
)
from .storage import SchemaError, canonical_json_bytes


P3I_SCHEMA_VERSION = "1.0"
MAX_IDEA_RESULT_SESSION_BYTES = 4 * 1024 * 1024
MAX_STAGE_PAYLOAD_BYTES = 2 * 1024 * 1024

_CODE = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SENSITIVE = re.compile(
    r"(?:\bsk-[A-Za-z0-9_-]{8,}|\bghp_[A-Za-z0-9]{8,}|"
    r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.|"
    r"\bbearer\s+[A-Za-z0-9._~+/-]{8,}|"
    r"\b(?:api[_-]?key|token|password|secret)\s*[:=]|"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----)",
    re.IGNORECASE,
)


class IdeaResultSessionError(ValueError):
    """Raised when P3-I input or canonical state is malformed."""


class SessionStage(str, Enum):
    INTENT = "intent"
    BLUEPRINT = "blueprint"
    READINESS = "readiness"
    TASK_PLAN = "task-plan"
    LIFECYCLE = "lifecycle"
    CONSOLIDATION = "consolidation"
    COMPLETE = "complete"


class SessionState(str, Enum):
    AUTO = "auto"
    RECOMMEND = "recommend"
    CONFIRM = "confirm"
    NEEDS_EVIDENCE = "needs-evidence"
    BLOCK = "block"
    COMPLETE = "complete"


_STAGE_ORDER = (
    SessionStage.INTENT,
    SessionStage.BLUEPRINT,
    SessionStage.READINESS,
    SessionStage.TASK_PLAN,
    SessionStage.LIFECYCLE,
    SessionStage.CONSOLIDATION,
)


def _scalar(value: object, label: str, maximum: int = 240) -> str:
    if type(value) is not str or not value or len(value) > maximum:
        raise IdeaResultSessionError(f"{label} must be bounded non-empty text")
    if value != unicodedata.normalize("NFC", value):
        raise IdeaResultSessionError(f"{label} must use NFC Unicode")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise IdeaResultSessionError(f"{label} contains control characters")
    if _SENSITIVE.search(value):
        raise IdeaResultSessionError(f"{label} contains a sensitive-value pattern")
    return value


def _code(value: object, label: str) -> str:
    text = _scalar(value, label, 128)
    if not _CODE.fullmatch(text):
        raise IdeaResultSessionError(f"{label} must be a bounded stable code")
    return text


def _digest(value: object, label: str) -> str:
    if type(value) is not str or not _SHA256.fullmatch(value):
        raise IdeaResultSessionError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _enum(value: object, enum_type: type[Enum], label: str) -> Enum:
    if type(value) is not str:
        raise IdeaResultSessionError(f"{label} must be a string enum")
    try:
        return enum_type(value)
    except ValueError as error:
        raise IdeaResultSessionError(f"{label} has an unsupported value") from error


def _canonical_codes(value: object, label: str) -> tuple[str, ...]:
    if type(value) is not tuple or len(value) > 128:
        raise IdeaResultSessionError(f"{label} must be a bounded immutable tuple")
    values = tuple(_code(item, f"{label}[{index}]") for index, item in enumerate(value))
    if values != tuple(sorted(set(values))):
        raise IdeaResultSessionError(f"{label} must use canonical unique order")
    return values


@dataclass(frozen=True)
class SessionStageInput:
    stage: SessionStage
    payload: bytes

    def __post_init__(self) -> None:
        if type(self) is not SessionStageInput:
            raise IdeaResultSessionError("SessionStageInput subclasses are not accepted")
        if type(self.stage) is not SessionStage or self.stage is SessionStage.COMPLETE:
            raise IdeaResultSessionError("stage input must name a canonical source stage")
        if type(self.payload) is not bytes or not self.payload or len(self.payload) > MAX_STAGE_PAYLOAD_BYTES:
            raise IdeaResultSessionError("stage payload must use bounded non-empty exact bytes")


@dataclass(frozen=True)
class SessionStageDigest:
    stage: SessionStage
    sha256: str

    def __post_init__(self) -> None:
        if type(self) is not SessionStageDigest:
            raise IdeaResultSessionError("SessionStageDigest subclasses are not accepted")
        if type(self.stage) is not SessionStage or self.stage is SessionStage.COMPLETE:
            raise IdeaResultSessionError("stage digest must name a canonical source stage")
        _digest(self.sha256, "stage_digest.sha256")


@dataclass(frozen=True)
class SessionUserResult:
    status_code: str
    result_code: str
    next_step_code: str
    stage: SessionStage
    phase: LifecyclePhase

    def __post_init__(self) -> None:
        if type(self) is not SessionUserResult:
            raise IdeaResultSessionError("SessionUserResult subclasses are not accepted")
        _code(self.status_code, "user_result.status_code")
        _code(self.result_code, "user_result.result_code")
        _code(self.next_step_code, "user_result.next_step_code")
        if type(self.stage) is not SessionStage:
            raise IdeaResultSessionError("user_result.stage must be a SessionStage")
        if type(self.phase) is not LifecyclePhase:
            raise IdeaResultSessionError("user_result.phase must be a LifecyclePhase")


@dataclass(frozen=True)
class IdeaResultSession:
    schema_version: str
    session_id: str
    intent: IntentDecisionResult
    blueprint: ProjectBlueprint | None
    readiness: ImplementationReadiness | None
    task_plan: AutonomousTaskPlan | None
    lifecycle: GoalDeliveryLifecycle | None
    consolidation: RequirementTraceConsolidation | None
    stage_digests: tuple[SessionStageDigest, ...]
    current_stage: SessionStage
    phase: LifecyclePhase
    state: SessionState
    reason_codes: tuple[str, ...]
    next_step_code: str
    user_result: SessionUserResult
    execution_performed: bool

    def __post_init__(self) -> None:
        if type(self) is not IdeaResultSession:
            raise IdeaResultSessionError("IdeaResultSession subclasses are not accepted")
        if self.schema_version != P3I_SCHEMA_VERSION:
            raise IdeaResultSessionError("unsupported idea-result-session schema_version")
        _code(self.session_id, "session_id")
        if type(self.intent) is not IntentDecisionResult:
            raise IdeaResultSessionError("intent must be an exact IntentDecisionResult")
        for label, value, record_type in (
            ("blueprint", self.blueprint, ProjectBlueprint),
            ("readiness", self.readiness, ImplementationReadiness),
            ("task_plan", self.task_plan, AutonomousTaskPlan),
            ("lifecycle", self.lifecycle, GoalDeliveryLifecycle),
            ("consolidation", self.consolidation, RequirementTraceConsolidation),
        ):
            if value is not None and type(value) is not record_type:
                raise IdeaResultSessionError(f"{label} must be an exact source record or null")
        digests = self.stage_digests
        if type(digests) is not tuple or len(digests) > len(_STAGE_ORDER):
            raise IdeaResultSessionError("stage_digests must be a bounded immutable tuple")
        if any(type(item) is not SessionStageDigest for item in digests):
            raise IdeaResultSessionError("stage_digests contains invalid records")
        stages = tuple(item.stage for item in digests)
        expected_order = tuple(stage for stage in _STAGE_ORDER if stage in set(stages))
        if stages != expected_order or len(stages) != len(set(stages)):
            raise IdeaResultSessionError("stage_digests must use canonical unique stage order")
        if type(self.current_stage) is not SessionStage:
            raise IdeaResultSessionError("current_stage must be a SessionStage")
        if type(self.phase) is not LifecyclePhase:
            raise IdeaResultSessionError("phase must be a LifecyclePhase")
        if type(self.state) is not SessionState:
            raise IdeaResultSessionError("state must be a SessionState")
        _canonical_codes(self.reason_codes, "reason_codes")
        _code(self.next_step_code, "next_step_code")
        if type(self.user_result) is not SessionUserResult:
            raise IdeaResultSessionError("user_result must be an exact SessionUserResult")
        if self.execution_performed is not False:
            raise IdeaResultSessionError("P3-I cannot claim stage execution")


def _parse_stage(stage: SessionStage, payload: bytes) -> object:
    try:
        if stage is SessionStage.INTENT:
            return parse_intent_decision_result(payload)
        if stage is SessionStage.BLUEPRINT:
            return parse_project_blueprint(payload)
        if stage is SessionStage.READINESS:
            return parse_implementation_readiness(payload)
        if stage is SessionStage.TASK_PLAN:
            return parse_autonomous_task_plan(payload)
        if stage is SessionStage.LIFECYCLE:
            return parse_goal_delivery_lifecycle(payload)
        if stage is SessionStage.CONSOLIDATION:
            return parse_requirement_trace_consolidation(payload)
    except (
        IntentDecisionError,
        ProjectBlueprintError,
        ImplementationReadinessError,
        AutonomousTaskOrchestrationError,
        GoalDeliveryLifecycleError,
        RequirementTraceConsolidationError,
        TypeError,
        ValueError,
    ) as error:
        raise IdeaResultSessionError(f"{stage.value} stage payload is invalid") from error
    raise IdeaResultSessionError("unsupported session stage")


def _render_stage(stage: SessionStage, value: object) -> bytes:
    if stage is SessionStage.INTENT:
        return render_intent_decision_result(value)  # type: ignore[arg-type]
    if stage is SessionStage.BLUEPRINT:
        return render_project_blueprint(value)  # type: ignore[arg-type]
    if stage is SessionStage.READINESS:
        return render_implementation_readiness(value)  # type: ignore[arg-type]
    if stage is SessionStage.TASK_PLAN:
        return render_autonomous_task_plan(value)  # type: ignore[arg-type]
    if stage is SessionStage.LIFECYCLE:
        return render_goal_delivery_lifecycle(value)  # type: ignore[arg-type]
    if stage is SessionStage.CONSOLIDATION:
        return render_requirement_trace_consolidation(value)  # type: ignore[arg-type]
    raise IdeaResultSessionError("unsupported session stage")


def _record_map(
    *,
    intent: IntentDecisionResult,
    blueprint: ProjectBlueprint | None,
    readiness: ImplementationReadiness | None,
    task_plan: AutonomousTaskPlan | None,
    lifecycle: GoalDeliveryLifecycle | None,
    consolidation: RequirementTraceConsolidation | None,
) -> dict[SessionStage, object]:
    records: dict[SessionStage, object] = {SessionStage.INTENT: intent}
    for stage, value in (
        (SessionStage.BLUEPRINT, blueprint),
        (SessionStage.READINESS, readiness),
        (SessionStage.TASK_PLAN, task_plan),
        (SessionStage.LIFECYCLE, lifecycle),
        (SessionStage.CONSOLIDATION, consolidation),
    ):
        if value is not None:
            records[stage] = value
    return records


def _chain_reasons(records: Mapping[SessionStage, object]) -> tuple[str, ...]:
    reasons: set[str] = set()
    present = set(records)
    for index, stage in enumerate(_STAGE_ORDER[1:], start=1):
        if stage in present and _STAGE_ORDER[index - 1] not in present:
            reasons.add("stage-predecessor-missing")
    intent = records.get(SessionStage.INTENT)
    blueprint = records.get(SessionStage.BLUEPRINT)
    readiness = records.get(SessionStage.READINESS)
    task_plan = records.get(SessionStage.TASK_PLAN)
    lifecycle = records.get(SessionStage.LIFECYCLE)
    consolidation = records.get(SessionStage.CONSOLIDATION)
    if intent is not None and blueprint is not None:
        intent_sha = hashlib.sha256(_render_stage(SessionStage.INTENT, intent)).hexdigest()
        if blueprint.source.intent_decision_sha256 != intent_sha:  # type: ignore[attr-defined]
            reasons.add("blueprint-intent-digest-drift")
    if blueprint is not None and readiness is not None:
        blueprint_sha = hashlib.sha256(_render_stage(SessionStage.BLUEPRINT, blueprint)).hexdigest()
        if readiness.source.blueprint_sha256 != blueprint_sha:  # type: ignore[attr-defined]
            reasons.add("readiness-blueprint-digest-drift")
    if readiness is not None and task_plan is not None:
        readiness_sha = hashlib.sha256(_render_stage(SessionStage.READINESS, readiness)).hexdigest()
        if task_plan.source.readiness_sha256 != readiness_sha:  # type: ignore[attr-defined]
            reasons.add("task-plan-readiness-digest-drift")
    if task_plan is not None and lifecycle is not None:
        task_plan_sha = hashlib.sha256(_render_stage(SessionStage.TASK_PLAN, task_plan)).hexdigest()
        if (
            lifecycle.plan_sha256 != task_plan_sha  # type: ignore[attr-defined]
            or lifecycle.plan_id != task_plan.plan_id  # type: ignore[attr-defined]
        ):
            reasons.add("lifecycle-task-plan-digest-drift")
    if lifecycle is not None and consolidation is not None:
        lifecycle_sha = hashlib.sha256(_render_stage(SessionStage.LIFECYCLE, lifecycle)).hexdigest()
        if (
            consolidation.source_lifecycle_sha256 != lifecycle_sha  # type: ignore[attr-defined]
            or consolidation.lifecycle_run_id != lifecycle.lifecycle_run_id  # type: ignore[attr-defined]
            or consolidation.plan_sha256 != lifecycle.plan_sha256  # type: ignore[attr-defined]
        ):
            reasons.add("consolidation-lifecycle-digest-drift")
    return tuple(sorted(reasons))


def _first_invalid_chain_stage(
    records: Mapping[SessionStage, object], reasons: tuple[str, ...]
) -> SessionStage:
    """Locate the earliest supplied stage made untrustworthy by the chain."""

    candidates: list[SessionStage] = []
    reason_stage = {
        "blueprint-intent-digest-drift": SessionStage.BLUEPRINT,
        "readiness-blueprint-digest-drift": SessionStage.READINESS,
        "task-plan-readiness-digest-drift": SessionStage.TASK_PLAN,
        "lifecycle-task-plan-digest-drift": SessionStage.LIFECYCLE,
        "consolidation-lifecycle-digest-drift": SessionStage.CONSOLIDATION,
    }
    candidates.extend(
        reason_stage[reason] for reason in reasons if reason in reason_stage
    )
    if "stage-predecessor-missing" in reasons:
        for index, stage in enumerate(_STAGE_ORDER[1:], start=1):
            if stage in records and _STAGE_ORDER[index - 1] not in records:
                candidates.append(stage)
                break
    if not candidates:
        return SessionStage.INTENT
    return min(candidates, key=_STAGE_ORDER.index)


def _derive_progress(
    records: Mapping[SessionStage, object], chain_reasons: tuple[str, ...]
) -> tuple[SessionStage, LifecyclePhase, SessionState, tuple[str, ...], str]:
    if chain_reasons:
        return (
            _first_invalid_chain_stage(records, chain_reasons),
            LifecyclePhase.PLANNED,
            SessionState.BLOCK,
            chain_reasons,
            "repair-stage-chain",
        )

    lifecycle = records.get(SessionStage.LIFECYCLE)
    consolidation = records.get(SessionStage.CONSOLIDATION)
    phase = (
        consolidation.phase  # type: ignore[attr-defined]
        if consolidation is not None
        else lifecycle.phase  # type: ignore[attr-defined]
        if lifecycle is not None
        else LifecyclePhase.PLANNED
    )
    intent = records[SessionStage.INTENT]
    if intent.confirmation_required_decisions or not intent.ready_for_blueprint:  # type: ignore[attr-defined]
        return (
            SessionStage.INTENT,
            phase,
            SessionState.CONFIRM,
            ("intent-confirmation-required",),
            "confirm-intent-decision",
        )
    if intent.recommended_decisions:  # type: ignore[attr-defined]
        return (
            SessionStage.INTENT,
            phase,
            SessionState.RECOMMEND,
            ("intent-recommendation-ready",),
            "review-intent-recommendation",
        )
    if SessionStage.BLUEPRINT not in records:
        return SessionStage.BLUEPRINT, phase, SessionState.AUTO, (), "generate-blueprint"
    if SessionStage.READINESS not in records:
        return SessionStage.READINESS, phase, SessionState.AUTO, (), "resolve-readiness"

    readiness = records[SessionStage.READINESS]
    if readiness.state is not ReadinessState.READY_FOR_MATERIALIZATION_PREVIEW:  # type: ignore[attr-defined]
        if readiness.state is ReadinessState.OWNER_CONFIRMATION_REQUIRED:  # type: ignore[attr-defined]
            return (
                SessionStage.READINESS,
                phase,
                SessionState.CONFIRM,
                ("readiness-owner-confirmation-required",),
                "confirm-readiness-decision",
            )
        return (
            SessionStage.READINESS,
            phase,
            SessionState.NEEDS_EVIDENCE,
            tuple(sorted(set(readiness.blocker_codes) | {readiness.state.value})),  # type: ignore[attr-defined]
            "collect-readiness-evidence",
        )
    if SessionStage.TASK_PLAN not in records:
        return SessionStage.TASK_PLAN, phase, SessionState.AUTO, (), "build-task-plan"

    task_plan = records[SessionStage.TASK_PLAN]
    if task_plan.state is OrchestrationState.BLOCK:  # type: ignore[attr-defined]
        return (
            SessionStage.TASK_PLAN,
            phase,
            SessionState.BLOCK,
            tuple(sorted(set(task_plan.blocker_codes) | {"task-plan-blocked"})),  # type: ignore[attr-defined]
            "resolve-task-plan-blockers",
        )
    if task_plan.state is OrchestrationState.PENDING_USER_INPUT:  # type: ignore[attr-defined]
        return (
            SessionStage.TASK_PLAN,
            phase,
            SessionState.CONFIRM,
            ("task-plan-confirmation-required",),
            "confirm-task-plan-boundary",
        )
    if task_plan.state is OrchestrationState.RECOMMENDATION_READY:  # type: ignore[attr-defined]
        return (
            SessionStage.TASK_PLAN,
            phase,
            SessionState.RECOMMEND,
            ("task-plan-recommendation-ready",),
            "review-recommended-task-path",
        )
    if SessionStage.LIFECYCLE not in records:
        return SessionStage.LIFECYCLE, phase, SessionState.AUTO, (), "start-goal-lifecycle"

    lifecycle = records[SessionStage.LIFECYCLE]
    if lifecycle.state is not LifecycleState.COMPLETE:  # type: ignore[attr-defined]
        state = {
            LifecycleState.AUTO: SessionState.AUTO,
            LifecycleState.RECOMMEND: SessionState.RECOMMEND,
            LifecycleState.CONFIRM: SessionState.CONFIRM,
            LifecycleState.BLOCK: SessionState.BLOCK,
        }[lifecycle.state]  # type: ignore[index]
        next_step = {
            SessionState.AUTO: "continue-goal-lifecycle",
            SessionState.RECOMMEND: "review-lifecycle-recommendation",
            SessionState.CONFIRM: "confirm-lifecycle-transaction",
            SessionState.BLOCK: "resolve-lifecycle-blockers",
        }[state]
        reasons = lifecycle.reason_codes or (f"lifecycle-{state.value}",)  # type: ignore[attr-defined]
        return SessionStage.LIFECYCLE, phase, state, reasons, next_step
    if SessionStage.CONSOLIDATION not in records:
        return SessionStage.CONSOLIDATION, phase, SessionState.AUTO, (), "consolidate-results"

    consolidation = records[SessionStage.CONSOLIDATION]
    if consolidation.state is ConsolidationState.ACCEPT:  # type: ignore[attr-defined]
        return SessionStage.COMPLETE, phase, SessionState.COMPLETE, (), "review-final-result"
    if consolidation.state is ConsolidationState.NEEDS_EVIDENCE:  # type: ignore[attr-defined]
        return (
            SessionStage.CONSOLIDATION,
            phase,
            SessionState.NEEDS_EVIDENCE,
            consolidation.reason_codes,  # type: ignore[attr-defined]
            "collect-consolidation-evidence",
        )
    return (
        SessionStage.CONSOLIDATION,
        phase,
        SessionState.BLOCK,
        consolidation.reason_codes or ("consolidation-blocked",),  # type: ignore[attr-defined]
        "resolve-consolidation-blockers",
    )


def _user_result(
    state: SessionState,
    stage: SessionStage,
    phase: LifecyclePhase,
    next_step_code: str,
) -> SessionUserResult:
    result_code = {
        SessionState.AUTO: "progressing-automatically",
        SessionState.RECOMMEND: "recommendation-ready",
        SessionState.CONFIRM: "confirmation-required",
        SessionState.NEEDS_EVIDENCE: "evidence-required",
        SessionState.BLOCK: "progress-blocked",
        SessionState.COMPLETE: "idea-result-complete",
    }[state]
    return SessionUserResult(
        status_code=state.value,
        result_code=result_code,
        next_step_code=next_step_code,
        stage=stage,
        phase=phase,
    )


def build_idea_result_session(
    *,
    session_id: str,
    stages: Sequence[SessionStageInput],
) -> IdeaResultSession:
    """Build one session from exact canonical stage payloads."""

    identifier = _code(session_id, "session_id")
    if not isinstance(stages, (tuple, list)) or not stages or len(stages) > len(_STAGE_ORDER):
        raise IdeaResultSessionError("stages must be a bounded non-empty sequence")
    inputs = tuple(stages)
    if any(type(item) is not SessionStageInput for item in inputs):
        raise IdeaResultSessionError("stages must contain exact SessionStageInput records")
    inputs = tuple(sorted(inputs, key=lambda item: _STAGE_ORDER.index(item.stage)))
    stage_ids = tuple(item.stage for item in inputs)
    if len(stage_ids) != len(set(stage_ids)):
        raise IdeaResultSessionError("stages contain duplicate stage records")
    if SessionStage.INTENT not in stage_ids:
        raise IdeaResultSessionError("intent stage is required")
    records = {item.stage: _parse_stage(item.stage, item.payload) for item in inputs}
    intent = records[SessionStage.INTENT]
    if type(intent) is not IntentDecisionResult:
        raise IdeaResultSessionError("intent stage has the wrong record type")
    typed_records = _record_map(
        intent=intent,
        blueprint=records.get(SessionStage.BLUEPRINT),  # type: ignore[arg-type]
        readiness=records.get(SessionStage.READINESS),  # type: ignore[arg-type]
        task_plan=records.get(SessionStage.TASK_PLAN),  # type: ignore[arg-type]
        lifecycle=records.get(SessionStage.LIFECYCLE),  # type: ignore[arg-type]
        consolidation=records.get(SessionStage.CONSOLIDATION),  # type: ignore[arg-type]
    )
    chain_reasons = _chain_reasons(typed_records)
    current_stage, phase, state, reason_codes, next_step = _derive_progress(
        typed_records, chain_reasons
    )
    stage_digests = tuple(
        SessionStageDigest(
            stage=stage,
            sha256=hashlib.sha256(_render_stage(stage, typed_records[stage])).hexdigest(),
        )
        for stage in _STAGE_ORDER
        if stage in typed_records
    )
    return IdeaResultSession(
        schema_version=P3I_SCHEMA_VERSION,
        session_id=identifier,
        intent=intent,
        blueprint=typed_records.get(SessionStage.BLUEPRINT),  # type: ignore[arg-type]
        readiness=typed_records.get(SessionStage.READINESS),  # type: ignore[arg-type]
        task_plan=typed_records.get(SessionStage.TASK_PLAN),  # type: ignore[arg-type]
        lifecycle=typed_records.get(SessionStage.LIFECYCLE),  # type: ignore[arg-type]
        consolidation=typed_records.get(SessionStage.CONSOLIDATION),  # type: ignore[arg-type]
        stage_digests=stage_digests,
        current_stage=current_stage,
        phase=phase,
        state=state,
        reason_codes=reason_codes,
        next_step_code=next_step,
        user_result=_user_result(state, current_stage, phase, next_step),
        execution_performed=False,
    )


def _stage_inputs(value: IdeaResultSession) -> tuple[SessionStageInput, ...]:
    records = _record_map(
        intent=value.intent,
        blueprint=value.blueprint,
        readiness=value.readiness,
        task_plan=value.task_plan,
        lifecycle=value.lifecycle,
        consolidation=value.consolidation,
    )
    return tuple(
        SessionStageInput(stage=stage, payload=_render_stage(stage, records[stage]))
        for stage in _STAGE_ORDER
        if stage in records
    )


def _recompute(value: IdeaResultSession) -> IdeaResultSession:
    return build_idea_result_session(session_id=value.session_id, stages=_stage_inputs(value))


def _mapping(value: IdeaResultSession) -> dict[str, object]:
    def embedded(stage: SessionStage, record: object | None) -> object | None:
        return None if record is None else json.loads(_render_stage(stage, record))

    return {
        "blueprint": embedded(SessionStage.BLUEPRINT, value.blueprint),
        "consolidation": embedded(SessionStage.CONSOLIDATION, value.consolidation),
        "current_stage": value.current_stage.value,
        "execution_performed": value.execution_performed,
        "intent": embedded(SessionStage.INTENT, value.intent),
        "lifecycle": embedded(SessionStage.LIFECYCLE, value.lifecycle),
        "next_step_code": value.next_step_code,
        "phase": value.phase.value,
        "readiness": embedded(SessionStage.READINESS, value.readiness),
        "reason_codes": list(value.reason_codes),
        "schema_version": value.schema_version,
        "session_id": value.session_id,
        "stage_digests": [
            {"sha256": item.sha256, "stage": item.stage.value}
            for item in value.stage_digests
        ],
        "state": value.state.value,
        "task_plan": embedded(SessionStage.TASK_PLAN, value.task_plan),
        "user_result": {
            "next_step_code": value.user_result.next_step_code,
            "phase": value.user_result.phase.value,
            "result_code": value.user_result.result_code,
            "stage": value.user_result.stage.value,
            "status_code": value.user_result.status_code,
        },
    }


def render_idea_result_session(value: IdeaResultSession) -> bytes:
    """Render canonical P3-I JSON after full stage-chain recomputation."""

    if type(value) is not IdeaResultSession:
        raise TypeError("value must be an exact IdeaResultSession")
    if _recompute(value) != value:
        raise IdeaResultSessionError("idea-result session does not match recomputed stages")
    try:
        rendered = canonical_json_bytes(_mapping(value))
    except SchemaError as error:
        raise IdeaResultSessionError(f"idea-result session cannot be encoded: {error}") from error
    if len(rendered) > MAX_IDEA_RESULT_SESSION_BYTES:
        raise IdeaResultSessionError("rendered idea-result session exceeds its byte bound")
    return rendered


def idea_result_user_result(value: IdeaResultSession) -> dict[str, str]:
    """Return the compact ordinary-user result without operator digests."""

    if type(value) is not IdeaResultSession:
        raise TypeError("value must be an exact IdeaResultSession")
    if _recompute(value) != value:
        raise IdeaResultSessionError("idea-result session does not match recomputed stages")
    return {
        "status": value.user_result.status_code,
        "result": value.user_result.result_code,
        "next_step": value.user_result.next_step_code,
        "stage": value.user_result.stage.value,
        "phase": value.user_result.phase.value,
    }


def _closed(value: object, fields: frozenset[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise IdeaResultSessionError(f"{label} must be an object")
    keys = set(value)
    if any(type(key) is not str for key in keys):
        raise IdeaResultSessionError(f"{label} keys must be strings")
    unknown = sorted(keys - fields)
    missing = sorted(fields - keys)
    if unknown:
        raise IdeaResultSessionError(f"{label} contains unknown fields: {', '.join(unknown)}")
    if missing:
        raise IdeaResultSessionError(f"{label} is missing fields: {', '.join(missing)}")
    return value


def _array(value: object, label: str, maximum: int) -> tuple[object, ...]:
    if type(value) is not list or len(value) > maximum:
        raise IdeaResultSessionError(f"{label} must be a bounded array")
    return tuple(value)


def _embedded(value: object, stage: SessionStage) -> object | None:
    if value is None:
        return None
    try:
        payload = canonical_json_bytes(value)
    except SchemaError as error:
        raise IdeaResultSessionError(f"embedded {stage.value} stage is invalid") from error
    return _parse_stage(stage, payload)


def _reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise IdeaResultSessionError("idea-result session contains duplicate object keys")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise IdeaResultSessionError(
        f"idea-result session contains unsupported JSON constant: {value}"
    )


def parse_idea_result_session(
    payload: bytes | bytearray | memoryview,
) -> IdeaResultSession:
    """Parse bounded canonical JSON and recompute the complete supplied chain."""

    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise IdeaResultSessionError("idea-result-session payload must be bytes")
    raw = bytes(payload)
    if not raw or len(raw) > MAX_IDEA_RESULT_SESSION_BYTES:
        raise IdeaResultSessionError("idea-result-session payload must use bounded non-empty bytes")
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicates,
            parse_constant=_reject_constant,
        )
    except IdeaResultSessionError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError, RecursionError) as error:
        raise IdeaResultSessionError("idea-result session is not valid UTF-8 JSON") from error
    item = _closed(
        value,
        frozenset(
            {
                "blueprint",
                "consolidation",
                "current_stage",
                "execution_performed",
                "intent",
                "lifecycle",
                "next_step_code",
                "phase",
                "readiness",
                "reason_codes",
                "schema_version",
                "session_id",
                "stage_digests",
                "state",
                "task_plan",
                "user_result",
            }
        ),
        "idea_result_session",
    )
    intent = _embedded(item["intent"], SessionStage.INTENT)
    if type(intent) is not IntentDecisionResult:
        raise IdeaResultSessionError("intent stage is required")
    user_item = _closed(
        item["user_result"],
        frozenset({"next_step_code", "phase", "result_code", "stage", "status_code"}),
        "user_result",
    )
    stage_digests = tuple(
        SessionStageDigest(
            stage=_enum(
                _closed(entry, frozenset({"sha256", "stage"}), f"stage_digests[{index}]")["stage"],
                SessionStage,
                f"stage_digests[{index}].stage",
            ),
            sha256=_digest(
                _closed(entry, frozenset({"sha256", "stage"}), f"stage_digests[{index}]")["sha256"],
                f"stage_digests[{index}].sha256",
            ),
        )
        for index, entry in enumerate(
            _array(item["stage_digests"], "stage_digests", len(_STAGE_ORDER))
        )
    )
    record = IdeaResultSession(
        schema_version=_scalar(item["schema_version"], "schema_version", 16),
        session_id=_code(item["session_id"], "session_id"),
        intent=intent,
        blueprint=_embedded(item["blueprint"], SessionStage.BLUEPRINT),  # type: ignore[arg-type]
        readiness=_embedded(item["readiness"], SessionStage.READINESS),  # type: ignore[arg-type]
        task_plan=_embedded(item["task_plan"], SessionStage.TASK_PLAN),  # type: ignore[arg-type]
        lifecycle=_embedded(item["lifecycle"], SessionStage.LIFECYCLE),  # type: ignore[arg-type]
        consolidation=_embedded(item["consolidation"], SessionStage.CONSOLIDATION),  # type: ignore[arg-type]
        stage_digests=stage_digests,
        current_stage=_enum(item["current_stage"], SessionStage, "current_stage"),
        phase=_enum(item["phase"], LifecyclePhase, "phase"),
        state=_enum(item["state"], SessionState, "state"),
        reason_codes=tuple(
            _code(entry, f"reason_codes[{index}]")
            for index, entry in enumerate(_array(item["reason_codes"], "reason_codes", 128))
        ),
        next_step_code=_code(item["next_step_code"], "next_step_code"),
        user_result=SessionUserResult(
            status_code=_code(user_item["status_code"], "user_result.status_code"),
            result_code=_code(user_item["result_code"], "user_result.result_code"),
            next_step_code=_code(user_item["next_step_code"], "user_result.next_step_code"),
            stage=_enum(user_item["stage"], SessionStage, "user_result.stage"),
            phase=_enum(user_item["phase"], LifecyclePhase, "user_result.phase"),
        ),
        execution_performed=item["execution_performed"],
    )
    if render_idea_result_session(record) != raw:
        raise IdeaResultSessionError("idea-result-session JSON is not canonical")
    return record


__all__ = [
    "P3I_SCHEMA_VERSION",
    "MAX_IDEA_RESULT_SESSION_BYTES",
    "MAX_STAGE_PAYLOAD_BYTES",
    "IdeaResultSessionError",
    "SessionStage",
    "SessionState",
    "SessionStageInput",
    "SessionStageDigest",
    "SessionUserResult",
    "IdeaResultSession",
    "build_idea_result_session",
    "render_idea_result_session",
    "parse_idea_result_session",
    "idea_result_user_result",
]
