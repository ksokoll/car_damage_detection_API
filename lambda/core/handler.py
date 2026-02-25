"""
Lambda entry point - orchestrates validation workflow.

Parses API Gateway events, coordinates contexts (validation, inference, storage),
applies business rules, and formats HTTP responses.

No business logic lives here beyond status determination and response formatting.
"""

import json
import base64
import time
from datetime import datetime, timezone
from typing import Any

from core.validator import validate_image, is_quality_acceptable, get_quality_feedback
from core.inference import predict_damage, get_prediction_summary
from core.storage import save_claim, get_claim, update_claim_status
from core.models import (
    ClaimRecord,
    ClaimStatus,
    InferenceError,
    StorageError,
    ClaimNotFoundError
)
from core.config import QUALITY_THRESHOLD, CONFIDENCE_THRESHOLD, MODEL_VERSION


# --- Lambda Entry Point ---

def lambda_handler(event: dict, context: Any) -> dict:
    """
    AWS Lambda handler for API Gateway HTTP API (v2).

    Routes:
    - POST /claims/validate
    - GET /claims/{claim_id}
    - PUT /claims/{claim_id}/override

    Never raises exceptions — all errors converted to HTTP responses.

    Note: Routing relies on path string matching for simplicity.
    Production would use API Gateway route integration with
    pathParameters instead of manual path parsing.
    """
    try:
        http_method = event["requestContext"]["http"]["method"]
        path = event["requestContext"]["http"]["path"]

        if http_method == "POST" and path.endswith("/validate"):
            return _handle_validate(event)

        if http_method == "GET" and "/claims/" in path and not path.endswith("/override"):
            return _handle_get_claim(event)

        if http_method == "PUT" and path.endswith("/override"):
            return _handle_override(event)

        return _error_response(404, "NOT_FOUND", "Route not found")

    except Exception as e:
        return _error_response(500, "INTERNAL_ERROR", "An unexpected error occurred")


# --- Route Handlers ---

def _handle_validate(event: dict) -> dict:
    """POST /claims/validate — validate image, run inference, persist claim."""
    start_time = time.perf_counter()

    try:
        # 1. Parse request
        body = json.loads(event.get("body", "{}"))

        claim_id = body.get("claim_id")
        customer_id = body.get("customer_id")
        image_base64 = body.get("image")

        if not claim_id:
            return _error_response(400, "VALIDATION_ERROR", "Missing required field: claim_id")
        if not customer_id:
            return _error_response(400, "VALIDATION_ERROR", "Missing required field: customer_id")
        if not image_base64:
            return _error_response(400, "VALIDATION_ERROR", "Missing required field: image")

        # 2. Decode image
        try:
            image_bytes = base64.b64decode(image_base64)
        except Exception:
            return _error_response(400, "INVALID_IMAGE", "Image must be valid base64-encoded data")

        # 3. Validate image (format, size, resolution, quality)
        validation = validate_image(image_bytes)

        if not validation.is_valid:
            return _error_response(
                400,
                "INVALID_IMAGE_FORMAT",
                validation.error_message or "Image validation failed",
            )

        # 4. Check quality threshold
        if not is_quality_acceptable(validation):
            return _error_response(
                400,
                "QUALITY_TOO_LOW",
                "Image quality insufficient for automated processing",
                details={
                    "quality_score": validation.quality.overall,
                    "quality_breakdown": {
                        "sharpness": validation.quality.sharpness,
                        "brightness": validation.quality.brightness,
                        "contrast": validation.quality.contrast,
                    },
                    "issues": validation.quality.issues,
                },
                feedback=get_quality_feedback(validation),
            )

        # 5. Run inference
        prediction = predict_damage(image_bytes)

        # 6. Determine status
        status = _determine_status(prediction)

        # 7. Build claim record
        claim = ClaimRecord(
            claim_id=claim_id,
            customer_id=customer_id,
            damage_detected=prediction.damage_detected,
            confidence=prediction.confidence,
            quality_score=validation.quality.overall,
            system_status=status,
            effective_status=status,
            timestamp=datetime.now(timezone.utc).isoformat(),
            processing_time_ms=int((time.perf_counter() - start_time) * 1000),
            model_version=MODEL_VERSION,
        )

        # 8. Persist
        saved = save_claim(claim)

        # 9. Response
        response_data = {
            "claim_id": saved.claim_id,
            "effective_status": saved.effective_status,
            "result": {
                "damage_detected": saved.damage_detected,
                "confidence": saved.confidence,
                "quality_score": saved.quality_score,
                "quality_breakdown": {
                    "sharpness": validation.quality.sharpness,
                    "brightness": validation.quality.brightness,
                    "contrast": validation.quality.contrast,
                },
            },
            "message": _status_message(saved),
            "user_override_allowed": _is_override_allowed(saved),
            "next_steps": _next_steps(saved),
            "processing_time_ms": saved.processing_time_ms,
            "timestamp": saved.timestamp,
        }

        if status == ClaimStatus.REJECTED:
            response_data["reason"] = _rejection_reason(saved)

        return _success_response(200, response_data)

    except InferenceError:
        return _error_response(500, "INFERENCE_ERROR", "Model processing failed")

    except StorageError as e:
        return _error_response(500, "STORAGE_ERROR", str(e))

    except Exception:
        return _error_response(500, "INTERNAL_ERROR", "Unexpected error during validation")


