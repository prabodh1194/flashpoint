# 301 the legacy domain to the product domain, path and query intact.
#
# Single Redirects are available on every Cloudflare plan; Free allows 10
# rules. The target is built with concat() rather than a fixed URL so
# sparksql.dev/quickstart.html lands on flashpointdb.com/quickstart.html
# instead of dumping every visitor on the homepage.

resource "cloudflare_ruleset" "legacy_redirect" {
  zone_id = var.redirect_zone_id
  name    = "redirect ${var.redirect_from} to ${var.domain}"
  kind    = "zone"
  phase   = "http_request_dynamic_redirect"

  rules = [{
    ref         = "legacy_to_product"
    description = "301 ${var.redirect_from} to ${var.domain}, path preserved"
    enabled     = true
    action      = "redirect"
    expression  = "(http.host eq \"${var.redirect_from}\" or http.host eq \"www.${var.redirect_from}\")"

    action_parameters = {
      from_value = {
        status_code           = 301
        preserve_query_string = true

        target_url = {
          expression = "concat(\"https://${var.domain}\", http.request.uri.path)"
        }
      }
    }
  }]
}
