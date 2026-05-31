resource "aws_cloudwatch_log_group" "driver" {
  name              = "/aws/lambda/flashpoint-dev-driver"
  retention_in_days = 1

  tags = local.tags
}
