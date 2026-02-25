"""
Unit tests for handler module (lambda entry point)

Tests cover:
- Route dispatching (POST /validate, GET /claims/{id}, PUT /claims/{id}/override)
- Business logic (_determine_status, _is_override_allowed)
- Error mapping (Exception types → HTTP status codes)
- Response formatting
- Edge cases and missing fields
"""

import json
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from core.handler import (
    lambda_handler,
    _determine_status,
    _is_override_allowed,
    _status_message,
    _rejection_reason,
    _next_steps,
)
from core.models import (
    ClaimRecord,
    PredictionResult,
    InferenceError,
    StorageError,
    ClaimNotFoundError,
    OverrideNotAllowedError,
)
from core.config import QUALITY_THRESHOLD, CONFIDENCE_THRESHOLD


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def valid_image_base64():
    """Small but valid base64-encoded JPEG"""
    from PIL import Image
    import io
    import base64
    img = Image.new("RGB", (600, 600), color="red")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return base64.b64encode(buf.getvalue()).decode()


@pytest.fixture
def validate_event(valid_image_base64):
    """Minimal valid POST /claims/validate event"""
    return {
        "requestContext": {"http": {"method": "POST", "path": "/v1/claims/validate"}},
        "body": json.dumps({
            "claim_id": "CLM-001",
            "customer_id": "CUST-42",
            "image": valid_image_base64,
        }),
    }


@pytest.fixture
def get_event():
    """GET /claims/{claim_id} event"""
    return {
        "requestContext": {"http": {"method": "GET", "path": "/v1/claims/CLM-001"}},
        "body": None,
    }


@pytest.fixture
def override_event():
    """PUT /claims/{claim_id}/override event"""
    return {
        "requestContext": {"http": {"method": "PUT", "path": "/v1/claims/CLM-001/override"}},
        "body": json.dumps({"reason": "Damage clearly visible on bumper"}),
    }


@pytest.fixture
def approved_claim():
    return ClaimRecord(
        claim_id="CLM-001",
        customer_id="CUST-42",
        damage_detected=True,
        confidence=0.94,
        quality_score=0.85,
        system_status="APPROVED",
        effective_status="APPROVED",
        timestamp=datetime.now(timezone.utc).isoformat(),
        processing_time_ms=120,
        model_version="v1",
    )


@pytest.fixture
def rejected_claim():
    return ClaimRecord(
        claim_id="CLM-002",
        customer_id="CUST-99",
        damage_detected=False,
        confidence=0.88,
        quality_score=0.75,
        system_status="REJECTED",
        effective_status="REJECTED",
        timestamp=datetime.now(timezone.utc).isoformat(),
        processing_time_ms=95,
        model_version="v1",
    )


@pytest.fixture
def overridden_claim(rejected_claim):
    rejected_claim.user_override = True
    rejected_claim.effective_status = "APPROVED"
    rejected_claim.override_reason = "Damage visible on hood"
    rejected_claim.override_timestamp = datetime.now(timezone.utc).isoformat()
    return rejected_claim


@pytest.fixture
def high_confidence_prediction():
    return PredictionResult(damage_detected=True, confidence=0.94)


@pytest.fixture
def low_confidence_prediction():
    return PredictionResult(damage_detected=True, confidence=0.55)


# ============================================================================
# ROUTE DISPATCHING
# ============================================================================

