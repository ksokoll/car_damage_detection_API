# Car Damage Detection System

An ML API that validates car damage photos for insurance claims, including quality checks, ONNX inference, DynamoDB persistence, deployed on AWS Lambda via Terraform. 91–100% pytest test coverage per module. Built as a portfolio project, but also built to actually work.

---

## What It Does

Insurance claims with either wrong uploaded photos or photos of bad quality are a headache for insurance-companies. My fictional client had enough and hired me to implement a system that handles the initial validation automatically: it checks whether the image is sharp and well-lit enough to process, runs a YOLOv8 classifier to detect damage, and gives the customer instant feedback in a fraction of a second after the upload. If the model rejects a claim with low confidence, the customer can override the decision (request by client). The system records both what the AI decided and what was ultimately submitted.

Measured latency on the live deployment: ~48ms p50 (warm). Cold start without Provisioned Concurrency was 3,359ms, which killed the <2s target. That's been fixed.

One word about the scope of the project: This portfolio project focussed on production grade ML implementation (ML Ops) and not the data science part. Therefore the training of the YOLOV8 Model is only a minor part, which is also mentioned in the limitations.

---

## Architecture

```
Client
  │  POST /claims/validate
  ▼
API Gateway (HTTP v2)
  │  $default route
  ▼
Lambda (Container Image, 1024MB)
  ├── core/validator.py    — quality checks (OpenCV, ~5ms)
  ├── core/inference.py    — ONNX damage detection (~40ms)
  ├── core/storage.py      — DynamoDB persistence (~10ms)
  └── core/handler.py      — orchestration + routing
  ▼
DynamoDB (PAY_PER_REQUEST)
```

The most important Architecture decision was to use Single Lambda over microservices: 1-3 req/min doesn't justify distributed architecture. Container image over ZIP. ONNX Runtime + OpenCV alone exceed the 250MB Lambda ZIP limit. Please find the full reasoning, as well as all other architecture desicn decisions in the ADR [`docs/architecture_decision_record.md`](docs/architecture_decision_record.md).

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| ML Model | YOLOv8n-cls → ONNX Runtime |
| Runtime | Python 3.13, AWS Lambda (Container) |
| Storage | DynamoDB (PAY_PER_REQUEST) |
| API | API Gateway HTTP v2 |
| IaC | Terraform |
| Container Registry | ECR |
| Testing | pytest, 139 tests, 91–100% coverage per module |

---

## API

Three endpoints:

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/claims/validate` | Validate photo, run inference, persist claim |
| GET | `/claims/{claim_id}` | Retrieve claim with audit trail |
| PUT | `/claims/{claim_id}/override` | Override AI rejection |

URL is offline. Below curl is only for visulazation.

Full spec in [`docs/api_specification.md`](docs/api_specification.md).

```bash
curl -X POST https://fsj2qravu3.execute-api.eu-central-1.amazonaws.com/dev/claims/validate \
  -H "Content-Type: application/json" \
  -d '{
    "claim_id": "CLM-2025-001",
    "customer_id": "CUST-123",
    "image": "<base64-encoded-jpeg>"
  }'
```

```json
{
  "claim_id": "CLM-2025-001",
  "effective_status": "APPROVED",
  "result": {
    "damage_detected": true,
    "confidence": 0.73,
    "quality_score": 0.84
  },
  "message": "Damage detected. Claim approved for processing.",
  "processing_time_ms": 48
}
```

---

## Project Structure

```
├── lambda/
│   ├── core/
│   │   ├── handler.py       # Orchestration + routing
│   │   ├── validator.py     # Image quality checks
│   │   ├── inference.py     # ONNX inference
│   │   ├── storage.py       # DynamoDB operations
│   │   ├── models.py        # Pydantic models + exceptions
│   │   └── config.py        # Configuration constants
│   ├── models/
│   │   └── car_damage_v1.onnx
│   ├── Dockerfile
│   └── requirements.txt
├── terraform/               # All infrastructure as code
├── tests/                   # 139 tests across 5 modules
├── scripts/
│   └── build.ps1            # Docker build + ECR push
└── docs/
    ├── architecture_decision_record.md
    ├── bounded_contexts.md
    ├── api_specification.md
    └── project_log.md
```

---

## Local Development

**Prerequisites:** Python 3.13, Docker Desktop, AWS CLI

```powershell
# Install dependencies
pip install -r lambda/requirements.txt

# Run tests
pytest tests/ --cov=lambda/core

# Manual end-to-end testing with DynamoDB Local
docker run -p 8000:8000 amazon/dynamodb-local
python scripts/setup_local_db.py
python scripts/manual_test.py
```

---

## Deployment

First deployment requires two `terraform apply` runs. ECR has to exist before the image can be pushed, and the image has to exist before Lambda can be created.

```powershell
cd terraform && terraform apply   # creates ECR, Lambda will fail — expected
cd .. && .\scripts\build.ps1      # build + push image
cd terraform && terraform apply   # creates Lambda
```

After that:
```powershell
.\scripts\build.ps1 && cd terraform && terraform apply
```

**Cost:** ~$9/month, mostly Provisioned Concurrency (~$8/month). Everything else is negligible at this traffic volume.

---

## Model

YOLOv8n-cls trained on 920 damage + 920 whole vehicle images, exported to ONNX. 94.6% accuracy on the validation set. One honest caveat: the model is inconsistent on subtle or unusual damage but this is a training data distribution issue, not a code issue, and it's documented as a known limitation rather than quietly ignored.

---

## Documentation

| Document | Description |
|----------|-------------|
| [`architecture_decision_record.md`](docs/architecture_decision_record.md) | Why things are built the way they are |
| [`bounded_contexts.md`](docs/bounded_contexts.md) | Module responsibilities and interfaces |
| [`api_specification.md`](docs/api_specification.md) | Full endpoint documentation |
| [`project_log.md`](docs/project_log.md) | What went wrong and what to watch out for |
