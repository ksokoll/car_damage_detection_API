# Car Damage Detection System

An ML API that validates car damage photos for insurance claims, including quality checks, ONNX inference, DynamoDB persistence, deployed on AWS Lambda via Terraform. 91–100% pytest test coverage per module. Built as a portfolio project, but also built to actually work.

---

## What It Does

Insurance claims with either wrong uploaded photos or photos of bad quality are a headache for insurance-companies. My fictional client had enough and hired me to implement a system that handles the initial validation automatically: it checks whether the image is sharp and well-lit enough to process, runs a YOLOv8 classifier to detect damage, and gives the customer instant feedback in a fraction of a second after the upload. If the model rejects a claim with low confidence, the customer can override the decision (request by client). The system records both what the AI decided and what was ultimately submitted.

Measured latency on the live deployment: ~48ms p50 (warm). Cold start without Provisioned Concurrency was 3,359ms, which killed the <2s target. That's been fixed.

One word about the scope of the project: This portfolio project focussed on production grade ML implementation (ML Ops) and not the data science part. Therefore the training of the YOLOV8 Model is only a minor part, which is also mentioned in the limitations.

---

## Business Case Overview

The fictional customer "insurisense GmbH" reached out to me to have a look on their car-damage claim-entry process. This process includes the entry of all relevant insurance claim information by the customer via a web frontend (desktop / mobile). After some analysis and subject-matter expert interviews, we figured out that every 4th case (25%) of uploaded images of the car damages is insufficient, and needs further clarification by the clerks.

### Business Case Calculation: Quantitative Factors

This might sound minor, but the insurisence GmbH receives ~1000 claims per day (with variance!). Each manuall processing of a claim leads to a long process chain:
1. View images and determine that the quality is insufficient
2. Open internal ticket
3. Contact Customer via mail, telephone or letter
4. Document result
5. Check for new images
6. Close Ticket
7. In case of no response: ask & escalate
8. Close Claim

Observing dozens of such cases, I measured classicaly with a stopwatch: The Median was 20 minutes, but range was 8-45 minutes depending on channel (email vs. phone vs. letter). I use the median for calculation, not the mean, because outliers (letter correspondence over weeks) would inflate the number unrealistically.
Automating the process of image quality detection serves the customer with a instant feedback, with a prognosed reduction of these claims by 25%. We assume therefore, that every 4th customer takes the initiative and resolves the picture-quality image in self service. (This needs to be measured and validated later, as it can be higher or lower!) We assume 25% as a starting point, but this is the most uncertain variable in the entire calculation. If only 10% self-resolve, savings drop to ~100.000€/year  still a 5x ROI. If 40% self-resolve, we're looking at 400.000€. The system logs every interaction, so we'll know the real number within 4 weeks of go-live.

Right now we expect savings about 20,8h of work time per day, the equivalent of 2,5 full time employees. 
The true quality of this automation therefore is not only the automatic picture quality check, but the elimination of the whole follow-up process in case of bad images.

The insurance reported 60€ / hour of hourly cost on average for insurance-claim clerks, accumulating to **24.000€ / month of savings** or over a quarter of million € per year.

On the contrary we have the initial and running cost for the automation:

For the initial cost I calculate the development cost and all adjacent costs like discovery workshops, analysis, handover, etc:

1. Discovery & Requirements: 3-5 days
2. Development & Integration: 5-10 days
3. Testing & UAT: 3-5 days
4. Deployment & handover: 2-3 days
5. Overall: 15-25 days

At 1000€ / day blended rate we have 15k-25k € of initial project cost.

For the running cost we can calculate 200€  / Year for the AWS infrastructure (neglegtible) as well as 6-8 days/year for maintanance (~8000€ / year) accumulating to ~8k € / year.

To summarize the quantitative Factors: A quarter million € stands contrary to 15-25k € of initial development cost and 8k€ of yearly maintanance, leading to 15-20x ROI with a cost-break even after approximately 6 weeks.
One little trick is to cut the adoption quote of the customers in half (from 25% to 12,5%) and take a look at the numbers:

