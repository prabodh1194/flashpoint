terraform {
  required_providers {
    cloudflare = {
      source  = "registry.opentofu.org/cloudflare/cloudflare"
      version = "~> 5.0"
    }
  }
  required_version = ">= 1.8"
}

# The API token is read from CLOUDFLARE_API_TOKEN. Never put it in a tfvars
# file — this repository is public.
#
# Required token permissions:
#   Zone → DNS → Edit              (records, redirect placeholder)
#   Zone → Zone Settings → Read    (zone lookup)
#   Zone → Config Rules → Edit     (the redirect ruleset)
#   Account → Registrar → Edit     (auto-renew and privacy, optional)
provider "cloudflare" {}
