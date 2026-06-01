resource "aws_cloudwatch_log_group" "driver" {
  name              = "/flashpoint/driver"
  retention_in_days = 1

  tags = local.tags
}
