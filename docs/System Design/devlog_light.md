# Project Log
## Car Damage Detection System

This is a retrospective. What I built, how it went, and what Id do differently. Written primarily for developers who want to build something similar and would rather learn from my mistakes than repeat them.

---

## What I Was Trying to Build

The idea was simple enough: an API that takes a car damage photo and tells you whether the damage is real and the photo is usable. The target user is an insurance company that currently has a human manually checking every submitted photo before it enters the claims workflow. The AI doesnt replace the adjuster. it just stops obviously bad submissions (blurry photos, no damage visible, wrong subject entirely) from wasting anyones time.

Simple idea. Took three weeks and more debugging than I like to admit.

---

## Phase 1: Figuring Out What to Actually Build (09.02. – 15.02.)

The project started bigger. The original plan was a two-component system: a police report classifier (PDF validation) plus the damage photo validator. I cut the police report component about two days in. Not because it was too hard, but because Id have shipped two half-finished things instead of one that actually works. That kind of scope decision feels uncomfortable in the moment as theres always a voice saying "but it would be so much more impressive" but it was right.

The more interesting early question was architectural. My first instinct was Step Functions + microservices. It felt like the serious, professional choice. Then I actually wrote down the requirements: 1–3 requests per minute, synchronous response under 2 seconds, small ops team. There was no justification for distributed architecture. A single Lambda with clean internal module structure was the right answer; not a compromise, just the right answer for these requirements. It took me longer than it should have to get there.

Before writing any production code, I spent a few days on documentation: bounded contexts, API specification, architecture decisions. This felt slow at the time. It wasnt. The API spec went through several iterations before implementation. every inconsistency I caught there was a bug I didnt have to debug later in deployed code. Id do this again.

---

## Phase 2 Implementation (15.02. – 20.02.)

Implementation followed the module structure cleanly: `validator.py` → `inference.py` → `storage.py` → `handler.py` → integration tests. Each module got its own test file before I moved on. This worked well. When something broke, I always knew which layer it was in.

The model training happened on Kaggle with a T4 GPU. 920 damage images, 920 whole-car images, balanced dataset. YOLOv8n-cls hit 94.6% accuracy on the first run, which was good enough to move on. I almost spent another day on hyperparameter tuning before realizing the target was 85% and I was already 10 points above it. Diminishing returns. Exported to ONNX and moved on.

ONNX over PyTorch was an easy call once I looked at the numbers: 30MB vs 700MB deployment size. PyTorch is for training, ONNX Runtime is for inference on Lambda. The cold start difference alone (1s vs 3–5s) would have made Provisioned Concurrency significantly more expensive.

The testing took longer than expected, mostly because of a few subtle issues that wasted time:

The `patch()` bug hit me twice. In unit tests, then again in integration tests. The rule is simple: patch where a function is *imported*, not where its *defined* , but its not obvious until youve been burned by it. `patch("handler.validate_image")` fails silently. `patch("core.handler.validate_image")` works. Ive now written this on a sticky note.

Test coverage metrics are a trap. I had 21/21 tests passing with one test that had `pass` in the body and did nothing. 100% green, zero value. Coverage percentage tells you what lines ran, not whether your tests are any good. Boundary tests (exactly at threshold, one below) and negative tests (`pytest.raises`) matter more.

Synthetic test images dont work for quality checks. I tried using `Image.new("RGB", (600, 600), "red")` as a test fixture. A plain red square has sharpness=0 and contrast=0. It fails the quality gate immediately. You need a real photo. I added a real car damage image to `tests/fixtures/` and the integration tests finally made sense.

The one thing that consistently saved time: when a test failed, reading the actual response body before guessing. `print(json.loads(response["body"]))` tells you exactly which module rejected the request and with which error code. One line. I kept trying to debug without it and kept wasting time.

---

## Phase 3 : Infrastructure & Deployment (25.02.)

Terraform was mostly smooth. The infrastructure design was clear from the start and the actual `terraform apply` worked on the second try. The interesting part was the deployment pipeline.

ZIP limit is the first thing youll hit with any ML stack on Lambda. ONNX Runtime is ~100MB. OpenCV headless is ~50MB. Thats already 150MB of your 250MB budget before you add application code. Container images (10GB limit) are the correct approach. Plan for this from the start, dont discover it when `terraform apply` fails.

Amazon Linux 2023 is not Amazon Linux 2. Lambda Python 3.13 runs on AL2023. Every Dockerfile example I found online used `yum`. AL2023 uses `dnf`. The package names also changed to `libGL.x86_64` is now `mesa-libGL`, `libgthread-2.0` is `glib2`. This cost me about an hour.

`--provenance=false`*is required for Lambda container images. Docker BuildKit creates multi-manifest images by default. Lambda doesnt support them. The error message (`image manifest media type not supported`) is cryptic enough that I spent time looking in the wrong places. Just add the flag.

The most frustrating issue was the hardcoded config value. `DYNAMODB_TABLE: str = "claims"` in `config.py` instead of `os.environ.get("DYNAMODB_TABLE", "claims")`. The environment variable was correctly set in Lambda. The code just never read it. The first live request came back with `AccessDeniedException on table/claims`. Lambda was trying to write to a table called `claims` that doesnt exist, instead of `car-damage-dev-claims`. After fixing the code, Dockers layer cache served the old version. Add `--no-cache` when something isnt behaving as expected after a code change.

After pushing a fixed image, the Lambda alias still pointed to the old published version. `update-function-code` doesnt publish automatically, you need `publish-version` and then `update-alias`. And then Provisioned Concurrency was still holding a warm instance with the old code. Delete it, recreate it, wait two minutes for `READY` status. Only then did the requests start hitting the new version.

That whole sequence fix code → rebuild → push → publish version → update alias → recycle Provisioned Concurrency took longer than it should have because I kept assuming the previous step had propagated. It hadnt. In production, a CI/CD pipeline handles all of this automatically. Doing it manually once is a good way to understand why CI/CD exists.

The live test was satisfying. `CLM-LIVE-004`, `damage_detected=True`, `confidence=0.73`, `APPROVED`, `processing_time_ms: 48`. First request after Provisioned Concurrency restart: 3,359ms (model loading). Every subsequent request: ~48ms. Thats the difference between a cold Lambda and a warm one with a loaded ONNX model.

---

## What Id Do Differently

Start with container images > Dont even attempt ZIP for an ML workload. The size constraints will force the switch anyway and its faster to just start there.

Set up the deployment script earlier > I was doing manual `aws lambda` commands for most of Phase 3. A `deploy.ps1` that handles the full sequence (build → push → publish → update alias → recycle concurrency) would have saved significant time.

Document the `patch()` rule somewhere visible > It will come up in every Python project with module boundaries.

---

## Final Numbers

| Metric | Result |
|--------|--------|
| Total tests | 139 across 5 modules |
| Coverage per module | 91–100% |
| API latency (warm) | ~48ms p50 |
| API latency (cold start) | ~3,359ms |
| Infrastructure resources | 15 (Terraform-managed) |
| Monthly cost | ~$9/month |
| Model accuracy | 94.6% on validation set |