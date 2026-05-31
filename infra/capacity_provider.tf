# Lambda Managed Instances capacity provider.
# This is the compute boundary for all Spark driver and executor functions.
# See: https://docs.aws.amazon.com/lambda/latest/dg/lambda-managed-instances.html

resource "aws_security_group" "capacity_provider" {
  name        = "${local.prefix}-capacity-provider"
  description = "Lambda Managed Instances capacity provider"
  vpc_id      = aws_vpc.main.id

  # Spark Connect gRPC (15002) — driver to client
  ingress {
    from_port   = 15002
    to_port     = 15002
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  # Spark executor RPC
  ingress {
    from_port   = 7337
    to_port     = 7337
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = local.tags
}

# IAM role assumed by Lambda functions (driver + executors) at runtime.
resource "aws_iam_role" "capacity_provider" {
  name = "${local.prefix}-capacity-provider"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = local.tags
}

resource "aws_iam_role_policy_attachment" "capacity_provider_basic" {
  role       = aws_iam_role.capacity_provider.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

# Operator role — used by the Lambda capacity provider control plane to manage EC2 instances.
# Trust principal is scaler.lambda.amazonaws.com, not lambda.amazonaws.com.
resource "aws_iam_role" "capacity_provider_operator" {
  name = "${local.prefix}-capacity-provider-operator"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "scaler.lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = local.tags
}

resource "aws_iam_role_policy_attachment" "capacity_provider_operator_ec2" {
  role       = aws_iam_role.capacity_provider_operator.name
  policy_arn = "arn:aws:iam::aws:policy/AWSLambdaManagedEC2ResourceOperator"
}

# Capacity provider — the compute boundary for Spark functions.
#
# aws_lambda_capacity_provider is not yet in the AWS provider (Lambda Managed Instances
# launched Nov 2025). Managed via AWS CLI until provider support lands.
resource "terraform_data" "capacity_provider" {
  input = {
    name                  = "${local.prefix}-spark"
    capacity_provider_arn = "arn:aws:lambda:${var.region}:${data.aws_caller_identity.current.account_id}:capacity-provider:${local.prefix}-spark"
    subnet_ids            = var.enable_vpc_endpoints ? jsonencode(aws_subnet.private[*].id) : jsonencode(aws_subnet.public[*].id)
    security_group_ids    = jsonencode([aws_security_group.capacity_provider.id])
    operator_role_arn     = aws_iam_role.capacity_provider_operator.arn
    region                = var.region
    profile               = "personal-aws"
  }

  # Create
  provisioner "local-exec" {
    command = <<-EOT
      aws lambda create-capacity-provider \
        --capacity-provider-name "${self.input.name}" \
        --vpc-config "SubnetIds=${self.input.subnet_ids},SecurityGroupIds=${self.input.security_group_ids}" \
        --permissions-config "CapacityProviderOperatorRoleArn=${self.input.operator_role_arn}" \
        --instance-requirements "Architectures=[arm64]" \
        --region ${self.input.region} \
        --profile ${self.input.profile} \
        --no-cli-pager
    EOT
  }

  # Destroy
  provisioner "local-exec" {
    when    = destroy
    command = <<-EOT
      aws lambda delete-capacity-provider \
        --capacity-provider-name "${self.input.name}" \
        --region ${self.input.region} \
        --profile ${self.input.profile} \
        --no-cli-pager
    EOT
  }
}
