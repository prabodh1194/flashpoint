# These resources were created by hand in the dashboard before this stack
# existed. The import blocks below adopt them on the first apply instead of
# trying to create duplicates. Once adopted they are no-ops, so they stay.
#
# IDs are `<zone_id>/<record_id>` for DNS and `zones/<zone_id>/<ruleset_id>`
# for the redirect, per the provider's import docs.

import {
  to = cloudflare_dns_record.apex_a["185.199.108.153"]
  id = "6c6b00bab580c968a85069ca92f08b75/9e1ac8585cc60917c03c96d37394b26d"
}

import {
  to = cloudflare_dns_record.apex_a["185.199.109.153"]
  id = "6c6b00bab580c968a85069ca92f08b75/e1f357a213ffe7b0b9383fb23681182a"
}

import {
  to = cloudflare_dns_record.apex_a["185.199.110.153"]
  id = "6c6b00bab580c968a85069ca92f08b75/7d38822d8b16a4e636ff465a1cfa3fc8"
}

import {
  to = cloudflare_dns_record.apex_a["185.199.111.153"]
  id = "6c6b00bab580c968a85069ca92f08b75/66c57131e4327121e586dde3da6e7d8b"
}

import {
  to = cloudflare_dns_record.apex_aaaa["2606:50c0:8000::153"]
  id = "6c6b00bab580c968a85069ca92f08b75/e0ed869c8f4523388389b9bcfefc6c74"
}

import {
  to = cloudflare_dns_record.apex_aaaa["2606:50c0:8001::153"]
  id = "6c6b00bab580c968a85069ca92f08b75/556ddeb58a50ccd073c85a74963ae71c"
}

import {
  to = cloudflare_dns_record.apex_aaaa["2606:50c0:8002::153"]
  id = "6c6b00bab580c968a85069ca92f08b75/6268bd7b6992e7e3ef834bcb04a78810"
}

import {
  to = cloudflare_dns_record.apex_aaaa["2606:50c0:8003::153"]
  id = "6c6b00bab580c968a85069ca92f08b75/8ee142d407ca9d3a7176986d6df2abb6"
}

import {
  to = cloudflare_dns_record.www
  id = "6c6b00bab580c968a85069ca92f08b75/2f7103812483a0d4fc2246d3db66d1ae"
}

import {
  to = cloudflare_dns_record.waitlist
  id = "6c6b00bab580c968a85069ca92f08b75/98faa5d574281ce88d95f02c722f362c"
}

import {
  to = cloudflare_dns_record.legacy_apex
  id = "9ab44ffc20da5842d431c3be2a515952/9b00cf278e0a43f68e63649e5a3ad477"
}

import {
  to = cloudflare_dns_record.legacy_www
  id = "9ab44ffc20da5842d431c3be2a515952/0a4b9f41456e960af839c5d65e3b05b2"
}

import {
  to = cloudflare_ruleset.legacy_redirect
  id = "zones/9ab44ffc20da5842d431c3be2a515952/1ce98497d70c404cb95de8592e28c0a3"
}