Maintanance stays the same: 8k
Savings are halved: ~125k.

Still a good business case. This should be enough for green light from the decision makers.

### Business Case Calculation: Qualitative Factors

**Customer experience** is a major lever for insurances to retain customers (and also aquire new ones). Getting an almost instant, helpful feedback as customer when uploading images that do not fit the quality standard is a way better experience than waiting several days and then getting a mail that the claim cannot be processed.

The possibility to manually override the models decision gives autonomy to the user.

This might also lead to **reputation gains**, as these kinds of checks show a digital-first mindset. This self service is a differentiating feature for an incurance especially to younger customers.

### Business Case - Risks and Counter-Arguments:

The business case assumes the model reliably distinguishes good from bad images. If that assumption breaks, say a false-rejection rate of 15%, customers get told their perfectly fine photo is insufficient. They get frustrated, call the hotline, and the clerks have more work than before, not less. The override mechanism mitigates this partially because users can push back immediately, and we monitor false-rejection rates from day one. If accuracy drops below an acceptable threshold, we adjust the confidence threshold or retrain with production data. But it's a real risk that needs to be tracked.

The 25% self-service assumption implies customers actually re-take photos when prompted. Older demographics may ignore the feedback and call anyway ('Hotline Backfire') If adoption is low, the automation still prevents bad images from entering the pipeline  but the savings shift from "eliminated follow-up" to "faster follow-up", because the clerk already knows the image is bad without having to assess it manually. The ROI shrinks but doesn't disappear.

Automated decision-making in insurance claims can trigger regulatory scrutiny depending on how far the automation goes. This system only pre-screens image quality, not the claim itself  the actual damage assessment and payout decision stays with humans. That distinction matters legally, but should be validated with the compliance team before go-live. BaFin may or may not care, but finding out after launch is not a position you want to be in.

Vendor Lock-In: If insurisense has no internal ML competency, they depend on the consulting partner for model retraining and maintenance indefinitely. Thats either a risk or a feature but it should be a conscious decision, not something that becomes obvious six months after handover. Knowledge transfer and documentation are part of the delivery for exactly this reason.

Car damage photos can contain license plates, faces, and location data, all personal data under GDPR. The system stores images temporarily for processing, which requires a data processing agreement, a GDPR impact assessment, and clear retention policies. Not a blocker, but a workstream that needs to happen in parallel to development, not after. If compliance blocks the project late, the financial upside is irrelevant. Therefore legal validation must happen before development starts.

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
  ├── core/validator.py     quality checks (OpenCV, ~5ms)
  ├── core/inference.py     ONNX damage detection (~40ms)
  ├── core/storage.py       DynamoDB persistence (~10ms)
  └── core/handler.py       orchestration + routing
  ▼
DynamoDB (PAY_PER_REQUEST)
```

The most important Architecture decision was to use Single Lambda over microservices: 1-3 req/min doesn't justify distributed architecture. Container image over ZIP. ONNX Runtime + OpenCV alone exceed the 250MB Lambda ZIP limit. Please find the full reasoning, as well as all other architecture desicn decisions in the ADR [`docs/architecture_decision_record.md`](docs/System_Design/architecture_decision_record.md).

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

Full spec in [`docs/api_specification.md`](docs/System_Design/api_specification.md).

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
cd terraform && terraform apply   # creates ECR, Lambda will fail  expected
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
| [`architecture_decision_record.md`](docs/System_Design/ADR.md) | Why things are built the way they are |
| [`bounded_contexts.md`](docs/System_Design/Bounded_Contexts.md) | Module responsibilities and interfaces |
| [`api_specification.md`](docs/System_Design/API_SPEC.md) | Full endpoint documentation |
| [`project_log.md`](docs/System_Design/project_log.md) | What went wrong and what to watch out for |
