"""IR-2 Foundation Registry V1 public contract interfaces."""

from .registry import ENVELOPE_SCHEMA_ID, FOUNDATION_CONTRACT_IDS, REGISTRY
from .business_registry import BUSINESS_ARTIFACT_IDS, BUSINESS_REGISTRY
from .envelope import ContractEnvelope, ProducerIdentity, build_envelope
from .errors import ContractError, ErrorCategory, ErrorCode
from .serialization import parse_json_object
from .validation import validate_envelope, validate_payload

__all__ = [
    "ContractEnvelope",
    "ContractError",
    "BUSINESS_ARTIFACT_IDS",
    "BUSINESS_REGISTRY",
    "ENVELOPE_SCHEMA_ID",
    "FOUNDATION_CONTRACT_IDS",
    "ErrorCategory",
    "ErrorCode",
    "ProducerIdentity",
    "REGISTRY",
    "build_envelope",
    "parse_json_object",
    "validate_envelope",
    "validate_payload",
]
