# VPC interface endpoints — provisioned only when enable_vpc_endpoints = true.
# Replaces NAT gateway for ECR image pulls and CloudWatch Logs. ~$22/month idle.
# Use for production; leave false for dev to keep idle cost at $0.

locals {
  endpoint_subnets = var.enable_vpc_endpoints ? aws_subnet.private[*].id : []
}

resource "aws_vpc_endpoint" "s3" {
  count        = var.enable_vpc_endpoints ? 1 : 0
  vpc_id       = aws_vpc.main.id
  service_name = "com.amazonaws.${var.region}.s3"
  # Gateway endpoint — free; routes S3 traffic (ECR layer pulls) without NAT.
  vpc_endpoint_type = "Gateway"
  route_table_ids   = aws_route_table.private[*].id
  tags              = merge(local.tags, { Name = "${local.prefix}-s3" })
}

resource "aws_vpc_endpoint" "ecr_api" {
  count               = var.enable_vpc_endpoints ? 1 : 0
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.region}.ecr.api"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = local.endpoint_subnets
  security_group_ids  = [aws_security_group.spark_task.id]
  private_dns_enabled = true
  tags                = merge(local.tags, { Name = "${local.prefix}-ecr-api" })
}

resource "aws_vpc_endpoint" "ecr_dkr" {
  count               = var.enable_vpc_endpoints ? 1 : 0
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.region}.ecr.dkr"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = local.endpoint_subnets
  security_group_ids  = [aws_security_group.spark_task.id]
  private_dns_enabled = true
  tags                = merge(local.tags, { Name = "${local.prefix}-ecr-dkr" })
}

resource "aws_vpc_endpoint" "logs" {
  count               = var.enable_vpc_endpoints ? 1 : 0
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.region}.logs"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = local.endpoint_subnets
  security_group_ids  = [aws_security_group.spark_task.id]
  private_dns_enabled = true
  tags                = merge(local.tags, { Name = "${local.prefix}-logs" })
}
