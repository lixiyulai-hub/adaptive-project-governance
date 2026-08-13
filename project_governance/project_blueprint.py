"""Closed, deterministic P3-B project-blueprint generation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from pathlib import PurePosixPath
import re
from typing import Any, Mapping
import unicodedata

from .intent_decision_router import (
    IntentDecisionResult,
    parse_intent_decision_result,
    render_intent_decision_result,
)
from .storage import SchemaError, canonical_json_bytes
from .user_intent import ConstraintCode, GoalCode, ProjectType, TargetPlatform


PROJECT_BLUEPRINT_SCHEMA_VERSION = "1.0"
MAX_PROJECT_BLUEPRINT_BYTES = 128 * 1024
MAX_PROJECT_BLUEPRINT_MARKDOWN_BYTES = 128 * 1024

_MAX_CODE_LENGTH = 80
_MAX_REFERENCE_LENGTH = 240
_MAX_REFERENCES = 64
_MAX_REFERENCES_PER_ITEM = 16
_MAX_ITEMS = 32
_MAX_TASKS = 32

_CODE = re.compile(r"[a-z0-9][a-z0-9._-]{0,79}\Z")
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


class ProjectBlueprintError(ValueError):
    """Raised when a P3-B blueprint violates its closed contract."""


class BlueprintConfirmationRequired(ProjectBlueprintError):
    """Raised when P3-A still requires an owner decision."""

    def __init__(
        self, decision_ids: tuple[str, ...], question_ids: tuple[str, ...]
    ) -> None:
        self.decision_ids = decision_ids
        self.question_ids = question_ids
        super().__init__("project blueprint requires resolved owner confirmation")


class BlueprintSection(str, Enum):
    PROJECT_BRIEF = "PROJECT_BRIEF"
    PRODUCT_PLAN = "PRODUCT_PLAN"
    UX_FLOW = "UX_FLOW"
    ARCHITECTURE = "ARCHITECTURE"
    STACK_DECISION = "STACK_DECISION"
    TASK_GRAPH = "TASK_GRAPH"
    QUALITY_PLAN = "QUALITY_PLAN"
    DEPLOYMENT_PLAN = "DEPLOYMENT_PLAN"


class StackEvidenceState(str, Enum):
    NEEDS_EVIDENCE = "needs-evidence"


class TaskPhase(str, Enum):
    DESIGN = "design"
    IMPLEMENTATION = "implementation"
    VERIFICATION = "verification"
    DELIVERY_PREPARATION = "delivery-preparation"


class ExecutionState(str, Enum):
    NOT_RUN = "not-run"


class DeploymentAuthority(str, Enum):
    NOT_AUTHORIZED = "not-authorized"


def _scalar(value: object, label: str, *, maximum: int) -> str:
    if type(value) is not str or not value:
        raise ProjectBlueprintError(f"{label} must be a non-empty string")
    if len(value) > maximum:
        raise ProjectBlueprintError(
            f"{label} exceeds its {maximum}-character bound"
        )
    if unicodedata.normalize("NFC", value) != value:
        raise ProjectBlueprintError(f"{label} must use NFC Unicode")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        raise ProjectBlueprintError(f"{label} contains control characters")
    if _SENSITIVE.search(value):
        raise ProjectBlueprintError(f"{label} contains a sensitive-value pattern")
    return value


def _code(value: object, label: str) -> str:
    text = _scalar(value, label, maximum=_MAX_CODE_LENGTH)
    if not _CODE.fullmatch(text):
        raise ProjectBlueprintError(f"{label} must be a bounded stable code")
    return text


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
    text = _scalar(value, label, maximum=_MAX_REFERENCE_LENGTH)
    if _CODE.fullmatch(text) or _safe_relative_path(text):
        return text
    raise ProjectBlueprintError(
        f"{label} must be a stable code or contained project-relative path"
    )


def _exact_enum(value: object, enum_type: type[Enum], label: str) -> None:
    if type(value) is not enum_type:
        raise ProjectBlueprintError(f"{label} must be an exact {enum_type.__name__}")


def _enum_value(enum_type: type[Enum], value: object, label: str) -> Enum:
    if type(value) is not str:
        raise ProjectBlueprintError(f"{label} must be a string enum value")
    try:
        return enum_type(value)
    except ValueError as error:
        raise ProjectBlueprintError(f"{label} has an unsupported value") from error


def _tuple(value: object, label: str, maximum: int) -> tuple[object, ...]:
    if type(value) is not tuple or len(value) > maximum:
        raise ProjectBlueprintError(f"{label} must be a bounded immutable tuple")
    return value


def _sequence(value: object, label: str, maximum: int) -> tuple[object, ...]:
    if type(value) is not list or len(value) > maximum:
        raise ProjectBlueprintError(f"{label} must be a bounded array")
    return tuple(value)


def _codes(
    value: object,
    label: str,
    maximum: int = _MAX_ITEMS,
    *,
    allow_empty: bool = True,
    semantic_order: bool = False,
) -> tuple[str, ...]:
    items = _tuple(value, label, maximum)
    if not allow_empty and not items:
        raise ProjectBlueprintError(f"{label} must not be empty")
    normalized = tuple(_code(item, f"{label}[{index}]") for index, item in enumerate(items))
    if len(set(normalized)) != len(normalized):
        raise ProjectBlueprintError(f"{label} must contain unique codes")
    if not semantic_order and normalized != tuple(sorted(normalized)):
        raise ProjectBlueprintError(f"{label} must use canonical order")
    return normalized


def _references(
    value: object, label: str, maximum: int = _MAX_REFERENCES_PER_ITEM
) -> tuple[str, ...]:
    items = _tuple(value, label, maximum)
    normalized = tuple(
        _reference(item, f"{label}[{index}]") for index, item in enumerate(items)
    )
    if normalized != tuple(sorted(set(normalized))):
        raise ProjectBlueprintError(f"{label} must use canonical unique order")
    return normalized


@dataclass(frozen=True)
class BlueprintSource:
    intent_decision_sha256: str
    intent_decision: IntentDecisionResult

    def __post_init__(self) -> None:
        if type(self) is not BlueprintSource:
            raise ProjectBlueprintError("BlueprintSource subclasses are not accepted")
        if type(self.intent_decision) is not IntentDecisionResult:
            raise ProjectBlueprintError(
                "source.intent_decision must be an exact IntentDecisionResult"
            )
        try:
            rendered = render_intent_decision_result(self.intent_decision)
        except (TypeError, ValueError) as error:
            raise ProjectBlueprintError("source intent decision is not canonical") from error
        expected = hashlib.sha256(rendered).hexdigest()
        if type(self.intent_decision_sha256) is not str or not _SHA256.fullmatch(
            self.intent_decision_sha256
        ):
            raise ProjectBlueprintError(
                "source intent_decision_sha256 must be a lowercase SHA-256 digest"
            )
        if self.intent_decision_sha256 != expected:
            raise ProjectBlueprintError("source digest does not bind intent decision")


@dataclass(frozen=True)
class ProjectBrief:
    project_type: str
    target_platform: str
    user_persona: str
    goal_codes: tuple[str, ...]
    constraint_codes: tuple[str, ...]
    assumption_decision_ids: tuple[str, ...]
    unresolved_codes: tuple[str, ...]
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self) is not ProjectBrief:
            raise ProjectBlueprintError("ProjectBrief subclasses are not accepted")
        _code(self.project_type, "project_brief.project_type")
        _code(self.target_platform, "project_brief.target_platform")
        _code(self.user_persona, "project_brief.user_persona")
        _codes(self.goal_codes, "project_brief.goal_codes")
        _codes(self.constraint_codes, "project_brief.constraint_codes")
        _codes(
            self.assumption_decision_ids,
            "project_brief.assumption_decision_ids",
        )
        _codes(self.unresolved_codes, "project_brief.unresolved_codes")
        _references(self.evidence_refs, "project_brief.evidence_refs", _MAX_REFERENCES)


@dataclass(frozen=True)
class ProductPlan:
    outcome_codes: tuple[str, ...]
    capability_codes: tuple[str, ...]
    milestone_codes: tuple[str, ...]
    assumption_decision_ids: tuple[str, ...]
    unresolved_codes: tuple[str, ...]
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self) is not ProductPlan:
            raise ProjectBlueprintError("ProductPlan subclasses are not accepted")
        _codes(self.outcome_codes, "product_plan.outcome_codes", allow_empty=False)
        _codes(self.capability_codes, "product_plan.capability_codes", allow_empty=False)
        _codes(
            self.milestone_codes,
            "product_plan.milestone_codes",
            semantic_order=True,
            allow_empty=False,
        )
        _codes(self.assumption_decision_ids, "product_plan.assumption_decision_ids")
        _codes(self.unresolved_codes, "product_plan.unresolved_codes")
        _references(self.evidence_refs, "product_plan.evidence_refs", _MAX_REFERENCES)


@dataclass(frozen=True)
class UXFlow:
    actor_code: str
    entry_code: str
    step_codes: tuple[str, ...]
    exit_code: str
    accessibility_required: bool
    assumption_decision_ids: tuple[str, ...]
    unresolved_codes: tuple[str, ...]
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self) is not UXFlow:
            raise ProjectBlueprintError("UXFlow subclasses are not accepted")
        _code(self.actor_code, "ux_flow.actor_code")
        _code(self.entry_code, "ux_flow.entry_code")
        _codes(
            self.step_codes,
            "ux_flow.step_codes",
            semantic_order=True,
            allow_empty=False,
        )
        _code(self.exit_code, "ux_flow.exit_code")
        if type(self.accessibility_required) is not bool:
            raise ProjectBlueprintError(
                "ux_flow.accessibility_required must be a boolean"
            )
        _codes(self.assumption_decision_ids, "ux_flow.assumption_decision_ids")
        _codes(self.unresolved_codes, "ux_flow.unresolved_codes")
        _references(self.evidence_refs, "ux_flow.evidence_refs", _MAX_REFERENCES)


@dataclass(frozen=True)
class ArchitecturePlan:
    architecture_code: str
    component_codes: tuple[str, ...]
    boundary_codes: tuple[str, ...]
    data_flow_codes: tuple[str, ...]
    external_dependency_code: str
    assumption_decision_ids: tuple[str, ...]
    unresolved_codes: tuple[str, ...]
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self) is not ArchitecturePlan:
            raise ProjectBlueprintError("ArchitecturePlan subclasses are not accepted")
        _code(self.architecture_code, "architecture.architecture_code")
        _codes(self.component_codes, "architecture.component_codes", allow_empty=False)
        _codes(self.boundary_codes, "architecture.boundary_codes", allow_empty=False)
        _codes(self.data_flow_codes, "architecture.data_flow_codes", allow_empty=False)
        _code(self.external_dependency_code, "architecture.external_dependency_code")
        _codes(self.assumption_decision_ids, "architecture.assumption_decision_ids")
        _codes(self.unresolved_codes, "architecture.unresolved_codes")
        _references(self.evidence_refs, "architecture.evidence_refs", _MAX_REFERENCES)


@dataclass(frozen=True)
class StackDecisionPlan:
    state: StackEvidenceState
    selected_candidate_id: None
    architecture_requirement_code: str
    capability_codes: tuple[str, ...]
    provider_selection_code: str
    rationale_codes: tuple[str, ...]
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self) is not StackDecisionPlan:
            raise ProjectBlueprintError(
                "StackDecisionPlan subclasses are not accepted"
            )
        _exact_enum(self.state, StackEvidenceState, "stack_decision.state")
        if self.selected_candidate_id is not None:
            raise ProjectBlueprintError(
                "stack_decision.selected_candidate_id must remain null"
            )
        _code(
            self.architecture_requirement_code,
            "stack_decision.architecture_requirement_code",
        )
        _codes(self.capability_codes, "stack_decision.capability_codes")
        _code(self.provider_selection_code, "stack_decision.provider_selection_code")
        _codes(
            self.rationale_codes,
            "stack_decision.rationale_codes",
            allow_empty=False,
        )
        _references(
            self.evidence_refs, "stack_decision.evidence_refs", _MAX_REFERENCES
        )


@dataclass(frozen=True)
class BlueprintTask:
    task_id: str
    phase: TaskPhase
    action_code: str
    output_code: str
    depends_on: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self) is not BlueprintTask:
            raise ProjectBlueprintError("BlueprintTask subclasses are not accepted")
        _code(self.task_id, "task.task_id")
        _exact_enum(self.phase, TaskPhase, "task.phase")
        _code(self.action_code, "task.action_code")
        _code(self.output_code, "task.output_code")
        _codes(self.depends_on, "task.depends_on", 8)
        if self.task_id in self.depends_on:
            raise ProjectBlueprintError("task cannot depend on itself")


@dataclass(frozen=True)
class TaskGraph:
    tasks: tuple[BlueprintTask, ...]
    entry_task_ids: tuple[str, ...]
    terminal_task_ids: tuple[str, ...]
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self) is not TaskGraph:
            raise ProjectBlueprintError("TaskGraph subclasses are not accepted")
        tasks = _tuple(self.tasks, "task_graph.tasks", _MAX_TASKS)
        if not tasks or any(type(item) is not BlueprintTask for item in tasks):
            raise ProjectBlueprintError(
                "task_graph.tasks must contain BlueprintTask records"
            )
        identifiers = tuple(item.task_id for item in tasks)
        if len(set(identifiers)) != len(identifiers):
            raise ProjectBlueprintError("task_graph contains duplicate task IDs")
        seen: set[str] = set()
        for task in tasks:
            if any(dependency not in seen for dependency in task.depends_on):
                raise ProjectBlueprintError(
                    "task_graph must use deterministic topological order"
                )
            seen.add(task.task_id)
        entries = _codes(self.entry_task_ids, "task_graph.entry_task_ids", _MAX_TASKS)
        terminals = _codes(
            self.terminal_task_ids, "task_graph.terminal_task_ids", _MAX_TASKS
        )
        if any(identifier not in seen for identifier in entries + terminals):
            raise ProjectBlueprintError("task_graph entry or terminal ID is unknown")
        expected_entries = tuple(sorted(task.task_id for task in tasks if not task.depends_on))
        depended_on = {item for task in tasks for item in task.depends_on}
        expected_terminals = tuple(sorted(set(identifiers) - depended_on))
        if entries != expected_entries or terminals != expected_terminals:
            raise ProjectBlueprintError(
                "task_graph entry and terminal IDs must match graph topology"
            )
        _references(self.evidence_refs, "task_graph.evidence_refs", _MAX_REFERENCES)


@dataclass(frozen=True)
class QualityCheck:
    check_id: str
    check_kind: str
    expected_result_code: str
    evidence_requirement_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self) is not QualityCheck:
            raise ProjectBlueprintError("QualityCheck subclasses are not accepted")
        _code(self.check_id, "quality_check.check_id")
        _code(self.check_kind, "quality_check.check_kind")
        _code(self.expected_result_code, "quality_check.expected_result_code")
        _codes(
            self.evidence_requirement_codes,
            "quality_check.evidence_requirement_codes",
            allow_empty=False,
        )


@dataclass(frozen=True)
class QualityPlan:
    checks: tuple[QualityCheck, ...]
    acceptance_codes: tuple[str, ...]
    professional_review_codes: tuple[str, ...]
    execution_state: ExecutionState
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self) is not QualityPlan:
            raise ProjectBlueprintError("QualityPlan subclasses are not accepted")
        checks = _tuple(self.checks, "quality_plan.checks", _MAX_ITEMS)
        if not checks or any(type(item) is not QualityCheck for item in checks):
            raise ProjectBlueprintError(
                "quality_plan.checks must contain QualityCheck records"
            )
        identifiers = tuple(item.check_id for item in checks)
        if identifiers != tuple(sorted(set(identifiers))):
            raise ProjectBlueprintError(
                "quality_plan.checks must use canonical unique order"
            )
        _codes(self.acceptance_codes, "quality_plan.acceptance_codes", allow_empty=False)
        _codes(
            self.professional_review_codes,
            "quality_plan.professional_review_codes",
            allow_empty=False,
        )
        _exact_enum(self.execution_state, ExecutionState, "quality_plan.execution_state")
        _references(self.evidence_refs, "quality_plan.evidence_refs", _MAX_REFERENCES)


@dataclass(frozen=True)
class DeploymentPlan:
    delivery_target_code: str
    artifact_codes: tuple[str, ...]
    precondition_codes: tuple[str, ...]
    rollback_codes: tuple[str, ...]
    verification_codes: tuple[str, ...]
    provider_selection_code: str
    execution_state: ExecutionState
    acceptance_state: ExecutionState
    authority: DeploymentAuthority
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self) is not DeploymentPlan:
            raise ProjectBlueprintError("DeploymentPlan subclasses are not accepted")
        _code(self.delivery_target_code, "deployment_plan.delivery_target_code")
        _codes(self.artifact_codes, "deployment_plan.artifact_codes", allow_empty=False)
        _codes(
            self.precondition_codes,
            "deployment_plan.precondition_codes",
            allow_empty=False,
        )
        _codes(self.rollback_codes, "deployment_plan.rollback_codes", allow_empty=False)
        _codes(
            self.verification_codes,
            "deployment_plan.verification_codes",
            allow_empty=False,
        )
        _code(
            self.provider_selection_code,
            "deployment_plan.provider_selection_code",
        )
        _exact_enum(
            self.execution_state, ExecutionState, "deployment_plan.execution_state"
        )
        _exact_enum(
            self.acceptance_state, ExecutionState, "deployment_plan.acceptance_state"
        )
        _exact_enum(self.authority, DeploymentAuthority, "deployment_plan.authority")
        _references(
            self.evidence_refs, "deployment_plan.evidence_refs", _MAX_REFERENCES
        )


_SECTION_TYPES = (
    ProjectBrief,
    ProductPlan,
    UXFlow,
    ArchitecturePlan,
    StackDecisionPlan,
    TaskGraph,
    QualityPlan,
    DeploymentPlan,
)


@dataclass(frozen=True)
class ProjectBlueprint:
    schema_version: str
    blueprint_id: str
    source: BlueprintSource
    ready_for_implementation: bool
    sections: tuple[object, ...]
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self) is not ProjectBlueprint:
            raise ProjectBlueprintError("ProjectBlueprint subclasses are not accepted")
        if self.schema_version != PROJECT_BLUEPRINT_SCHEMA_VERSION:
            raise ProjectBlueprintError("unsupported project-blueprint schema_version")
        _code(self.blueprint_id, "blueprint_id")
        if type(self.source) is not BlueprintSource:
            raise ProjectBlueprintError("source must be an exact BlueprintSource")
        if type(self.ready_for_implementation) is not bool:
            raise ProjectBlueprintError("ready_for_implementation must be a boolean")
        if self.ready_for_implementation:
            raise ProjectBlueprintError(
                "P3-B v1 cannot claim implementation readiness"
            )
        sections = _tuple(self.sections, "sections", len(_SECTION_TYPES))
        if len(sections) != len(_SECTION_TYPES):
            raise ProjectBlueprintError("sections must contain exactly eight records")
        if tuple(type(item) for item in sections) != _SECTION_TYPES:
            raise ProjectBlueprintError("sections use the wrong type or order")
        refs = _references(self.evidence_refs, "evidence_refs", _MAX_REFERENCES)
        if refs != self.source.intent_decision.evidence_refs:
            raise ProjectBlueprintError(
                "blueprint evidence_refs must exactly bind source evidence"
            )

    @property
    def project_brief(self) -> ProjectBrief:
        return self.sections[0]  # type: ignore[return-value]

    @property
    def product_plan(self) -> ProductPlan:
        return self.sections[1]  # type: ignore[return-value]

    @property
    def ux_flow(self) -> UXFlow:
        return self.sections[2]  # type: ignore[return-value]

    @property
    def architecture(self) -> ArchitecturePlan:
        return self.sections[3]  # type: ignore[return-value]

    @property
    def stack_decision(self) -> StackDecisionPlan:
        return self.sections[4]  # type: ignore[return-value]

    @property
    def task_graph(self) -> TaskGraph:
        return self.sections[5]  # type: ignore[return-value]

    @property
    def quality_plan(self) -> QualityPlan:
        return self.sections[6]  # type: ignore[return-value]

    @property
    def deployment_plan(self) -> DeploymentPlan:
        return self.sections[7]  # type: ignore[return-value]


_OUTCOME_BY_GOAL = {
    GoalCode.BUILD_PRODUCT: "outcome.runnable-product",
    GoalCode.AUTOMATE_WORKFLOW: "outcome.workflow-automation",
    GoalCode.ORGANIZE_INFORMATION: "outcome.organized-information",
    GoalCode.ANALYZE_DATA: "outcome.data-insight",
    GoalCode.PUBLISH_CONTENT: "outcome.publishable-content",
    GoalCode.INTEGRATE_SYSTEMS: "outcome.system-integration",
    GoalCode.LEARN_OR_PROTOTYPE: "outcome.validated-prototype",
}

_CAPABILITY_BY_GOAL = {
    GoalCode.BUILD_PRODUCT: "capability.product-experience",
    GoalCode.AUTOMATE_WORKFLOW: "capability.workflow-orchestration",
    GoalCode.ORGANIZE_INFORMATION: "capability.information-management",
    GoalCode.ANALYZE_DATA: "capability.data-analysis",
    GoalCode.PUBLISH_CONTENT: "capability.content-delivery",
    GoalCode.INTEGRATE_SYSTEMS: "capability.system-interface",
    GoalCode.LEARN_OR_PROTOTYPE: "capability.prototype-feedback",
}

_COMPONENTS_BY_PROJECT_TYPE = {
    ProjectType.APPLICATION: (
        "component.application-logic",
        "component.data-boundary",
        "component.user-interface",
    ),
    ProjectType.WEBSITE: (
        "component.application-logic",
        "component.content-interface",
        "component.data-boundary",
    ),
    ProjectType.AUTOMATION: (
        "component.input-adapter",
        "component.output-adapter",
        "component.workflow-engine",
    ),
    ProjectType.API: (
        "component.api-interface",
        "component.data-boundary",
        "component.service-logic",
    ),
    ProjectType.LIBRARY: (
        "component.public-contract",
        "component.validation-core",
        "component.verification-harness",
    ),
    ProjectType.DATA_PIPELINE: (
        "component.data-ingestion",
        "component.data-output",
        "component.data-transformation",
    ),
    ProjectType.DOCUMENT: (
        "component.content-model",
        "component.rendering-projection",
        "component.source-ingestion",
    ),
    ProjectType.UNKNOWN: (
        "component.logical-boundary",
        "component.requirements-boundary",
        "component.verification-boundary",
    ),
}


def _sorted_codes(values: Any) -> tuple[str, ...]:
    return tuple(sorted(set(values)))


def _quality_checks(accessibility_required: bool) -> tuple[QualityCheck, ...]:
    checks = [
        QualityCheck(
            check_id="check.acceptance",
            check_kind="check-kind.acceptance",
            expected_result_code="expected.acceptance-criteria-satisfied",
            evidence_requirement_codes=("evidence.acceptance-report",),
        ),
        QualityCheck(
            check_id="check.behavior",
            check_kind="check-kind.behavior",
            expected_result_code="expected.required-behavior-observed",
            evidence_requirement_codes=("evidence.focused-test-report",),
        ),
        QualityCheck(
            check_id="check.independent-review",
            check_kind="check-kind.independent-review",
            expected_result_code="expected.independent-review-accepted",
            evidence_requirement_codes=("evidence.independent-review",),
        ),
        QualityCheck(
            check_id="check.regression",
            check_kind="check-kind.regression",
            expected_result_code="expected.required-gates-pass",
            evidence_requirement_codes=("evidence.plan-bound-gate-receipt",),
        ),
    ]
    if accessibility_required:
        checks.append(
            QualityCheck(
                check_id="check.accessibility",
                check_kind="check-kind.accessibility",
                expected_result_code="expected.accessibility-requirements-satisfied",
                evidence_requirement_codes=("evidence.accessibility-review",),
            )
        )
    return tuple(sorted(checks, key=lambda item: item.check_id))


def generate_project_blueprint(source: IntentDecisionResult) -> ProjectBlueprint:
    """Generate one deterministic, non-executing blueprint from canonical P3-A."""

    if type(source) is not IntentDecisionResult:
        raise TypeError("source must be an exact IntentDecisionResult")
    try:
        source_bytes = render_intent_decision_result(source)
    except (TypeError, ValueError) as error:
        raise ProjectBlueprintError("source intent decision is not canonical") from error
    if source.ready_for_blueprint is not True or source.confirmation_required_decisions:
        raise BlueprintConfirmationRequired(
            tuple(
                item.decision_id for item in source.confirmation_required_decisions
            ),
            tuple(item.question_id for item in source.necessary_questions),
        )

    intent = source.structured_intent
    digest = hashlib.sha256(source_bytes).hexdigest()
    assumptions = tuple(item.decision_id for item in source.recommended_decisions)
    unresolved = _sorted_codes(
        f"uncertainty.{item.value}" for item in intent.uncertainty_codes
    )
    refs = source.evidence_refs
    goals = tuple(item.value for item in intent.goal_codes)
    constraints = tuple(item.value for item in intent.constraint_codes)
    outcomes = _sorted_codes(_OUTCOME_BY_GOAL[item] for item in intent.goal_codes)
    capabilities = _sorted_codes(
        _CAPABILITY_BY_GOAL[item] for item in intent.goal_codes
    )
    if not outcomes:
        outcomes = ("outcome.needs-product-direction",)
    if not capabilities:
        capabilities = ("capability.needs-product-direction",)

    project_brief = ProjectBrief(
        project_type=intent.project_type.value,
        target_platform=intent.target_platform.value,
        user_persona=intent.user_persona.value,
        goal_codes=goals,
        constraint_codes=constraints,
        assumption_decision_ids=assumptions,
        unresolved_codes=unresolved,
        evidence_refs=refs,
    )
    product_plan = ProductPlan(
        outcome_codes=outcomes,
        capability_codes=capabilities,
        milestone_codes=(
            "milestone.blueprint-reviewed",
            "milestone.implementation-authorized",
            "milestone.solution-implemented",
            "milestone.quality-evidence-accepted",
            "milestone.delivery-authorized",
        ),
        assumption_decision_ids=assumptions,
        unresolved_codes=unresolved,
        evidence_refs=refs,
    )
    ux_flow = UXFlow(
        actor_code=f"actor.{intent.user_persona.value}",
        entry_code="entry.accepted-intent-decision",
        step_codes=(
            "step.review-project-brief",
            "step.review-product-plan",
            "step.review-ux-flow",
            "step.review-architecture-and-stack-evidence",
            "step.authorize-later-implementation",
        ),
        exit_code="exit.blueprint-planning-complete",
        accessibility_required=ConstraintCode.ACCESSIBILITY
        in intent.constraint_codes,
        assumption_decision_ids=assumptions,
        unresolved_codes=unresolved,
        evidence_refs=refs,
    )
    architecture = ArchitecturePlan(
        architecture_code=(
            f"architecture.logical.{intent.project_type.value}."
            f"{intent.target_platform.value}"
        ),
        component_codes=_COMPONENTS_BY_PROJECT_TYPE[intent.project_type],
        boundary_codes=(
            "boundary.external-effects-separate",
            "boundary.plan-before-execution",
            "boundary.source-evidence-bound",
        ),
        data_flow_codes=(
            "data-flow.intent-to-blueprint",
            "data-flow.plan-to-later-materialization",
        ),
        external_dependency_code="external-dependency.needs-evidence",
        assumption_decision_ids=assumptions,
        unresolved_codes=unresolved,
        evidence_refs=refs,
    )
    stack = StackDecisionPlan(
        state=StackEvidenceState.NEEDS_EVIDENCE,
        selected_candidate_id=None,
        architecture_requirement_code=(
            f"requirement.{intent.project_type.value}.{intent.target_platform.value}"
        ),
        capability_codes=capabilities,
        provider_selection_code="provider.not-selected",
        rationale_codes=(
            "rationale.p3-a-source-lacks-stack-candidate-evidence",
            "rationale.stack-selection-requires-separate-evidence",
        ),
        evidence_refs=refs,
    )
    tasks = (
        BlueprintTask(
            "task.design.product",
            TaskPhase.DESIGN,
            "action.refine-product-plan",
            "output.accepted-product-plan",
            (),
        ),
        BlueprintTask(
            "task.design.ux",
            TaskPhase.DESIGN,
            "action.refine-ux-flow",
            "output.accepted-ux-flow",
            ("task.design.product",),
        ),
        BlueprintTask(
            "task.design.architecture",
            TaskPhase.DESIGN,
            "action.refine-logical-architecture",
            "output.accepted-architecture",
            ("task.design.product",),
        ),
        BlueprintTask(
            "task.decide.stack",
            TaskPhase.DESIGN,
            "action.collect-stack-evidence",
            "output.evidence-bound-stack-decision",
            ("task.design.architecture",),
        ),
        BlueprintTask(
            "task.implement.solution",
            TaskPhase.IMPLEMENTATION,
            "action.materialize-and-implement-solution",
            "output.runnable-solution",
            (
                "task.decide.stack",
                "task.design.architecture",
                "task.design.product",
                "task.design.ux",
            ),
        ),
        BlueprintTask(
            "task.verify.solution",
            TaskPhase.VERIFICATION,
            "action.execute-quality-plan",
            "output.accepted-quality-evidence",
            ("task.implement.solution",),
        ),
        BlueprintTask(
            "task.prepare.delivery",
            TaskPhase.DELIVERY_PREPARATION,
            "action.prepare-authorized-delivery",
            "output.delivery-candidate",
            ("task.verify.solution",),
        ),
    )
    task_graph = TaskGraph(
        tasks=tasks,
        entry_task_ids=("task.design.product",),
        terminal_task_ids=("task.prepare.delivery",),
        evidence_refs=refs,
    )
    quality = QualityPlan(
        checks=_quality_checks(ux_flow.accessibility_required),
        acceptance_codes=(
            "acceptance.behavior-evidence-required",
            "acceptance.independent-review-required",
            "acceptance.plan-bound-gates-required",
        ),
        professional_review_codes=(
            "review.accessibility-when-applicable",
            "review.architecture-and-security",
            "review.user-outcome",
        ),
        execution_state=ExecutionState.NOT_RUN,
        evidence_refs=refs,
    )
    deployment = DeploymentPlan(
        delivery_target_code=f"delivery-target.{intent.target_platform.value}",
        artifact_codes=(
            "artifact.acceptance-evidence",
            "artifact.rollback-plan",
            "artifact.runnable-project",
        ),
        precondition_codes=(
            "precondition.deployment-approved",
            "precondition.implementation-authorized",
            "precondition.quality-evidence-passed",
            "precondition.stack-evidence-accepted",
        ),
        rollback_codes=(
            "rollback.exact-artifact-cas",
            "rollback.verified-restore",
        ),
        verification_codes=(
            "verification.deployment-separate",
            "verification.publication-separate",
            "verification.runtime-separate",
        ),
        provider_selection_code="provider.not-selected",
        execution_state=ExecutionState.NOT_RUN,
        acceptance_state=ExecutionState.NOT_RUN,
        authority=DeploymentAuthority.NOT_AUTHORIZED,
        evidence_refs=refs,
    )
    return ProjectBlueprint(
        schema_version=PROJECT_BLUEPRINT_SCHEMA_VERSION,
        blueprint_id=f"blueprint.p3b.{digest[:16]}",
        source=BlueprintSource(
            intent_decision_sha256=digest,
            intent_decision=source,
        ),
        ready_for_implementation=False,
        sections=(
            project_brief,
            product_plan,
            ux_flow,
            architecture,
            stack,
            task_graph,
            quality,
            deployment,
        ),
        evidence_refs=refs,
    )


def _source_mapping(source: BlueprintSource) -> dict[str, object]:
    return {
        "intent_decision": json.loads(
            render_intent_decision_result(source.intent_decision)
        ),
        "intent_decision_sha256": source.intent_decision_sha256,
    }


def _task_mapping(task: BlueprintTask) -> dict[str, object]:
    return {
        "action_code": task.action_code,
        "depends_on": list(task.depends_on),
        "output_code": task.output_code,
        "phase": task.phase.value,
        "task_id": task.task_id,
    }


def _quality_check_mapping(check: QualityCheck) -> dict[str, object]:
    return {
        "check_id": check.check_id,
        "check_kind": check.check_kind,
        "evidence_requirement_codes": list(check.evidence_requirement_codes),
        "expected_result_code": check.expected_result_code,
    }


def _section_mapping(section: object) -> dict[str, object]:
    if type(section) is ProjectBrief:
        return {
            "assumption_decision_ids": list(section.assumption_decision_ids),
            "constraint_codes": list(section.constraint_codes),
            "evidence_refs": list(section.evidence_refs),
            "goal_codes": list(section.goal_codes),
            "project_type": section.project_type,
            "section": BlueprintSection.PROJECT_BRIEF.value,
            "target_platform": section.target_platform,
            "unresolved_codes": list(section.unresolved_codes),
            "user_persona": section.user_persona,
        }
    if type(section) is ProductPlan:
        return {
            "assumption_decision_ids": list(section.assumption_decision_ids),
            "capability_codes": list(section.capability_codes),
            "evidence_refs": list(section.evidence_refs),
            "milestone_codes": list(section.milestone_codes),
            "outcome_codes": list(section.outcome_codes),
            "section": BlueprintSection.PRODUCT_PLAN.value,
            "unresolved_codes": list(section.unresolved_codes),
        }
    if type(section) is UXFlow:
        return {
            "accessibility_required": section.accessibility_required,
            "actor_code": section.actor_code,
            "assumption_decision_ids": list(section.assumption_decision_ids),
            "entry_code": section.entry_code,
            "evidence_refs": list(section.evidence_refs),
            "exit_code": section.exit_code,
            "section": BlueprintSection.UX_FLOW.value,
            "step_codes": list(section.step_codes),
            "unresolved_codes": list(section.unresolved_codes),
        }
    if type(section) is ArchitecturePlan:
        return {
            "architecture_code": section.architecture_code,
            "assumption_decision_ids": list(section.assumption_decision_ids),
            "boundary_codes": list(section.boundary_codes),
            "component_codes": list(section.component_codes),
            "data_flow_codes": list(section.data_flow_codes),
            "evidence_refs": list(section.evidence_refs),
            "external_dependency_code": section.external_dependency_code,
            "section": BlueprintSection.ARCHITECTURE.value,
            "unresolved_codes": list(section.unresolved_codes),
        }
    if type(section) is StackDecisionPlan:
        return {
            "architecture_requirement_code": section.architecture_requirement_code,
            "capability_codes": list(section.capability_codes),
            "evidence_refs": list(section.evidence_refs),
            "provider_selection_code": section.provider_selection_code,
            "rationale_codes": list(section.rationale_codes),
            "section": BlueprintSection.STACK_DECISION.value,
            "selected_candidate_id": section.selected_candidate_id,
            "state": section.state.value,
        }
    if type(section) is TaskGraph:
        return {
            "entry_task_ids": list(section.entry_task_ids),
            "evidence_refs": list(section.evidence_refs),
            "section": BlueprintSection.TASK_GRAPH.value,
            "tasks": [_task_mapping(item) for item in section.tasks],
            "terminal_task_ids": list(section.terminal_task_ids),
        }
    if type(section) is QualityPlan:
        return {
            "acceptance_codes": list(section.acceptance_codes),
            "checks": [_quality_check_mapping(item) for item in section.checks],
            "evidence_refs": list(section.evidence_refs),
            "execution_state": section.execution_state.value,
            "professional_review_codes": list(section.professional_review_codes),
            "section": BlueprintSection.QUALITY_PLAN.value,
        }
    if type(section) is DeploymentPlan:
        return {
            "acceptance_state": section.acceptance_state.value,
            "artifact_codes": list(section.artifact_codes),
            "authority": section.authority.value,
            "delivery_target_code": section.delivery_target_code,
            "evidence_refs": list(section.evidence_refs),
            "execution_state": section.execution_state.value,
            "precondition_codes": list(section.precondition_codes),
            "provider_selection_code": section.provider_selection_code,
            "rollback_codes": list(section.rollback_codes),
            "section": BlueprintSection.DEPLOYMENT_PLAN.value,
            "verification_codes": list(section.verification_codes),
        }
    raise ProjectBlueprintError("blueprint contains an unsupported section record")


def _mapping(blueprint: ProjectBlueprint) -> dict[str, object]:
    return {
        "blueprint_id": blueprint.blueprint_id,
        "evidence_refs": list(blueprint.evidence_refs),
        "ready_for_implementation": blueprint.ready_for_implementation,
        "schema_version": blueprint.schema_version,
        "sections": [_section_mapping(item) for item in blueprint.sections],
        "source": _source_mapping(blueprint.source),
    }


def render_project_blueprint(blueprint: ProjectBlueprint) -> bytes:
    """Render one recomputable blueprint to canonical UTF-8 JSON bytes."""

    if type(blueprint) is not ProjectBlueprint:
        raise TypeError("blueprint must be an exact ProjectBlueprint")
    if generate_project_blueprint(blueprint.source.intent_decision) != blueprint:
        raise ProjectBlueprintError(
            "project blueprint does not match the recomputed derived record"
        )
    try:
        rendered = canonical_json_bytes(_mapping(blueprint))
    except SchemaError as error:
        raise ProjectBlueprintError(f"project blueprint cannot be encoded: {error}") from error
    if len(rendered) > MAX_PROJECT_BLUEPRINT_BYTES:
        raise ProjectBlueprintError("rendered project blueprint exceeds its byte bound")
    return rendered


def render_project_blueprint_markdown(blueprint: ProjectBlueprint) -> bytes:
    """Render a deterministic, non-normative Markdown projection."""

    render_project_blueprint(blueprint)
    lines = [
        "# Project Blueprint",
        "",
        f"- Blueprint ID: `{blueprint.blueprint_id}`",
        f"- P3-A source SHA-256: `{blueprint.source.intent_decision_sha256}`",
        "- Ready for implementation: `false`",
        "",
    ]
    for section_name, section in zip(BlueprintSection, blueprint.sections):
        lines.extend(
            (
                f"## {section_name.value}",
                "",
                "```json",
                canonical_json_bytes(_section_mapping(section)).decode("utf-8").rstrip("\n"),
                "```",
                "",
            )
        )
    rendered = "\n".join(lines).encode("utf-8")
    if len(rendered) > MAX_PROJECT_BLUEPRINT_MARKDOWN_BYTES:
        raise ProjectBlueprintError("rendered project-blueprint Markdown exceeds its byte bound")
    return rendered


def _closed_mapping(
    value: object, fields: frozenset[str], label: str
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProjectBlueprintError(f"{label} must be an object")
    keys = set(value)
    if any(type(key) is not str for key in keys):
        raise ProjectBlueprintError(f"{label} field names must be strings")
    unknown = sorted(keys - fields)
    missing = sorted(fields - keys)
    if unknown:
        raise ProjectBlueprintError(f"{label} contains unknown fields: {', '.join(unknown)}")
    if missing:
        raise ProjectBlueprintError(f"{label} is missing fields: {', '.join(missing)}")
    return value


def _parse_codes(
    value: object,
    label: str,
    maximum: int = _MAX_ITEMS,
) -> tuple[str, ...]:
    return tuple(
        _code(item, f"{label}[{index}]")
        for index, item in enumerate(_sequence(value, label, maximum))
    )


def _parse_refs(
    value: object, label: str, maximum: int = _MAX_REFERENCES_PER_ITEM
) -> tuple[str, ...]:
    return tuple(
        _reference(item, f"{label}[{index}]")
        for index, item in enumerate(_sequence(value, label, maximum))
    )


def _parse_task(value: object, label: str) -> BlueprintTask:
    item = _closed_mapping(
        value,
        frozenset({"action_code", "depends_on", "output_code", "phase", "task_id"}),
        label,
    )
    return BlueprintTask(
        task_id=_code(item["task_id"], f"{label}.task_id"),
        phase=_enum_value(TaskPhase, item["phase"], f"{label}.phase"),  # type: ignore[arg-type]
        action_code=_code(item["action_code"], f"{label}.action_code"),
        output_code=_code(item["output_code"], f"{label}.output_code"),
        depends_on=_parse_codes(item["depends_on"], f"{label}.depends_on", 8),
    )


def _parse_quality_check(value: object, label: str) -> QualityCheck:
    item = _closed_mapping(
        value,
        frozenset(
            {
                "check_id",
                "check_kind",
                "evidence_requirement_codes",
                "expected_result_code",
            }
        ),
        label,
    )
    return QualityCheck(
        check_id=_code(item["check_id"], f"{label}.check_id"),
        check_kind=_code(item["check_kind"], f"{label}.check_kind"),
        expected_result_code=_code(
            item["expected_result_code"], f"{label}.expected_result_code"
        ),
        evidence_requirement_codes=_parse_codes(
            item["evidence_requirement_codes"],
            f"{label}.evidence_requirement_codes",
        ),
    )


def _parse_section(value: object, index: int) -> object:
    label = f"sections[{index}]"
    if not isinstance(value, Mapping):
        raise ProjectBlueprintError(f"{label} must be an object")
    expected_section = tuple(BlueprintSection)[index]
    if value.get("section") != expected_section.value:
        raise ProjectBlueprintError("sections use the wrong name or order")
    if expected_section is BlueprintSection.PROJECT_BRIEF:
        item = _closed_mapping(
            value,
            frozenset(
                {
                    "assumption_decision_ids",
                    "constraint_codes",
                    "evidence_refs",
                    "goal_codes",
                    "project_type",
                    "section",
                    "target_platform",
                    "unresolved_codes",
                    "user_persona",
                }
            ),
            label,
        )
        return ProjectBrief(
            project_type=_code(item["project_type"], f"{label}.project_type"),
            target_platform=_code(item["target_platform"], f"{label}.target_platform"),
            user_persona=_code(item["user_persona"], f"{label}.user_persona"),
            goal_codes=_parse_codes(item["goal_codes"], f"{label}.goal_codes"),
            constraint_codes=_parse_codes(
                item["constraint_codes"], f"{label}.constraint_codes"
            ),
            assumption_decision_ids=_parse_codes(
                item["assumption_decision_ids"], f"{label}.assumption_decision_ids"
            ),
            unresolved_codes=_parse_codes(
                item["unresolved_codes"], f"{label}.unresolved_codes"
            ),
            evidence_refs=_parse_refs(
                item["evidence_refs"], f"{label}.evidence_refs", _MAX_REFERENCES
            ),
        )
    if expected_section is BlueprintSection.PRODUCT_PLAN:
        item = _closed_mapping(
            value,
            frozenset(
                {
                    "assumption_decision_ids",
                    "capability_codes",
                    "evidence_refs",
                    "milestone_codes",
                    "outcome_codes",
                    "section",
                    "unresolved_codes",
                }
            ),
            label,
        )
        return ProductPlan(
            outcome_codes=_parse_codes(item["outcome_codes"], f"{label}.outcome_codes"),
            capability_codes=_parse_codes(
                item["capability_codes"], f"{label}.capability_codes"
            ),
            milestone_codes=_parse_codes(
                item["milestone_codes"], f"{label}.milestone_codes"
            ),
            assumption_decision_ids=_parse_codes(
                item["assumption_decision_ids"], f"{label}.assumption_decision_ids"
            ),
            unresolved_codes=_parse_codes(
                item["unresolved_codes"], f"{label}.unresolved_codes"
            ),
            evidence_refs=_parse_refs(
                item["evidence_refs"], f"{label}.evidence_refs", _MAX_REFERENCES
            ),
        )
    if expected_section is BlueprintSection.UX_FLOW:
        item = _closed_mapping(
            value,
            frozenset(
                {
                    "accessibility_required",
                    "actor_code",
                    "assumption_decision_ids",
                    "entry_code",
                    "evidence_refs",
                    "exit_code",
                    "section",
                    "step_codes",
                    "unresolved_codes",
                }
            ),
            label,
        )
        return UXFlow(
            actor_code=_code(item["actor_code"], f"{label}.actor_code"),
            entry_code=_code(item["entry_code"], f"{label}.entry_code"),
            step_codes=_parse_codes(item["step_codes"], f"{label}.step_codes"),
            exit_code=_code(item["exit_code"], f"{label}.exit_code"),
            accessibility_required=item["accessibility_required"],
            assumption_decision_ids=_parse_codes(
                item["assumption_decision_ids"], f"{label}.assumption_decision_ids"
            ),
            unresolved_codes=_parse_codes(
                item["unresolved_codes"], f"{label}.unresolved_codes"
            ),
            evidence_refs=_parse_refs(
                item["evidence_refs"], f"{label}.evidence_refs", _MAX_REFERENCES
            ),
        )
    if expected_section is BlueprintSection.ARCHITECTURE:
        item = _closed_mapping(
            value,
            frozenset(
                {
                    "architecture_code",
                    "assumption_decision_ids",
                    "boundary_codes",
                    "component_codes",
                    "data_flow_codes",
                    "evidence_refs",
                    "external_dependency_code",
                    "section",
                    "unresolved_codes",
                }
            ),
            label,
        )
        return ArchitecturePlan(
            architecture_code=_code(
                item["architecture_code"], f"{label}.architecture_code"
            ),
            component_codes=_parse_codes(
                item["component_codes"], f"{label}.component_codes"
            ),
            boundary_codes=_parse_codes(
                item["boundary_codes"], f"{label}.boundary_codes"
            ),
            data_flow_codes=_parse_codes(
                item["data_flow_codes"], f"{label}.data_flow_codes"
            ),
            external_dependency_code=_code(
                item["external_dependency_code"],
                f"{label}.external_dependency_code",
            ),
            assumption_decision_ids=_parse_codes(
                item["assumption_decision_ids"], f"{label}.assumption_decision_ids"
            ),
            unresolved_codes=_parse_codes(
                item["unresolved_codes"], f"{label}.unresolved_codes"
            ),
            evidence_refs=_parse_refs(
                item["evidence_refs"], f"{label}.evidence_refs", _MAX_REFERENCES
            ),
        )
    if expected_section is BlueprintSection.STACK_DECISION:
        item = _closed_mapping(
            value,
            frozenset(
                {
                    "architecture_requirement_code",
                    "capability_codes",
                    "evidence_refs",
                    "provider_selection_code",
                    "rationale_codes",
                    "section",
                    "selected_candidate_id",
                    "state",
                }
            ),
            label,
        )
        return StackDecisionPlan(
            state=_enum_value(
                StackEvidenceState, item["state"], f"{label}.state"
            ),  # type: ignore[arg-type]
            selected_candidate_id=item["selected_candidate_id"],
            architecture_requirement_code=_code(
                item["architecture_requirement_code"],
                f"{label}.architecture_requirement_code",
            ),
            capability_codes=_parse_codes(
                item["capability_codes"], f"{label}.capability_codes"
            ),
            provider_selection_code=_code(
                item["provider_selection_code"], f"{label}.provider_selection_code"
            ),
            rationale_codes=_parse_codes(
                item["rationale_codes"], f"{label}.rationale_codes"
            ),
            evidence_refs=_parse_refs(
                item["evidence_refs"], f"{label}.evidence_refs", _MAX_REFERENCES
            ),
        )
    if expected_section is BlueprintSection.TASK_GRAPH:
        item = _closed_mapping(
            value,
            frozenset(
                {
                    "entry_task_ids",
                    "evidence_refs",
                    "section",
                    "tasks",
                    "terminal_task_ids",
                }
            ),
            label,
        )
        return TaskGraph(
            tasks=tuple(
                _parse_task(task, f"{label}.tasks[{task_index}]")
                for task_index, task in enumerate(
                    _sequence(item["tasks"], f"{label}.tasks", _MAX_TASKS)
                )
            ),
            entry_task_ids=_parse_codes(
                item["entry_task_ids"], f"{label}.entry_task_ids", _MAX_TASKS
            ),
            terminal_task_ids=_parse_codes(
                item["terminal_task_ids"], f"{label}.terminal_task_ids", _MAX_TASKS
            ),
            evidence_refs=_parse_refs(
                item["evidence_refs"], f"{label}.evidence_refs", _MAX_REFERENCES
            ),
        )
    if expected_section is BlueprintSection.QUALITY_PLAN:
        item = _closed_mapping(
            value,
            frozenset(
                {
                    "acceptance_codes",
                    "checks",
                    "evidence_refs",
                    "execution_state",
                    "professional_review_codes",
                    "section",
                }
            ),
            label,
        )
        return QualityPlan(
            checks=tuple(
                _parse_quality_check(check, f"{label}.checks[{check_index}]")
                for check_index, check in enumerate(
                    _sequence(item["checks"], f"{label}.checks", _MAX_ITEMS)
                )
            ),
            acceptance_codes=_parse_codes(
                item["acceptance_codes"], f"{label}.acceptance_codes"
            ),
            professional_review_codes=_parse_codes(
                item["professional_review_codes"],
                f"{label}.professional_review_codes",
            ),
            execution_state=_enum_value(
                ExecutionState,
                item["execution_state"],
                f"{label}.execution_state",
            ),  # type: ignore[arg-type]
            evidence_refs=_parse_refs(
                item["evidence_refs"], f"{label}.evidence_refs", _MAX_REFERENCES
            ),
        )
    item = _closed_mapping(
        value,
        frozenset(
            {
                "acceptance_state",
                "artifact_codes",
                "authority",
                "delivery_target_code",
                "evidence_refs",
                "execution_state",
                "precondition_codes",
                "provider_selection_code",
                "rollback_codes",
                "section",
                "verification_codes",
            }
        ),
        label,
    )
    return DeploymentPlan(
        delivery_target_code=_code(
            item["delivery_target_code"], f"{label}.delivery_target_code"
        ),
        artifact_codes=_parse_codes(
            item["artifact_codes"], f"{label}.artifact_codes"
        ),
        precondition_codes=_parse_codes(
            item["precondition_codes"], f"{label}.precondition_codes"
        ),
        rollback_codes=_parse_codes(
            item["rollback_codes"], f"{label}.rollback_codes"
        ),
        verification_codes=_parse_codes(
            item["verification_codes"], f"{label}.verification_codes"
        ),
        provider_selection_code=_code(
            item["provider_selection_code"], f"{label}.provider_selection_code"
        ),
        execution_state=_enum_value(
            ExecutionState, item["execution_state"], f"{label}.execution_state"
        ),  # type: ignore[arg-type]
        acceptance_state=_enum_value(
            ExecutionState, item["acceptance_state"], f"{label}.acceptance_state"
        ),  # type: ignore[arg-type]
        authority=_enum_value(
            DeploymentAuthority, item["authority"], f"{label}.authority"
        ),  # type: ignore[arg-type]
        evidence_refs=_parse_refs(
            item["evidence_refs"], f"{label}.evidence_refs", _MAX_REFERENCES
        ),
    )


def _parse_mapping(value: object) -> ProjectBlueprint:
    item = _closed_mapping(
        value,
        frozenset(
            {
                "blueprint_id",
                "evidence_refs",
                "ready_for_implementation",
                "schema_version",
                "sections",
                "source",
            }
        ),
        "project_blueprint",
    )
    if item["schema_version"] != PROJECT_BLUEPRINT_SCHEMA_VERSION:
        raise ProjectBlueprintError("unsupported project-blueprint schema_version")
    source_item = _closed_mapping(
        item["source"],
        frozenset({"intent_decision", "intent_decision_sha256"}),
        "source",
    )
    try:
        source_record = parse_intent_decision_result(
            canonical_json_bytes(source_item["intent_decision"])
        )
    except (SchemaError, TypeError, ValueError) as error:
        raise ProjectBlueprintError("embedded P3-A source is invalid") from error
    source = BlueprintSource(
        intent_decision_sha256=source_item["intent_decision_sha256"],
        intent_decision=source_record,
    )
    raw_sections = _sequence(item["sections"], "sections", len(_SECTION_TYPES))
    if len(raw_sections) != len(_SECTION_TYPES):
        raise ProjectBlueprintError("sections must contain exactly eight records")
    return ProjectBlueprint(
        schema_version=PROJECT_BLUEPRINT_SCHEMA_VERSION,
        blueprint_id=_code(item["blueprint_id"], "blueprint_id"),
        source=source,
        ready_for_implementation=item["ready_for_implementation"],
        sections=tuple(
            _parse_section(section, index)
            for index, section in enumerate(raw_sections)
        ),
        evidence_refs=_parse_refs(
            item["evidence_refs"], "evidence_refs", _MAX_REFERENCES
        ),
    )


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProjectBlueprintError(
                "project blueprint contains duplicate object fields"
            )
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ProjectBlueprintError(
        f"project blueprint contains unsupported JSON constant: {value}"
    )


def parse_project_blueprint(
    payload: bytes | bytearray | memoryview,
) -> ProjectBlueprint:
    """Parse only bounded canonical UTF-8 JSON bytes into an immutable blueprint."""

    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise ProjectBlueprintError("project-blueprint payload must be bytes")
    raw = bytes(payload)
    if not raw or len(raw) > MAX_PROJECT_BLUEPRINT_BYTES:
        raise ProjectBlueprintError(
            "project-blueprint payload must use bounded non-empty bytes"
        )
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicates,
            parse_constant=_reject_constant,
        )
    except ProjectBlueprintError:
        raise
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
        TypeError,
        RecursionError,
    ) as error:
        raise ProjectBlueprintError(
            "project blueprint is not valid UTF-8 JSON"
        ) from error
    blueprint = _parse_mapping(value)
    if render_project_blueprint(blueprint) != raw:
        raise ProjectBlueprintError("project-blueprint JSON is not canonical")
    return blueprint


__all__ = [
    "ArchitecturePlan",
    "BlueprintConfirmationRequired",
    "BlueprintSection",
    "BlueprintSource",
    "BlueprintTask",
    "DeploymentAuthority",
    "DeploymentPlan",
    "ExecutionState",
    "MAX_PROJECT_BLUEPRINT_BYTES",
    "MAX_PROJECT_BLUEPRINT_MARKDOWN_BYTES",
    "PROJECT_BLUEPRINT_SCHEMA_VERSION",
    "ProductPlan",
    "ProjectBlueprint",
    "ProjectBlueprintError",
    "ProjectBrief",
    "QualityCheck",
    "QualityPlan",
    "StackDecisionPlan",
    "StackEvidenceState",
    "TaskGraph",
    "TaskPhase",
    "UXFlow",
    "generate_project_blueprint",
    "parse_project_blueprint",
    "render_project_blueprint",
    "render_project_blueprint_markdown",
]