def _handle_get_claim(event: dict) -> dict:
    """GET /claims/{claim_id} — retrieve claim details with audit trail."""
    try:
        path = event["requestContext"]["http"]["path"]
        claim_id = path.rstrip("/").split("/")[-1]

        claim = get_claim(claim_id)

        if claim is None:
            return _error_response(404, "CLAIM_NOT_FOUND", f"No claim found with ID: {claim_id}")

        response_data = {
            "claim_id": claim.claim_id,
            "customer_id": claim.customer_id,
            "effective_status": claim.effective_status,
            "system_status": claim.system_status,
            "result": {
                "damage_detected": claim.damage_detected,
                "confidence": claim.confidence,
                "quality_score": claim.quality_score,
            },
            "user_override": claim.user_override,
            "submitted_at": claim.timestamp,
            "processing_time_ms": claim.processing_time_ms,
        }

        if claim.user_override:
            response_data["override_timestamp"] = claim.override_timestamp
            response_data["override_reason"] = claim.override_reason

        return _success_response(200, response_data)

    except StorageError:
        return _error_response(500, "STORAGE_ERROR", "Failed to retrieve claim")

    except Exception:
        return _error_response(500, "INTERNAL_ERROR", "Unexpected error")


def _handle_override(event: dict) -> dict:
    """PUT /claims/{claim_id}/override — user overrides AI rejection."""
    try:
        path = event["requestContext"]["http"]["path"]
        # /v1/claims/{claim_id}/override → split and take second-to-last
        parts = path.rstrip("/").split("/")
        claim_id = parts[-2]

        body = json.loads(event.get("body", "{}"))
        reason = body.get("reason")

        if not reason:
            return _error_response(400, "VALIDATION_ERROR", "Missing required field: reason")

        updated = update_claim_status(
            claim_id=claim_id,
            new_status=ClaimStatus.APPROVED,
            override_reason=reason,
        )

        return _success_response(200, {
            "claim_id": updated.claim_id,
            "effective_status": updated.effective_status,
            "system_status": updated.system_status,
            "user_override": updated.user_override,
            "override_timestamp": updated.override_timestamp,
            "override_reason": updated.override_reason,
            "message": "Claim status updated. Flagged for manual review during processing.",
        })

    except ClaimNotFoundError as e:
        return _error_response(404, "CLAIM_NOT_FOUND", str(e))
    except StorageError:
        return _error_response(500, "STORAGE_ERROR", "Failed to update claim")
    except Exception:
        return _error_response(500, "INTERNAL_ERROR", "Unexpected error")


# --- Business Logic ---

def _determine_status(prediction) -> ClaimStatus:
    """
    Final claim status based on prediction.

    Quality is already checked before this point.
    Only high-confidence damage detection results in approval.
    """
    if prediction.confidence >= CONFIDENCE_THRESHOLD and prediction.damage_detected:
        return ClaimStatus.APPROVED
    return ClaimStatus.REJECTED


def _is_override_allowed(claim: ClaimRecord) -> bool:
    """
    Override allowed for any rejected claim.

    Quality check is not repeated here — images already passed
    quality validation at POST /validate time. The user knows
    their damage better than the model does.
    """
    return claim.effective_status == ClaimStatus.REJECTED


def _status_message(claim: ClaimRecord) -> str:
    if claim.effective_status == ClaimStatus.APPROVED:
        return "Damage detected. Claim approved for processing."
    return "Claim rejected. See reason and next_steps for details."


def _rejection_reason(claim: ClaimRecord) -> str:
    if not claim.damage_detected and claim.confidence >= CONFIDENCE_THRESHOLD:
        return "no_damage"
    if claim.confidence < CONFIDENCE_THRESHOLD:
        return "low_confidence"
    return "unknown"


def _next_steps(claim: ClaimRecord) -> str:
    if claim.effective_status == ClaimStatus.APPROVED:
        return "Your claim will be reviewed by an adjuster within 2 business days."
    if _is_override_allowed(claim):
        return "If you believe damage is visible, you can override this decision or upload a different photo."
    return "Please upload a higher quality image to proceed."


# --- Response Helpers ---

def _success_response(status_code: int, data: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(data),
    }


def _error_response(
    status_code: int,
    code: str,
    message: str,
    details: dict | str | None = None,
    feedback: str | None = None,
) -> dict:
    error_body: dict[str, Any] = {
        "error": {
            "code": code,
            "message": message,
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if details is not None:
        error_body["error"]["details"] = details

    if feedback is not None:
        error_body["error"]["feedback"] = feedback

    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(error_body),
    }