class TestRouteDispatching:
    """Lambda handler correctly routes to the right handler"""

    def test_unknown_route_returns_404(self):
        event = {
            "requestContext": {"http": {"method": "DELETE", "path": "/v1/claims/CLM-001"}},
            "body": None,
        }
        response = lambda_handler(event, None)
        assert response["statusCode"] == 404
        body = json.loads(response["body"])
        assert body["error"]["code"] == "NOT_FOUND"

    def test_post_validate_route_dispatches(self, validate_event, approved_claim, high_confidence_prediction):
        from core.models import ValidationResult, QualityMetrics
        validation = ValidationResult(
            is_valid=True,
            quality=QualityMetrics(overall=0.85, sharpness=0.8, brightness=0.9, contrast=0.8),
        )
        with patch("core.handler.validate_image", return_value=validation), \
             patch("core.handler.is_quality_acceptable", return_value=True), \
             patch("core.handler.predict_damage", return_value=high_confidence_prediction), \
             patch("core.handler.save_claim", return_value=approved_claim):
            response = lambda_handler(validate_event, None)
        assert response["statusCode"] == 200

    def test_get_claim_route_dispatches(self, get_event, approved_claim):
        with patch("core.handler.get_claim", return_value=approved_claim):
            response = lambda_handler(get_event, None)
        assert response["statusCode"] == 200

    def test_put_override_route_dispatches(self, override_event, overridden_claim):
        with patch("core.handler.update_claim_status", return_value=overridden_claim):
            response = lambda_handler(override_event, None)
        assert response["statusCode"] == 200

    def test_malformed_event_returns_500(self):
        """Event missing requestContext should not crash with unhandled exception"""
        response = lambda_handler({}, None)
        assert response["statusCode"] == 500


# ============================================================================
# POST /claims/validate
# ============================================================================

