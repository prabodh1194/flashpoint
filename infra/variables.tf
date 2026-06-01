variable "region" {
  type    = string
  default = "us-east-1"
}

variable "project" {
  type    = string
  default = "flashpoint"
}

variable "env" {
  type    = string
  default = "dev"
}

variable "vpc_cidr" {
  type    = string
  default = "10.0.0.0/16"
}

variable "availability_zones" {
  type    = list(string)
  default = ["us-east-1a", "us-east-1b", "us-east-1c"]
}

# When true: private subnets + VPC interface endpoints for ECR/CWL (no public IPs on compute).
# When false (default): public subnets, no NAT, no endpoints — zero idle cost for dev.
variable "enable_vpc_endpoints" {
  type    = bool
  default = false
}

variable "gateway_branch" {
  type        = string
  default     = "main"
  description = "Git branch to deploy on the gateway EC2 instance"
}
