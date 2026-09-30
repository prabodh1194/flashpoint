# Scripts

| Script | Role |
|---|---|
| `e2e_demo.py` | full local demo: venv → local Spark Connect (`:15002`) → seed 1M customers × 10M orders to `/tmp/spark-data` → gateway via `local_dev.py` (`:8080`) → create warehouse → register views → join/group-by → print profile summary |
| `teardown.sh` | stop Fargate tasks → `tofu destroy` → verify zero remaining resources |

## e2e_demo.py

    python3 scripts/e2e_demo.py            # boot, run, stop on Ctrl-C
    python3 scripts/e2e_demo.py --keep     # leave Spark + gateway running
    python3 scripts/e2e_demo.py --reseed   # regenerate demo data
    python3 scripts/e2e_demo.py --skip-seed

Logs: `/tmp/flashpoint-demo/{spark-connect,gateway}.log`. Spark 4 needs JDK 17 or 21 —
the script prefers a Homebrew JDK when present. After a run: Spark UI on `:4040`, gateway
docs on `:8080/docs`, profile in the web UI at `#/history/<query_id>`.

## teardown.sh

    scripts/teardown.sh [tfvars-file]   # default: dev.tfvars

Uses `AWS_PROFILE=personal-aws-iam` unless overridden. Exits non-zero if any Flashpoint
resource survives the destroy.
