output "vpc_id" {
  value = aws_vpc.main.id
}

output "private_subnet_ids" {
  value = aws_subnet.private[*].id
}

output "capacity_provider_name" {
  value = terraform_data.capacity_provider.input.name
}

output "capacity_provider_security_group_id" {
  value = aws_security_group.capacity_provider.id
}
