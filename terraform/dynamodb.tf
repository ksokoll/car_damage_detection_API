resource "aws_dynamodb_table" "claims" {
  name         = "${var.project_name}-${var.environment}-${var.dynamodb_table_name}"
    # I try to keep the table names following the same convinience like in the other resources: car-damage-dev-claims
  billing_mode = "PAY_PER_REQUEST"
  # Here i have two options: Either I pay per single request, OR provisioned. Since the use-case is about 1000 requests per day,
  # PAY_PER_REQUEST is way cheaper than privisioned, which would only be worth it from ~1 Million requests per day.
  hash_key     = "claim_id"
  # This is our Primary key for each claim. DynamoDB is distributing the data internally and this key helps stitching it back together.

  attribute {
    name = "claim_id"
    type = "S"
  }
  # This is concerning ONLY the primary key which is a string, therefore "S". The other fields like "damage" do not need to be defined here!

  tags = {
    Project     = var.project_name
    Environment = var.environment
  }
}
