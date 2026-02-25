"""
Domain models for the car damage detection system.

All Pydantic models in one place. Imported by validator, inference,
storage, and handler modules. Single source of truth for data contracts.
"""

from enum import Enum
from pydantic import BaseModel, Field


# --- Domain Enums ---

class ClaimStatus(str, Enum):
    """
    Valid claim statuses. Inherits str so Pydantic serializes
    to "APPROVED" / "REJECTED" without extra conversion.
    """
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


# --- Validation Context ---

class QualityMetrics(BaseModel):
    """Technical image quality scores."""
    overall: float = Field(0.0, ge=0.0, le=1.0)
    sharpness: float = Field(0.0, ge=0.0, le=1.0)
    brightness: float = Field(0.0, ge=0.0, le=1.0)
    contrast: float = Field(0.0, ge=0.0, le=1.0)
    issues: list[str] = []


class ValidationResult(BaseModel):
    """Result of image validation and quality assessment."""
    is_valid: bool
    error_message: str | None = None

    format: str | None = None
    size_bytes: int | None = Field(None, ge=0)
    resolution: tuple[int, int] | None = None

    quality: QualityMetrics = QualityMetrics()


# --- Inference Context ---

class PredictionResult(BaseModel):
    """ML model prediction output."""
    damage_detected: bool
    confidence: float = Field(ge=0.0, le=1.0)
    probabilities: dict[str, float] = {}


# --- Storage Context ---

class ClaimRecord(BaseModel):
    """Persisted claim data in DynamoDB."""
    claim_id: str
    customer_id: str

    # AI results
    damage_detected: bool
    confidence: float = Field(ge=0.0, le=1.0)
    quality_score: float = Field(ge=0.0, le=1.0)

    # Status — typed via enum, no magic strings
    system_status: ClaimStatus   # immutable (original AI decision)
    effective_status: ClaimStatus  # mutable via user override

    # Override
    user_override: bool = False
    override_timestamp: str | None = None
    override_reason: str | None = None

    # Metadata
    timestamp: str
    processing_time_ms: int = Field(ge=0)
    model_version: str


# --- Exceptions ---

class ValidationError(Exception):
    """Image is fundamentally invalid (corrupt, unreadable)."""
    pass


class InferenceError(Exception):
    """Model execution failed."""
    pass


class StorageError(Exception):
    """Database operation failed."""
    pass


class ClaimNotFoundError(Exception):
    """Requested claim does not exist."""
    pass


class OverrideNotAllowedError(Exception):
    """Override blocked by business rules (e.g. quality too low)."""
    pass