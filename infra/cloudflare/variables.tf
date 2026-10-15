variable "account_id" {
  description = "Cloudflare account ID — needed only for the registrar settings."
  type        = string
}

variable "domain" {
  description = "The product domain, served by GitHub Pages."
  type        = string
  default     = "flashpointdb.com"
}

variable "zone_id" {
  description = "Zone ID of var.domain (dashboard → the domain → Overview → Zone ID)."
  type        = string
}

variable "redirect_from" {
  description = "Legacy domain that 301s to var.domain."
  type        = string
  default     = "sparksql.dev"
}

variable "redirect_zone_id" {
  description = "Zone ID of var.redirect_from."
  type        = string
}

variable "github_pages_owner" {
  description = "GitHub account hosting the Pages site, used for the www CNAME."
  type        = string
  default     = "prabodh1194"
}

variable "proxy_pages_records" {
  description = <<-EOT
    Proxy the GitHub Pages records through Cloudflare.
    Leave false for the first apply: GitHub cannot issue its certificate while
    the records are proxied. Turn it on once HTTPS is enforced.
  EOT
  type        = bool
  default     = false
}

