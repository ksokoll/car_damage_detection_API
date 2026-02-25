# Architecture Decision Record
## Car Damage Detection System

---

## 1. Single Lambda vs. Microservices

My first instinct was Step Functions but it Turned out to be wrong.

The system processes 1–3 requests per minute. The workflow completes in under 2 seconds synchronously. The target customers are mid-sized insurance companies with small IT teams. None of that justifies distributed architecture. Microservices would have added four IAM roles, four CloudWatch log groups, four deployment pipelines, and a whole new class of distributed debugging problems for a workflow that a single Lambda handles in 48ms.

The code is still structured as if the services were separate: `validator.py`, `inference.py`, `storage.py` have no cross-dependencies and are independently testable. The modularity is real, the operational overhead isnt.

If the workflow becomes async (a human review loop that takes hours or days), or volume exceeds ~100 req/min sustained, or separate teams need independent deployment cycles — the modules are already written to be extracted.

---

## 2. Lambda: Container Image vs. ZIP

Not much of a choice once you look at the numbers: ONNX Runtime is ~100MB, OpenCV headless is ~50MB. The Lambda ZIP limit is 250MB uncompressed. Thats gone before you add application code.

Container images support up to 10GB, are locally testable with `docker run`, and are the standard approach for ML workloads on Lambda. The trade-off is a slightly slower initial deployment and an ECR repository. Both are minor compared to the alternative of fighting dependency size limits.

---

## 3. Lambda Memory: 1024MB

ONNX Runtime + OpenCV + PIL + the image itself in memory adds up to roughly 400–600MB at peak. 512MB would have been a gamble, especially with Provisioned Concurrency keeping everything permanently loaded in RAM.

The bonus: Lambda allocates CPU proportional to memory, so 1024MB doubles the CPU allocation vs. 512MB. The measured result was ~48ms p50 latency, well under the <2s p95 target.

---

## 4. Provisioned Concurrency: 1 Permanently Warm Instance

Cold start was 3,359ms. I measured it, but afterwards the latency dropt to a staggering ~50ms response which is amazing! Really opened my eyes about what optimizing for latency can yeild for result.s ~$8/month for Provisioned Concurrency was an obvious fix. the only annoying part is that after updating the Lambda you have to manually delete and recreate the config, otherwise the warm instance keeps running old code.

---

## 5. API Gateway: HTTP API vs. REST API

HTTP API is about 70% cheaper than REST API and has lower latency. Sure, REST API has more features like WAF, request caching API key management. None of which are needed here. HTTP API was the right fit.

---

## 6. Routing: $default Route

The handler does its own routing internally via path string matching. This means fewer Terraform resources and a simpler configuration, at the cost of not using API Gateways native `pathParameters`. For a three-endpoint API, the trade-off is fine. In production with more routes, individual route definitions would be cleaner.

---

## 7. DynamoDB: PAY_PER_REQUEST

At 1,000 requests/day PAY_PER_REQUEST costs about $0.01/day. PROVISIONED only makes sense above ~1M requests/day.

---

## 8. IAM: Least Privilege

Only `PutItem`, `GetItem`, `UpdateItem` on the specific table ARN.

No `DeleteItem`, claims are an immutable audit trail, nothing gets deleted. No `Scan`, every lookup is by `claim_id`. If the Lambda is ever compromised, an attacker can read and write claims but cant wipe the table.

---

## 9. CloudWatch Log Retention: 30 Days

AWSs default is never expire. Logs accumulate forever and cost money. 30 days is enough to debug any production issue. Defined in Terraform so its version-controlled and doesnt depend on someone remembering to set it manually.

---

## 10. ECR: MUTABLE Tags + Lifecycle Policy

For a portfolio project, overwriting `latest` on every deploy is fine. In production, Git commit hash tags would be the right call: reproducible, auditable. The lifecycle policy keeps only the 3 most recent images to avoid accumulating storage costs (~$0.10/GB/month).

---

## 11. Override Logic: No Quality Check at Override Time

Quality is checked at `POST /validate` only, not at `PUT /override`.

Any claim that exists in DynamoDB has already passed the quality gate. Checking quality again at override time would be redundant and frankly a bit paternalistic. The user can see their own photo. If the AI rejected it with low confidence, the user is in a better position than the model to know whether damage is actually visible. The original AI decision is preserved in `system_status` regardless, so the audit trail stays clean.

---

## 12. ClaimStatus: str Enum

Inheriting from both `str` and `Enum` means Pydantic serializes the enum values to plain strings automatically — no `.value` calls scattered through the codebase, no custom serializers, and the DynamoDB writes just work. Small thing, but it removes a whole category of subtle serialization bugs.

---

## Whats Missing for Production

This is a portfolio project, not a production deployment. The gaps are documented here because knowing whats missing is part of the design, not because any of it was forgotten.

The biggest practical gaps: theres no authentication (any request hits the API), image upload is Base64 in the JSON body which approaches API Gateways 10MB payload limit (pre-signed S3 URLs would solve this), and theres no CI/CD pipeline. Deployments are manual `build.ps1` + `terraform apply`. For a real rollout these would be the first things to address.

Other gaps are less urgent: the `$default` catch-all route works fine but individual API Gateway routes with `pathParameters` would be cleaner at scale; CloudWatch logs are sufficient for now but X-Ray tracing would make distributed debugging easier; the ONNX model is baked into the container image rather than versioned in S3, which makes model updates a full redeploy.

None of this was an oversight. The infrastructure that exists is production-quality. The missing pieces are mostly things Id add before going live — not things that change how the system works.