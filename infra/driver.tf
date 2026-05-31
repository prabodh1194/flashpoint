locals {
  driver_image_uri = "${aws_ecr_repository.driver.repository_url}:latest"
}

# aws_lambda_function does not support capacity_provider_config (Lambda Managed Instances
# launched Nov 2025; provider hasn't caught up). Created via CLI like the capacity provider.
resource "terraform_data" "driver_function" {
  input = {
    name                  = "${local.prefix}-driver"
    image_uri             = local.driver_image_uri
    role_arn              = aws_iam_role.capacity_provider.arn
    capacity_provider_arn = terraform_data.capacity_provider.input.capacity_provider_arn
    region                = var.region
    profile               = "personal-aws"
  }

  # Create
  provisioner "local-exec" {
    command = <<-EOT
      aws lambda create-function \
        --function-name "${self.input.name}" \
        --package-type Image \
        --code ImageUri="${self.input.image_uri}" \
        --role "${self.input.role_arn}" \
        --architectures arm64 \
        --timeout 900 \
        --memory-size 3008 \
        --environment 'Variables={SPARK_DRIVER_MEMORY=12g}' \
        --capacity-provider-config 'LambdaManagedInstancesCapacityProviderConfig={CapacityProviderArn=${self.input.capacity_provider_arn}}' \
        --region ${self.input.region} \
        --profile ${self.input.profile} \
        --no-cli-pager
    EOT
  }

  # Destroy
  provisioner "local-exec" {
    when    = destroy
    command = <<-EOT
      aws lambda delete-function \
        --function-name "${self.input.name}" \
        --region ${self.input.region} \
        --profile ${self.input.profile} \
        --no-cli-pager || true
    EOT
  }

  depends_on = [
    aws_ecr_repository.driver,
    terraform_data.capacity_provider,
  ]
}
