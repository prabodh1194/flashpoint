#!/usr/bin/env python3
"""Flashpoint local e2e demo.

Recreates the blog-post scenario entirely on a laptop: local Spark Connect
server + seeded demo data (1M customers, 10M orders) + gateway, then runs the
join/group-by query and prints its query profile summary.

Usage:
    python scripts/e2e_demo.py            # full run (boots everything)
    python scripts/e2e_demo.py --keep     # leave processes running
    python scripts/e2e_demo.py --reseed   # regenerate demo data
    python scripts/e2e_demo.py --skip-seed

The same steps run in order are documented at docs/quickstart.html.
"""

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GATEWAY = os.path.join(ROOT, 'gateway')
VENV_PY = os.path.join(GATEWAY, '.venv', 'bin', 'python')
LOG_DIR = '/tmp/flashpoint-demo'
DATA_DIR = os.environ.get('FLASHPOINT_DATA_DIR', '/tmp/spark-data')

GRPC_PORT = 15002
SPARK_UI_PORT = 4040
GATEWAY_PORT = 8080

QUERY = """SELECT c.region, count(*) AS cnt
FROM orders o JOIN customers c ON o.customer_id = c.customer_id
GROUP BY c.region
ORDER BY cnt DESC"""

CUSTOMERS_N = 1_000_000
ORDERS_N = 10_000_000

YELLOW = '\033[93m'
GREEN = '\033[92m'
RED = '\033[91m'
DIM = '\033[90m'
BOLD = '\033[1m'
RESET = '\033[0m'

children: list[subprocess.Popen] = []


def say(step: str, msg: str) -> None:
    print(f'\n{YELLOW}{BOLD}── {step}{RESET} {DIM}{msg}{RESET}')


def die(msg: str) -> None:
    print(f'{RED}error: {msg}{RESET}')
    sys.exit(1)


def warn(msg: str) -> None:
    print(f'{YELLOW}warning: {msg}{RESET}')


def ok(msg: str) -> None:
    print(f'{GREEN}ok: {msg}{RESET}')


def wait_port(port: int, timeout: int, host: str = '127.0.0.1') -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return
        except OSError:
            time.sleep(1)
    die(f'{host}:{port} did not come up within {timeout}s')


def http_json(method: str, url: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            return json.loads(resp.read() or b'{}')
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()[:500]
        die(f'HTTP {exc.code} from {url}: {detail}')
    except urllib.error.URLError as exc:
        die(f'could not reach {url}: {exc.reason}')
    return {}


def _pick_java_home() -> str | None:
    """Spark 4.2 needs JDK 17/21 — newer JDKs fail with ClassNotFoundError
    on jdk.internal.ref.Cleaner. Prefer an explicit Homebrew JDK."""
    for candidate in ('/opt/homebrew/opt/openjdk@17',
                      '/opt/homebrew/opt/openjdk@21',
                      '/opt/homebrew/opt/openjdk'):
        if os.path.exists(os.path.join(candidate, 'bin', 'java')):
            return candidate
    return None


def ensure_venv() -> None:
    if os.path.exists(VENV_PY):
        ok(f'venv present at {VENV_PY}')
        return
    say('prerequisites', 'creating gateway venv via uv')
    if subprocess.run(['uv', 'sync', '--directory', GATEWAY],
                      check=False).returncode != 0:
        die('`uv sync --directory gateway` failed (see quickstart step 2)')


def boot_spark_connect() -> None:
    say('step 1/5', 'booting local Spark Connect server')
    try:
        sock = socket.create_connection(('127.0.0.1', GRPC_PORT), timeout=2)
        sock.close()
        warn(f'port {GRPC_PORT} already in use — reusing the running server. '
             f'Kill it first for a fully fresh run.')
        return
    except OSError:
        pass

    spark_home = subprocess.check_output(
        [VENV_PY, '-c',
         'import pyspark, os; print(os.path.dirname(pyspark.__file__))'],
        text=True).strip()
    java_home = _pick_java_home()
    log = open(os.path.join(LOG_DIR, 'spark-connect.log'), 'ab')
    cmd = [os.path.join(spark_home, 'bin', 'spark-class'),
           'org.apache.spark.deploy.SparkSubmit',
           '--master', 'local[*]',
           '--conf', f'spark.ui.port={SPARK_UI_PORT}',
           '--class', 'org.apache.spark.sql.connect.service.SparkConnectServer',
           'spark-internal']
    env = dict(os.environ)
    if java_home:
        env['JAVA_HOME'] = java_home
        env['PATH'] = f'{java_home}/bin:' + env.get('PATH', '')
    proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT,
                            start_new_session=True, env=env)
    children.append(proc)
    wait_port(GRPC_PORT, 180)
    ok(f'Spark Connect listening on :{GRPC_PORT} (log: {LOG_DIR}/spark-connect.log)')


