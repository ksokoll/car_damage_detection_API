"""
Unit tests for storage module
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from pydantic import ValidationError as PydanticValidationError

from core.storage import (
    save_claim,
    get_claim,
    update_claim_status,
    clear_table_cache,
)
from core.models import (
    ClaimRecord,
    ClaimStatus,
    StorageError,
    ClaimNotFoundError,
    OverrideNotAllowedError,
)
from core.config import QUALITY_THRESHOLD


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def sample_claim():
    return ClaimRecord(
        claim_id="CLM-001",
        customer_id="CUST-123",
        damage_detected=True,
        confidence=0.94,
        quality_score=0.82,
        system_status=ClaimStatus.APPROVED,
        effective_status=ClaimStatus.APPROVED,
        user_override=False,
        override_timestamp=None,
        override_reason=None,
        timestamp=datetime.now(timezone.utc).isoformat(),
        processing_time_ms=150,
        model_version="v1.0"
    )


@pytest.fixture
def rejected_claim():
    return ClaimRecord(
        claim_id="CLM-002",
        customer_id="CUST-456",
        damage_detected=False,
        confidence=0.88,
        quality_score=0.75,
        system_status=ClaimStatus.REJECTED,
        effective_status=ClaimStatus.REJECTED,
        user_override=False,
        timestamp=datetime.now(timezone.utc).isoformat(),
        processing_time_ms=145,
        model_version="v1.0"
    )


@pytest.fixture
def low_quality_claim():
    """Low quality claim — override now always allowed if claim exists."""
    return ClaimRecord(
        claim_id="CLM-003",
        customer_id="CUST-789",
        damage_detected=False,
        confidence=0.65,
        quality_score=0.25,  # Below threshold — but override still allowed
        system_status=ClaimStatus.REJECTED,
        effective_status=ClaimStatus.REJECTED,
        user_override=False,
        timestamp=datetime.now(timezone.utc).isoformat(),
        processing_time_ms=120,
        model_version="v1.0"
    )


@pytest.fixture(autouse=True)
def clear_cache_after_test():
    yield
    clear_table_cache()


@pytest.fixture
def mock_dynamodb_table():
    with patch('core.storage.boto3.resource') as mock_resource:
        mock_table = MagicMock()
        mock_resource.return_value.Table.return_value = mock_table
        yield mock_table


# ============================================================================
# SAVE CLAIM TESTS
# ============================================================================

class TestSaveClaim:

    def test_save_claim_success(self, sample_claim, mock_dynamodb_table):
        mock_dynamodb_table.put_item.return_value = {}
        result = save_claim(sample_claim)
        assert isinstance(result, ClaimRecord)
        assert result.claim_id == "CLM-001"
        mock_dynamodb_table.put_item.assert_called_once()
        call_args = mock_dynamodb_table.put_item.call_args
        assert call_args[1]['Item']['claim_id'] == "CLM-001"

    def test_save_claim_with_all_fields(self, sample_claim, mock_dynamodb_table):
        mock_dynamodb_table.put_item.return_value = {}
        result = save_claim(sample_claim)
        assert result.damage_detected == True
        assert result.confidence == 0.94
        assert result.quality_score == 0.82
        assert result.system_status == ClaimStatus.APPROVED
        assert result.effective_status == ClaimStatus.APPROVED

    def test_save_claim_dynamodb_error(self, sample_claim, mock_dynamodb_table):
        mock_dynamodb_table.put_item.side_effect = Exception("DynamoDB unavailable")
        with pytest.raises(StorageError) as exc_info:
            save_claim(sample_claim)
        assert "Failed to save claim CLM-001" in str(exc_info.value)

    def test_save_claim_idempotent(self, sample_claim, mock_dynamodb_table):
        mock_dynamodb_table.put_item.return_value = {}
        result1 = save_claim(sample_claim)
        result2 = save_claim(sample_claim)
        assert result1.claim_id == result2.claim_id
        assert mock_dynamodb_table.put_item.call_count == 2


# ============================================================================
# GET CLAIM TESTS
# ============================================================================

class TestGetClaim:

    def test_get_claim_exists(self, sample_claim, mock_dynamodb_table):
        mock_dynamodb_table.get_item.return_value = {'Item': sample_claim.model_dump()}
        result = get_claim("CLM-001")
        assert isinstance(result, ClaimRecord)
        assert result.claim_id == "CLM-001"
        mock_dynamodb_table.get_item.assert_called_once_with(Key={'claim_id': "CLM-001"})

    def test_get_claim_not_found(self, mock_dynamodb_table):
        mock_dynamodb_table.get_item.return_value = {}
        result = get_claim("CLM-999")
        assert result is None

    def test_get_claim_dynamodb_error(self, mock_dynamodb_table):
        mock_dynamodb_table.get_item.side_effect = Exception("Network error")
        with pytest.raises(StorageError) as exc_info:
            get_claim("CLM-001")
        assert "Failed to retrieve claim CLM-001" in str(exc_info.value)


# ============================================================================
# UPDATE CLAIM STATUS TESTS
# ============================================================================

class TestUpdateClaimStatus:

    def test_update_claim_status_success(self, rejected_claim, mock_dynamodb_table):
        mock_dynamodb_table.get_item.return_value = {'Item': rejected_claim.model_dump()}
        updated_claim = rejected_claim.model_copy()
        updated_claim.effective_status = ClaimStatus.APPROVED
        updated_claim.user_override = True
        updated_claim.override_reason = "User confirmed damage visible"
        updated_claim.override_timestamp = datetime.now(timezone.utc).isoformat()
        mock_dynamodb_table.update_item.return_value = {'Attributes': updated_claim.model_dump()}

        result = update_claim_status("CLM-002", "APPROVED", "User confirmed damage visible")

        assert result.effective_status == ClaimStatus.APPROVED
        assert result.system_status == ClaimStatus.REJECTED  # Immutable
        assert result.user_override == True
        assert result.override_timestamp is not None

    def test_update_claim_not_found(self, mock_dynamodb_table):
        mock_dynamodb_table.get_item.return_value = {}
        with pytest.raises(ClaimNotFoundError) as exc_info:
            update_claim_status("CLM-999", "APPROVED", "Test")
        assert "CLM-999 not found" in str(exc_info.value)

    def test_update_claim_low_quality_still_allowed(self, low_quality_claim, mock_dynamodb_table):
        """
        Override is allowed even for low quality claims.
        Quality gate is at POST /validate — not here.
        Any claim in DB has already passed quality check.
        """
        mock_dynamodb_table.get_item.return_value = {'Item': low_quality_claim.model_dump()}
        updated_claim = low_quality_claim.model_copy()
        updated_claim.effective_status = ClaimStatus.APPROVED
        updated_claim.user_override = True
        updated_claim.override_reason = "User confirmed submission"
        updated_claim.override_timestamp = datetime.now(timezone.utc).isoformat()
        mock_dynamodb_table.update_item.return_value = {'Attributes': updated_claim.model_dump()}

        # Should NOT raise OverrideNotAllowedError anymore
        result = update_claim_status("CLM-003", "APPROVED", "User confirmed submission")
        assert result.effective_status == ClaimStatus.APPROVED

    def test_update_claim_invalid_status(self, rejected_claim, mock_dynamodb_table):
        mock_dynamodb_table.get_item.return_value = {'Item': rejected_claim.model_dump()}
        with pytest.raises(OverrideNotAllowedError) as exc_info:
            update_claim_status("CLM-002", "PENDING", "Test")
        assert "Invalid status: PENDING" in str(exc_info.value)
        assert "APPROVED" in str(exc_info.value)

    def test_update_claim_dynamodb_error(self, rejected_claim, mock_dynamodb_table):
        mock_dynamodb_table.get_item.return_value = {'Item': rejected_claim.model_dump()}
        mock_dynamodb_table.update_item.side_effect = Exception("Write failed")
        with pytest.raises(StorageError) as exc_info:
            update_claim_status("CLM-002", "APPROVED", "Test")
        assert "Failed to update claim CLM-002" in str(exc_info.value)

    def test_update_preserves_system_status(self, rejected_claim, mock_dynamodb_table):
        mock_dynamodb_table.get_item.return_value = {'Item': rejected_claim.model_dump()}
        updated_claim = rejected_claim.model_copy()
        updated_claim.effective_status = ClaimStatus.APPROVED
        updated_claim.user_override = True
        mock_dynamodb_table.update_item.return_value = {'Attributes': updated_claim.model_dump()}

        update_claim_status("CLM-002", "APPROVED", "Test")

        call_args = mock_dynamodb_table.update_item.call_args
        update_expr = call_args[1]['UpdateExpression']
        assert 'effective_status' in update_expr
        assert 'system_status' not in update_expr


# ============================================================================
# CACHING TESTS
# ============================================================================

class TestCaching:

    def test_clear_table_cache_is_idempotent(self):
        clear_table_cache()
        clear_table_cache()
        clear_table_cache()

    @patch('core.storage.boto3.resource')
    def test_table_cached_across_calls(self, mock_resource, sample_claim):
        mock_table = MagicMock()
        mock_resource.return_value.Table.return_value = mock_table
        mock_table.put_item.return_value = {}
        save_claim(sample_claim)
        save_claim(sample_claim)
        get_claim("CLM-001")
        assert mock_resource.call_count == 1

    @patch('core.storage.boto3.resource')
    def test_cache_cleared_forces_reconnect(self, mock_resource, sample_claim):
        mock_table = MagicMock()
        mock_resource.return_value.Table.return_value = mock_table
        mock_table.put_item.return_value = {}
        save_claim(sample_claim)
        assert mock_resource.call_count == 1
        clear_table_cache()
        save_claim(sample_claim)
        assert mock_resource.call_count == 2


# ============================================================================
# EDGE CASES
# ============================================================================

class TestEdgeCases:

    def test_override_allowed_regardless_of_quality(self, mock_dynamodb_table):
        """Any claim in DB can be overridden — quality was checked at /validate."""
        for quality_score in [0.0, 0.1, QUALITY_THRESHOLD - 0.01, QUALITY_THRESHOLD, 0.9]:
            claim = ClaimRecord(
                claim_id=f"CLM-Q{int(quality_score*100)}",
                customer_id="CUST-001",
                damage_detected=False,
                confidence=0.8,
                quality_score=quality_score,
                system_status=ClaimStatus.REJECTED,
                effective_status=ClaimStatus.REJECTED,
                user_override=False,
                timestamp=datetime.now(timezone.utc).isoformat(),
                processing_time_ms=100,
                model_version="v1.0"
            )
            mock_dynamodb_table.get_item.return_value = {'Item': claim.model_dump()}
            updated = claim.model_copy()
            updated.effective_status = ClaimStatus.APPROVED
            updated.user_override = True
            updated.override_timestamp = datetime.now(timezone.utc).isoformat()
            updated.override_reason = "Test"
            mock_dynamodb_table.update_item.return_value = {'Attributes': updated.model_dump()}

            # Should never raise — quality is irrelevant here
            result = update_claim_status(claim.claim_id, "APPROVED", "Test")
            assert result.effective_status == ClaimStatus.APPROVED


# Run with:
# pytest tests/test_storage.py -v
# pytest tests/test_storage.py --cov=core.storage --cov-report=term-missing