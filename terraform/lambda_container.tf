locals {
  lambda_name = "${var.project_name}-${var.environment}-handler"
  # For convenience and better readability the lambda name gets saved here in a local variable
  # instead of writing it out in the big string every time.
  # Result: "car-damage-dev-handler"
}

# --- Lambda Function ---

resource "aws_lambda_function" "main" {
  function_name = local.lambda_name
  role          = aws_iam_role.lambda.arn

  package_type = "Image"
  # "Image" instead of "Zip" — Lambda loads the container image from ECR.
  # Limit: 10GB instead of 250MB — no more issues with ONNX Runtime + OpenCV.

  image_uri = "${aws_ecr_repository.lambda.repository_url}:latest"
  # ECR URL + tag: {account}.dkr.ecr.eu-central-1.amazonaws.com/car-damage-dev:latest
  # "latest" = always the most recently pushed image.
  # Terraform re-deploys Lambda when image_uri changes.
  # For production: use a specific tag instead of "latest" (e.g. Git commit hash)
  # to guarantee reproducible deployments.

  memory_size = var.lambda_memory_mb
  timeout     = var.lambda_timeout_seconds
  # These are defined in variables.tf — please find the explanations for the chosen values there.

  environment {
    variables = {
      DYNAMODB_TABLE = aws_dynamodb_table.claims.name
    }
  }
  # Gets passed at runtime and matches os.environ.get("DYNAMODB_TABLE") in config.py.
  # Using environment variables saves us from manually changing the table path —
  # Lambda doesn't care where it runs, the correct table name is always injected automatically.

  publish = true
  # publish = true means every deployment creates a numbered version (v1, v2, ...)
  # otherwise it would only expose $LATEST — a mutable, unversioned reference.
  # Required for Provisioned Concurrency — it only works on fixed versions, not $LATEST.

  tags = {
    Project     = var.project_name
    Environment = var.environment
  }
}

# --- Alias ---
# Alias points to the latest published version.
# API Gateway and Provisioned Concurrency reference the alias, not the function directly.
# This allows blue/green deployments later without changing API Gateway config.

resource "aws_lambda_alias" "main" {
  name             = var.environment
  function_name    = aws_lambda_function.main.function_name
  function_version = aws_lambda_function.main.version
  # .version returns the most recently published version number (e.g. "3").
  # The alias always points to the latest version after each deploy.
}

# --- Provisioned Concurrency ---
# Keeps one Lambda instance permanently warm — eliminates cold starts.
# Especially important for container images: cold start takes longer than ZIP
# because the full image (~500MB) needs to be pulled on first invocation.
# With Provisioned Concurrency: cold start happens once at terraform apply time, not at request time.
# Cost: ~$8/month for 1 instance in eu-central-1.
# Required for latency-sensitive user-facing flows like ours (target: <2s p95).

resource "aws_lambda_provisioned_concurrency_config" "main" {
  function_name                     = aws_lambda_function.main.function_name
  qualifier                         = aws_lambda_alias.main.name
  provisioned_concurrent_executions = 1
}
