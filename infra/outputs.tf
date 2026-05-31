output "vpc_id" {
  value = aws_vpc.main.id
}

output "public_subnet_ids" {
  value = aws_subnet.public[*].id
}

output "capacity_provider_name" {
  value = terraform_data.capacity_provider.input.name
}

output "capacity_provider_security_group_id" {
  value = aws_security_group.capacity_provider.id
}

output "ecr_repository_url" {
  value = aws_ecr_repository.driver.repository_url
}

output "driver_function_name" {
  value = terraform_data.driver_function.input.name
}
