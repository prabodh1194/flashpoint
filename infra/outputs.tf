output "vpc_id" {
  value = aws_vpc.main.id
}

output "public_subnet_ids" {
  value = aws_subnet.public[*].id
}

output "task_security_group_id" {
  value = aws_security_group.spark_task.id
}

output "ecr_repository_url" {
  value = aws_ecr_repository.driver.repository_url
}

output "ecs_cluster_arn" {
  value = aws_ecs_cluster.flashpoint.arn
}

output "driver_task_definition_arn" {
  value = aws_ecs_task_definition.driver.arn
}

output "gateway_public_ip" {
  value = aws_instance.gateway.public_ip
}

output "gateway_api" {
  value = "http://${aws_instance.gateway.public_ip}:8080"
}
