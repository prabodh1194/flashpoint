resource "aws_ecs_cluster" "flashpoint" {
  name = "${local.prefix}-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = local.tags
}

resource "aws_ecs_cluster_capacity_providers" "flashpoint" {
  cluster_name       = aws_ecs_cluster.flashpoint.name
  capacity_providers = ["FARGATE", "FARGATE_SPOT"]
}

# Security group for all Spark Fargate tasks (driver + executors).
# Replaces the old LMI capacity-provider SG — same resource, renamed in IaC.
resource "aws_security_group" "spark_task" {
  name        = "${local.prefix}-spark-task"
  description = "Spark Fargate tasks - driver and executors"
  vpc_id      = aws_vpc.main.id

  # Spark Connect gRPC
  ingress {
    from_port   = 15002
    to_port     = 15002
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  # Spark Standalone master
  ingress {
    from_port   = 7077
    to_port     = 7077
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  # Spark driver RPC
  ingress {
    from_port   = 7078
    to_port     = 7078
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  # Spark block manager
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

# IAM — ECS task execution role (agent pulls image, writes logs)
resource "aws_iam_role" "ecs_execution" {
  name = "${local.prefix}-ecs-execution"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = local.tags
}

resource "aws_iam_role_policy_attachment" "ecs_execution" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# IAM — Spark task role (what the Spark process itself can do)
resource "aws_iam_role" "spark_task" {
  name = "${local.prefix}-spark-task"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = local.tags
}

# Driver task definition — Spark Connect gRPC server
resource "aws_ecs_task_definition" "driver" {
  family                   = "${local.prefix}-driver"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "4096"
  memory                   = "16384"
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.spark_task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }

  container_definitions = jsonencode([{
    name      = "spark-connect"
    image     = "${aws_ecr_repository.driver.repository_url}:latest"
    essential = true

    portMappings = [
      { containerPort = 15002, protocol = "tcp" },
      { containerPort = 7077,  protocol = "tcp" },
      { containerPort = 7078,  protocol = "tcp" },
      { containerPort = 7337,  protocol = "tcp" }
    ]

    environment = [
      { name = "SPARK_DRIVER_MEMORY", value = "12g" }
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.driver.name
        "awslogs-region"        = var.region
        "awslogs-stream-prefix" = "driver"
      }
    }
  }])

  tags = local.tags
}

# Executor task definition — Spark Standalone worker connecting to driver master
resource "aws_ecs_task_definition" "executor" {
  family                   = "${local.prefix}-executor"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "2048"
  memory                   = "8192"
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.spark_task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }

  container_definitions = jsonencode([{
    name       = "spark-executor"
    image      = "${aws_ecr_repository.driver.repository_url}:latest"
    essential  = true
    entryPoint = ["/opt/executor-entrypoint.sh"]

    portMappings = [
      { containerPort = 7337, protocol = "tcp" }
    ]

    environment = [
      { name = "SPARK_EXECUTOR_CORES",  value = "2" },
      { name = "SPARK_EXECUTOR_MEMORY", value = "6g" }
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.executor.name
        "awslogs-region"        = var.region
        "awslogs-stream-prefix" = "executor"
      }
    }
  }])

  tags = local.tags
}
