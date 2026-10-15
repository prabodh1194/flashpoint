output "product_zone_id" {
  description = "Zone ID for the product domain."
  value       = var.zone_id
}

output "pages_record_ids" {
  description = "DNS record IDs serving the product domain."
  value = merge(
    { for ip, r in cloudflare_dns_record.apex_a : ip => r.id },
    { for ip, r in cloudflare_dns_record.apex_aaaa : ip => r.id },
    { "www" = cloudflare_dns_record.www.id },
  )
}

output "redirect_ruleset_id" {
  description = "Ruleset carrying the legacy-domain redirect."
  value       = cloudflare_ruleset.legacy_redirect.id
}

output "redirect_target_expression" {
  description = "What the legacy domain rewrites to."
  value       = "https://${var.domain}$${http.request.uri.path}"
}
