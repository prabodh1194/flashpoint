resource "aws_dynamodb_table" "warehouses" {
  name         = "${local.prefix}-warehouses"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "name"

  attribute {
    name = "name"
    type = "S"
  }

  tags = local.tags
}

resource "aws_dynamodb_table" "meters" {
  name         = "${local.prefix}-meters"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  range_key    = "sk"

  attribute {
    name = "pk"
    type = "S"
  }

  attribute {
    name = "sk"
    type = "S"
  }

  tags = local.tags
}
