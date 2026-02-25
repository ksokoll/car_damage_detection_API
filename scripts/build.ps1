# build.ps1
# Builds and pushes the Lambda container image to ECR.
#
# Prerequisites:
#   - Docker Desktop running
#   - AWS CLI configured (aws configure)
#   - terraform apply already run once (ECR repository must exist)
#
# Usage:
#   .\scripts\build.ps1

param(
    [string]$Region      = "eu-central-1",
    [string]$Environment = "dev",
    [string]$ProjectName = "car-damage"
)

$ErrorActionPreference = "Stop"

$ROOT      = Split-Path -Parent $PSScriptRoot
$LAMBDA_DIR = Join-Path $ROOT "lambda"

# Derive ECR repository URL from AWS account ID
# aws sts get-caller-identity returns the AWS account ID of the current credentials
$AccountId = (& "C:\Program Files\Amazon\AWSCLIV2\aws.exe" sts get-caller-identity --query Account --output text)
$EcrUrl    = "$AccountId.dkr.ecr.$Region.amazonaws.com"
$ImageName = "$ProjectName-$Environment"
$FullImage = "$EcrUrl/$ImageName`:latest"

Write-Host "Building image: $FullImage"

# 1. Authenticate Docker with ECR
# ECR requires a temporary login token — valid for 12 hours
Write-Host "Authenticating Docker with ECR..."
& "C:\Program Files\Amazon\AWSCLIV2\aws.exe" ecr get-login-password --region $Region | docker login --username AWS --password-stdin $EcrUrl

# 2. Build the Docker image
# --platform linux/amd64 = Lambda runs on x86_64 Linux
# Without this flag, builds on ARM machines produce incompatible images
Write-Host "Building Docker image..."
docker build --platform linux/amd64 -t $ImageName $LAMBDA_DIR

# 3. Tag the image with the full ECR URL
Write-Host "Tagging image..."
docker tag "$ImageName`:latest" $FullImage

# 4. Push to ECR
Write-Host "Pushing image to ECR..."
docker push $FullImage

Write-Host ""
Write-Host "Done. Image pushed: $FullImage"
Write-Host "Run 'terraform apply' to deploy the updated Lambda."