data "aws_ami" "al2023_arm64" {
  most_recent = true
  owners      = ["amazon"]
  filter {
    name   = "name"
    values = ["al2023-ami-*-arm64"]
  }
  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

resource "aws_security_group" "gateway" {
  name        = "${local.prefix}-gateway"
  description = "Flashpoint gateway EC2"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "Gateway API"
    from_port   = 8080
    to_port     = 8080
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = local.tags
}

resource "aws_iam_role" "gateway" {
  name = "${local.prefix}-gateway"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = local.tags
}

resource "aws_iam_role_policy" "gateway_ecs" {
  name = "ecs-fargate-ops"
  role = aws_iam_role.gateway.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ecs:RunTask",
          "ecs:StopTask",
          "ecs:DescribeTasks",
          "ecs:ListTasks",
        ]
        Resource = "*"
      },
      {
        # Required to pass the task role to ECS
        Effect   = "Allow"
        Action   = "iam:PassRole"
        Resource = [
          aws_iam_role.ecs_execution.arn,
          aws_iam_role.spark_task.arn,
        ]
      },
      {
        Effect   = "Allow"
        Action   = "ec2:DescribeNetworkInterfaces"
        Resource = "*"
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "gateway_ssm" {
  role       = aws_iam_role.gateway.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "gateway" {
  name = "${local.prefix}-gateway"
  role = aws_iam_role.gateway.name
}

resource "aws_instance" "gateway" {
  ami                         = data.aws_ami.al2023_arm64.id
  instance_type               = "t4g.small"
  subnet_id                   = aws_subnet.public[0].id
  vpc_security_group_ids      = [aws_security_group.gateway.id]
  iam_instance_profile        = aws_iam_instance_profile.gateway.name
  associate_public_ip_address = true

  user_data = base64encode(templatefile("${path.module}/gateway-init.sh", {
    cluster        = aws_ecs_cluster.flashpoint.name
    task_def       = aws_ecs_task_definition.driver.arn
    subnets        = join(",", aws_subnet.public[*].id)
    security_group = aws_security_group.spark_task.id
    region         = var.region
    branch         = var.gateway_branch
  }))

  tags = merge(local.tags, { Name = "${local.prefix}-gateway" })
}
