resource "aws_ecr_repository" "lambda" {
  name = "${var.project_name}-${var.environment}"
  # ECR = Elastic Container Registry is the AWS Docker Registry
  # It serves as a cache for our docker image before the Lambda gets loaded (a bit like Docker Hub)

  image_tag_mutability = "MUTABLE"
  # MUTABLE means that tags with the same name can be overwritten. This is OK for this project, in production IMMUTABLE is the safer bet.
  # IMMUTABLE = each image needs a unique tag and cannot be overwritten; better for production.

  image_scanning_configuration {
    scan_on_push = true
    # ECR scans for known security vulnerabilities before loading the image
    # Results are visible under ECR → Repository → Images
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
  }
}

resource "aws_ecr_lifecycle_policy" "lambda" {
  repository = aws_ecr_repository.lambda.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep only the 3 most recent images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 3
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
  # Lifecycle Policy = automatic cleaning of older images, it keeps only the 3 most recent ones
  # Without this policy old images can stack up and create costs (~$0.10/GB/Month)
  # Note: lifecycle_policy must be a separate resource in Terraform — not an attribute of aws_ecr_repository
}

output "ecr_repository_url" {
  description = "ECR repository URL — used in build script to push the image"
  value       = aws_ecr_repository.lambda.repository_url
  # Format: {account_id}.dkr.ecr.eu-central-1.amazonaws.com/car-damage-dev
  # The build script needs this URL to tag and push the image
}
