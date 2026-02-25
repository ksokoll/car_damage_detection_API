"""
Storage layer - DynamoDB operations for claim persistence.

Handles claim creation, retrieval, and user override updates.
All database interaction is isolated here.
"""

import boto3
from datetime import datetime, timezone
from decimal import Decimal
import json

from core.models import (
    ClaimRecord,
    ClaimStatus,
    StorageError,
    ClaimNotFoundError,
    OverrideNotAllowedError,
)
from core.config import DYNAMODB_TABLE


# --- DynamoDB client cache ---
# Initialized once per Lambda container, reused across invocations.

_dynamodb = None
_table = None


def _get_table():
    """Lazy-initialized DynamoDB table with caching."""
    global _dynamodb, _table

    if _table is not None:
        return _table

    _dynamodb = boto3.resource("dynamodb")
    _table = _dynamodb.Table(DYNAMODB_TABLE)
    return _table


# --- Public API ---

def save_claim(claim: ClaimRecord) -> ClaimRecord:
    """
    Persists a claim record to DynamoDB.

    Expects a fully constructed ClaimRecord (validation happens
    at creation time in the handler, not here).

    Raises:
        StorageError: If DynamoDB write fails.
    """
    try:
        table = _get_table()
        table.put_item(Item=_to_dynamodb(claim.model_dump(mode="json")))
        return claim
    except Exception as e:
        raise StorageError(f"Failed to save claim {claim.claim_id}: {e}")


def get_claim(claim_id: str) -> ClaimRecord | None:
    """
    Retrieves claim by ID.

    Returns None if claim does not exist.

    Raises:
        StorageError: If DynamoDB read fails.
    """
    try:
        table = _get_table()
        response = table.get_item(Key={"claim_id": claim_id})

        if "Item" not in response:
            return None

        return ClaimRecord(**response["Item"])
    except Exception as e:
        raise StorageError(f"Failed to retrieve claim {claim_id}: {e}")


def update_claim_status(
    claim_id: str,
    new_status: ClaimStatus | str,
    override_reason: str,
) -> ClaimRecord:
    """
    Updates effective_status when user overrides AI decision.

    Quality check is intentionally NOT performed here.
    Images already passed quality validation at POST /validate time.
    Any claim that exists in the DB has already cleared the quality gate.

    Override is always allowed for existing claims — the user knows
    their damage better than the model does.

    Does NOT change system_status (immutable audit trail).

    Raises:
        ClaimNotFoundError: If claim does not exist.
        OverrideNotAllowedError: If new_status is invalid.
        StorageError: If DynamoDB update fails.
    """
    # 1. Retrieve existing claim
    claim = get_claim(claim_id)
    if claim is None:
        raise ClaimNotFoundError(f"Claim {claim_id} not found")

    # 2. Validate and normalize status — accepts both ClaimStatus and plain string
    try:
        new_status = ClaimStatus(new_status)
    except ValueError:
        raise OverrideNotAllowedError(
            f"Invalid status: {new_status}. Must be one of {[s.value for s in ClaimStatus]}"
        )

    # 3. Write update
    try:
        table = _get_table()
        response = table.update_item(
            Key={"claim_id": claim_id},
            UpdateExpression=(
                "SET effective_status = :status, "
                "user_override = :override, "
                "override_timestamp = :ts, "
                "override_reason = :reason"
            ),
            ExpressionAttributeValues={
                ":status": new_status.value,
                ":override": True,
                ":ts": datetime.now(timezone.utc).isoformat(),
                ":reason": override_reason,
            },
            ReturnValues="ALL_NEW",
        )
        return ClaimRecord(**response["Attributes"])
    except Exception as e:
        raise StorageError(f"Failed to update claim {claim_id}: {e}")


def clear_table_cache() -> None:
    """Clears cached DynamoDB client. Testing only."""
    global _dynamodb, _table
    _dynamodb = None
    _table = None

def _to_dynamodb(data: dict) -> dict:
    """Convert floats to Decimal for DynamoDB compatibility."""
    return json.loads(json.dumps(data), parse_float=Decimal)