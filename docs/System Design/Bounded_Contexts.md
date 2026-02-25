# Bounded Contexts
## Car Damage Detection System

---

## Overview

Although deployed as a single Lambda, the system is organized into four distinct bounded contexts with clear responsibilities. Each context operates independently — cross-context dependencies are forbidden.

```
┌─────────────────────────────────────────────────────────┐
│                  Orchestration Context                  │
│                      handler.py                         │
└────────────┬──────────────┬──────────────┬─────────────┘
             │              │              │
             ▼              ▼              ▼
    ┌──────────────┐ ┌────────────┐ ┌───────────────┐
    │  Validation  │ │ Inference  │ │    Storage    │
    │  validator.py│ │inference.py│ │  storage.py   │
    └──────────────┘ └────────────┘ └───────────────┘
```

**Dependency rule:** Orchestration knows all contexts. Contexts know nothing about each other.

---

## 1. Input Validation Context — `validator.py`

**Responsibility:** Determine whether an image is usable for ML processing.

**Owns:**
- Format validation (JPEG/PNG only)
- Size and resolution checks (min 320x320px)
- Quality assessment (sharpness, brightness, contrast)

**Does not own:** Damage detection, persistence, business status logic

**Interface:**
```python
def validate_image(image_bytes: bytes) -> ValidationResult
def is_quality_acceptable(result: ValidationResult) -> bool
def get_quality_feedback(result: ValidationResult) -> str
```

**Output:** `ValidationResult` with `is_valid`, `quality_score`, `quality_breakdown`, `issues`

---

## 2. Inference Context — `inference.py`

**Responsibility:** Run ML model and return damage prediction.

**Owns:**
- ONNX model lifecycle (load once, cache per container)
- Image preprocessing (resize → normalize → tensor)
- Model execution and confidence scoring

**Does not own:** Quality checks, persistence, status determination

**Interface:**
```python
def predict_damage(image_bytes: bytes) -> PredictionResult
```

**Output:** `PredictionResult` with `damage_detected`, `confidence`, `probabilities`

---

## 3. Storage Context — `storage.py`

**Responsibility:** Persist claim data and handle status updates.

**Owns:**
- DynamoDB CRUD operations
- Audit trail (immutable `system_status`, mutable `effective_status`)
- Override processing (`update_claim_status`)

**Does not own:** Business rules, validation logic, ML inference

**Interface:**
```python
def save_claim(claim: ClaimRecord) -> ClaimRecord
def get_claim(claim_id: str) -> ClaimRecord | None
def update_claim_status(claim_id: str, new_status: ClaimStatus, override_reason: str) -> ClaimRecord
```

---

## 4. Orchestration Context — `handler.py`

**Responsibility:** Coordinate the other three contexts, apply business rules, format HTTP responses.

**Owns:**
- Request parsing and response formatting
- Status determination (`confidence >= 0.7 AND damage_detected → APPROVED`)
- Error handling and HTTP status mapping
- Route handling (`POST /validate`, `GET /claims/{id}`, `PUT /override`)

**Does not own:** Validation logic, ML execution, persistence

**Business rule — status determination:**
```python
if prediction.confidence >= 0.7 and prediction.damage_detected:
    return ClaimStatus.APPROVED
return ClaimStatus.REJECTED
```

---

## Context Interaction Rules

- Contexts communicate only through return values — no shared mutable state
- No context imports from another context
- Unit tests cover each context in isolation
- Integration tests cover the full orchestration flow