class TestHandleValidate:
    """Tests for the validate route"""

    def _mock_successful_pipeline(self, validation_quality=0.85, confidence=0.94, damage=True):
        """Helper: returns mocks for a fully successful validation pipeline"""
        from core.models import ValidationResult, QualityMetrics
        validation = ValidationResult(
            is_valid=True,
            quality=QualityMetrics(
                overall=validation_quality,
                sharpness=0.8,
                brightness=0.9,
                contrast=0.8,
            ),
        )
        prediction = PredictionResult(damage_detected=damage, confidence=confidence)
        return validation, prediction

    def test_missing_claim_id_returns_400(self, valid_image_base64):
        event = {
            "requestContext": {"http": {"method": "POST", "path": "/v1/claims/validate"}},
            "body": json.dumps({"customer_id": "CUST-1", "image": valid_image_base64}),
        }
        response = lambda_handler(event, None)
        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert body["error"]["code"] == "VALIDATION_ERROR"

    def test_missing_customer_id_returns_400(self, valid_image_base64):
        event = {
            "requestContext": {"http": {"method": "POST", "path": "/v1/claims/validate"}},
            "body": json.dumps({"claim_id": "CLM-001", "image": valid_image_base64}),
        }
        response = lambda_handler(event, None)
        assert response["statusCode"] == 400

    def test_missing_image_returns_400(self):
        event = {
            "requestContext": {"http": {"method": "POST", "path": "/v1/claims/validate"}},
            "body": json.dumps({"claim_id": "CLM-001", "customer_id": "CUST-1"}),
        }
        response = lambda_handler(event, None)
        assert response["statusCode"] == 400

    def test_invalid_base64_returns_400(self):
        event = {
            "requestContext": {"http": {"method": "POST", "path": "/v1/claims/validate"}},
            "body": json.dumps({
                "claim_id": "CLM-001",
                "customer_id": "CUST-1",
                "image": "not-valid-base64!!!",
            }),
        }
        response = lambda_handler(event, None)
        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert body["error"]["code"] == "INVALID_IMAGE"

    def test_invalid_image_format_returns_400(self, valid_image_base64):
        from core.models import ValidationResult
        validation = ValidationResult(is_valid=False, error_message="Not a JPEG or PNG")
        event = {
            "requestContext": {"http": {"method": "POST", "path": "/v1/claims/validate"}},
            "body": json.dumps({
                "claim_id": "CLM-001", "customer_id": "CUST-1", "image": valid_image_base64
            }),
        }
        with patch("core.handler.validate_image", return_value=validation):
            response = lambda_handler(event, None)
        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert body["error"]["code"] == "INVALID_IMAGE_FORMAT"

    def test_low_quality_image_returns_400_with_details(self, valid_image_base64):
        from core.models import ValidationResult, QualityMetrics
        validation = ValidationResult(
            is_valid=True,
            quality=QualityMetrics(overall=0.2, sharpness=0.1, brightness=0.3, contrast=0.2),
        )
        event = {
            "requestContext": {"http": {"method": "POST", "path": "/v1/claims/validate"}},
            "body": json.dumps({
                "claim_id": "CLM-001", "customer_id": "CUST-1", "image": valid_image_base64
            }),
        }
        with patch("core.handler.validate_image", return_value=validation), \
             patch("core.handler.is_quality_acceptable", return_value=False), \
             patch("core.handler.get_quality_feedback", return_value="Image too dark — use flash"):
            response = lambda_handler(event, None)
        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert body["error"]["code"] == "QUALITY_TOO_LOW"
        assert "quality_score" in body["error"]["details"]
        assert body["error"]["feedback"] == "Image too dark — use flash"

    def test_approved_claim_returns_200(self, validate_event, approved_claim):
        validation, prediction = self._mock_successful_pipeline()
        with patch("core.handler.validate_image", return_value=validation), \
             patch("core.handler.is_quality_acceptable", return_value=True), \
             patch("core.handler.predict_damage", return_value=prediction), \
             patch("core.handler.save_claim", return_value=approved_claim):
            response = lambda_handler(validate_event, None)
        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["effective_status"] == "APPROVED"
        assert "claim_id" in body
        assert "result" in body
        assert "processing_time_ms" in body

    def test_rejected_claim_includes_reason(self, validate_event, rejected_claim):
        validation, prediction = self._mock_successful_pipeline(damage=False, confidence=0.88)
        with patch("core.handler.validate_image", return_value=validation), \
             patch("core.handler.is_quality_acceptable", return_value=True), \
             patch("core.handler.predict_damage", return_value=prediction), \
             patch("core.handler.save_claim", return_value=rejected_claim):
            response = lambda_handler(validate_event, None)
        body = json.loads(response["body"])
        assert body["effective_status"] == "REJECTED"
        assert "reason" in body

    def test_inference_error_returns_500(self, validate_event):
        from core.models import ValidationResult, QualityMetrics
        validation = ValidationResult(
            is_valid=True,
            quality=QualityMetrics(overall=0.85, sharpness=0.8, brightness=0.9, contrast=0.8),
        )
        with patch("core.handler.validate_image", return_value=validation), \
             patch("core.handler.is_quality_acceptable", return_value=True), \
             patch("core.handler.predict_damage", side_effect=InferenceError("model failed")):
            response = lambda_handler(validate_event, None)
        assert response["statusCode"] == 500
        body = json.loads(response["body"])
        assert body["error"]["code"] == "INFERENCE_ERROR"

    def test_storage_error_returns_500(self, validate_event, high_confidence_prediction):
        from core.models import ValidationResult, QualityMetrics
        validation = ValidationResult(
            is_valid=True,
            quality=QualityMetrics(overall=0.85, sharpness=0.8, brightness=0.9, contrast=0.8),
        )
        with patch("core.handler.validate_image", return_value=validation), \
             patch("core.handler.is_quality_acceptable", return_value=True), \
             patch("core.handler.predict_damage", return_value=high_confidence_prediction), \
             patch("core.handler.save_claim", side_effect=StorageError("DynamoDB error")):
            response = lambda_handler(validate_event, None)
        assert response["statusCode"] == 500
        body = json.loads(response["body"])
        assert body["error"]["code"] == "STORAGE_ERROR"

    def test_response_contains_user_override_allowed_flag(self, validate_event, rejected_claim):
        validation, prediction = self._mock_successful_pipeline(damage=False, confidence=0.88)
        with patch("core.handler.validate_image", return_value=validation), \
             patch("core.handler.is_quality_acceptable", return_value=True), \
             patch("core.handler.predict_damage", return_value=prediction), \
             patch("core.handler.save_claim", return_value=rejected_claim):
            response = lambda_handler(validate_event, None)
        body = json.loads(response["body"])
        assert "user_override_allowed" in body

    def test_response_contains_next_steps(self, validate_event, approved_claim):
        validation, prediction = self._mock_successful_pipeline()
        with patch("core.handler.validate_image", return_value=validation), \
             patch("core.handler.is_quality_acceptable", return_value=True), \
             patch("core.handler.predict_damage", return_value=prediction), \
             patch("core.handler.save_claim", return_value=approved_claim):
            response = lambda_handler(validate_event, None)
        body = json.loads(response["body"])
        assert "next_steps" in body


