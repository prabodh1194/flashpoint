"""Flashpoint gateway — EC2 control plane.

State lives in DynamoDB. The gateway is stateless — restart it and it
picks up where it left off. Executors run on Fargate Spot; the driver
runs on-demand so Spot reclamation never kills the whole warehouse.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import reconcile as _reconcile_mod
import routes_queries
import routes_warehouses
import spark_client
import store
from config import CLUSTER, WAREHOUSE_TTL_S

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info('Flashpoint gateway starting (cluster=%s, ttl=%ds)', CLUSTER, WAREHOUSE_TTL_S)
    _reconcile_mod.reconcile(CLUSTER)
    reaper = asyncio.create_task(
        _reconcile_mod.reap_idle_warehouses(spark_client, WAREHOUSE_TTL_S, CLUSTER)
    )
    yield
    reaper.cancel()
    log.info('Flashpoint gateway shutting down')


app = FastAPI(title='Flashpoint Gateway', lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=['*'],
    allow_headers=['*'],
)

app.include_router(routes_warehouses.router)
app.include_router(routes_queries.router)
app.include_router(routes_queries.history_router)


@app.get('/healthz')
def health():
    return {
        'status': 'ok',
        'warehouses': store.count_running_warehouses(),
        'sessions_table': store._TABLE_NAME,
    }


if __name__ == '__main__':
    uvicorn.run('main:app', host='0.0.0.0', port=8080, log_level='info')