def seed_data(reseed: bool, skip_seed: bool) -> None:
    customers_dir = os.path.join(DATA_DIR, 'customers')
    orders_dir = os.path.join(DATA_DIR, 'orders')
    if not skip_seed and not reseed and os.path.exists(customers_dir) \
            and os.path.exists(orders_dir):
        ok(f'demo data already present at {DATA_DIR} (pass --reseed to regenerate)')
    elif skip_seed:
        die(f'--skip-seed but no data at {DATA_DIR}')
    else:
        say('step 2/5', f'seeding {CUSTOMERS_N:,} customers × {ORDERS_N:,} orders → {DATA_DIR}')
        script = f'''
from pyspark.sql import SparkSession
s = SparkSession.builder.remote('sc://127.0.0.1:{GRPC_PORT}').getOrCreate()
s.range({CUSTOMERS_N}).selectExpr(
    'CAST(id AS INT) AS customer_id',
    "CONCAT('user_', id) AS name",
    "CASE WHEN id % 5 = 0 THEN 'north' WHEN id % 5 = 1 THEN 'south' "
    "WHEN id % 5 = 2 THEN 'east' WHEN id % 5 = 3 THEN 'west' ELSE 'central' END AS region",
    'CAST(id % 3 AS INT) AS tier',
).write.mode('overwrite').parquet('{DATA_DIR}/customers')
s.range({ORDERS_N}).selectExpr(
    'id',
    'CAST(id % {CUSTOMERS_N} AS INT) AS customer_id',
    'CAST(id % 5000 AS INT) AS product_id',
    'CAST(id AS DECIMAL(10,2)) AS amount',
    "CAST(date_add(CAST('2024-01-01' AS DATE), CAST(id % 365 AS INT)) AS STRING) AS order_date",
).write.mode('overwrite').parquet('{DATA_DIR}/orders')
print('seeded')
'''
        r = subprocess.run([VENV_PY, '-c', script], capture_output=True, text=True,
                           timeout=900)
        if 'seeded' not in r.stdout:
            die(f'seeding failed:\n{r.stderr[-2000:]}')
        ok(f'{CUSTOMERS_N:,} customers + {ORDERS_N:,} orders written as parquet')


def boot_gateway() -> None:
    say('step 3/5', 'booting gateway (local mode, AWS mocked)')
    try:
        urllib.request.urlopen(f'http://127.0.0.1:{GATEWAY_PORT}/healthz', timeout=2)
        warn(f'gateway already running on :{GATEWAY_PORT} — reusing it')
        return
    except (urllib.error.URLError, OSError):
        pass
    log = open(os.path.join(LOG_DIR, 'gateway.log'), 'ab')
    proc = subprocess.Popen([VENV_PY, 'local_dev.py'], cwd=GATEWAY,
                            stdout=log, stderr=subprocess.STDOUT,
                            start_new_session=True)
    children.append(proc)
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f'http://127.0.0.1:{GATEWAY_PORT}/healthz', timeout=1)
            break
        except (urllib.error.URLError, OSError):
            time.sleep(1)
    else:
        die(f'gateway did not come up on :{GATEWAY_PORT} '
            f'(log: {LOG_DIR}/gateway.log)')
    ok(f'gateway healthy on http://localhost:{GATEWAY_PORT}')


