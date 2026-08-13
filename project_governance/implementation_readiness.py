"""Closed, source-complete P3-C implementation-readiness resolution."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from pathlib import PurePosixPath
import re
from typing import Any, Mapping
import unicodedata

from .domain_pack import (
    DOMAIN_PACK_SCHEMA_VERSION,
    MAX_PACKS,
    Comparator,
    DomainApplicability,
    DomainCode,
    DomainPack,
    DomainPackRegistry,
    GatePhase,
    GateRouteEvidence,
    PerformanceProfile,
    ProfessionalGateRequirement,
    TestProfile,
)
from .intake import (
    NeedEvidenceLevel,
    ProjectIntake,
    StopState,
    parse_intake,
    render_intake,
)
from .intake_routing import RoutingDisposition
from .intake_ux import (
    DomainApplicabilityEvidence,
    build_guided_intake_view,
)
from .project_blueprint import (
    ProjectBlueprint,
    ProjectBlueprintError,
    generate_project_blueprint,
    parse_project_blueprint,
    render_project_blueprint,
)
from .stack_decision import (
    CandidateKind,
    DimensionAssessment,
    RecommendationDisposition,
    StackCandidate,
    StackDecision,
    StackDimension,
    score_stack_candidates,
)
from .storage import SchemaError, canonical_json_bytes


IMPLEMENTATION_READINESS_SCHEMA_VERSION = "1.0"
MAX_IMPLEMENTATION_READINESS_BYTES = 512 * 1024
MAX_BINDING_REFERENCES = 32
MAX_COMPATIBILITY_RECORDS = 16
MAX_EVIDENCE_REFERENCES = 512

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


class ImplementationReadinessError(ValueError):
    """Raised when a P3-C source bundle or result violates its contract."""


class _DomainEvidenceRequired(ImplementationReadinessError):
    """Internal signal for a valid but incomplete domain-evidence bundle."""


class ReadinessState(str, Enum):
    SOURCE_BINDING_REQUIRED = "source-binding-required"
    OWNER_CONFIRMATION_REQUIRED = "owner-confirmation-required"
    INTAKE_EVIDENCE_REQUIRED = "intake-evidence-required"
    STACK_EVIDENCE_REQUIRED = "stack-evidence-required"
    STACK_CORRECTION_REQUIRED = "stack-correction-required"
    DOMAIN_EVIDENCE_REQUIRED = "domain-evidence-required"
    READY_FOR_MATERIALIZATION_PREVIEW = "ready-for-materialization-preview"


class ImplementationAuthority(str, Enum):
    NOT_AUTHORIZED = "not-authorized"


def _scalar(value: object, label: str, *, maximum: int = 240) -> str:
    if type(value) is not str or not value or len(value) > maximum:
        raise ImplementationReadinessError(f"{label} must be bounded non-empty text")
    if unicodedata.normalize("NFC", value) != value:
        raise ImplementationReadinessError(f"{label} must use NFC Unicode")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        raise ImplementationReadinessError(f"{label} contains control characters")
    if _SENSITIVE.search(value):
        raise ImplementationReadinessError(f"{label} contains a sensitive-value pattern")
    return value


def _code(value: object, label: str) -> str:
    text = _scalar(value, label, maximum=80)
    if not _CODE.fullmatch(text):
        raise ImplementationReadinessError(f"{label} must be a bounded stable code")
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
    text = _scalar(value, label)
    if _CODE.fullmatch(text) or _safe_relative_path(text):
        return text
    raise ImplementationReadinessError(
        f"{label} must be a stable code or contained project-relative path"
    )


def _tuple(value: object, label: str, maximum: int) -> tuple[object, ...]:
    if type(value) is not tuple or len(value) > maximum:
        raise ImplementationReadinessError(f"{label} must be a bounded immutable tuple")
    return value


def _codes(
    value: object, label: str, maximum: int, *, allow_empty: bool = True
) -> tuple[str, ...]:
    items = _tuple(value, label, maximum)
    if not allow_empty and not items:
        raise ImplementationReadinessError(f"{label} must not be empty")
    result = tuple(_code(item, f"{label}[{index}]") for index, item in enumerate(items))
    if result != tuple(sorted(set(result))):
        raise ImplementationReadinessError(f"{label} must use canonical unique order")
    return result


def _references(
    value: object, label: str, maximum: int, *, allow_empty: bool = True
) -> tuple[str, ...]:
    items = _tuple(value, label, maximum)
    if not allow_empty and not items:
        raise ImplementationReadinessError(f"{label} must not be empty")
    result = tuple(
        _reference(item, f"{label}[{index}]") for index, item in enumerate(items)
    )
    if result != tuple(sorted(set(result))):
        raise ImplementationReadinessError(f"{label} must use canonical unique order")
    return result


def _digest(value: object, label: str) -> str:
    if type(value) is not str or not _SHA256.fullmatch(value):
        raise ImplementationReadinessError(f"{label} must be a lowercase SHA-256 digest")
    return value


@dataclass(frozen=True)
class IntentIntakeBinding:
    """Explicit shared evidence binding between the P3-A intent and P2 intake."""

    intent_id: str
    intake_id: str
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self) is not IntentIntakeBinding:
            raise ImplementationReadinessError(
                "IntentIntakeBinding subclasses are not accepted"
            )
        _code(self.intent_id, "intent_intake_binding.intent_id")
        _code(self.intake_id, "intent_intake_binding.intake_id")
        _references(
            self.evidence_refs,
            "intent_intake_binding.evidence_refs",
            MAX_BINDING_REFERENCES,
            allow_empty=False,
        )


@dataclass(frozen=True)
class ArchitectureCompatibilityEvidence:
    """Evidence-bound compatibility claim; no string similarity is inferred."""

    candidate_id: str
    candidate_architecture_code: str
    blueprint_architecture_code: str
    architecture_requirement_code: str
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self) is not ArchitectureCompatibilityEvidence:
            raise ImplementationReadinessError(
                "ArchitectureCompatibilityEvidence subclasses are not accepted"
            )
        _code(self.candidate_id, "architecture_compatibility.candidate_id")
        _code(
            self.candidate_architecture_code,
            "architecture_compatibility.candidate_architecture_code",
        )
        _code(
            self.blueprint_architecture_code,
            "architecture_compatibility.blueprint_architecture_code",
        )
        _code(
            self.architecture_requirement_code,
            "architecture_compatibility.architecture_requirement_code",
        )
        _references(
            self.evidence_refs,
            "architecture_compatibility.evidence_refs",
            MAX_BINDING_REFERENCES,
            allow_empty=False,
        )


@dataclass(frozen=True)
class ImplementationReadinessSource:
    blueprint_sha256: str
    blueprint: ProjectBlueprint
    intake_sha256: str
    intake: ProjectIntake
    intent_intake_binding: IntentIntakeBinding | None
    stack_candidates: tuple[StackCandidate, ...]
    domain_pack_registry: DomainPackRegistry | None
    applicable_pack_ids: tuple[str, ...]
    applicability_evidence: DomainApplicabilityEvidence | None
    architecture_compatibility: tuple[ArchitectureCompatibilityEvidence, ...]

    def __post_init__(self) -> None:
        if type(self) is not ImplementationReadinessSource:
            raise ImplementationReadinessError(
                "ImplementationReadinessSource subclasses are not accepted"
            )
        if type(self.blueprint) is not ProjectBlueprint:
            raise ImplementationReadinessError("blueprint must be an exact ProjectBlueprint")
        if type(self.intake) is not ProjectIntake:
            raise ImplementationReadinessError("intake must be an exact ProjectIntake")
        try:
            blueprint_bytes = render_project_blueprint(self.blueprint)
            intake_bytes = render_intake(self.intake)
        except (TypeError, ValueError) as error:
            raise ImplementationReadinessError("source records are not canonical") from error
        _digest(self.blueprint_sha256, "blueprint_sha256")
        _digest(self.intake_sha256, "intake_sha256")
        if self.blueprint_sha256 != hashlib.sha256(blueprint_bytes).hexdigest():
            raise ImplementationReadinessError("blueprint_sha256 does not bind blueprint")
        if self.intake_sha256 != hashlib.sha256(intake_bytes).hexdigest():
            raise ImplementationReadinessError("intake_sha256 does not bind intake")
        if self.intent_intake_binding is not None and type(
            self.intent_intake_binding
        ) is not IntentIntakeBinding:
            raise ImplementationReadinessError(
                "intent_intake_binding must be an exact IntentIntakeBinding or null"
            )
        candidates = _tuple(self.stack_candidates, "stack_candidates", 16)
        if any(type(item) is not StackCandidate for item in candidates):
            raise ImplementationReadinessError(
                "stack_candidates must contain exact StackCandidate records"
            )
        candidate_ids = tuple(item.candidate_id for item in candidates)
        if candidate_ids != tuple(sorted(set(candidate_ids))):
            raise ImplementationReadinessError(
                "stack_candidates must use canonical unique candidate_id order"
            )
        if self.domain_pack_registry is not None and type(
            self.domain_pack_registry
        ) is not DomainPackRegistry:
            raise ImplementationReadinessError(
                "domain_pack_registry must be an exact DomainPackRegistry or null"
            )
        _codes(self.applicable_pack_ids, "applicable_pack_ids", MAX_PACKS)
        if self.applicability_evidence is not None and type(
            self.applicability_evidence
        ) is not DomainApplicabilityEvidence:
            raise ImplementationReadinessError(
                "applicability_evidence must be exact DomainApplicabilityEvidence or null"
            )
        compatibility = _tuple(
            self.architecture_compatibility,
            "architecture_compatibility",
            MAX_COMPATIBILITY_RECORDS,
        )
        if any(type(item) is not ArchitectureCompatibilityEvidence for item in compatibility):
            raise ImplementationReadinessError(
                "architecture_compatibility must contain exact evidence records"
            )
        compatibility_ids = tuple(item.candidate_id for item in compatibility)
        if compatibility_ids != tuple(sorted(set(compatibility_ids))):
            raise ImplementationReadinessError(
                "architecture_compatibility must use canonical unique candidate_id order"
            )


@dataclass(frozen=True)
class ImplementationReadiness:
    schema_version: str
    readiness_id: str
    source: ImplementationReadinessSource
    state: ReadinessState
    selected_stack_candidate_id: str | None
    selected_architecture_code: str | None
    professional_gate_requirements: tuple[GateRouteEvidence, ...]
    ready_for_materialization_preview: bool
    implementation_authority: ImplementationAuthority
    blocker_codes: tuple[str, ...]
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self) is not ImplementationReadiness:
            raise ImplementationReadinessError(
                "ImplementationReadiness subclasses are not accepted"
            )
        if self.schema_version != IMPLEMENTATION_READINESS_SCHEMA_VERSION:
            raise ImplementationReadinessError(
                "unsupported implementation-readiness schema_version"
            )
        _code(self.readiness_id, "readiness_id")
        if type(self.source) is not ImplementationReadinessSource:
            raise ImplementationReadinessError(
                "source must be an exact ImplementationReadinessSource"
            )
        if type(self.state) is not ReadinessState:
            raise ImplementationReadinessError("state must be an exact ReadinessState")
        if self.selected_stack_candidate_id is not None:
            _code(self.selected_stack_candidate_id, "selected_stack_candidate_id")
        if self.selected_architecture_code is not None:
            _code(self.selected_architecture_code, "selected_architecture_code")
        gates = _tuple(
            self.professional_gate_requirements,
            "professional_gate_requirements",
            MAX_PACKS * 32,
        )
        if any(type(item) is not GateRouteEvidence for item in gates):
            raise ImplementationReadinessError(
                "professional_gate_requirements must contain exact GateRouteEvidence records"
            )
        gate_keys = tuple((item.pack_id, item.gate_id, item.reason_code) for item in gates)
        if gate_keys != tuple(sorted(set(gate_keys))):
            raise ImplementationReadinessError(
                "professional_gate_requirements must use canonical unique order"
            )
        if type(self.ready_for_materialization_preview) is not bool:
            raise ImplementationReadinessError(
                "ready_for_materialization_preview must be a boolean"
            )
        if type(self.implementation_authority) is not ImplementationAuthority:
            raise ImplementationReadinessError(
                "implementation_authority must be exact ImplementationAuthority"
            )
        if self.implementation_authority is not ImplementationAuthority.NOT_AUTHORIZED:
            raise ImplementationReadinessError(
                "P3-C cannot grant implementation authority"
            )
        _codes(self.blocker_codes, "blocker_codes", 32)
        _references(self.evidence_refs, "evidence_refs", MAX_EVIDENCE_REFERENCES)
        expected = _derive(self.source)
        actual = {
            "state": self.state,
            "selected_stack_candidate_id": self.selected_stack_candidate_id,
            "selected_architecture_code": self.selected_architecture_code,
            "professional_gate_requirements": self.professional_gate_requirements,
            "ready_for_materialization_preview": self.ready_for_materialization_preview,
            "implementation_authority": self.implementation_authority,
            "blocker_codes": self.blocker_codes,
            "evidence_refs": self.evidence_refs,
        }
        if actual != expected:
            raise ImplementationReadinessError(
                "implementation readiness fields must match recomputed source evidence"
            )


def _all_source_refs(source: ImplementationReadinessSource) -> tuple[str, ...]:
    refs = set(source.blueprint.evidence_refs)
    refs.update(item.reference_id for item in source.intake.evidence)
    if source.intent_intake_binding is not None:
        refs.update(source.intent_intake_binding.evidence_refs)
    for candidate in source.stack_candidates:
        refs.update(candidate.evidence_refs)
    if source.applicability_evidence is not None:
        refs.update(source.applicability_evidence.evidence_refs)
    for item in source.architecture_compatibility:
        refs.update(item.evidence_refs)
    if source.domain_pack_registry is not None:
        for pack in source.domain_pack_registry.packs:
            refs.update(pack.source_refs)
            for profile in pack.test_profiles:
                refs.update(profile.evidence_refs)
            for profile in pack.performance_profiles:
                refs.add(profile.baseline_ref)
                refs.update(profile.evidence_refs)
            for gate in pack.professional_gates:
                refs.update(gate.evidence_refs)
    return tuple(sorted(refs))


def _binding_blockers(source: ImplementationReadinessSource) -> tuple[str, ...]:
    binding = source.intent_intake_binding
    if binding is None:
        return ("binding.intent-intake-missing",)
    intent = source.blueprint.source.intent_decision
    intake_refs = {item.reference_id for item in source.intake.evidence}
    shared_refs = set(intent.evidence_refs).intersection(intake_refs)
    blockers: set[str] = set()
    if binding.intent_id != intent.intent_id:
        blockers.add("binding.intent-id-mismatch")
    if binding.intake_id != source.intake.intake_id:
        blockers.add("binding.intake-id-mismatch")
    if not set(binding.evidence_refs).issubset(shared_refs):
        blockers.add("binding.shared-evidence-missing")
    return tuple(sorted(blockers))


def _compatibility_source_blockers(
    source: ImplementationReadinessSource,
) -> tuple[str, ...]:
    candidates = {item.candidate_id: item for item in source.stack_candidates}
    intake_refs = {item.reference_id for item in source.intake.evidence}
    blueprint_refs = set(source.blueprint.architecture.evidence_refs).intersection(
        source.blueprint.stack_decision.evidence_refs
    )
    blockers: set[str] = set()
    for evidence in source.architecture_compatibility:
        candidate = candidates.get(evidence.candidate_id)
        if candidate is None:
            raise ImplementationReadinessError(
                "architecture compatibility references an unknown stack candidate"
            )
        if evidence.candidate_architecture_code != candidate.architecture_code:
            blockers.add("binding.candidate-architecture-mismatch")
        if (
            evidence.blueprint_architecture_code
            != source.blueprint.architecture.architecture_code
        ):
            blockers.add("binding.blueprint-architecture-mismatch")
        if (
            evidence.architecture_requirement_code
            != source.blueprint.stack_decision.architecture_requirement_code
        ):
            blockers.add("binding.architecture-requirement-mismatch")
        bound_refs = intake_refs.intersection(candidate.evidence_refs, blueprint_refs)
        if not set(evidence.evidence_refs).issubset(bound_refs):
            blockers.add("binding.architecture-evidence-missing")
    return tuple(sorted(blockers))


def _architecture_blockers(
    source: ImplementationReadinessSource,
    candidate: StackCandidate,
) -> tuple[str, ...]:
    matches = tuple(
        item
        for item in source.architecture_compatibility
        if item.candidate_id == candidate.candidate_id
    )
    if len(matches) != 1:
        return ("binding.architecture-compatibility-missing",)
    return ()


def _domain_projection(
    source: ImplementationReadinessSource,
    stack_decision: StackDecision,
) -> tuple[tuple[str, ...], tuple[GateRouteEvidence, ...]]:
    registry = source.domain_pack_registry
    evidence = source.applicability_evidence
    if registry is None or evidence is None:
        raise _DomainEvidenceRequired("domain source records are incomplete")
    intake_refs = {item.reference_id for item in source.intake.evidence}
    if not set(evidence.evidence_refs).issubset(intake_refs):
        raise _DomainEvidenceRequired(
            "domain applicability evidence is not bound to intake evidence"
        )
    supported_domains = {item.value for item in DomainCode}
    if not set(evidence.domains).issubset(supported_domains):
        raise ImplementationReadinessError("domain applicability uses unsupported domains")

    direct: set[str] = set()
    for domain in evidence.domains:
        context = {
            "domain": domain,
            "project_mode": source.intake.project_mode.value,
            "purpose": source.intake.purpose.value,
            "risk_level": evidence.risk_level,
            "data_class": evidence.data_class,
        }
        direct.update(pack.pack_id for pack in registry.applicable(context))
    by_id = {pack.pack_id: pack for pack in registry.packs}
    expected = set(direct)
    pending = list(expected)
    while pending:
        pack_id = pending.pop()
        for dependency in by_id[pack_id].dependencies:
            if dependency not in expected:
                expected.add(dependency)
                pending.append(dependency)
    expected_ids = tuple(sorted(expected))
    if not expected_ids:
        raise _DomainEvidenceRequired("no applicable Domain Pack is evidenced")
    if source.applicable_pack_ids != expected_ids:
        if not source.applicable_pack_ids:
            raise _DomainEvidenceRequired(
                "applicable Domain Pack selection is missing"
            )
        raise ImplementationReadinessError(
            "applicable_pack_ids do not match recomputed applicability and dependency closure"
        )

    direct_ids = tuple(sorted(direct))
    view = build_guided_intake_view(
        source.intake,
        stack_decision=stack_decision,
        domain_pack_registry=registry,
        applicable_pack_ids=direct_ids,
        applicability_evidence=evidence,
    )
    if view.disposition is not RoutingDisposition.READY_FOR_PREVIEW:
        raise ImplementationReadinessError("guided intake remains nonterminal")
    if view.selected_stack_candidate_id != stack_decision.selected_candidate_id:
        raise ImplementationReadinessError("guided intake stack selection is stale")

    direct_gate_ids = tuple(
        sorted(
            {
                requirement.gate_id
                for pack_id in direct_ids
                for requirement in by_id[pack_id].professional_gates
            }
        )
    )
    if view.professional_gate_ids != direct_gate_ids:
        raise ImplementationReadinessError("guided intake professional Gate route is stale")

    routes = []
    for pack_id in expected_ids:
        pack = by_id[pack_id]
        routes.extend(
            GateRouteEvidence(
                pack_id=pack.pack_id,
                domain=pack.domain,
                gate_id=requirement.gate_id,
                reason_code=requirement.reason_code,
                phase=requirement.phase,
                required=requirement.required,
                owner_gate=requirement.owner_gate,
                evidence_refs=requirement.evidence_refs,
            )
            for requirement in pack.professional_gates
        )
    unique = {(item.pack_id, item.gate_id, item.reason_code): item for item in routes}
    gates = tuple(unique[key] for key in sorted(unique))
    return expected_ids, gates


def _projection(
    source: ImplementationReadinessSource,
    state: ReadinessState,
    blockers: tuple[str, ...],
    *,
    selected_candidate_id: str | None = None,
    selected_architecture_code: str | None = None,
    gates: tuple[GateRouteEvidence, ...] = (),
) -> dict[str, object]:
    return {
        "state": state,
        "selected_stack_candidate_id": selected_candidate_id,
        "selected_architecture_code": selected_architecture_code,
        "professional_gate_requirements": gates,
        "ready_for_materialization_preview": (
            state is ReadinessState.READY_FOR_MATERIALIZATION_PREVIEW
        ),
        "implementation_authority": ImplementationAuthority.NOT_AUTHORIZED,
        "blocker_codes": blockers,
        "evidence_refs": _all_source_refs(source),
    }


def _derive(source: ImplementationReadinessSource) -> dict[str, object]:
    if generate_project_blueprint(source.blueprint.source.intent_decision) != source.blueprint:
        return _projection(
            source,
            ReadinessState.SOURCE_BINDING_REQUIRED,
            ("binding.blueprint-recomputation-mismatch",),
        )
    binding_blockers = _binding_blockers(source)
    if binding_blockers:
        return _projection(
            source, ReadinessState.SOURCE_BINDING_REQUIRED, binding_blockers
        )
    compatibility_blockers = _compatibility_source_blockers(source)
    if compatibility_blockers:
        return _projection(
            source, ReadinessState.SOURCE_BINDING_REQUIRED, compatibility_blockers
        )

    open_human = tuple(
        item.decision_id
        for item in source.intake.decisions
        if item.resolution_state.value == "open" and item.disposition.value == "B"
    )
    if source.intake.stop_state is StopState.OWNER_GATE or open_human:
        return _projection(
            source,
            ReadinessState.OWNER_CONFIRMATION_REQUIRED,
            tuple(sorted({"owner.intake-confirmation-required", *open_human})),
        )
    open_intake = tuple(
        item.decision_id
        for item in source.intake.decisions
        if item.resolution_state.value == "open"
    )
    if source.intake.stop_state is not StopState.READY_FOR_PREVIEW or open_intake:
        return _projection(
            source,
            ReadinessState.INTAKE_EVIDENCE_REQUIRED,
            tuple(sorted({"intake.open-evidence-required", *open_intake})),
        )
    if not source.stack_candidates:
        return _projection(
            source,
            ReadinessState.STACK_EVIDENCE_REQUIRED,
            ("stack.candidates-required",),
        )

    decision = score_stack_candidates(source.intake, source.stack_candidates)
    if decision.disposition is RecommendationDisposition.OWNER_GATE:
        blockers = decision.unresolved_decision_ids or ("owner.stack-confirmation-required",)
        return _projection(
            source, ReadinessState.OWNER_CONFIRMATION_REQUIRED, tuple(sorted(blockers))
        )
    if decision.disposition is RecommendationDisposition.NEEDS_EVIDENCE:
        blockers = decision.correction_codes or ("stack.more-evidence-required",)
        return _projection(
            source, ReadinessState.STACK_EVIDENCE_REQUIRED, tuple(sorted(blockers))
        )
    if decision.disposition is RecommendationDisposition.CORRECTION:
        return _projection(
            source,
            ReadinessState.STACK_CORRECTION_REQUIRED,
            decision.correction_codes,
        )
    if decision.selected_candidate_id is None:
        return _projection(
            source,
            ReadinessState.STACK_EVIDENCE_REQUIRED,
            ("stack.selection-missing",),
        )
    selected = next(
        item
        for item in source.stack_candidates
        if item.candidate_id == decision.selected_candidate_id
    )
    architecture_blockers = _architecture_blockers(source, selected)
    if architecture_blockers:
        return _projection(
            source, ReadinessState.SOURCE_BINDING_REQUIRED, architecture_blockers
        )
    try:
        _, gates = _domain_projection(source, decision)
    except _DomainEvidenceRequired:
        return _projection(
            source,
            ReadinessState.DOMAIN_EVIDENCE_REQUIRED,
            ("domain.evidence-or-routing-incomplete",),
            selected_candidate_id=selected.candidate_id,
            selected_architecture_code=selected.architecture_code,
        )
    return _projection(
        source,
        ReadinessState.READY_FOR_MATERIALIZATION_PREVIEW,
        (),
        selected_candidate_id=selected.candidate_id,
        selected_architecture_code=selected.architecture_code,
        gates=gates,
    )


def resolve_implementation_readiness(
    blueprint: ProjectBlueprint,
    intake: ProjectIntake,
    *,
    intent_intake_binding: IntentIntakeBinding | None = None,
    stack_candidates: tuple[StackCandidate, ...] = (),
    domain_pack_registry: DomainPackRegistry | None = None,
    applicable_pack_ids: tuple[str, ...] = (),
    applicability_evidence: DomainApplicabilityEvidence | None = None,
    architecture_compatibility: tuple[ArchitectureCompatibilityEvidence, ...] = (),
    readiness_id: str | None = None,
) -> ImplementationReadiness:
    """Resolve whether a separate P3-D materialization preview may be planned."""

    if type(blueprint) is not ProjectBlueprint:
        raise TypeError("blueprint must be an exact ProjectBlueprint")
    if type(intake) is not ProjectIntake:
        raise TypeError("intake must be an exact ProjectIntake")
    source = ImplementationReadinessSource(
        blueprint_sha256=hashlib.sha256(render_project_blueprint(blueprint)).hexdigest(),
        blueprint=blueprint,
        intake_sha256=hashlib.sha256(render_intake(intake)).hexdigest(),
        intake=intake,
        intent_intake_binding=intent_intake_binding,
        stack_candidates=stack_candidates,
        domain_pack_registry=domain_pack_registry,
        applicable_pack_ids=applicable_pack_ids,
        applicability_evidence=applicability_evidence,
        architecture_compatibility=architecture_compatibility,
    )
    projection = _derive(source)
    identifier = readiness_id or f"readiness.{blueprint.blueprint_id}"
    return ImplementationReadiness(
        schema_version=IMPLEMENTATION_READINESS_SCHEMA_VERSION,
        readiness_id=_code(identifier, "readiness_id"),
        source=source,
        **projection,
    )


def _assessment_mapping(value: DimensionAssessment) -> dict[str, object]:
    return {
        "dimension": value.dimension.value,
        "evidence_refs": list(value.evidence_refs),
        "rationale_code": value.rationale_code,
        "score": value.score,
    }


def _candidate_mapping(value: StackCandidate) -> dict[str, object]:
    return {
        "architecture_code": value.architecture_code,
        "assessments": [_assessment_mapping(item) for item in value.assessments],
        "candidate_id": value.candidate_id,
        "candidate_kind": value.candidate_kind.value,
        "evidence_level": value.evidence_level.value,
        "evidence_refs": list(value.evidence_refs),
    }


def _pack_mapping(value: DomainPack) -> dict[str, object]:
    return {
        "applicability": {
            "data_classes": list(value.applicability.data_classes),
            "domains": list(value.applicability.domains),
            "project_modes": list(value.applicability.project_modes),
            "purposes": list(value.applicability.purposes),
            "risk_levels": list(value.applicability.risk_levels),
        },
        "dependencies": list(value.dependencies),
        "domain": value.domain.value,
        "pack_id": value.pack_id,
        "performance_profiles": [
            {
                "baseline_ref": item.baseline_ref,
                "comparator": item.comparator.value,
                "environment": item.environment,
                "evidence_refs": list(item.evidence_refs),
                "metric": item.metric,
                "profile_id": item.profile_id,
                "threshold": item.threshold,
                "tolerance": item.tolerance,
                "variance_policy": item.variance_policy,
                "workload": item.workload,
            }
            for item in value.performance_profiles
        ],
        "professional_gates": [
            {
                "evidence_refs": list(item.evidence_refs),
                "gate_id": item.gate_id,
                "owner_gate": item.owner_gate,
                "phase": item.phase.value,
                "reason_code": item.reason_code,
                "required": item.required,
            }
            for item in value.professional_gates
        ],
        "schema_version": value.schema_version,
        "source_refs": list(value.source_refs),
        "test_profiles": [
            {
                "evidence_refs": list(item.evidence_refs),
                "profile_id": item.profile_id,
                "required": item.required,
                "test_kind": item.test_kind,
            }
            for item in value.test_profiles
        ],
        "version": value.version,
    }


def _gate_mapping(value: GateRouteEvidence) -> dict[str, object]:
    return {
        "domain": value.domain.value,
        "evidence_refs": list(value.evidence_refs),
        "gate_id": value.gate_id,
        "owner_gate": value.owner_gate,
        "pack_id": value.pack_id,
        "phase": value.phase.value,
        "reason_code": value.reason_code,
        "required": value.required,
    }


def _source_mapping(source: ImplementationReadinessSource) -> dict[str, object]:
    return {
        "applicability_evidence": (
            {
                "data_class": source.applicability_evidence.data_class,
                "domains": list(source.applicability_evidence.domains),
                "evidence_refs": list(source.applicability_evidence.evidence_refs),
                "risk_level": source.applicability_evidence.risk_level,
            }
            if source.applicability_evidence is not None
            else None
        ),
        "applicable_pack_ids": list(source.applicable_pack_ids),
        "architecture_compatibility": [
            {
                "architecture_requirement_code": item.architecture_requirement_code,
                "blueprint_architecture_code": item.blueprint_architecture_code,
                "candidate_architecture_code": item.candidate_architecture_code,
                "candidate_id": item.candidate_id,
                "evidence_refs": list(item.evidence_refs),
            }
            for item in source.architecture_compatibility
        ],
        "blueprint": json.loads(render_project_blueprint(source.blueprint)),
        "blueprint_sha256": source.blueprint_sha256,
        "domain_pack_registry": (
            {
                "packs": [_pack_mapping(item) for item in source.domain_pack_registry.packs],
                "schema_version": source.domain_pack_registry.schema_version,
            }
            if source.domain_pack_registry is not None
            else None
        ),
        "intake": json.loads(render_intake(source.intake)),
        "intake_sha256": source.intake_sha256,
        "intent_intake_binding": (
            {
                "evidence_refs": list(source.intent_intake_binding.evidence_refs),
                "intake_id": source.intent_intake_binding.intake_id,
                "intent_id": source.intent_intake_binding.intent_id,
            }
            if source.intent_intake_binding is not None
            else None
        ),
        "stack_candidates": [_candidate_mapping(item) for item in source.stack_candidates],
    }


def _mapping(value: ImplementationReadiness) -> dict[str, object]:
    return {
        "blocker_codes": list(value.blocker_codes),
        "evidence_refs": list(value.evidence_refs),
        "implementation_authority": value.implementation_authority.value,
        "professional_gate_requirements": [
            _gate_mapping(item) for item in value.professional_gate_requirements
        ],
        "readiness_id": value.readiness_id,
        "ready_for_materialization_preview": value.ready_for_materialization_preview,
        "schema_version": value.schema_version,
        "selected_architecture_code": value.selected_architecture_code,
        "selected_stack_candidate_id": value.selected_stack_candidate_id,
        "source": _source_mapping(value.source),
        "state": value.state.value,
    }


def render_implementation_readiness(value: ImplementationReadiness) -> bytes:
    """Render canonical JSON after recomputing every derived readiness field."""

    if type(value) is not ImplementationReadiness:
        raise TypeError("value must be an exact ImplementationReadiness")
    expected = resolve_implementation_readiness(
        value.source.blueprint,
        value.source.intake,
        intent_intake_binding=value.source.intent_intake_binding,
        stack_candidates=value.source.stack_candidates,
        domain_pack_registry=value.source.domain_pack_registry,
        applicable_pack_ids=value.source.applicable_pack_ids,
        applicability_evidence=value.source.applicability_evidence,
        architecture_compatibility=value.source.architecture_compatibility,
        readiness_id=value.readiness_id,
    )
    if expected != value:
        raise ImplementationReadinessError(
            "implementation readiness does not match recomputed source evidence"
        )
    try:
        rendered = canonical_json_bytes(_mapping(value))
    except SchemaError as error:
        raise ImplementationReadinessError(
            f"implementation readiness cannot be encoded: {error}"
        ) from error
    if len(rendered) > MAX_IMPLEMENTATION_READINESS_BYTES:
        raise ImplementationReadinessError(
            "rendered implementation readiness exceeds its byte bound"
        )
    return rendered


def _closed(value: object, fields: frozenset[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ImplementationReadinessError(f"{label} must be an object")
    keys = set(value)
    if any(type(key) is not str for key in keys):
        raise ImplementationReadinessError(f"{label} field names must be strings")
    unknown = sorted(keys - fields)
    missing = sorted(fields - keys)
    if unknown:
        raise ImplementationReadinessError(
            f"{label} contains unknown fields: {', '.join(unknown)}"
        )
    if missing:
        raise ImplementationReadinessError(
            f"{label} is missing fields: {', '.join(missing)}"
        )
    return value


def _sequence(value: object, label: str, maximum: int) -> tuple[object, ...]:
    if type(value) is not list or len(value) > maximum:
        raise ImplementationReadinessError(f"{label} must be a bounded array")
    return tuple(value)


def _parse_codes(value: object, label: str, maximum: int) -> tuple[str, ...]:
    return tuple(
        _code(item, f"{label}[{index}]")
        for index, item in enumerate(_sequence(value, label, maximum))
    )


def _parse_refs(value: object, label: str, maximum: int) -> tuple[str, ...]:
    return tuple(
        _reference(item, f"{label}[{index}]")
        for index, item in enumerate(_sequence(value, label, maximum))
    )


def _enum(enum_type: type[Enum], value: object, label: str) -> Enum:
    if type(value) is not str:
        raise ImplementationReadinessError(f"{label} must be a string enum value")
    try:
        return enum_type(value)
    except ValueError as error:
        raise ImplementationReadinessError(f"{label} has an unsupported value") from error


def _parse_candidate(value: object, index: int) -> StackCandidate:
    label = f"source.stack_candidates[{index}]"
    item = _closed(
        value,
        frozenset(
            {
                "architecture_code",
                "assessments",
                "candidate_id",
                "candidate_kind",
                "evidence_level",
                "evidence_refs",
            }
        ),
        label,
    )
    assessments = []
    for assessment_index, raw in enumerate(
        _sequence(item["assessments"], f"{label}.assessments", 6)
    ):
        assessment_label = f"{label}.assessments[{assessment_index}]"
        assessment = _closed(
            raw,
            frozenset({"dimension", "evidence_refs", "rationale_code", "score"}),
            assessment_label,
        )
        assessments.append(
            DimensionAssessment(
                dimension=_enum(
                    StackDimension,
                    assessment["dimension"],
                    f"{assessment_label}.dimension",
                ),
                score=assessment["score"],
                rationale_code=_code(
                    assessment["rationale_code"],
                    f"{assessment_label}.rationale_code",
                ),
                evidence_refs=_parse_refs(
                    assessment["evidence_refs"],
                    f"{assessment_label}.evidence_refs",
                    16,
                ),
            )
        )
    return StackCandidate(
        candidate_id=_code(item["candidate_id"], f"{label}.candidate_id"),
        architecture_code=_code(
            item["architecture_code"], f"{label}.architecture_code"
        ),
        candidate_kind=_enum(
            CandidateKind, item["candidate_kind"], f"{label}.candidate_kind"
        ),
        evidence_level=_enum(
            NeedEvidenceLevel, item["evidence_level"], f"{label}.evidence_level"
        ),
        assessments=tuple(assessments),
        evidence_refs=_parse_refs(item["evidence_refs"], f"{label}.evidence_refs", 16),
    )


def _parse_pack(value: object, index: int) -> DomainPack:
    label = f"source.domain_pack_registry.packs[{index}]"
    item = _closed(
        value,
        frozenset(
            {
                "applicability",
                "dependencies",
                "domain",
                "pack_id",
                "performance_profiles",
                "professional_gates",
                "schema_version",
                "source_refs",
                "test_profiles",
                "version",
            }
        ),
        label,
    )
    applicability_item = _closed(
        item["applicability"],
        frozenset(
            {"data_classes", "domains", "project_modes", "purposes", "risk_levels"}
        ),
        f"{label}.applicability",
    )
    applicability = DomainApplicability(
        domains=_parse_codes(
            applicability_item["domains"], f"{label}.applicability.domains", 16
        ),
        project_modes=_parse_codes(
            applicability_item["project_modes"],
            f"{label}.applicability.project_modes",
            16,
        ),
        purposes=_parse_codes(
            applicability_item["purposes"], f"{label}.applicability.purposes", 16
        ),
        risk_levels=_parse_codes(
            applicability_item["risk_levels"],
            f"{label}.applicability.risk_levels",
            16,
        ),
        data_classes=_parse_codes(
            applicability_item["data_classes"],
            f"{label}.applicability.data_classes",
            16,
        ),
    )
    tests = []
    for profile_index, raw in enumerate(
        _sequence(item["test_profiles"], f"{label}.test_profiles", 32)
    ):
        profile_label = f"{label}.test_profiles[{profile_index}]"
        profile = _closed(
            raw,
            frozenset({"evidence_refs", "profile_id", "required", "test_kind"}),
            profile_label,
        )
        tests.append(
            TestProfile(
                profile_id=_code(profile["profile_id"], f"{profile_label}.profile_id"),
                test_kind=_code(profile["test_kind"], f"{profile_label}.test_kind"),
                evidence_refs=_parse_refs(
                    profile["evidence_refs"], f"{profile_label}.evidence_refs", 16
                ),
                required=profile["required"],
            )
        )
    performance = []
    for profile_index, raw in enumerate(
        _sequence(item["performance_profiles"], f"{label}.performance_profiles", 32)
    ):
        profile_label = f"{label}.performance_profiles[{profile_index}]"
        profile = _closed(
            raw,
            frozenset(
                {
                    "baseline_ref",
                    "comparator",
                    "environment",
                    "evidence_refs",
                    "metric",
                    "profile_id",
                    "threshold",
                    "tolerance",
                    "variance_policy",
                    "workload",
                }
            ),
            profile_label,
        )
        performance.append(
            PerformanceProfile(
                profile_id=_code(profile["profile_id"], f"{profile_label}.profile_id"),
                metric=_code(profile["metric"], f"{profile_label}.metric"),
                workload=_code(profile["workload"], f"{profile_label}.workload"),
                environment=_code(
                    profile["environment"], f"{profile_label}.environment"
                ),
                comparator=_enum(
                    Comparator, profile["comparator"], f"{profile_label}.comparator"
                ),
                threshold=profile["threshold"],
                tolerance=profile["tolerance"],
                variance_policy=_code(
                    profile["variance_policy"], f"{profile_label}.variance_policy"
                ),
                baseline_ref=_reference(
                    profile["baseline_ref"], f"{profile_label}.baseline_ref"
                ),
                evidence_refs=_parse_refs(
                    profile["evidence_refs"], f"{profile_label}.evidence_refs", 16
                ),
            )
        )
    gates = []
    for gate_index, raw in enumerate(
        _sequence(item["professional_gates"], f"{label}.professional_gates", 32)
    ):
        gate_label = f"{label}.professional_gates[{gate_index}]"
        gate = _closed(
            raw,
            frozenset(
                {
                    "evidence_refs",
                    "gate_id",
                    "owner_gate",
                    "phase",
                    "reason_code",
                    "required",
                }
            ),
            gate_label,
        )
        gates.append(
            ProfessionalGateRequirement(
                gate_id=_code(gate["gate_id"], f"{gate_label}.gate_id"),
                reason_code=_code(
                    gate["reason_code"], f"{gate_label}.reason_code"
                ),
                phase=_enum(GatePhase, gate["phase"], f"{gate_label}.phase"),
                required=gate["required"],
                owner_gate=gate["owner_gate"],
                evidence_refs=_parse_refs(
                    gate["evidence_refs"], f"{gate_label}.evidence_refs", 16
                ),
            )
        )
    return DomainPack(
        pack_id=_code(item["pack_id"], f"{label}.pack_id"),
        version=_scalar(item["version"], f"{label}.version", maximum=32),
        domain=_enum(DomainCode, item["domain"], f"{label}.domain"),
        source_refs=_parse_refs(item["source_refs"], f"{label}.source_refs", 16),
        applicability=applicability,
        dependencies=_parse_codes(item["dependencies"], f"{label}.dependencies", 16),
        test_profiles=tuple(tests),
        performance_profiles=tuple(performance),
        professional_gates=tuple(gates),
        schema_version=item["schema_version"],
    )


def _parse_gate(value: object, index: int) -> GateRouteEvidence:
    label = f"professional_gate_requirements[{index}]"
    item = _closed(
        value,
        frozenset(
            {
                "domain",
                "evidence_refs",
                "gate_id",
                "owner_gate",
                "pack_id",
                "phase",
                "reason_code",
                "required",
            }
        ),
        label,
    )
    return GateRouteEvidence(
        pack_id=_code(item["pack_id"], f"{label}.pack_id"),
        domain=_enum(DomainCode, item["domain"], f"{label}.domain"),
        gate_id=_code(item["gate_id"], f"{label}.gate_id"),
        reason_code=_code(item["reason_code"], f"{label}.reason_code"),
        phase=_enum(GatePhase, item["phase"], f"{label}.phase"),
        required=item["required"],
        owner_gate=item["owner_gate"],
        evidence_refs=_parse_refs(item["evidence_refs"], f"{label}.evidence_refs", 16),
    )


def _parse_source(value: object) -> ImplementationReadinessSource:
    item = _closed(
        value,
        frozenset(
            {
                "applicability_evidence",
                "applicable_pack_ids",
                "architecture_compatibility",
                "blueprint",
                "blueprint_sha256",
                "domain_pack_registry",
                "intake",
                "intake_sha256",
                "intent_intake_binding",
                "stack_candidates",
            }
        ),
        "source",
    )
    try:
        blueprint = parse_project_blueprint(canonical_json_bytes(item["blueprint"]))
        intake = parse_intake(canonical_json_bytes(item["intake"]))
    except (SchemaError, ProjectBlueprintError, TypeError, ValueError) as error:
        raise ImplementationReadinessError("embedded blueprint or intake is invalid") from error

    binding = None
    if item["intent_intake_binding"] is not None:
        raw_binding = _closed(
            item["intent_intake_binding"],
            frozenset({"evidence_refs", "intake_id", "intent_id"}),
            "source.intent_intake_binding",
        )
        binding = IntentIntakeBinding(
            intent_id=_code(
                raw_binding["intent_id"], "source.intent_intake_binding.intent_id"
            ),
            intake_id=_code(
                raw_binding["intake_id"], "source.intent_intake_binding.intake_id"
            ),
            evidence_refs=_parse_refs(
                raw_binding["evidence_refs"],
                "source.intent_intake_binding.evidence_refs",
                MAX_BINDING_REFERENCES,
            ),
        )

    registry = None
    if item["domain_pack_registry"] is not None:
        raw_registry = _closed(
            item["domain_pack_registry"],
            frozenset({"packs", "schema_version"}),
            "source.domain_pack_registry",
        )
        raw_packs = _sequence(
            raw_registry["packs"], "source.domain_pack_registry.packs", MAX_PACKS
        )
        registry = DomainPackRegistry(
            packs=tuple(_parse_pack(raw, index) for index, raw in enumerate(raw_packs)),
            schema_version=raw_registry["schema_version"],
        )

    applicability = None
    if item["applicability_evidence"] is not None:
        raw_applicability = _closed(
            item["applicability_evidence"],
            frozenset({"data_class", "domains", "evidence_refs", "risk_level"}),
            "source.applicability_evidence",
        )
        data_class = raw_applicability["data_class"]
        if data_class is not None:
            data_class = _code(data_class, "source.applicability_evidence.data_class")
        applicability = DomainApplicabilityEvidence(
            domains=_parse_codes(
                raw_applicability["domains"],
                "source.applicability_evidence.domains",
                MAX_PACKS,
            ),
            risk_level=_code(
                raw_applicability["risk_level"],
                "source.applicability_evidence.risk_level",
            ),
            data_class=data_class,
            evidence_refs=_parse_refs(
                raw_applicability["evidence_refs"],
                "source.applicability_evidence.evidence_refs",
                64,
            ),
        )

    raw_compatibility = _sequence(
        item["architecture_compatibility"],
        "source.architecture_compatibility",
        MAX_COMPATIBILITY_RECORDS,
    )
    compatibility = []
    for index, raw in enumerate(raw_compatibility):
        label = f"source.architecture_compatibility[{index}]"
        record = _closed(
            raw,
            frozenset(
                {
                    "architecture_requirement_code",
                    "blueprint_architecture_code",
                    "candidate_architecture_code",
                    "candidate_id",
                    "evidence_refs",
                }
            ),
            label,
        )
        compatibility.append(
            ArchitectureCompatibilityEvidence(
                candidate_id=_code(record["candidate_id"], f"{label}.candidate_id"),
                candidate_architecture_code=_code(
                    record["candidate_architecture_code"],
                    f"{label}.candidate_architecture_code",
                ),
                blueprint_architecture_code=_code(
                    record["blueprint_architecture_code"],
                    f"{label}.blueprint_architecture_code",
                ),
                architecture_requirement_code=_code(
                    record["architecture_requirement_code"],
                    f"{label}.architecture_requirement_code",
                ),
                evidence_refs=_parse_refs(
                    record["evidence_refs"], f"{label}.evidence_refs", 32
                ),
            )
        )
    raw_candidates = _sequence(
        item["stack_candidates"], "source.stack_candidates", 16
    )
    return ImplementationReadinessSource(
        blueprint_sha256=_digest(item["blueprint_sha256"], "source.blueprint_sha256"),
        blueprint=blueprint,
        intake_sha256=_digest(item["intake_sha256"], "source.intake_sha256"),
        intake=intake,
        intent_intake_binding=binding,
        stack_candidates=tuple(
            _parse_candidate(raw, index) for index, raw in enumerate(raw_candidates)
        ),
        domain_pack_registry=registry,
        applicable_pack_ids=_parse_codes(
            item["applicable_pack_ids"], "source.applicable_pack_ids", MAX_PACKS
        ),
        applicability_evidence=applicability,
        architecture_compatibility=tuple(compatibility),
    )


def _parse_mapping(value: object) -> ImplementationReadiness:
    item = _closed(
        value,
        frozenset(
            {
                "blocker_codes",
                "evidence_refs",
                "implementation_authority",
                "professional_gate_requirements",
                "readiness_id",
                "ready_for_materialization_preview",
                "schema_version",
                "selected_architecture_code",
                "selected_stack_candidate_id",
                "source",
                "state",
            }
        ),
        "implementation_readiness",
    )
    if item["schema_version"] != IMPLEMENTATION_READINESS_SCHEMA_VERSION:
        raise ImplementationReadinessError(
            "unsupported implementation-readiness schema_version"
        )
    selected_candidate = item["selected_stack_candidate_id"]
    if selected_candidate is not None:
        selected_candidate = _code(selected_candidate, "selected_stack_candidate_id")
    selected_architecture = item["selected_architecture_code"]
    if selected_architecture is not None:
        selected_architecture = _code(
            selected_architecture, "selected_architecture_code"
        )
    raw_gates = _sequence(
        item["professional_gate_requirements"],
        "professional_gate_requirements",
        MAX_PACKS * 32,
    )
    return ImplementationReadiness(
        schema_version=IMPLEMENTATION_READINESS_SCHEMA_VERSION,
        readiness_id=_code(item["readiness_id"], "readiness_id"),
        source=_parse_source(item["source"]),
        state=_enum(ReadinessState, item["state"], "state"),
        selected_stack_candidate_id=selected_candidate,
        selected_architecture_code=selected_architecture,
        professional_gate_requirements=tuple(
            _parse_gate(raw, index) for index, raw in enumerate(raw_gates)
        ),
        ready_for_materialization_preview=item["ready_for_materialization_preview"],
        implementation_authority=_enum(
            ImplementationAuthority,
            item["implementation_authority"],
            "implementation_authority",
        ),
        blocker_codes=_parse_codes(item["blocker_codes"], "blocker_codes", 32),
        evidence_refs=_parse_refs(
            item["evidence_refs"], "evidence_refs", MAX_EVIDENCE_REFERENCES
        ),
    )


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ImplementationReadinessError(
                "implementation readiness contains duplicate object fields"
            )
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ImplementationReadinessError(
        f"implementation readiness contains unsupported JSON constant: {value}"
    )


def parse_implementation_readiness(
    payload: bytes | bytearray | memoryview,
) -> ImplementationReadiness:
    """Parse only bounded canonical UTF-8 JSON with full source recomputation."""

    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise ImplementationReadinessError(
            "implementation-readiness payload must be bytes"
        )
    raw = bytes(payload)
    if not raw or len(raw) > MAX_IMPLEMENTATION_READINESS_BYTES:
        raise ImplementationReadinessError(
            "implementation-readiness payload must use bounded non-empty bytes"
        )
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicates,
            parse_constant=_reject_constant,
        )
    except ImplementationReadinessError:
        raise
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
        RecursionError,
    ) as error:
        raise ImplementationReadinessError(
            "implementation readiness is not valid UTF-8 JSON"
        ) from error
    record = _parse_mapping(value)
    if render_implementation_readiness(record) != raw:
        raise ImplementationReadinessError(
            "implementation-readiness JSON is not canonical"
        )
    return record


build_implementation_readiness = resolve_implementation_readiness
render_readiness = render_implementation_readiness
parse_readiness = parse_implementation_readiness


__all__ = [
    "ArchitectureCompatibilityEvidence",
    "IMPLEMENTATION_READINESS_SCHEMA_VERSION",
    "ImplementationAuthority",
    "ImplementationReadiness",
    "ImplementationReadinessError",
    "ImplementationReadinessSource",
    "IntentIntakeBinding",
    "MAX_IMPLEMENTATION_READINESS_BYTES",
    "ReadinessState",
    "build_implementation_readiness",
    "parse_implementation_readiness",
    "parse_readiness",
    "render_implementation_readiness",
    "render_readiness",
    "resolve_implementation_readiness",
]
