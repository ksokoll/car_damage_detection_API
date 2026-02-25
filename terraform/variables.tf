variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "eu-central-1"
}
# Chose the next location for DACH-Customers. Adjust based on your local circumstamces.
# This choice influences latency but also data security and cost.

variable "environment" {
  description = "Deployment environment (dev, staging, prod)"
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be one of: dev, staging, prod"
  }
}
# Terraform will break with the above error message if someone calls for example "production" instad of "prod".

variable "project_name" {
  description = "Project name used as prefix for all resource names"
  type        = string
  default     = "car-damage"
}
# Is used as prefix for all resource names. This enables multiple projects on the same AWS account without having name conflicts.

variable "lambda_memory_mb" {
  description = "Lambda memory in MB. ONNX Runtime + OpenCV + image processing requires ~400-600MB. 1024MB provides headroom and doubles CPU allocation (Lambda scales CPU proportional to memory)."
  type        = number
  default     = 1024
}
# The CPU config is not missing, instead Lambda scales the CPU proportional to memory (1024MB memory = 1 CPU)
# I figured 1024 is the sweet spot for this use-case as it gives enough wiggling room for the ML-Model & Dependencies in comparison to 512 MB.
# TYou might think this is a lot, since we have a lightweight onnx-runtime instead of the whole Ultralytics dependancy, but even then it quickly adds up:
# ONNX runtime: ~100MB, OpenCV (headless) ~50MB, Numpy ~25 MB, Pillow, Pydantic, Boto3, Python interpreter, etc. Which adds up to 240MB.
# Also the temporary memory needed to cover a request: Load ONNX model, PIL image, ...) -> ~20MB
# Overall we can estimate about ~300MB of memory usage. Choosing 512MB here would be a gamble, and we risk a OOM error.


variable "lambda_timeout_seconds" {
  description = "Lambda function timeout in seconds"
  type        = number
  default     = 30
}
# After 30 seconds our Lambda will cancel the request and throw an error. Our inference should be <2 seconds, so 30 seconds is very generous.
# A maximum of 15 minutes would be possible, but doesnt make sense for a user facing automation like our use case.

variable "dynamodb_table_name" {
  description = "DynamoDB table name for claim records"
  type        = string
  default     = "claims"
}
