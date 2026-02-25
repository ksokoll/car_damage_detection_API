# Cloudwatch Log Groups are known Containers for Log-Entries which our Lambda can automatically write to which is quite handy.
# But why do I create it here? Because if I dont, retention_in_days is infinity which means the logs never run out.
# Thats oftentimes not necessary and costs money, and 30 days is oftentimes enough for debugging.
# If you have stricter intercompany rules, for example the 90 days for SOC compliance, you can change it here.

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${local.lambda_name}"
  retention_in_days = 30

  tags = {
    Project     = var.project_name
    Environment = var.environment
  }
}
