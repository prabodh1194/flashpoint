# DNS for the product domain, pointing at GitHub Pages.
#
# GitHub publishes these four addresses for Pages apex domains; the www
# subdomain is a CNAME to the Pages host. Source:
# docs.github.com → Pages → Managing a custom domain for your GitHub Pages site

locals {
  github_pages_ipv4 = [
    "185.199.108.153",
    "185.199.109.153",
    "185.199.110.153",
    "185.199.111.153",
  ]

  github_pages_ipv6 = [
    "2606:50c0:8000::153",
    "2606:50c0:8001::153",
    "2606:50c0:8002::153",
    "2606:50c0:8003::153",
  ]

  pages_hostname = "${var.github_pages_owner}.github.io"
}

resource "cloudflare_dns_record" "apex_a" {
  for_each = toset(local.github_pages_ipv4)

  zone_id = var.zone_id
  name    = var.domain
  type    = "A"
  content = each.value
  ttl     = 1 # automatic
  proxied = var.proxy_pages_records
  comment = "GitHub Pages apex"
}

resource "cloudflare_dns_record" "apex_aaaa" {
  for_each = toset(local.github_pages_ipv6)

  zone_id = var.zone_id
  name    = var.domain
  type    = "AAAA"
  content = each.value
  ttl     = 1
  proxied = var.proxy_pages_records
  comment = "GitHub Pages apex"
}

resource "cloudflare_dns_record" "www" {
  zone_id = var.zone_id
  name    = "www.${var.domain}"
  type    = "CNAME"
  content = local.pages_hostname
  ttl     = 1
  proxied = var.proxy_pages_records
  comment = "GitHub Pages www"
}

# The redirect rule only fires for hostnames that resolve through Cloudflare,
# so the legacy domain needs a proxied record. This address is never reached —
# RFC 5737 reserves 192.0.2.0/24 for documentation, and the redirect answers
# before any origin lookup.
resource "cloudflare_dns_record" "legacy_apex" {
  zone_id = var.redirect_zone_id
  name    = var.redirect_from
  type    = "A"
  content = "192.0.2.1"
  ttl     = 1
  proxied = true
  comment = "placeholder so the redirect rule can fire"
}

resource "cloudflare_dns_record" "legacy_www" {
  zone_id = var.redirect_zone_id
  name    = "www.${var.redirect_from}"
  type    = "A"
  content = "192.0.2.1"
  ttl     = 1
  proxied = true
  comment = "placeholder so the redirect rule can fire"
}

# Cloudflare routes a Worker by hostname, which needs a proxied DNS record.
# 100:: is Cloudflare's discard prefix — nothing is ever dialled.
resource "cloudflare_dns_record" "waitlist" {
  zone_id = var.zone_id
  name    = "waitlist.${var.domain}"
  type    = "AAAA"
  content = "100::"
  ttl     = 1
  proxied = true
  comment = "route for the waitlist Worker"
}
