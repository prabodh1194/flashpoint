terraform {
  required_providers {
    aws = {
      source  = "registry.opentofu.org/hashicorp/aws"
      version = "~> 5.0"
    }
  }
  required_version = ">= 1.8"
}

provider "aws" {
  region  = var.region
  profile = "personal-aws"
}

data "aws_caller_identity" "current" {}
