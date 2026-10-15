# Cloudflare stack

DNS, the legacy-domain redirect, and the waitlist Worker route for Flashpoint DB.

Separate from `../` on purpose: `scripts/teardown.sh` runs `tofu destroy` on the
AWS stack to guarantee zero spend, and DNS must not disappear with it. This
directory has its own state.

## What it manages

| File | Resources |
|---|---|
| `dns.tf` | GitHub Pages A/AAAA records for the apex, a `www` CNAME, proxied placeholders on the legacy domain so the redirect can fire, and the `AAAA 100::` record that routes the waitlist Worker |
| `redirect.tf` | A 301 from `sparksql.dev` to `flashpointdb.com` that preserves path and query |

Not managed:

- The `TXT` record holding the Google Search Console verification token — a one-off
  verification value, not infrastructure.
- The registration itself. Cloudflare's provider used to expose
  `cloudflare_registrar_domain` for auto-renew, privacy and transfer lock; **5.28.0 removed it**
  (5.26.0 still has it, 5.28.0 does not). Auto-renew therefore stays a dashboard setting until
  the provider brings it back or it moves to another resource. The registration runs to
  2028-09-30 and auto-renew is on.
- The waitlist Worker's code and KV namespace. Only the DNS route to it lives here.

## Setup

1. Create an API token (Cloudflare dashboard → My Profile → API Tokens) with:
   - Zone → DNS → Edit
   - Zone → Zone Settings → Read
   - Zone → Config Rules → Edit

   Export it — never write it to a file in this repo:

   ```sh
   export CLOUDFLARE_API_TOKEN=...
   ```

2. `terraform.tfvars` already holds this account's real identifiers and is
   git-ignored. `terraform.tfvars.example` documents every field.

3. Plan and apply. The resources already exist — they were created by hand in
   the dashboard — so `imports.tf` adopts them rather than duplicating them.
   The import blocks are no-ops once the resources are in state.

   ```sh
   tofu init
   tofu plan -var-file=terraform.tfvars    # expect imports, no creates
   tofu apply -var-file=terraform.tfvars
   ```

## Order of operations with GitHub Pages

1. Apply this stack with `proxy_pages_records = false` (DNS only).
2. In the repository: Settings → Pages → Custom domain → `flashpointdb.com`.
   GitHub writes the `CNAME` file and starts issuing a certificate.
3. Once **Enforce HTTPS** is available, tick it.
4. Set `proxy_pages_records = true` and apply again if you want Cloudflare in
   front of Pages. It is off today: GitHub already serves the static site from
   its own CDN, so the proxy adds a hop without adding anything.

## Verify

```sh
curl -sI https://flashpointdb.com | head -1
curl -sI https://sparksql.dev/quickstart.html | grep -i '^location'
```

The second must print `https://flashpointdb.com/quickstart.html`.