def run_query() -> None:
    say('step 4/5', 'creating warehouse "demo" (size S)')
    base = f'http://127.0.0.1:{GATEWAY_PORT}'
    try:
        http_json('DELETE', f'{base}/warehouses/demo')
        ok('removed stale "demo" warehouse from a previous run')
    except SystemExit:
        pass
    http_json('POST', f'{base}/warehouses', {'name': 'demo', 'size': 'S'})
    ok('warehouse demo running (mapped to the local Spark Connect server)')

    say('step 4b/5', 'registering parquet data as views (through the gateway session)')
    for view in ('customers', 'orders'):
        http_json('POST', f'{base}/warehouses/demo/query',
                  {'sql': f"CREATE OR REPLACE TEMPORARY VIEW {view} USING parquet "
                          f"OPTIONS (path '{DATA_DIR}/{view}')"})
    ok('temporary views customers + orders live in the gateway\'s session')

    say('step 5/5', 'running the join/group-by query')
    t0 = time.time()
    resp = http_json('POST',
                     f'{base}/warehouses/demo/query',
                     {'sql': QUERY})
    api_ms = int((time.time() - t0) * 1000)

    profile = resp.get('profile') or {}
    nodes = profile.get('nodes', [])
    treated = sum(1 for n in nodes if n.get('treatments'))
    print(f'\n{BOLD}query id:{RESET}   {resp["query_id"]}')
    print(f'{BOLD}columns:{RESET}    {resp["columns"]}')
    print(f'{BOLD}rows:{RESET}       {resp["row_count"]} — {resp["rows"][:3]}')
    print(f'{BOLD}duration:{RESET}   {resp["duration_ms"]} ms (api round-trip {api_ms} ms)')
    print(f'{BOLD}profile:{RESET}    {len(nodes)} nodes, {treated} with column treatments')
    root = next((n['name'] for n in nodes if n['name'].startswith('AdaptiveSparkPlan')), '—')
    print(f'{DIM}          plan tree root: {root}{RESET}')

    if len(nodes) < 5 or not treated:
        warn('profile looks thin — check Spark UI logs; the tree grows once '
             'the data is read')
    return resp['query_id']


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--keep', action='store_true',
                        help='leave Spark Connect + gateway running on exit')
    parser.add_argument('--reseed', action='store_true',
                        help='regenerate demo data even if present')
    parser.add_argument('--skip-seed', action='store_true',
                        help='skip data seeding (must already exist)')
    args = parser.parse_args()

    if not os.path.isdir(LOG_DIR):
        os.makedirs(LOG_DIR)

    def cleanup(_sig=None, _frm=None) -> None:
        for p in children:
            try:
                os.killpg(os.getpgid(p.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
        if not args.keep:
            print(f'\n{DIM}stopped demo processes (--keep to leave them running){RESET}')

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    print(f'{BOLD}Flashpoint local e2e demo{RESET} {DIM}(docs/quickstart.html){RESET}')
    ensure_venv()
    boot_spark_connect()
    seed_data(args.reseed, args.skip_seed)
    boot_gateway()
    qid = run_query()

    print(f'\n{GREEN}{BOLD}done.{RESET}')
    print(f'{DIM}  Spark UI : http://localhost:{SPARK_UI_PORT}{RESET}')
    print(f'{DIM}  Gateway  : http://localhost:{GATEWAY_PORT}/docs{RESET}')
    print(f'{DIM}  Web UI   : cd web && npm run dev → http://localhost:5173'
          f'{RESET}')
    print(f'{DIM}  Profile  : #/history/{qid} (after the query above, in the UI){RESET}')

    if not args.keep:
        print(f'\n{DIM}press Ctrl-C to stop the demo servers{RESET}')
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            cleanup()


if __name__ == '__main__':
    main()
