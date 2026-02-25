# API Specification
## Car Damage Detection System

---

## Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/claims/validate` | Validate damage photo, run inference, persist claim |
| GET | `/claims/{claim_id}` | Get claim details with audit trail |
| PUT | `/claims/{claim_id}/override` | Override AI rejection |

---

## POST /claims/validate

**Request:**
```json
{
  "claim_id": "CLM-2025-001234",
  "customer_id": "CUST-456789",
  "image": "base64_encoded_image..."
}
```

**Image constraints:** JPEG/PNG, min 320x320px, max ~10MB raw (13.3MB Base64), quality score >= 0.4

**Known limitation:** Base64 in JSON body approaches API Gateways 10MB payload limit. Production improvement: pre-signed S3 URLs for direct upload.

---

**Response — Damage detected (200):**
```json
{
  "claim_id": "CLM-2025-001234",
  "effective_status": "APPROVED",
  "result": {
    "damage_detected": true,
    "confidence": 0.94,
    "quality_score": 0.82,
    "quality_breakdown": {
      "sharpness": 0.87,
      "brightness": 0.79,
      "contrast": 0.75
    }
  },
  "message": "Damage detected. Claim approved for processing.",
  "user_override_allowed": false,
  "next_steps": "Your claim will be reviewed by an adjuster within 2 business days.",
  "processing_time_ms": 48,
  "timestamp": "2025-02-10T14:23:45.123Z"
}
```

**Response — Rejected (200):**
```json
{
  "claim_id": "CLM-2025-001235",
  "effective_status": "REJECTED",
  "result": {
    "damage_detected": true,
    "confidence": 0.62,
    "quality_score": 0.71,
    "quality_breakdown": { ... }
  },
  "message": "Claim rejected. See reason and next_steps for details.",
  "reason": "low_confidence",
  "user_override_allowed": true,
  "next_steps": "If you believe damage is visible, you can override this decision or upload a different photo.",
  "processing_time_ms": 51,
  "timestamp": "2025-02-10T14:24:12.456Z"
}
```

**`reason` values:**
- `no_damage` — model is confident, no damage found
- `low_confidence` — model is uncertain (confidence < 0.7)

**Response — Quality too low (400):**
```json
{
  "error": {
    "code": "QUALITY_TOO_LOW",
    "message": "Image quality insufficient for automated processing",
    "details": {
      "quality_score": 0.23,
      "quality_breakdown": { ... },
      "issues": ["Image too blurry - hold camera steady"]
    },
    "feedback": "Please retake the photo with a steady hand."
  },
  "timestamp": "2025-02-10T14:28:00.000Z"
}
```

**Note:** Quality rejections (score < 0.4) do not create a database record.

---

## GET /claims/{claim_id}

Returns full claim including audit trail. Only endpoint that returns `system_status`.

**Response (200):**
```json
{
  "claim_id": "CLM-2025-001234",
  "customer_id": "CUST-456789",
  "effective_status": "APPROVED",
  "system_status": "REJECTED",
  "result": {
    "damage_detected": false,
    "confidence": 0.73,
    "quality_score": 0.68
  },
  "user_override": true,
  "override_timestamp": "2025-02-10T14:35:22.000Z",
  "override_reason": "User confirmed damage visible despite AI rejection",
  "submitted_at": "2025-02-10T14:33:10.000Z",
  "processing_time_ms": 48
}
```

**Note:** `override_timestamp` and `override_reason` only appear when `user_override: true`.

---

## PUT /claims/{claim_id}/override

Always sets `effective_status` to APPROVED. `system_status` remains unchanged.

**Request:**
```json
{
  "reason": "User confirmed damage is visible on closer inspection"
}
```

**Response (200):**
```json
{
  "claim_id": "CLM-2025-001234",
  "effective_status": "APPROVED",
  "system_status": "REJECTED",
  "user_override": true,
  "override_timestamp": "2025-02-10T14:40:00.000Z",
  "override_reason": "User confirmed damage is visible on closer inspection",
  "message": "Claim status updated. Flagged for manual review during processing."
}
```

**Override rules:**

| Condition | Override allowed |
|-----------|-----------------|
| `quality_score < 0.4` | ❌ — image objectively unusable |
| `confidence < 0.7` | ✅ — AI uncertain, user decides |
| `damage_detected = false` | ✅ — AI may be wrong |
| `effective_status = APPROVED` | ❌ — nothing to override |

**Current implementation:** Quality check only runs at `POST /validate`. Any claim that exists in DynamoDB has already passed the quality gate.Override is always allowed for REJECTED claims.

---

## Error Codes

| Code | HTTP | Description |
|------|------|-------------|
| `VALIDATION_ERROR` | 400 | Missing required field |
| `INVALID_IMAGE` | 400 | Not valid Base64 |
| `INVALID_IMAGE_FORMAT` | 400 | Not JPEG/PNG |
| `QUALITY_TOO_LOW` | 400 | Quality score < 0.4 |
| `CLAIM_NOT_FOUND` | 404 | Claim ID does not exist |
| `INFERENCE_ERROR` | 500 | Model processing failed |
| `STORAGE_ERROR` | 500 | DynamoDB operation failed |
| `INTERNAL_ERROR` | 500 | Unexpected error |

---

## Key Design Decisions

**`effective_status` vs `system_status`**
- `system_status` = original AI decision, never changes (audit trail)
- `effective_status` = current status shown to user, can change via override
- `system_status` only returned by GET — POST and PUT return `effective_status` only

**Idempotency**
- Same `claim_id` submitted twice overwrites the previous result
- Use case: user uploads a better quality photo for the same claim
- Only applies to successful submissions (200) — quality rejections (400) create no DB record

**Status determination**
```
confidence >= 0.7 AND damage_detected = true  → APPROVED
everything else                                → REJECTED
```