"""Closed, immutable P3-A user-intent contract and bounded idea intake."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
from pathlib import PurePosixPath
import re
from typing import Any, Mapping
import unicodedata

from .storage import SchemaError, canonical_json_bytes


USER_INTENT_SCHEMA_VERSION = "1.0"
MAX_IDEA_BYTES = 4 * 1024
MAX_USER_INTENT_BYTES = 64 * 1024

_MAX_CODES = 16
_MAX_EVIDENCE_REFS = 64
_MAX_CODE_LENGTH = 80
_MAX_REFERENCE_LENGTH = 240
_CODE = re.compile(r"[a-z0-9][a-z0-9._-]{0,79}\Z")
_WINDOWS_DRIVE = re.compile(r"[A-Za-z]:")
_WINDOWS_PATH = re.compile(r"(?:^|\s)(?:[A-Za-z]:[\\/]|\\\\)[^\s]*")
_POSIX_PATH = re.compile(r"(?:^|\s)/(?:[^\s/]+/)*[^\s/]+")
_PATH_TRAVERSAL = re.compile(r"(?:^|[\s/])\.\.(?:[/\s]|$)")
_CREDENTIAL_ASSIGNMENT = re.compile(
    r"\b(?:password|passwd|secret|api[-_. ]?key|access[-_. ]?token|"
    r"refresh[-_. ]?token|session[-_. ]?id|private[-_. ]?key)\s*[:=]\s*\S+",
    re.IGNORECASE,
)
_BEARER_VALUE = re.compile(r"\bbearer\s+[A-Za-z0-9._~-]{8,}", re.IGNORECASE)
_OPAQUE_SECRET = re.compile(
    r"(?:\bsk-[A-Za-z0-9_-]{8,}|\bghp_[A-Za-z0-9]{8,}|"
    r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.)"
)
_PROVIDER_NETWORK_PATTERN = re.compile(
    r"(?:\b(?:use|using|call|calling|connect|connecting|integrate|integrating|via)\b"
    r".{0,40}\b(?:api|provider|service)\b|"
    r"\b(?:openai|anthropic|gemini|stripe|twilio|sendgrid|aws|azure|"
    r"google cloud)\b|"
    r"(?:\u8c03\u7528|\u63a5\u5165|\u8fde\u63a5).{0,20}"
    r"(?:api|\u63a5\u53e3|\u670d\u52a1))",
    re.IGNORECASE,
)

_TOP_LEVEL_FIELDS = frozenset(
    {
        "constraint_codes",
        "evidence_refs",
        "goal_codes",
        "intent_id",
        "project_type",
        "schema_version",
        "target_platform",
        "uncertainty_codes",
        "user_persona",
    }
)


class UserIntentError(ValueError):
    """Raised when idea bytes or user-intent records violate P3-A."""


class ProjectType(str, Enum):
    APPLICATION = "application"
    WEBSITE = "website"
    AUTOMATION = "automation"
    API = "api"
    LIBRARY = "library"
    DATA_PIPELINE = "data-pipeline"
    DOCUMENT = "document"
    UNKNOWN = "unknown"


class TargetPlatform(str, Enum):
    WEB = "web"
    DESKTOP = "desktop"
    MOBILE = "mobile"
    CLI = "cli"
    SERVER = "server"
    CLOUD = "cloud"
    EMBEDDED = "embedded"
    MULTI_PLATFORM = "multi-platform"
    UNKNOWN = "unknown"


class UserPersona(str, Enum):
    INDIVIDUAL = "individual"
    TEAM = "team"
    ORGANIZATION = "organization"
    PUBLIC = "public"
    UNKNOWN = "unknown"


class GoalCode(str, Enum):
    BUILD_PRODUCT = "build-product"
    AUTOMATE_WORKFLOW = "automate-workflow"
    ORGANIZE_INFORMATION = "organize-information"
    ANALYZE_DATA = "analyze-data"
    PUBLISH_CONTENT = "publish-content"
    INTEGRATE_SYSTEMS = "integrate-systems"
    LEARN_OR_PROTOTYPE = "learn-or-prototype"


class ConstraintCode(str, Enum):
    COST = "cost"
    PRODUCTION = "production"
    PRIVACY = "privacy"
    REAL_DATA = "real-data"
    PROVIDER_NETWORK = "provider-network"
    PUBLICATION = "publication"
    DEPLOYMENT = "deployment"
    IRREVERSIBLE_EXTERNAL_ACTION = "irreversible-external-action"
    OFFLINE = "offline"
    FAST_DELIVERY = "fast-delivery"
    ACCESSIBILITY = "accessibility"


class UncertaintyCode(str, Enum):
    PROJECT_TYPE = "project-type"
    TARGET_PLATFORM = "target-platform"
    USER_PERSONA = "user-persona"
    PRODUCT_DIRECTION = "product-direction"


def _scalar(value: object, label: str, *, maximum: int) -> str:
    if type(value) is not str or not value:
        raise UserIntentError(f"{label} must be a non-empty string")
    if len(value) > maximum:
        raise UserIntentError(f"{label} exceeds its {maximum}-character bound")
    if unicodedata.normalize("NFC", value) != value:
        raise UserIntentError(f"{label} must use NFC Unicode")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        raise UserIntentError(f"{label} contains control characters")
    if (
        _CREDENTIAL_ASSIGNMENT.search(value)
        or _BEARER_VALUE.search(value)
        or _OPAQUE_SECRET.search(value)
    ):
        raise UserIntentError(f"{label} contains a sensitive-value pattern")
    return value


def _code(value: object, label: str) -> str:
    text = _scalar(value, label, maximum=_MAX_CODE_LENGTH)
    if not _CODE.fullmatch(text):
        raise UserIntentError(f"{label} must be a bounded stable code")
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
    raise UserIntentError(
        f"{label} must be a stable code or contained project-relative path"
    )


def _require_enum(value: object, enum_type: type[Enum], label: str) -> None:
    if not isinstance(value, enum_type):
        raise UserIntentError(f"{label} must be a {enum_type.__name__}")


def _enum_value(enum_type: type[Enum], value: object, label: str) -> Enum:
    if type(value) is not str:
        raise UserIntentError(f"{label} must be a string enum value")
    try:
        return enum_type(value)
    except ValueError as error:
        raise UserIntentError(f"{label} has an unsupported value") from error


def _enum_tuple(
    value: object,
    enum_type: type[Enum],
    label: str,
    *,
    allow_empty: bool = False,
) -> tuple[Enum, ...]:
    if type(value) is not tuple or len(value) > _MAX_CODES:
        raise UserIntentError(f"{label} must be a bounded immutable tuple")
    if not allow_empty and not value:
        raise UserIntentError(f"{label} must not be empty")
    if any(not isinstance(item, enum_type) for item in value):
        raise UserIntentError(f"{label} must contain {enum_type.__name__} values")
    canonical = tuple(sorted(set(value), key=lambda item: item.value))
    if value != canonical:
        raise UserIntentError(f"{label} must use canonical unique order")
    return value


def _reference_tuple(value: object, label: str) -> tuple[str, ...]:
    if type(value) is not tuple or len(value) > _MAX_EVIDENCE_REFS:
        raise UserIntentError(f"{label} must be a bounded immutable tuple")
    normalized = tuple(
        _reference(item, f"{label}[{index}]") for index, item in enumerate(value)
    )
    if normalized != tuple(sorted(set(normalized))):
        raise UserIntentError(f"{label} must use canonical unique order")
    return normalized


@dataclass(frozen=True)
class UserIntent:
    """Normalized intent codes; raw idea text and prompt digests are excluded."""

    schema_version: str
    intent_id: str
    project_type: ProjectType
    target_platform: TargetPlatform
    user_persona: UserPersona
    goal_codes: tuple[GoalCode, ...]
    constraint_codes: tuple[ConstraintCode, ...]
    uncertainty_codes: tuple[UncertaintyCode, ...]
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self) is not UserIntent:
            raise UserIntentError("UserIntent subclasses are not accepted")
        if self.schema_version != USER_INTENT_SCHEMA_VERSION:
            raise UserIntentError("unsupported user-intent schema_version")
        _code(self.intent_id, "intent_id")
        _require_enum(self.project_type, ProjectType, "project_type")
        _require_enum(self.target_platform, TargetPlatform, "target_platform")
        _require_enum(self.user_persona, UserPersona, "user_persona")
        _enum_tuple(
            self.goal_codes, GoalCode, "goal_codes", allow_empty=True
        )
        _enum_tuple(
            self.constraint_codes,
            ConstraintCode,
            "constraint_codes",
            allow_empty=True,
        )
        _enum_tuple(
            self.uncertainty_codes,
            UncertaintyCode,
            "uncertainty_codes",
            allow_empty=True,
        )
        _reference_tuple(self.evidence_refs, "evidence_refs")

        expected: set[UncertaintyCode] = set()
        if self.project_type is ProjectType.UNKNOWN:
            expected.add(UncertaintyCode.PROJECT_TYPE)
        if self.target_platform is TargetPlatform.UNKNOWN:
            expected.add(UncertaintyCode.TARGET_PLATFORM)
        if self.user_persona is UserPersona.UNKNOWN:
            expected.add(UncertaintyCode.USER_PERSONA)
        if not self.goal_codes:
            expected.add(UncertaintyCode.PRODUCT_DIRECTION)
        if not expected.issubset(self.uncertainty_codes):
            missing = ", ".join(
                item.value for item in sorted(expected, key=lambda item: item.value)
            )
            raise UserIntentError(
                f"uncertainty_codes omit inferred uncertainty: {missing}"
            )


def _idea_text(payload: bytes | bytearray | memoryview) -> str:
    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise UserIntentError("idea payload must be caller-owned bytes")
    raw = bytes(payload)
    if not raw or len(raw) > MAX_IDEA_BYTES:
        raise UserIntentError("idea payload must use bounded non-empty bytes")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise UserIntentError("idea payload must be valid UTF-8") from error
    if text != text.strip() or unicodedata.normalize("NFC", text) != text:
        raise UserIntentError("idea payload must use trimmed NFC text")
    _scalar(text, "idea payload", maximum=MAX_IDEA_BYTES)
    if (
        _WINDOWS_PATH.search(text)
        or _POSIX_PATH.search(text)
        or _PATH_TRAVERSAL.search(text)
    ):
        raise UserIntentError("idea payload must not contain a filesystem path")
    if "://" in text:
        raise UserIntentError("idea payload must not contain a network locator")
    return text.casefold()


def _contains(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _classify_project_type(text: str) -> ProjectType:
    specific_groups = (
        (
            ProjectType.WEBSITE,
            ("website", "web site", "landing page", "\u7f51\u7ad9", "\u7f51\u9875"),
        ),
        (
            ProjectType.AUTOMATION,
            ("automation", "automate", "workflow", "\u81ea\u52a8\u5316", "\u5de5\u4f5c\u6d41"),
        ),
        (
            ProjectType.API,
            (
                "build an api",
                "build api",
                "api service",
                "api server",
                "webhook",
                "service endpoint",
                "\u63a5\u53e3\u670d\u52a1",
            ),
        ),
        (ProjectType.LIBRARY, ("library", "sdk", "package", "\u7a0b\u5e8f\u5e93")),
        (
            ProjectType.DATA_PIPELINE,
            ("pipeline", "etl", "data processing", "\u6570\u636e\u7ba1\u9053", "\u6570\u636e\u5904\u7406"),
        ),
        (
            ProjectType.DOCUMENT,
            ("document", "report", "spreadsheet", "\u6587\u6863", "\u62a5\u544a", "\u8868\u683c"),
        ),
    )
    padded = f" {text} "
    matches = tuple(
        kind for kind, terms in specific_groups if _contains(padded, terms)
    )
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        return ProjectType.UNKNOWN
    if _contains(
        padded,
        ("application", " app ", "software", "tool", "\u8f6f\u4ef6", "\u5e94\u7528", "\u5de5\u5177"),
    ):
        return ProjectType.APPLICATION
    return ProjectType.UNKNOWN


def _classify_platform(text: str) -> TargetPlatform:
    groups = (
        (TargetPlatform.WEB, ("browser", "website", "web app", "\u7f51\u9875", "\u6d4f\u89c8\u5668")),
        (TargetPlatform.DESKTOP, ("desktop", "windows app", "mac app", "\u684c\u9762", "windows")),
        (TargetPlatform.MOBILE, ("mobile", "android", "ios", "\u624b\u673a", "\u79fb\u52a8\u7aef")),
        (TargetPlatform.CLI, ("command line", "terminal", " cli ", "\u547d\u4ee4\u884c", "\u7ec8\u7aef")),
        (TargetPlatform.SERVER, ("server", "backend", "\u670d\u52a1\u7aef", "\u540e\u7aef")),
        (TargetPlatform.CLOUD, ("cloud", "serverless", "\u4e91\u7aef", "\u4e91\u670d\u52a1")),
        (TargetPlatform.EMBEDDED, ("embedded", "device", "\u5d4c\u5165\u5f0f", "\u8bbe\u5907\u7aef")),
    )
    padded = f" {text} "
    matches = tuple(platform for platform, terms in groups if _contains(padded, terms))
    if len(matches) > 1:
        return TargetPlatform.MULTI_PLATFORM
    return matches[0] if matches else TargetPlatform.UNKNOWN


def _classify_persona(text: str) -> UserPersona:
    if _contains(text, ("public users", "customers", "everyone", "\u516c\u4f17", "\u5ba2\u6237")):
        return UserPersona.PUBLIC
    if _contains(text, ("company", "enterprise", "organization", "\u516c\u53f8", "\u4f01\u4e1a", "\u7ec4\u7ec7")):
        return UserPersona.ORGANIZATION
    if _contains(text, ("team", "colleagues", "\u56e2\u961f", "\u540c\u4e8b")):
        return UserPersona.TEAM
    if _contains(text, ("for me", "personal", "my own", "\u7ed9\u6211", "\u4e2a\u4eba", "\u81ea\u5df1\u7528")):
        return UserPersona.INDIVIDUAL
    return UserPersona.UNKNOWN


def _classify_goals(text: str) -> tuple[GoalCode, ...]:
    groups = (
        (GoalCode.AUTOMATE_WORKFLOW, ("automate", "automation", "workflow", "\u81ea\u52a8", "\u5de5\u4f5c\u6d41")),
        (GoalCode.ANALYZE_DATA, ("analyze", "analytics", "dashboard", "\u5206\u6790", "\u770b\u677f")),
        (GoalCode.ORGANIZE_INFORMATION, ("organize", "manage", "catalog", "\u6574\u7406", "\u7ba1\u7406", "\u5f52\u6863")),
        (GoalCode.PUBLISH_CONTENT, ("publish", "share publicly", "\u53d1\u5e03", "\u516c\u5f00")),
        (GoalCode.INTEGRATE_SYSTEMS, ("integrate", "connect", "sync", "\u96c6\u6210", "\u8fde\u63a5", "\u540c\u6b65")),
        (GoalCode.LEARN_OR_PROTOTYPE, ("learn", "prototype", "experiment", "\u5b66\u4e60", "\u539f\u578b", "\u5b9e\u9a8c")),
        (GoalCode.BUILD_PRODUCT, ("build", "create", "make", "\u5f00\u53d1", "\u521b\u5efa", "\u505a\u4e00\u4e2a")),
    )
    result = {code for code, terms in groups if _contains(text, terms)}
    return tuple(sorted(result, key=lambda item: item.value))


def _classify_constraints(text: str) -> tuple[ConstraintCode, ...]:
    groups = (
        (ConstraintCode.COST, ("budget", "cost", "cheap", "\u9884\u7b97", "\u6210\u672c", "\u7701\u94b1")),
        (ConstraintCode.PRODUCTION, ("production", "live users", "\u6b63\u5f0f\u73af\u5883", "\u751f\u4ea7\u73af\u5883", "\u4e0a\u7ebf")),
        (ConstraintCode.PRIVACY, ("privacy", "personal data", "pii", "\u9690\u79c1", "\u4e2a\u4eba\u4fe1\u606f")),
        (ConstraintCode.REAL_DATA, ("real data", "customer data", "\u771f\u5b9e\u6570\u636e", "\u5ba2\u6237\u6570\u636e")),
        (ConstraintCode.PROVIDER_NETWORK, ("provider", "third-party api", "network call", "\u4f9b\u5e94\u5546", "\u7b2c\u4e09\u65b9\u63a5\u53e3", "\u8054\u7f51")),
        (ConstraintCode.PUBLICATION, ("publish", "public release", "\u516c\u5f00\u53d1\u5e03", "\u53d1\u5e03\u5230")),
        (ConstraintCode.DEPLOYMENT, ("deploy", "hosting", "\u4e0a\u7ebf", "\u90e8\u7f72", "\u6258\u7ba1")),
        (ConstraintCode.IRREVERSIBLE_EXTERNAL_ACTION, ("send email", "charge", "delete account", "\u53d1\u9001\u90ae\u4ef6", "\u6263\u6b3e", "\u5220\u9664\u8d26\u53f7")),
        (ConstraintCode.OFFLINE, ("offline", "local only", "\u79bb\u7ebf", "\u4ec5\u672c\u5730")),
        (ConstraintCode.FAST_DELIVERY, ("quickly", "asap", "today", "\u5c3d\u5feb", "\u9a6c\u4e0a", "\u4eca\u5929")),
        (ConstraintCode.ACCESSIBILITY, ("accessibility", "screen reader", "\u65e0\u969c\u788d", "\u8bfb\u5c4f")),
    )
    result = {code for code, terms in groups if _contains(text, terms)}
    if _PROVIDER_NETWORK_PATTERN.search(text):
        result.add(ConstraintCode.PROVIDER_NETWORK)
    return tuple(sorted(result, key=lambda item: item.value))


def build_user_intent(
    idea: bytes | bytearray | memoryview,
    *,
    intent_id: str = "intent.user-idea",
    evidence_refs: tuple[str, ...] = (),
) -> UserIntent:
    """Apply deterministic bounded keyword extraction, not arbitrary NLP proof.

    The returned record contains only normalized codes and caller-supplied evidence
    references. Raw idea text and raw-text digests are neither retained nor rendered.
    Unmatched or conflicting concepts remain explicit uncertainty.
    """

    text = _idea_text(idea)
    project_type = _classify_project_type(text)
    target_platform = _classify_platform(text)
    user_persona = _classify_persona(text)
    goals = _classify_goals(text)
    uncertainties: set[UncertaintyCode] = set()
    if project_type is ProjectType.UNKNOWN:
        uncertainties.add(UncertaintyCode.PROJECT_TYPE)
    if target_platform is TargetPlatform.UNKNOWN:
        uncertainties.add(UncertaintyCode.TARGET_PLATFORM)
    if user_persona is UserPersona.UNKNOWN:
        uncertainties.add(UncertaintyCode.USER_PERSONA)
    if not goals:
        uncertainties.add(UncertaintyCode.PRODUCT_DIRECTION)
    return UserIntent(
        schema_version=USER_INTENT_SCHEMA_VERSION,
        intent_id=_code(intent_id, "intent_id"),
        project_type=project_type,
        target_platform=target_platform,
        user_persona=user_persona,
        goal_codes=goals,
        constraint_codes=_classify_constraints(text),
        uncertainty_codes=tuple(sorted(uncertainties, key=lambda item: item.value)),
        evidence_refs=_reference_tuple(evidence_refs, "evidence_refs"),
    )


def _mapping(record: UserIntent) -> dict[str, object]:
    return {
        "constraint_codes": [item.value for item in record.constraint_codes],
        "evidence_refs": list(record.evidence_refs),
        "goal_codes": [item.value for item in record.goal_codes],
        "intent_id": record.intent_id,
        "project_type": record.project_type.value,
        "schema_version": record.schema_version,
        "target_platform": record.target_platform.value,
        "uncertainty_codes": [item.value for item in record.uncertainty_codes],
        "user_persona": record.user_persona.value,
    }


def render_user_intent(record: UserIntent) -> bytes:
    """Render one validated user intent to canonical UTF-8 JSON bytes."""

    if type(record) is not UserIntent:
        raise TypeError("record must be an exact UserIntent")
    try:
        rendered = canonical_json_bytes(_mapping(record))
    except SchemaError as error:
        raise UserIntentError(f"user intent cannot be encoded: {error}") from error
    if len(rendered) > MAX_USER_INTENT_BYTES:
        raise UserIntentError("rendered user intent exceeds its byte bound")
    return rendered


def _closed_mapping(
    value: object, fields: frozenset[str], label: str
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise UserIntentError(f"{label} must be an object")
    keys = set(value)
    if any(type(key) is not str for key in keys):
        raise UserIntentError(f"{label} field names must be strings")
    unknown = sorted(keys - fields)
    missing = sorted(fields - keys)
    if unknown:
        raise UserIntentError(f"{label} contains unknown fields: {', '.join(unknown)}")
    if missing:
        raise UserIntentError(f"{label} is missing fields: {', '.join(missing)}")
    return value


def _sequence(value: object, label: str, maximum: int) -> tuple[object, ...]:
    if type(value) is not list or len(value) > maximum:
        raise UserIntentError(f"{label} must be a bounded array")
    return tuple(value)


def _parse_enum_sequence(
    value: object, enum_type: type[Enum], label: str
) -> tuple[Enum, ...]:
    items = _sequence(value, label, _MAX_CODES)
    return tuple(
        _enum_value(enum_type, item, f"{label}[{index}]")
        for index, item in enumerate(items)
    )


def _parse_mapping(value: object) -> UserIntent:
    item = _closed_mapping(value, _TOP_LEVEL_FIELDS, "user_intent")
    version = item["schema_version"]
    if version != USER_INTENT_SCHEMA_VERSION:
        raise UserIntentError("unsupported user-intent schema_version")
    refs = _sequence(item["evidence_refs"], "evidence_refs", _MAX_EVIDENCE_REFS)
    return UserIntent(
        schema_version=version,
        intent_id=_code(item["intent_id"], "intent_id"),
        project_type=_enum_value(ProjectType, item["project_type"], "project_type"),
        target_platform=_enum_value(
            TargetPlatform, item["target_platform"], "target_platform"
        ),
        user_persona=_enum_value(UserPersona, item["user_persona"], "user_persona"),
        goal_codes=_parse_enum_sequence(item["goal_codes"], GoalCode, "goal_codes"),
        constraint_codes=_parse_enum_sequence(
            item["constraint_codes"], ConstraintCode, "constraint_codes"
        ),
        uncertainty_codes=_parse_enum_sequence(
            item["uncertainty_codes"], UncertaintyCode, "uncertainty_codes"
        ),
        evidence_refs=tuple(
            _reference(ref, f"evidence_refs[{index}]")
            for index, ref in enumerate(refs)
        ),
    )


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise UserIntentError("user intent contains duplicate object fields")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise UserIntentError(f"user intent contains unsupported JSON constant: {value}")


def parse_user_intent(payload: bytes | bytearray | memoryview) -> UserIntent:
    """Parse only bounded canonical UTF-8 JSON bytes into an immutable intent."""

    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise UserIntentError("user-intent payload must be bytes")
    raw = bytes(payload)
    if not raw or len(raw) > MAX_USER_INTENT_BYTES:
        raise UserIntentError("user-intent payload must use bounded non-empty bytes")
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicates,
            parse_constant=_reject_constant,
        )
    except UserIntentError:
        raise
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
        TypeError,
        RecursionError,
    ) as error:
        raise UserIntentError("user intent is not valid UTF-8 JSON") from error
    record = _parse_mapping(value)
    if render_user_intent(record) != raw:
        raise UserIntentError("user-intent JSON is not canonical")
    return record


intake_user_idea = build_user_intent
structure_user_intent = build_user_intent


__all__ = [
    "ConstraintCode",
    "GoalCode",
    "MAX_IDEA_BYTES",
    "MAX_USER_INTENT_BYTES",
    "ProjectType",
    "TargetPlatform",
    "USER_INTENT_SCHEMA_VERSION",
    "UncertaintyCode",
    "UserIntent",
    "UserIntentError",
    "UserPersona",
    "build_user_intent",
    "intake_user_idea",
    "parse_user_intent",
    "render_user_intent",
    "structure_user_intent",
]
