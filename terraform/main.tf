# The main are only 14 lines of code (excluding comments), but quite important ones.


terraform {
  required_version = ">= 1.6"
  # This protects us from aged installations, as if someone uses a older version, Terraform will break with a clear error statement
  # instead of a silent failure inmidst of the runtime.

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
      # I pinned the version to avoid having groundbreaking changes (which can happen when a version changes from 5.X to 6.X) without us noticing it.
    }
  }
}

provider "aws" {
  region = var.aws_region
}
# This points AWS to our region which is stated in our variables.tf.
