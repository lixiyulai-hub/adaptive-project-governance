"""Closed, side-effect-free P3-D project materialization preview records."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from .implementation_readiness import (
    ImplementationAuthority,
    ImplementationReadiness,
    ReadinessState,
    parse_implementation_readiness,
    render_implementation_readiness,
)
from .storage import SchemaError, canonical_json_bytes


PROJECT_MATERIALIZATION_SCHEMA_VERSION = "1.0"
MAX_PROJECT_MATERIALIZATION_BYTES = 262_144
MAX_MANIFEST_ENTRIES = 256
MAX_GATES = 64
MAX_ACCEPTANCE_REFS = 64
_CODE_RE = re.compile(r"[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*\Z")
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_PRIVATE_KEY_HEADER_RE = r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE " + r"KEY-----"
_SENSITIVE_RE = re.compile(
    r"(?:sk-[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{20,}|"
    + _PRIVATE_KEY_HEADER_RE
    + r")",
    re.IGNORECASE,
)


class ProjectMaterializationError(ValueError):
    """Raised when a P3-D preview record is invalid or non-canonical."""


class PreviewState(Enum):
    PREVIEW_READY = "preview-ready"
    PENDING_USER_INPUT = "pending-user-input"
    BLOCK = "block"


class ApprovalState(Enum):
    APPROVED = "approved"
    PENDING_USER_INPUT = "pending-user-input"


def _text(value: object, label: str, maximum: int = 256) -> str:
    if type(value) is not str or not value or len(value) > maximum:
        raise ProjectMaterializationError(f"{label} must be bounded non-empty text")
    if value != unicodedata.normalize("NFC", value):
        raise ProjectMaterializationError(f"{label} must use NFC Unicode")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ProjectMaterializationError(f"{label} contains control characters")
    if _SENSITIVE_RE.search(value):
        raise ProjectMaterializationError(f"{label} contains a sensitive-value pattern")
    return value


def _code(value: object, label: str) -> str:
    value = _text(value, label, 128)
    if not _CODE_RE.fullmatch(value):
        raise ProjectMaterializationError(f"{label} must be a bounded stable code")
    return value


def _digest(value: object, label: str) -> str:
    if type(value) is not str or not _SHA256_RE.fullmatch(value):
        raise ProjectMaterializationError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _path(value: object, label: str) -> str:
    value = _text(value, label, 240)
    if "\\" in value or value.startswith("/") or ":" in value:
        raise ProjectMaterializationError(f"{label} must be a relative slash-separated path")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ProjectMaterializationError(f"{label} contains an unsafe path segment")
    return value


def _root_locator(value: object, label: str) -> str:
    return _code(value, label)


def _tuple(value: object, label: str, maximum: int) -> tuple[Any, ...]:
    if type(value) is not tuple or len(value) > maximum:
        raise ProjectMaterializationError(f"{label} must be a bounded immutable tuple")
    return value


def _codes(value: object, label: str, maximum: int, *, allow_empty: bool = False) -> tuple[str, ...]:
    items = _tuple(value, label, maximum)
    if not items and not allow_empty:
        raise ProjectMaterializationError(f"{label} must not be empty")
    codes = tuple(_code(item, f"{label}[{index}]") for index, item in enumerate(items))
    if codes != tuple(sorted(set(codes))):
        raise ProjectMaterializationError(f"{label} must use canonical unique order")
    return codes


def _closed(value: object, fields: frozenset[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProjectMaterializationError(f"{label} must be an object")
    if any(type(key) is not str for key in value):
        raise ProjectMaterializationError(f"{label} field names must be strings")
    unknown = set(value) - fields
    missing = fields - set(value)
    if unknown:
        raise ProjectMaterializationError(
            f"{label} contains unknown fields: {', '.join(sorted(unknown))}"
        )
    if missing:
        raise ProjectMaterializationError(
            f"{label} is missing fields: {', '.join(sorted(missing))}"
        )
    return value


def _reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ProjectMaterializationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise ProjectMaterializationError(
        f"project materialization contains unsupported JSON constant: {value}"
    )


@dataclass(frozen=True)
class ManifestEntry:
    path: str
    content_sha256: str

    def __post_init__(self) -> None:
        if type(self) is not ManifestEntry:
            raise ProjectMaterializationError("ManifestEntry subclasses are not accepted")
        _path(self.path, "path")
        _digest(self.content_sha256, "content_sha256")


@dataclass(frozen=True)
class BaselineEntry:
    path: str
    expected_sha256: str | None

    def __post_init__(self) -> None:
        if type(self) is not BaselineEntry:
            raise ProjectMaterializationError("BaselineEntry subclasses are not accepted")
        _path(self.path, "path")
        if self.expected_sha256 is not None:
            _digest(self.expected_sha256, "expected_sha256")


@dataclass(frozen=True)
class MaterializationGate:
    gate_id: str
    phase: str
    acceptance_ref: str

    def __post_init__(self) -> None:
        if type(self) is not MaterializationGate:
            raise ProjectMaterializationError(
                "MaterializationGate subclasses are not accepted"
            )
        _code(self.gate_id, "gate_id")
        _code(self.phase, "phase")
        _code(self.acceptance_ref, "acceptance_ref")


@dataclass(frozen=True)
class MaterializationProposal:
    proposal_id: str
    downstream_root: str | None
    manifest_id: str | None
    manifest_entries: tuple[ManifestEntry, ...]
    baseline_entries: tuple[BaselineEntry, ...]
    approval_state: ApprovalState | None
    approval_ref: str | None
    gates: tuple[MaterializationGate, ...]
    acceptance_refs: tuple[str, ...]
    rollback_id: str | None
    policy_sha256: str | None

    def __post_init__(self) -> None:
        if type(self) is not MaterializationProposal:
            raise ProjectMaterializationError(
                "MaterializationProposal subclasses are not accepted"
            )
        _code(self.proposal_id, "proposal_id")
        if self.downstream_root is not None:
            _root_locator(self.downstream_root, "downstream_root")
        if self.manifest_id is not None:
            _code(self.manifest_id, "manifest_id")
        manifest = _tuple(self.manifest_entries, "manifest_entries", MAX_MANIFEST_ENTRIES)
        if any(type(item) is not ManifestEntry for item in manifest):
            raise ProjectMaterializationError(
                "manifest_entries must contain exact ManifestEntry records"
            )
        manifest_paths = tuple(item.path for item in manifest)
        if manifest_paths != tuple(sorted(set(manifest_paths))):
            raise ProjectMaterializationError(
                "manifest_entries must use canonical unique path order"
            )
        baseline = _tuple(self.baseline_entries, "baseline_entries", MAX_MANIFEST_ENTRIES)
        if any(type(item) is not BaselineEntry for item in baseline):
            raise ProjectMaterializationError(
                "baseline_entries must contain exact BaselineEntry records"
            )
        baseline_paths = tuple(item.path for item in baseline)
        if baseline_paths != tuple(sorted(set(baseline_paths))):
            raise ProjectMaterializationError(
                "baseline_entries must use canonical unique path order"
            )
        if manifest_paths and baseline_paths and manifest_paths != baseline_paths:
            raise ProjectMaterializationError(
                "baseline_entries must match manifest_entries exactly"
            )
        if self.approval_state is not None and type(self.approval_state) is not ApprovalState:
            raise ProjectMaterializationError(
                "approval_state must be an exact ApprovalState or null"
            )
        if self.approval_ref is not None:
            _code(self.approval_ref, "approval_ref")
        if self.approval_state is ApprovalState.APPROVED and self.approval_ref is None:
            raise ProjectMaterializationError("approved proposal requires approval_ref")
        if self.approval_state is ApprovalState.PENDING_USER_INPUT and self.approval_ref is not None:
            raise ProjectMaterializationError(
                "pending approval must not carry approval_ref"
            )
        gates = _tuple(self.gates, "gates", MAX_GATES)
        if any(type(item) is not MaterializationGate for item in gates):
            raise ProjectMaterializationError(
                "gates must contain exact MaterializationGate records"
            )
        gate_keys = tuple((item.gate_id, item.phase, item.acceptance_ref) for item in gates)
        if gate_keys != tuple(sorted(set(gate_keys))):
            raise ProjectMaterializationError("gates must use canonical unique order")
        _codes(self.acceptance_refs, "acceptance_refs", MAX_ACCEPTANCE_REFS, allow_empty=True)
        if self.rollback_id is not None:
            _code(self.rollback_id, "rollback_id")
        if self.policy_sha256 is not None:
            _digest(self.policy_sha256, "policy_sha256")


def _missing_inputs(proposal: MaterializationProposal) -> tuple[str, ...]:
    missing: list[str] = []
    if proposal.downstream_root is None:
        missing.append("downstream-root-required")
    if proposal.manifest_id is None or not proposal.manifest_entries:
        missing.append("manifest-required")
    if not proposal.baseline_entries:
        missing.append("baseline-required")
    if proposal.approval_state is None or proposal.approval_state is ApprovalState.PENDING_USER_INPUT:
        missing.append("owner-approval-required")
    if not proposal.gates:
        missing.append("gates-required")
    if not proposal.acceptance_refs:
        missing.append("acceptance-required")
    if proposal.rollback_id is None:
        missing.append("rollback-required")
    if proposal.policy_sha256 is None:
        missing.append("policy-digest-required")
    return tuple(sorted(missing))


def _derived_state(
    readiness: ImplementationReadiness, proposal: MaterializationProposal
) -> tuple[PreviewState, tuple[str, ...]]:
    if (
        readiness.state is not ReadinessState.READY_FOR_MATERIALIZATION_PREVIEW
        or not readiness.ready_for_materialization_preview
        or readiness.implementation_authority is not ImplementationAuthority.NOT_AUTHORIZED
    ):
        return PreviewState.BLOCK, ("p3-c-readiness-required",)
    missing = _missing_inputs(proposal)
    if missing:
        return PreviewState.PENDING_USER_INPUT, missing
    return PreviewState.PREVIEW_READY, ()


@dataclass(frozen=True)
class ProjectMaterializationPreview:
    schema_version: str
    preview_id: str
    source_readiness_sha256: str
    source_readiness: ImplementationReadiness
    blueprint_sha256: str
    proposal: MaterializationProposal
    state: PreviewState
    blocker_codes: tuple[str, ...]
    preview_only: bool
    apply_authority: bool

    def __post_init__(self) -> None:
        if type(self) is not ProjectMaterializationPreview:
            raise ProjectMaterializationError(
                "ProjectMaterializationPreview subclasses are not accepted"
            )
        if self.schema_version != PROJECT_MATERIALIZATION_SCHEMA_VERSION:
            raise ProjectMaterializationError(
                "unsupported project-materialization schema_version"
            )
        _code(self.preview_id, "preview_id")
        _digest(self.source_readiness_sha256, "source_readiness_sha256")
        if type(self.source_readiness) is not ImplementationReadiness:
            raise ProjectMaterializationError(
                "source_readiness must be an exact ImplementationReadiness"
            )
        try:
            readiness_bytes = render_implementation_readiness(self.source_readiness)
        except (TypeError, ValueError) as error:
            raise ProjectMaterializationError(
                "source_readiness is not canonical"
            ) from error
        if hashlib.sha256(readiness_bytes).hexdigest() != self.source_readiness_sha256:
            raise ProjectMaterializationError(
                "source_readiness_sha256 does not bind source_readiness"
            )
        _digest(self.blueprint_sha256, "blueprint_sha256")
        if self.blueprint_sha256 != self.source_readiness.source.blueprint_sha256:
            raise ProjectMaterializationError(
                "blueprint_sha256 does not bind source_readiness blueprint"
            )
        if type(self.proposal) is not MaterializationProposal:
            raise ProjectMaterializationError(
                "proposal must be an exact MaterializationProposal"
            )
        if type(self.state) is not PreviewState:
            raise ProjectMaterializationError("state must be an exact PreviewState")
        blockers = _codes(self.blocker_codes, "blocker_codes", 32, allow_empty=True)
        if type(self.preview_only) is not bool or self.preview_only is not True:
            raise ProjectMaterializationError("preview_only must be exactly true")
        if type(self.apply_authority) is not bool or self.apply_authority is not False:
            raise ProjectMaterializationError("apply_authority must be exactly false")
        expected_id = f"preview.{self.source_readiness.readiness_id}.{self.proposal.proposal_id}"
        if self.preview_id != expected_id:
            raise ProjectMaterializationError("preview_id does not match bound sources")
        expected_state, expected_blockers = _derived_state(
            self.source_readiness, self.proposal
        )
        if self.state is not expected_state or blockers != expected_blockers:
            raise ProjectMaterializationError(
                "preview fields must match recomputed source and proposal evidence"
            )


def build_project_materialization_preview(
    readiness: ImplementationReadiness,
    proposal: MaterializationProposal,
) -> ProjectMaterializationPreview:
    """Build a deterministic preview without materializing a downstream root."""

    if type(readiness) is not ImplementationReadiness:
        raise TypeError("readiness must be an exact ImplementationReadiness")
    if type(proposal) is not MaterializationProposal:
        raise TypeError("proposal must be an exact MaterializationProposal")
    readiness_bytes = render_implementation_readiness(readiness)
    state, blocker_codes = _derived_state(readiness, proposal)
    return ProjectMaterializationPreview(
        schema_version=PROJECT_MATERIALIZATION_SCHEMA_VERSION,
        preview_id=f"preview.{readiness.readiness_id}.{proposal.proposal_id}",
        source_readiness_sha256=hashlib.sha256(readiness_bytes).hexdigest(),
        source_readiness=readiness,
        blueprint_sha256=readiness.source.blueprint_sha256,
        proposal=proposal,
        state=state,
        blocker_codes=blocker_codes,
        preview_only=True,
        apply_authority=False,
    )


def _manifest_mapping(value: ManifestEntry) -> dict[str, object]:
    return {"content_sha256": value.content_sha256, "path": value.path}


def _baseline_mapping(value: BaselineEntry) -> dict[str, object]:
    return {"expected_sha256": value.expected_sha256, "path": value.path}


def _gate_mapping(value: MaterializationGate) -> dict[str, object]:
    return {
        "acceptance_ref": value.acceptance_ref,
        "gate_id": value.gate_id,
        "phase": value.phase,
    }


def _proposal_mapping(value: MaterializationProposal) -> dict[str, object]:
    return {
        "acceptance_refs": list(value.acceptance_refs),
        "approval_ref": value.approval_ref,
        "approval_state": value.approval_state.value
        if value.approval_state is not None
        else None,
        "baseline_entries": [_baseline_mapping(item) for item in value.baseline_entries],
        "downstream_root": value.downstream_root,
        "gates": [_gate_mapping(item) for item in value.gates],
        "manifest_entries": [_manifest_mapping(item) for item in value.manifest_entries],
        "manifest_id": value.manifest_id,
        "policy_sha256": value.policy_sha256,
        "proposal_id": value.proposal_id,
        "rollback_id": value.rollback_id,
    }


def _mapping(value: ProjectMaterializationPreview) -> dict[str, object]:
    return {
        "apply_authority": value.apply_authority,
        "blocker_codes": list(value.blocker_codes),
        "blueprint_sha256": value.blueprint_sha256,
        "preview_id": value.preview_id,
        "preview_only": value.preview_only,
        "proposal": _proposal_mapping(value.proposal),
        "schema_version": value.schema_version,
        "source_readiness": json.loads(
            render_implementation_readiness(value.source_readiness).decode("utf-8")
        ),
        "source_readiness_sha256": value.source_readiness_sha256,
        "state": value.state.value,
    }


def render_project_materialization_preview(value: ProjectMaterializationPreview) -> bytes:
    """Render canonical JSON after recomputing the preview state."""

    if type(value) is not ProjectMaterializationPreview:
        raise TypeError("value must be an exact ProjectMaterializationPreview")
    expected = build_project_materialization_preview(
        value.source_readiness, value.proposal
    )
    if expected != value:
        raise ProjectMaterializationError(
            "project materialization preview does not match recomputed evidence"
        )
    try:
        rendered = canonical_json_bytes(_mapping(value))
    except SchemaError as error:
        raise ProjectMaterializationError(
            f"project materialization preview cannot be encoded: {error}"
        ) from error
    if len(rendered) > MAX_PROJECT_MATERIALIZATION_BYTES:
        raise ProjectMaterializationError(
            "rendered project materialization preview exceeds its byte bound"
        )
    return rendered


def _parse_manifest(value: object) -> ManifestEntry:
    item = _closed(value, frozenset({"path", "content_sha256"}), "manifest entry")
    return ManifestEntry(path=_path(item["path"], "manifest entry.path"), content_sha256=_digest(item["content_sha256"], "manifest entry.content_sha256"))


def _parse_baseline(value: object) -> BaselineEntry:
    item = _closed(value, frozenset({"path", "expected_sha256"}), "baseline entry")
    expected = item["expected_sha256"]
    if expected is not None:
        expected = _digest(expected, "baseline entry.expected_sha256")
    return BaselineEntry(path=_path(item["path"], "baseline entry.path"), expected_sha256=expected)


def _parse_gate(value: object) -> MaterializationGate:
    item = _closed(value, frozenset({"gate_id", "phase", "acceptance_ref"}), "gate")
    return MaterializationGate(
        gate_id=_code(item["gate_id"], "gate.gate_id"),
        phase=_code(item["phase"], "gate.phase"),
        acceptance_ref=_code(item["acceptance_ref"], "gate.acceptance_ref"),
    )


def _parse_array(value: object, label: str, maximum: int) -> list[object]:
    if type(value) is not list or len(value) > maximum:
        raise ProjectMaterializationError(f"{label} must be a bounded array")
    return value


def _parse_proposal(value: object) -> MaterializationProposal:
    item = _closed(
        value,
        frozenset(
            {
                "acceptance_refs",
                "approval_ref",
                "approval_state",
                "baseline_entries",
                "downstream_root",
                "gates",
                "manifest_entries",
                "manifest_id",
                "policy_sha256",
                "proposal_id",
                "rollback_id",
            }
        ),
        "proposal",
    )
    root = item["downstream_root"]
    if root is not None:
        root = _root_locator(root, "proposal.downstream_root")
    manifest_id = item["manifest_id"]
    if manifest_id is not None:
        manifest_id = _code(manifest_id, "proposal.manifest_id")
    approval_value = item["approval_state"]
    if approval_value is None:
        approval_state = None
    elif type(approval_value) is str:
        try:
            approval_state = ApprovalState(approval_value)
        except ValueError as error:
            raise ProjectMaterializationError(
                "proposal.approval_state has an unsupported value"
            ) from error
    else:
        raise ProjectMaterializationError("proposal.approval_state must be a string or null")
    approval_ref = item["approval_ref"]
    if approval_ref is not None:
        approval_ref = _code(approval_ref, "proposal.approval_ref")
    rollback_id = item["rollback_id"]
    if rollback_id is not None:
        rollback_id = _code(rollback_id, "proposal.rollback_id")
    policy_sha256 = item["policy_sha256"]
    if policy_sha256 is not None:
        policy_sha256 = _digest(policy_sha256, "proposal.policy_sha256")
    acceptance_refs = tuple(
        _code(entry, f"proposal.acceptance_refs[{index}]")
        for index, entry in enumerate(
            _parse_array(item["acceptance_refs"], "proposal.acceptance_refs", MAX_ACCEPTANCE_REFS)
        )
    )
    return MaterializationProposal(
        proposal_id=_code(item["proposal_id"], "proposal.proposal_id"),
        downstream_root=root,
        manifest_id=manifest_id,
        manifest_entries=tuple(
            _parse_manifest(entry)
            for entry in _parse_array(
                item["manifest_entries"], "proposal.manifest_entries", MAX_MANIFEST_ENTRIES
            )
        ),
        baseline_entries=tuple(
            _parse_baseline(entry)
            for entry in _parse_array(
                item["baseline_entries"], "proposal.baseline_entries", MAX_MANIFEST_ENTRIES
            )
        ),
        approval_state=approval_state,
        approval_ref=approval_ref,
        gates=tuple(
            _parse_gate(entry)
            for entry in _parse_array(item["gates"], "proposal.gates", MAX_GATES)
        ),
        acceptance_refs=acceptance_refs,
        rollback_id=rollback_id,
        policy_sha256=policy_sha256,
    )


def _parse_mapping(value: object) -> ProjectMaterializationPreview:
    item = _closed(
        value,
        frozenset(
            {
                "apply_authority",
                "blocker_codes",
                "blueprint_sha256",
                "preview_id",
                "preview_only",
                "proposal",
                "schema_version",
                "source_readiness",
                "source_readiness_sha256",
                "state",
            }
        ),
        "project materialization preview",
    )
    try:
        readiness = parse_implementation_readiness(
            canonical_json_bytes(item["source_readiness"])
        )
    except (SchemaError, TypeError, ValueError) as error:
        raise ProjectMaterializationError("embedded source_readiness is invalid") from error
    state_value = item["state"]
    if type(state_value) is not str:
        raise ProjectMaterializationError("state must be a string enum value")
    try:
        state = PreviewState(state_value)
    except ValueError as error:
        raise ProjectMaterializationError("state has an unsupported value") from error
    blockers = tuple(
        _code(entry, f"blocker_codes[{index}]")
        for index, entry in enumerate(
            _parse_array(item["blocker_codes"], "blocker_codes", 32)
        )
    )
    return ProjectMaterializationPreview(
        schema_version=_text(item["schema_version"], "schema_version", 16),
        preview_id=_code(item["preview_id"], "preview_id"),
        source_readiness_sha256=_digest(
            item["source_readiness_sha256"], "source_readiness_sha256"
        ),
        source_readiness=readiness,
        blueprint_sha256=_digest(item["blueprint_sha256"], "blueprint_sha256"),
        proposal=_parse_proposal(item["proposal"]),
        state=state,
        blocker_codes=blockers,
        preview_only=item["preview_only"],
        apply_authority=item["apply_authority"],
    )


def parse_project_materialization_preview(
    payload: bytes | bytearray | memoryview,
) -> ProjectMaterializationPreview:
    """Parse only bounded canonical JSON with full P3-C source binding."""

    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise ProjectMaterializationError("project-materialization payload must be bytes")
    raw = bytes(payload)
    if not raw or len(raw) > MAX_PROJECT_MATERIALIZATION_BYTES:
        raise ProjectMaterializationError(
            "project-materialization payload must use bounded non-empty bytes"
        )
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicates,
            parse_constant=_reject_constant,
        )
    except ProjectMaterializationError:
        raise
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
        RecursionError,
    ) as error:
        raise ProjectMaterializationError(
            "project materialization preview is not valid UTF-8 JSON"
        ) from error
    record = _parse_mapping(value)
    if render_project_materialization_preview(record) != raw:
        raise ProjectMaterializationError(
            "project-materialization JSON is not canonical"
        )
    return record


__all__ = [
    "PROJECT_MATERIALIZATION_SCHEMA_VERSION",
    "MAX_PROJECT_MATERIALIZATION_BYTES",
    "ProjectMaterializationError",
    "PreviewState",
    "ApprovalState",
    "ManifestEntry",
    "BaselineEntry",
    "MaterializationGate",
    "MaterializationProposal",
    "ProjectMaterializationPreview",
    "build_project_materialization_preview",
    "render_project_materialization_preview",
    "parse_project_materialization_preview",
]