# ============================================================================
# GET /claims/{claim_id}
# ============================================================================

class TestHandleGetClaim:
    """Tests for the GET claim route"""

    def test_existing_claim_returns_200(self, get_event, approved_claim):
        with patch("core.handler.get_claim", return_value=approved_claim):
            response = lambda_handler(get_event, None)
        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["claim_id"] == "CLM-001"
        assert "effective_status" in body
        assert "system_status" in body

    def test_non_existing_claim_returns_404(self, get_event):
        with patch("core.handler.get_claim", return_value=None):
            response = lambda_handler(get_event, None)
        assert response["statusCode"] == 404
        body = json.loads(response["body"])
        assert body["error"]["code"] == "CLAIM_NOT_FOUND"

    def test_storage_error_returns_500(self, get_event):
        with patch("core.handler.get_claim", side_effect=StorageError("timeout")):
            response = lambda_handler(get_event, None)
        assert response["statusCode"] == 500
        body = json.loads(response["body"])
        assert body["error"]["code"] == "STORAGE_ERROR"

    def test_claim_id_extracted_from_path(self):
        """claim_id should be extracted correctly from URL path"""
        event = {
            "requestContext": {"http": {"method": "GET", "path": "/v1/claims/CLM-XYZ-999"}},
            "body": None,
        }
        mock_claim = MagicMock()
        mock_claim.claim_id = "CLM-XYZ-999"
        mock_claim.customer_id = "CUST-1"
        mock_claim.effective_status = "APPROVED"
        mock_claim.system_status = "APPROVED"
        mock_claim.damage_detected = True
        mock_claim.confidence = 0.94
        mock_claim.quality_score = 0.85
        mock_claim.user_override = False
        mock_claim.timestamp = datetime.now(timezone.utc).isoformat()
        mock_claim.processing_time_ms = 100
        with patch("core.handler.get_claim", return_value=mock_claim) as mock_get:
            lambda_handler(event, None)
        mock_get.assert_called_once_with("CLM-XYZ-999")

    def test_overridden_claim_includes_override_fields(self, overridden_claim):
        event = {
            "requestContext": {"http": {"method": "GET", "path": "/v1/claims/CLM-002"}},
            "body": None,
        }
        with patch("core.handler.get_claim", return_value=overridden_claim):
            response = lambda_handler(event, None)
        body = json.loads(response["body"])
        assert body["user_override"] is True
        assert "override_timestamp" in body
        assert "override_reason" in body

    def test_non_overridden_claim_omits_override_fields(self, get_event, approved_claim):
        with patch("core.handler.get_claim", return_value=approved_claim):
            response = lambda_handler(get_event, None)
        body = json.loads(response["body"])
        assert body["user_override"] is False
        assert "override_timestamp" not in body
        assert "override_reason" not in body


# ============================================================================
# PUT /claims/{claim_id}/override
# ============================================================================

