# build.ps1
# Builds and pushes the Lambda container image to ECR.
#
# Prerequisites:
#   - Docker Desktop running
#   - AWS CLI configured (aws configure)
#   - terraform apply already run once (ECR repository must exist)
#
# Usage:
#   .\scripts\build.ps1 -Region eu-central-1 -Environment dev
#
# On first run: terraform apply → build.ps1 → terraform apply again
# (Lambda needs the image to exist before it can be created)

param(
    [string]$Region      = "eu-central-1",
    [string]$Environment = "dev",
    [string]$ProjectName = "car-damage"
)

$ErrorActionPreference = "Stop"

# Derive ECR repository URL from AWS account ID
$AccountId = (aws sts get-caller-identity --query Account --output text)
# aws sts get-caller-identity = returns the AWS account ID of the current credentials
# Used to construct the full ECR URL without hardcoding the account ID

$EcrUrl    = "$AccountId.dkr.ecr.$Region.amazonaws.com"
$ImageName = "$ProjectName-$Environment"
$FullImage = "$EcrUrl/$ImageName`:latest"

Write-Host "Building image: $FullImage"

# 1. Authenticate Docker with ECR
# ECR requires a temporary login token — valid for 12 hours
aws ecr get-login-password --region $Region | docker login --username AWS --password-stdin $EcrUrl
Write-Host "Docker authenticated with ECR."

# 2. Build the Docker image
# --platform linux/amd64 = Lambda runs on x86_64 Linux
# Build on Apple Silicon (M1/M2) or ARM without this flag produces an incompatible image
docker build --platform linux/amd64 -t $ImageName (Join-Path $PSScriptRoot "..\lambda")
Write-Host "Image built."

# 3. Tag the image with the full ECR URL
docker tag "$ImageName`:latest" $FullImage
Write-Host "Image tagged."

# 4. Push to ECR
docker push $FullImage
Write-Host "Image pushed to ECR: $FullImage"

Write-Host ""
Write-Host "Done. Run 'terraform apply' to deploy the updated Lambda."
