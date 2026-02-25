output "api_url" {
  description = "Base URL for the API — append /claims/validate etc."
  value       = aws_apigatewayv2_stage.main.invoke_url
}
# This is the URL of our API which then can be used in Postman for example.

output "lambda_function_name" {
  description = "Lambda function name — use for manual invocation and debugging"
  value       = aws_lambda_function.main.function_name
}
# Helpful for manual Calls via the AWS CLI.

output "dynamodb_table_name" {
  description = "DynamoDB table name — use for manual queries and setup_local_db.py"
  value       = aws_dynamodb_table.claims.name
}
# Helpful for direct DynamoDB Calls via AWS CLI.

output "cloudwatch_log_group" {
  description = "CloudWatch log group — use for debugging Lambda errors"
  value       = aws_cloudwatch_log_group.lambda.name
}
# Helpful for direct access to Log Group via AWS CLI.