class TestHandleOverride:
    """Tests for the override route"""

    def test_valid_override_returns_200(self, override_event, overridden_claim):
        with patch("core.handler.update_claim_status", return_value=overridden_claim):
            response = lambda_handler(override_event, None)
        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["effective_status"] == "APPROVED"
        assert body["user_override"] is True
        assert "override_timestamp" in body
        assert "override_reason" in body

    def test_missing_reason_returns_400(self):
        event = {
            "requestContext": {"http": {"method": "PUT", "path": "/v1/claims/CLM-001/override"}},
            "body": json.dumps({}),
        }
        response = lambda_handler(event, None)
        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert body["error"]["code"] == "VALIDATION_ERROR"

    def test_claim_not_found_returns_404(self, override_event):
        with patch("core.handler.update_claim_status", side_effect=ClaimNotFoundError("CLM-001 not found")):
            response = lambda_handler(override_event, None)
        assert response["statusCode"] == 404
        body = json.loads(response["body"])
        assert body["error"]["code"] == "CLAIM_NOT_FOUND"

    def test_override_not_allowed_returns_400(self, override_event):
        with patch("core.handler.update_claim_status", side_effect=OverrideNotAllowedError("Quality too low")):
            response = lambda_handler(override_event, None)
        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert body["error"]["code"] == "OVERRIDE_NOT_ALLOWED"

    def test_storage_error_returns_500(self, override_event):
        with patch("core.handler.update_claim_status", side_effect=StorageError("write failed")):
            response = lambda_handler(override_event, None)
        assert response["statusCode"] == 500

    def test_claim_id_extracted_from_path(self, overridden_claim):
        event = {
            "requestContext": {"http": {"method": "PUT", "path": "/v1/claims/CLM-999/override"}},
            "body": json.dumps({"reason": "Damage visible"}),
        }
        with patch("core.handler.update_claim_status", return_value=overridden_claim) as mock_update:
            lambda_handler(event, None)
        mock_update.assert_called_once_with(
            claim_id="CLM-999",
            new_status="APPROVED",
            override_reason="Damage visible",
        )

    def test_response_includes_manual_review_message(self, override_event, overridden_claim):
        with patch("core.handler.update_claim_status", return_value=overridden_claim):
            response = lambda_handler(override_event, None)
        body = json.loads(response["body"])
        assert "manual review" in body["message"].lower()


# ============================================================================
# BUSINESS LOGIC: _determine_status
# ============================================================================

class TestDetermineStatus:
    """Unit tests for status determination logic"""

    def test_high_confidence_damage_is_approved(self):
        prediction = PredictionResult(damage_detected=True, confidence=CONFIDENCE_THRESHOLD + 0.1)
        assert _determine_status(prediction) == "APPROVED"

    def test_high_confidence_no_damage_is_rejected(self):
        prediction = PredictionResult(damage_detected=False, confidence=0.95)
        assert _determine_status(prediction) == "REJECTED"

    def test_low_confidence_damage_is_rejected(self):
        """Low confidence → REJECTED, even if damage detected"""
        prediction = PredictionResult(damage_detected=True, confidence=CONFIDENCE_THRESHOLD - 0.1)
        assert _determine_status(prediction) == "REJECTED"

    def test_exactly_at_threshold_is_approved(self):
        prediction = PredictionResult(damage_detected=True, confidence=CONFIDENCE_THRESHOLD)
        assert _determine_status(prediction) == "APPROVED"

    def test_low_confidence_no_damage_is_rejected(self):
        prediction = PredictionResult(damage_detected=False, confidence=0.45)
        assert _determine_status(prediction) == "REJECTED"


# ============================================================================
# BUSINESS LOGIC: _is_override_allowed
# ============================================================================

