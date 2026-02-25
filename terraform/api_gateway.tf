resource "aws_apigatewayv2_api" "main" {
  name          = "${var.project_name}-${var.environment}-api"
  protocol_type = "HTTP"
  # Why HTTP? It is ~70% cheaper than REST API and has a lower latency, which is key for the use case.
  # REST API offers more functionality like caching, which is however not necessary for this use case.
  # Also Supports Lambda integration without extra configuration

  cors_configuration {
    allow_origins = ["*"]
    # For production please restrict allow_origins to the actual frontend domain! '*' is a testing wildcard.
    allow_methods = ["GET", "POST", "PUT"]
    # it is best practise to restrict the HTTP-methods only to the ones you actually use, which is GET, POST, PUt in our case.
    # Skipped "OPTIONS" here as this is already handled automatically by the API Gateway.
    allow_headers = ["Content-Type"]
    # Necessary to enable Preflight
    
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
  }
}

# --- Lambda Integration ---
# Connects API Gateway to our Lambda alias.
# payload_format_version 2.0 = the event format our handler expects
# (requestContext.http.method / path)

resource "aws_apigatewayv2_integration" "lambda" {
  api_id             = aws_apigatewayv2_api.main.id
  integration_type   = "AWS_PROXY"
  # Choosing not to use "AWS" here to keep it simpler
  integration_uri    = aws_lambda_alias.main.invoke_arn
  payload_format_version = "2.0"
}

# --- Routes ---
# Catch-all route — all requests go to Lambda, handler routes internally

resource "aws_apigatewayv2_route" "default" {
  api_id    = aws_apigatewayv2_api.main.id
  route_key = "$default"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}
# Redirecting everything to lambda as our handler is already doing the routing internally by string-matching, which saves terraform resources.

# --- Stage ---
# A stage is a named deployment of the API (like dev, prod)
# auto_deploy = true: changes go live immediately without manual deployment steps in the AWS console; Can be switched to false for productive use cases for more control.

resource "aws_apigatewayv2_stage" "main" {
  api_id      = aws_apigatewayv2_api.main.id
  name        = var.environment
  auto_deploy = true

  tags = {
    Project     = var.project_name
    Environment = var.environment
  }
}

# --- Permission ---
# Explicitly grants API Gateway permission to invoke the Lambda alias.
# Without this, API Gateway gets a 403 even with correct IAM roles.

resource "aws_lambda_permission" "api_gateway" {
  # The IAM roles are needed to not receive a 403 Error when trying to call Lambda
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  # Defining the only allowed action here and exclude anything else: It is only allowed to call Lambda
  function_name = aws_lambda_function.main.function_name
  qualifier     = aws_lambda_alias.main.name
  # Explicitly defining the main.name here, so the permission is narrower and not valid for all versions and aliases.
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*/*"
  # Narrows down permission for our specific Api. If I left that out, every API gateway instance could call this Lambda.
}
