"""
Integration Tests — Full Pipeline

Strategy:
- Real code: validator.py, inference.py, storage.py, handler.py interact for real
- Mocked: DynamoDB (boto3) and ONNX model (external services only)
- Goal: Verify Bounded Contexts work together correctly end-to-end

Difference vs Unit Tests:
- test_handler.py mocked every context individually
- Here: only external dependencies are mocked, real logic runs through
"""

import json
import pytest
import base64
import io
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock
from PIL import Image

from core.handler import lambda_handler
from core.models import PredictionResult
from core.config import QUALITY_THRESHOLD, CONFIDENCE_THRESHOLD


# ============================================================================
# HELPERS
# ============================================================================

def make_image_base64(path="tests/fixtures/test_car_damage.jpg", fmt="JPEG") -> str:
    """Load real test image and ensure it meets minimum resolution (512x512)."""
    with open(path, "rb") as f:
        img = Image.open(f).convert("RGB")
    # Ensure minimum resolution required by validator
    if img.width < 512 or img.height < 512:
        img = img.resize((max(img.width, 512), max(img.height, 512)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return base64.b64encode(buf.getvalue()).decode()


def make_dark_image_base64() -> str:
    """Nearly black image — guaranteed to fail quality check."""
    img = Image.new("RGB", (600, 600), color=(5, 5, 5))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return base64.b64encode(buf.getvalue()).decode()


def make_validate_event(claim_id="CLM-INT-001", customer_id="CUST-INT-1", image_b64=None) -> dict:
    if image_b64 is None:
        image_b64 = make_image_base64()
    return {
        "requestContext": {"http": {"method": "POST", "path": "/v1/claims/validate"}},
        "body": json.dumps({
            "claim_id": claim_id,
            "customer_id": customer_id,
            "image": image_b64,
        }),
    }


def make_get_event(claim_id="CLM-INT-001") -> dict:
    return {
        "requestContext": {"http": {"method": "GET", "path": f"/v1/claims/{claim_id}"}},
        "body": None,
    }


def make_override_event(claim_id="CLM-INT-001", reason="Damage visible on bumper") -> dict:
    return {
        "requestContext": {"http": {"method": "PUT", "path": f"/v1/claims/{claim_id}/override"}},
        "body": json.dumps({"reason": reason}),
    }


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def mock_dynamodb():
    """Mock boto3 DynamoDB — prevents real AWS calls. Storage logic runs for real."""
    with patch("core.storage.boto3.resource") as mock_resource:
        mock_table = MagicMock()
        mock_resource.return_value.Table.return_value = mock_table

        # Default: put_item succeeds
        mock_table.put_item.return_value = {}

        # Default: get_item returns None (claim not found)
        mock_table.get_item.return_value = {}

        yield mock_table


@pytest.fixture(autouse=True)
def clear_storage_cache():
    """Clear DynamoDB table cache between tests."""
    import core.storage
    core.storage._table = None
    yield
    core.storage._table = None


@pytest.fixture
def high_confidence_prediction():
    return PredictionResult(
        damage_detected=True,
        confidence=CONFIDENCE_THRESHOLD + 0.15,
        probabilities={"damage": CONFIDENCE_THRESHOLD + 0.15, "whole": 1 - (CONFIDENCE_THRESHOLD + 0.15)},
    )


@pytest.fixture
def low_confidence_prediction():
    return PredictionResult(
        damage_detected=True,
        confidence=CONFIDENCE_THRESHOLD - 0.2,
        probabilities={"damage": CONFIDENCE_THRESHOLD - 0.2, "whole": 1 - (CONFIDENCE_THRESHOLD - 0.2)},
    )


@pytest.fixture
def no_damage_prediction():
    return PredictionResult(
        damage_detected=False,
        confidence=0.92,
        probabilities={"damage": 0.08, "whole": 0.92},
    )


# ============================================================================
# END-TO-END: APPROVED CLAIM
# ============================================================================

class TestApprovedPipeline:
    """Full pipeline: image → validate → infer → store → 200 APPROVED"""

    def test_approved_claim_full_pipeline(self, mock_dynamodb, high_confidence_prediction):
        """Real validator + real storage + mocked ONNX → APPROVED response"""
        saved_items = {}

        def capture_put(Item):
            saved_items[Item["claim_id"]] = Item
            return {}

        mock_dynamodb.put_item.side_effect = capture_put

        with patch("core.handler.predict_damage", return_value=high_confidence_prediction):
            response = lambda_handler(make_validate_event(), None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["effective_status"] == "APPROVED"
        assert body["result"]["damage_detected"] is True
        assert body["result"]["confidence"] >= CONFIDENCE_THRESHOLD

        # Verify storage was actually called with correct data
        assert "CLM-INT-001" in saved_items
        assert saved_items["CLM-INT-001"]["system_status"] == "APPROVED"

    def test_approved_response_contains_all_required_fields(self, mock_dynamodb, high_confidence_prediction):
        with patch("core.handler.predict_damage", return_value=high_confidence_prediction):
            response = lambda_handler(make_validate_event(), None)

        body = json.loads(response["body"])
        required_fields = [
            "claim_id", "effective_status", "result",
            "message", "user_override_allowed", "next_steps",
            "processing_time_ms", "timestamp",
        ]
        for field in required_fields:
            assert field in body, f"Missing field: {field}"

    def test_approved_claim_override_not_allowed(self, mock_dynamodb, high_confidence_prediction):
        """APPROVED claims should not be overrideable"""
        with patch("core.handler.predict_damage", return_value=high_confidence_prediction):
            response = lambda_handler(make_validate_event(), None)

        body = json.loads(response["body"])
        assert body["user_override_allowed"] is False


# ============================================================================
# END-TO-END: REJECTED CLAIM
# ============================================================================

class TestRejectedPipeline:
    """Full pipeline scenarios that result in REJECTED"""

    def test_no_damage_detected_results_in_rejected(self, mock_dynamodb, no_damage_prediction):
        with patch("core.handler.predict_damage", return_value=no_damage_prediction):
            response = lambda_handler(make_validate_event(), None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["effective_status"] == "REJECTED"
        assert body["reason"] == "no_damage"

    def test_low_confidence_results_in_rejected(self, mock_dynamodb, low_confidence_prediction):
        with patch("core.handler.predict_damage", return_value=low_confidence_prediction):
            response = lambda_handler(make_validate_event(), None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["effective_status"] == "REJECTED"
        assert body["reason"] == "low_confidence"

    def test_rejected_claim_override_allowed_when_quality_ok(self, mock_dynamodb, no_damage_prediction):
        """High quality image + REJECTED → override should be allowed"""
        with patch("core.handler.predict_damage", return_value=no_damage_prediction):
            response = lambda_handler(make_validate_event(), None)

        body = json.loads(response["body"])
        assert body["effective_status"] == "REJECTED"
        # Real image (600x600, good contrast) should pass quality threshold
        assert body["user_override_allowed"] is True

    def test_rejected_claim_stored_with_system_status_rejected(self, mock_dynamodb, no_damage_prediction):
        saved_items = {}

        def capture_put(Item):
            saved_items[Item["claim_id"]] = Item
            return {}

        mock_dynamodb.put_item.side_effect = capture_put

        with patch("core.handler.predict_damage", return_value=no_damage_prediction):
            lambda_handler(make_validate_event(), None)

        assert saved_items["CLM-INT-001"]["system_status"] == "REJECTED"
        assert saved_items["CLM-INT-001"]["effective_status"] == "REJECTED"


# ============================================================================
# END-TO-END: QUALITY REJECTION (before inference)
# ============================================================================

class TestQualityRejectionPipeline:
    """Low quality images should be rejected before inference is called"""

    def test_dark_image_rejected_before_inference(self, mock_dynamodb):
        """Very dark image → Quality Check → 400, inference never called"""
        dark_image = make_dark_image_base64()  # Nearly black

        with patch("core.handler.predict_damage") as mock_predict:
            response = lambda_handler(make_validate_event(image_b64=dark_image), None)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert body["error"]["code"] == "QUALITY_TOO_LOW"
        # Inference should NOT have been called
        mock_predict.assert_not_called()

    def test_quality_rejection_includes_feedback(self, mock_dynamodb):
        dark_image = make_dark_image_base64()

        response = lambda_handler(make_validate_event(image_b64=dark_image), None)

        body = json.loads(response["body"])
        assert "feedback" in body["error"]
        assert isinstance(body["error"]["feedback"], str)
        assert len(body["error"]["feedback"]) > 0

    def test_quality_rejection_includes_breakdown(self, mock_dynamodb):
        dark_image = make_dark_image_base64()

        response = lambda_handler(make_validate_event(image_b64=dark_image), None)

        body = json.loads(response["body"])
        details = body["error"]["details"]
        assert "quality_score" in details
        assert "quality_breakdown" in details
        assert details["quality_score"] < QUALITY_THRESHOLD


# ============================================================================
# END-TO-END: OVERRIDE FLOW
# ============================================================================

class TestOverridePipeline:
    """Full reject → override → approved flow"""

    def _make_stored_claim_dict(self, claim_id="CLM-INT-001", quality_score=0.85):
        """Helper: DynamoDB Item for a rejected claim"""
        return {
            "claim_id": claim_id,
            "customer_id": "CUST-INT-1",
            "damage_detected": False,
            "confidence": str(0.92),
            "quality_score": str(quality_score),
            "system_status": "REJECTED",
            "effective_status": "REJECTED",
            "user_override": False,
            "override_reason": None,
            "override_timestamp": None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "processing_time_ms": 95,
            "model_version": "v1",
        }

    def test_override_changes_effective_status(self, mock_dynamodb):
        """Override should change effective_status to APPROVED, system_status stays REJECTED"""
        stored = self._make_stored_claim_dict()
        mock_dynamodb.get_item.return_value = {"Item": stored}

        updated_stored = {**stored, "effective_status": "APPROVED", "user_override": True,
                         "override_reason": "Damage visible on bumper",
                         "override_timestamp": datetime.now(timezone.utc).isoformat()}
        mock_dynamodb.update_item.return_value = {"Attributes": updated_stored}

        response = lambda_handler(make_override_event(), None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["effective_status"] == "APPROVED"
        assert body["system_status"] == "REJECTED"   # Immutable audit trail
        assert body["user_override"] is True

    def test_override_system_status_immutable(self, mock_dynamodb):
        """system_status must never change — this is the audit trail"""
        stored = self._make_stored_claim_dict()
        mock_dynamodb.get_item.return_value = {"Item": stored}

        updated_stored = {**stored, "effective_status": "APPROVED", "user_override": True,
                         "override_reason": "Visible damage",
                         "override_timestamp": datetime.now(timezone.utc).isoformat()}
        mock_dynamodb.update_item.return_value = {"Attributes": updated_stored}

        # Verify update_item was NOT called with system_status in UpdateExpression
        response = lambda_handler(make_override_event(), None)

        call_kwargs = mock_dynamodb.update_item.call_args
        update_expression = call_kwargs.kwargs.get("UpdateExpression", "")
        assert "system_status" not in update_expression

    def test_override_blocked_for_low_quality_claim(self, mock_dynamodb):
        """Claims with quality below threshold cannot be overridden"""
        stored = self._make_stored_claim_dict(quality_score=QUALITY_THRESHOLD - 0.1)
        mock_dynamodb.get_item.return_value = {"Item": stored}

        response = lambda_handler(make_override_event(), None)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert body["error"]["code"] == "OVERRIDE_NOT_ALLOWED"

    def test_override_nonexistent_claim_returns_404(self, mock_dynamodb):
        """Overriding a claim that doesn't exist → 404"""
        mock_dynamodb.get_item.return_value = {}  # No Item key → claim not found

        response = lambda_handler(make_override_event(claim_id="DOES-NOT-EXIST"), None)

        assert response["statusCode"] == 404
        body = json.loads(response["body"])
        assert body["error"]["code"] == "CLAIM_NOT_FOUND"


# ============================================================================
# CROSS-CONTEXT: STORAGE INTERACTION
# ============================================================================

class TestCrossContextStorageInteraction:
    """Verify handler and storage interact correctly — not just mocked returns"""

    def test_validate_calls_save_claim_exactly_once(self, mock_dynamodb, high_confidence_prediction):
        with patch("core.handler.predict_damage", return_value=high_confidence_prediction):
            lambda_handler(make_validate_event(), None)

        mock_dynamodb.put_item.assert_called_once()

    def test_validate_saves_correct_claim_id(self, mock_dynamodb, high_confidence_prediction):
        with patch("core.handler.predict_damage", return_value=high_confidence_prediction):
            lambda_handler(make_validate_event(claim_id="CLM-SPECIFIC-42"), None)

        call_args = mock_dynamodb.put_item.call_args
        saved_item = call_args.kwargs["Item"]
        assert saved_item["claim_id"] == "CLM-SPECIFIC-42"

    def test_get_claim_calls_dynamodb_with_correct_key(self, mock_dynamodb):
        mock_dynamodb.get_item.return_value = {}  # Not found — we just want to check the call

        lambda_handler(make_get_event(claim_id="CLM-LOOKUP-99"), None)

        call_args = mock_dynamodb.get_item.call_args
        assert call_args.kwargs["Key"]["claim_id"] == "CLM-LOOKUP-99"


# ============================================================================
# REAL MODEL (optional, skipped when model not available)
# ============================================================================

class TestWithRealModel:
    """End-to-end with real ONNX model — skipped in CI without model file"""

    @pytest.mark.skipif(
        not Path("models/car_damage_v1.onnx").exists(),
        reason="ONNX model not available"
    )
    def test_full_pipeline_real_inference(self, mock_dynamodb):
        """No mocking of inference — real model runs end-to-end"""
        response = lambda_handler(make_validate_event(), None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["effective_status"] in ("APPROVED", "REJECTED")
        assert 0.0 <= body["result"]["confidence"] <= 1.0
        assert isinstance(body["result"]["damage_detected"], bool)

    @pytest.mark.skipif(
        not Path("models/car_damage_v1.onnx").exists(),
        reason="ONNX model not available"
    )
    def test_real_inference_processing_time_under_2s(self, mock_dynamodb):
        """p95 latency requirement: <2000ms"""
        import time
        start = time.perf_counter()
        lambda_handler(make_validate_event(), None)
        duration_ms = (time.perf_counter() - start) * 1000

        assert duration_ms < 2000, f"Pipeline too slow: {duration_ms:.0f}ms (limit: 2000ms)"


# Run with:
# pytest tests/test_integration.py -v
# pytest tests/test_integration.py --cov=core --cov-report=term-missing