"""Evaluate the six canonical P2-E guided-intake examples offline."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) in sys.path:
    sys.path.remove(str(ROOT))
sys.path.insert(0, str(ROOT))


from project_governance.domain_pack import (
    DomainApplicability,
    DomainPack,
    DomainPackRegistry,
    ProfessionalGateRequirement,
)
from project_governance.intake import ProjectIntake, StopState, parse_intake
from project_governance.intake_ux import (
    DomainApplicabilityEvidence,
    build_guided_intake_view,
    render_guided_intake_view,
)
from project_governance.stack_decision import (
    CandidateKind,
    DimensionAssessment,
    RecommendationDisposition,
    StackCandidate,
    StackDimension,
    score_stack_candidates,
)


SCHEMA_VERSION = "1.0"
CANONICAL_CASE_IDS = (
    "case-01-3d-racing-game",
    "case-02-ecommerce",
    "case-03-existing-wrong-stack",
    "case-04-t0-learning",
    "case-05-cross-domain-system",
    "case-06-high-risk-payment",
)
_ROOT_FIELDS = frozenset({"schema_version", "cases"})
_CASE_FIELDS = frozenset(
    {
        "applicability_context",
        "case_id",
        "scenario_code",
        "applicable_pack_ids",
        "expected_disposition",
        "expected_question_count",
        "intake",
    }
)
_CONTEXT_FIELDS = frozenset(
    {"domains", "risk_level", "data_class", "evidence_refs"}
)
_CATALOG_FIELDS = frozenset(
    {"schema_version", "catalog_id", "catalog_version", "packs"}
)
_PACK_FIELDS = frozenset(
    {
        "pack_id",
        "domain",
        "version",
        "source",
        "applicability",
        "test_profile_ids",
        "performance_profile_ids",
        "professional_gate_ids",
    }
)
_APPLICABILITY_FIELDS = frozenset(
    {"project_modes", "purposes", "risk_levels"}
)
_STOP_BY_DISPOSITION = {
    "next-question": StopState.CONTINUE.value,
    "owner-gate": StopState.OWNER_GATE.value,
    "ready-for-preview": StopState.READY_FOR_PREVIEW.value,
}
_CANONICAL_PACK_IDENTITIES = (
    ("accessibility", "accessibility"),
    ("ai-content", "ai-content"),
    ("copyright", "copyright"),
    ("ecommerce", "ecommerce"),
    ("finance", "finance"),
    ("game", "game"),
    ("industrial-control", "industrial-control"),
    ("medical", "medical"),
    ("payments", "payments"),
    ("privacy", "privacy"),
    ("security", "security"),
    ("three-d", "three-d"),
)
_CANONICAL_CATALOG_SHA256 = (
    "c81db1820440a799e04234c26014a6415b57a03092241abd2eb3a4d2944d9f73"
)


class EvaluationError(ValueError):
    """Raised when an example or catalog violates the evaluation contract."""


@dataclass(frozen=True)
class _CaseContract:
    case_id: str
    scenario_code: str
    pack_ids: tuple[str, ...]
    risk_level: str
    data_class: str | None
    applicability_evidence_refs: tuple[str, ...]
    expected_disposition: str
    expected_question_count: int
    intake_sha256: str
    stack_disposition: str
    selected_stack_candidate_id: str | None


_CASE_CONTRACTS = (
    _CaseContract(
        "case-01-3d-racing-game",
        "new.3d-racing-game",
        ("game", "three-d"),
        "routine",
        None,
        ("evidence.domain.game", "evidence.domain.three-d", "evidence.risk.routine"),
        "ready-for-preview",
        0,
        "8cc0dfb975edf27ed2b68d4ba0c4f5b955edccbc5fa5c78bb6e4361575bb9751",
        "not-evaluated",
        None,
    ),
    _CaseContract(
        "case-02-ecommerce",
        "new.ecommerce",
        ("ecommerce",),
        "moderate",
        None,
        ("evidence.domain.ecommerce", "evidence.risk.moderate"),
        "next-question",
        1,
        "cb2b4f69bc1c52d96432b034bd747b2cbe931b2e9d1346b09b4eafb5ee91f59b",
        "not-evaluated",
        None,
    ),
    _CaseContract(
        "case-03-existing-wrong-stack",
        "existing.wrong-stack",
        ("security",),
        "high",
        None,
        ("evidence.domain.security", "evidence.risk.high"),
        "ready-for-preview",
        0,
        "05f12da60b4d0b7aef62a14e5582c2b167779b8cf4e28072ed183318e5fd700d",
        RecommendationDisposition.RECOMMEND.value,
        "candidate.replacement",
    ),
    _CaseContract(
        "case-04-t0-learning",
        "personal.learning",
        ("accessibility",),
        "routine",
        None,
        ("evidence.domain.accessibility", "evidence.risk.routine"),
        "ready-for-preview",
        0,
        "8efc422617919fe7707fd5e6a5226ebdb6d1948923bc4a728340b829ac1a5ad0",
        "not-evaluated",
        None,
    ),
    _CaseContract(
        "case-05-cross-domain-system",
        "existing.cross-domain",
        ("privacy", "security"),
        "high",
        None,
        ("evidence.domain.privacy", "evidence.domain.security", "evidence.risk.high"),
        "next-question",
        1,
        "1864a9fb64d52ba34d82d1f5901bced635b8663fb1b8d8b4d80d4620970ce40f",
        "not-evaluated",
        None,
    ),
    _CaseContract(
        "case-06-high-risk-payment",
        "high-risk.payment-data-external",
        ("payments", "privacy", "security"),
        "critical",
        None,
        (
            "evidence.domain.payments",
            "evidence.domain.privacy",
            "evidence.domain.security",
            "evidence.risk.critical",
        ),
        "owner-gate",
        1,
        "57430034dae7fc406c3654c1b04cbbdf0460301955d9a539c81b8a1d8dd9cab9",
        "not-evaluated",
        None,
    ),
)


def _closed_mapping(
    value: object, fields: frozenset[str], label: str
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise EvaluationError(f"{label} must be an object")
    keys = set(value)
    unknown = sorted(keys - fields)
    missing = sorted(fields - keys)
    if unknown:
        raise EvaluationError(f"{label} has unknown fields: {', '.join(unknown)}")
    if missing:
        raise EvaluationError(f"{label} is missing fields: {', '.join(missing)}")
    return value


def _string(value: object, label: str) -> str:
    if type(value) is not str or not value or len(value) > 160:
        raise EvaluationError(f"{label} must be bounded non-empty text")
    if any(ord(character) < 32 for character in value):
        raise EvaluationError(f"{label} must not contain control characters")
    return value


def _canonical_strings(
    value: object, label: str, *, maximum: int = 32
) -> tuple[str, ...]:
    if type(value) is not list or len(value) > maximum:
        raise EvaluationError(f"{label} must be a bounded array")
    result = tuple(_string(item, f"{label}[{index}]") for index, item in enumerate(value))
    if result != tuple(sorted(set(result))):
        raise EvaluationError(f"{label} must use canonical unique order")
    return result


def _sorted_strings(
    value: object, label: str, *, maximum: int = 32
) -> tuple[str, ...]:
    if type(value) is not list or len(value) > maximum:
        raise EvaluationError(f"{label} must be a bounded array")
    result = tuple(_string(item, f"{label}[{index}]") for index, item in enumerate(value))
    if len(result) != len(set(result)):
        raise EvaluationError(f"{label} must contain unique values")
    return tuple(sorted(result))


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )


def _read_json(path: Path, label: str) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise EvaluationError(f"cannot read {label}: {error}") from error


def _registry_from_catalog(value: object) -> tuple[DomainPackRegistry, str]:
    catalog = _closed_mapping(value, _CATALOG_FIELDS, "catalog")
    catalog_sha256 = hashlib.sha256(_canonical_bytes(value)).hexdigest()
    if catalog_sha256 != _CANONICAL_CATALOG_SHA256:
        raise EvaluationError("catalog canonical digest does not match P2-D evidence")
    if catalog["schema_version"] != SCHEMA_VERSION:
        raise EvaluationError(f"catalog.schema_version must be {SCHEMA_VERSION}")
    if catalog["catalog_id"] != "apg-domain-catalog":
        raise EvaluationError("catalog.catalog_id is not canonical")
    if catalog["catalog_version"] != "1.0.0":
        raise EvaluationError("catalog.catalog_version is not canonical")
    raw_packs = catalog["packs"]
    if type(raw_packs) is not list or len(raw_packs) != 12:
        raise EvaluationError("catalog.packs must contain exactly 12 records")

    catalog_ref = "fixtures/domain-packs/catalog-v1.json"
    packs: list[DomainPack] = []
    identities: list[tuple[str, str]] = []
    for index, raw_pack in enumerate(raw_packs):
        item = _closed_mapping(raw_pack, _PACK_FIELDS, f"catalog.packs[{index}]")
        applicability = _closed_mapping(
            item["applicability"],
            _APPLICABILITY_FIELDS,
            f"catalog.packs[{index}].applicability",
        )
        pack_id = _string(item["pack_id"], f"catalog.packs[{index}].pack_id")
        domain = _string(item["domain"], f"catalog.packs[{index}].domain")
        identities.append((pack_id, domain))
        _string(item["source"], f"catalog.packs[{index}].source")
        _canonical_strings(
            item["test_profile_ids"], f"catalog.packs[{index}].test_profile_ids"
        )
        _canonical_strings(
            item["performance_profile_ids"],
            f"catalog.packs[{index}].performance_profile_ids",
        )
        gate_ids = _canonical_strings(
            item["professional_gate_ids"],
            f"catalog.packs[{index}].professional_gate_ids",
        )
        packs.append(
            DomainPack(
                pack_id=pack_id,
                version=_string(item["version"], f"catalog.packs[{index}].version"),
                domain=domain,
                source_refs=(catalog_ref,),
                applicability=DomainApplicability(
                    domains=(domain,),
                    project_modes=_sorted_strings(
                        applicability["project_modes"],
                        f"catalog.packs[{index}].applicability.project_modes",
                    ),
                    purposes=_sorted_strings(
                        applicability["purposes"],
                        f"catalog.packs[{index}].applicability.purposes",
                    ),
                    risk_levels=_sorted_strings(
                        applicability["risk_levels"],
                        f"catalog.packs[{index}].applicability.risk_levels",
                    ),
                ),
                professional_gates=tuple(
                    ProfessionalGateRequirement(
                        gate_id=gate_id,
                        reason_code=f"{pack_id}.catalog-requirement",
                        evidence_refs=(catalog_ref,),
                    )
                    for gate_id in gate_ids
                ),
            )
        )

    if tuple(identities) != _CANONICAL_PACK_IDENTITIES:
        raise EvaluationError("catalog pack/domain identities are not canonical")
    registry = DomainPackRegistry.from_packs(packs)
    return registry, catalog_sha256


def _stack_candidate(
    record: ProjectIntake,
    *,
    candidate_id: str,
    kind: CandidateKind,
    score: int,
    evidence_ref: str,
) -> StackCandidate:
    assessments = tuple(
        DimensionAssessment(
            dimension=dimension,
            score=score,
            rationale_code=f"rationale.{candidate_id}.{dimension.value}",
            evidence_refs=(evidence_ref,),
        )
        for dimension in sorted(StackDimension, key=lambda item: item.value)
    )
    return StackCandidate(
        candidate_id=candidate_id,
        architecture_code=f"architecture.{kind.value}",
        candidate_kind=kind,
        evidence_level=record.need_evidence_level,
        assessments=assessments,
        evidence_refs=(evidence_ref,),
    )


def _stack_for_case(record: ProjectIntake, contract: _CaseContract):
    if contract.case_id != "case-03-existing-wrong-stack":
        return None
    return score_stack_candidates(
        record,
        (
            _stack_candidate(
                record,
                candidate_id="candidate.existing",
                kind=CandidateKind.EXISTING,
                score=1,
                evidence_ref="evidence.project-code",
            ),
            _stack_candidate(
                record,
                candidate_id="candidate.replacement",
                kind=CandidateKind.REPLACEMENT,
                score=5,
                evidence_ref="evidence.viability",
            ),
        ),
    )


def evaluate(cases_value: object, catalog_value: object) -> dict[str, object]:
    root = _closed_mapping(cases_value, _ROOT_FIELDS, "examples")
    if root["schema_version"] != SCHEMA_VERSION:
        raise EvaluationError(f"examples.schema_version must be {SCHEMA_VERSION}")
    raw_cases = root["cases"]
    if type(raw_cases) is not list or len(raw_cases) != len(CANONICAL_CASE_IDS):
        raise EvaluationError("examples.cases must contain exactly six records")

    registry, catalog_sha256 = _registry_from_catalog(catalog_value)
    results: list[dict[str, object]] = []
    for index, raw_case in enumerate(raw_cases):
        contract = _CASE_CONTRACTS[index]
        item = _closed_mapping(raw_case, _CASE_FIELDS, f"cases[{index}]")
        case_id = _string(item["case_id"], f"cases[{index}].case_id")
        if case_id != contract.case_id:
            raise EvaluationError(
                f"cases[{index}].case_id must be {contract.case_id}"
            )
        scenario_code = _string(
            item["scenario_code"], f"cases[{index}].scenario_code"
        )
        if scenario_code != contract.scenario_code:
            raise EvaluationError(f"cases[{index}].scenario_code is not canonical")
        pack_ids = _canonical_strings(
            item["applicable_pack_ids"], f"cases[{index}].applicable_pack_ids"
        )
        if pack_ids != contract.pack_ids:
            raise EvaluationError(
                f"cases[{index}].applicable_pack_ids are not canonical"
            )
        expected_disposition = _string(
            item["expected_disposition"],
            f"cases[{index}].expected_disposition",
        )
        if expected_disposition != contract.expected_disposition:
            raise EvaluationError(
                f"cases[{index}].expected_disposition is not canonical"
            )
        expected_question_count = item["expected_question_count"]
        if expected_question_count != contract.expected_question_count:
            raise EvaluationError(
                f"cases[{index}].expected_question_count is not canonical"
            )

        context = _closed_mapping(
            item["applicability_context"],
            _CONTEXT_FIELDS,
            f"cases[{index}].applicability_context",
        )
        risk_level = _string(
            context["risk_level"],
            f"cases[{index}].applicability_context.risk_level",
        )
        data_class = context["data_class"]
        if data_class is not None:
            data_class = _string(
                data_class,
                f"cases[{index}].applicability_context.data_class",
            )
        applicability_refs = _canonical_strings(
            context["evidence_refs"],
            f"cases[{index}].applicability_context.evidence_refs",
        )
        domains = _canonical_strings(
            context["domains"],
            f"cases[{index}].applicability_context.domains",
        )
        if (
            domains != contract.pack_ids
            or risk_level != contract.risk_level
            or data_class != contract.data_class
            or applicability_refs != contract.applicability_evidence_refs
        ):
            raise EvaluationError(
                f"cases[{index}].applicability_context is not canonical"
            )

        intake_bytes = _canonical_bytes(item["intake"])
        intake_sha256 = hashlib.sha256(intake_bytes).hexdigest()
        if intake_sha256 != contract.intake_sha256:
            raise EvaluationError(f"cases[{index}].intake is not canonical")
        record = parse_intake(intake_bytes)
        stack_decision = _stack_for_case(record, contract)
        applicability_evidence = DomainApplicabilityEvidence(
            domains=domains,
            risk_level=risk_level,
            data_class=data_class,
            evidence_refs=applicability_refs,
        )
        view = build_guided_intake_view(
            record,
            stack_decision=stack_decision,
            domain_pack_registry=registry,
            applicable_pack_ids=pack_ids,
            applicability_evidence=applicability_evidence,
        )
        rendered = render_guided_intake_view(view)
        disposition = view.disposition.value
        question_count = int(view.question is not None)
        route_correct = disposition == expected_disposition
        question_correct = question_count == expected_question_count
        stop_correct = (
            record.stop_state.value
            == _STOP_BY_DISPOSITION[expected_disposition]
        )
        stack_disposition = (
            view.stack_disposition.value
            if view.stack_disposition is not None
            else "not-evaluated"
        )
        stack_correct = (
            stack_disposition == contract.stack_disposition
            and view.selected_stack_candidate_id
            == contract.selected_stack_candidate_id
        )
        passed = route_correct and question_correct and stop_correct and stack_correct
        results.append(
            {
                "ai_resolved_count": record.ai_resolved_count,
                "case_id": case_id,
                "disposition": disposition,
                "human_decision_count": record.human_decision_count,
                "intake_sha256": intake_sha256,
                "pack_ids": list(view.applicable_pack_ids),
                "passed": passed,
                "professional_gate_ids": list(view.professional_gate_ids),
                "question_count": question_count,
                "question_correct": question_correct,
                "render_sha256": hashlib.sha256(rendered).hexdigest(),
                "route_correct": route_correct,
                "risk_level": risk_level,
                "scenario_code": scenario_code,
                "selected_stack_candidate_id": view.selected_stack_candidate_id,
                "stack_correct": stack_correct,
                "stack_disposition": stack_disposition,
                "stack_fitness": record.stack_fitness.value,
                "stop_correct": stop_correct,
                "stop_state": record.stop_state.value,
            }
        )

    passed = all(bool(item["passed"]) for item in results)
    return {
        "aggregate": {
            "ai_resolved_count": sum(
                int(item["ai_resolved_count"]) for item in results
            ),
            "human_decision_count": sum(
                int(item["human_decision_count"]) for item in results
            ),
            "passed": passed,
            "question_count": sum(int(item["question_count"]) for item in results),
            "route_correct_count": sum(bool(item["route_correct"]) for item in results),
            "stack_correct_count": sum(bool(item["stack_correct"]) for item in results),
            "stop_correct_count": sum(bool(item["stop_correct"]) for item in results),
        },
        "case_count": len(results),
        "cases": results,
        "catalog_sha256": catalog_sha256,
        "no_side_effect_status": "read-only-offline",
        "passed": passed,
        "schema_version": SCHEMA_VERSION,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate the six canonical guided-intake examples offline."
    )
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument(
        "--catalog",
        type=Path,
        default=ROOT / "fixtures" / "domain-packs" / "catalog-v1.json",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        result = evaluate(
            _read_json(arguments.cases, "examples"),
            _read_json(arguments.catalog, "catalog"),
        )
    except (EvaluationError, TypeError, ValueError) as error:
        print(f"evaluation error: {error}", file=sys.stderr)
        return 2
    sys.stdout.buffer.write(_canonical_bytes(result))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
