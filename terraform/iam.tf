# The IAM role is like a ID-card for AWS, and Lambda is taking this role at the start. Else it could do nothing.

resource "aws_iam_role" "lambda" {
  name = "${var.project_name}-${var.environment}-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "lambda.amazonaws.com" }
        # Choosing lambda.amazonaws.com to narrow the role down by purpose.
        Action    = "sts:AssumeRole"
      }
    ]
  })

  tags = {
    Project     = var.project_name
    Environment = var.environment
  }
}

# Handing out policys to the above defined role. I use the predefined AWS-policys as it is fine.

# --- CloudWatch Logs ---
# Allows Lambda to write logs to CloudWatch.
# Attached via managed policy, no need to write this manually.

resource "aws_iam_role_policy_attachment" "lambda_logs" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
   # AWSLambdaBasicExecutionRole is the important part: It allows Lambda to write Logs to CloudWatch.
}

# --- DynamoDB Access ---
# Least privilege: only the actions our code actually uses.
# No DeleteItem — claims are never deleted (audit trail).
# As apposed to above, I do not use the standard AWS policy here to have a bit more control.

resource "aws_iam_role_policy" "dynamodb" {
  name = "${var.project_name}-${var.environment}-dynamodb-policy"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "dynamodb:PutItem",
          "dynamodb:GetItem",
          "dynamodb:UpdateItem",
        ]
        # Following the least-priviledge principle here, only actions that the user Code is actually using.
        # Items do not get deleted. reason: audit trail
        # No scan: I want to search only via predifined primary key 'claim_id', not the whole table to save resources.
        # Therefore No DescribeTable, Lambda doesnt have to know the table structure
        # Also in Case Lambda gets hacked: The attacker can only read claims, not write or delete.
        Resource = aws_dynamodb_table.claims.arn
        # The permission is only for our very specific table, not for all DynamoDB tables in the AWS account!
      }
    ]
  })
}
