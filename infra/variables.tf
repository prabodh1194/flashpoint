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

# EventBridge cron expressions (UTC). Defaults: 9am–midnight IST = 3:30am–6:30pm UTC.
# Set to empty string "" to disable scheduling entirely.
variable "gateway_start_cron" {
  type        = string
  default     = "cron(30 3 * * ? *)"
  description = "EventBridge cron to START the gateway EC2 (UTC). Default: 09:00 IST."
}

variable "gateway_stop_cron" {
  type        = string
  default     = "cron(30 18 * * ? *)"
  description = "EventBridge cron to STOP the gateway EC2 (UTC). Default: 00:00 IST."
}