class TestIsOverrideAllowed:
    """Unit tests for override eligibility logic"""

    def test_rejected_high_quality_allows_override(self, rejected_claim):
        """REJECTED + quality >= threshold → override allowed"""
        rejected_claim.quality_score = QUALITY_THRESHOLD + 0.1
        assert _is_override_allowed(rejected_claim) is True

    def test_rejected_low_quality_blocks_override(self, rejected_claim):
        """REJECTED + quality < threshold → override NOT allowed"""
        rejected_claim.quality_score = QUALITY_THRESHOLD - 0.1
        assert _is_override_allowed(rejected_claim) is False

    def test_approved_claim_cannot_be_overridden(self, approved_claim):
        """APPROVED claims should not be overrideable"""
        assert _is_override_allowed(approved_claim) is False

    def test_quality_exactly_at_threshold_allows_override(self, rejected_claim):
        rejected_claim.quality_score = QUALITY_THRESHOLD
        assert _is_override_allowed(rejected_claim) is True


# ============================================================================
# BUSINESS LOGIC: _rejection_reason
# ============================================================================

class TestRejectionReason:

    def test_no_damage_high_confidence(self, rejected_claim):
        rejected_claim.damage_detected = False
        rejected_claim.confidence = 0.95
        assert _rejection_reason(rejected_claim) == "no_damage"

    def test_low_confidence_damage_detected(self, rejected_claim):
        rejected_claim.damage_detected = True
        rejected_claim.confidence = 0.55
        assert _rejection_reason(rejected_claim) == "low_confidence"


# ============================================================================
# BUSINESS LOGIC: _next_steps
# ============================================================================

class TestNextSteps:

    def test_approved_claim_next_steps(self, approved_claim):
        steps = _next_steps(approved_claim)
        assert isinstance(steps, str)
        assert len(steps) > 0
        # Should mention adjuster or review
        assert "adjuster" in steps.lower() or "review" in steps.lower()

    def test_rejected_overridable_mentions_override(self, rejected_claim):
        rejected_claim.quality_score = QUALITY_THRESHOLD + 0.1
        steps = _next_steps(rejected_claim)
        assert "override" in steps.lower() or "upload" in steps.lower()

    def test_rejected_low_quality_mentions_better_image(self, rejected_claim):
        rejected_claim.quality_score = QUALITY_THRESHOLD - 0.1
        steps = _next_steps(rejected_claim)
        assert "image" in steps.lower() or "quality" in steps.lower()


# ============================================================================
# RESPONSE STRUCTURE
# ============================================================================

class TestResponseStructure:
    """Validate HTTP response envelope is correct"""

    def test_success_response_has_correct_headers(self, validate_event, approved_claim):
        from core.models import ValidationResult, QualityMetrics
        validation = ValidationResult(
            is_valid=True,
            quality=QualityMetrics(overall=0.85, sharpness=0.8, brightness=0.9, contrast=0.8),
        )
        prediction = PredictionResult(damage_detected=True, confidence=0.94)
        with patch("core.handler.validate_image", return_value=validation), \
             patch("core.handler.is_quality_acceptable", return_value=True), \
             patch("core.handler.predict_damage", return_value=prediction), \
             patch("core.handler.save_claim", return_value=approved_claim):
            response = lambda_handler(validate_event, None)
        assert response["headers"]["Content-Type"] == "application/json"
        assert "Access-Control-Allow-Origin" in response["headers"]

    def test_error_response_includes_timestamp(self):
        event = {
            "requestContext": {"http": {"method": "GET", "path": "/v1/claims/DOES-NOT-EXIST"}},
            "body": None,
        }
        with patch("core.handler.get_claim", return_value=None):
            response = lambda_handler(event, None)
        body = json.loads(response["body"])
        assert "timestamp" in body

    def test_body_is_valid_json(self, get_event, approved_claim):
        with patch("core.handler.get_claim", return_value=approved_claim):
            response = lambda_handler(get_event, None)
        # Should not raise
        parsed = json.loads(response["body"])
        assert isinstance(parsed, dict)


# Run with:
# pytest tests/test_handler.py -v
# pytest tests/test_handler.py --cov=handler --cov-report=term-missing