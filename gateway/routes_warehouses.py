"""Warehouse CRUD routes — create, get, list, delete, suspend, resume, resize."""

import logging
import time

from fastapi import APIRouter, HTTPException

import ecs_tasks
import meters
import spark_client
import store
from config import CLUSTER, GRPC_PORT, MAX_WAREHOUSES, SIZES
from models import CreateWarehouseRequest, ResizeRequest, WarehouseResponse

log = logging.getLogger(__name__)
router = APIRouter(prefix='/warehouses', tags=['warehouses'])


@router.post('', response_model=WarehouseResponse, status_code=201)
def create_warehouse(req: CreateWarehouseRequest):
    if req.size not in SIZES:
        raise HTTPException(status_code=400, detail=f'unknown size {req.size!r}')
    if store.get_warehouse(req.name) is not None:
        raise HTTPException(status_code=409, detail=f'warehouse {req.name!r} already exists')
    if store.count_running_warehouses() >= MAX_WAREHOUSES:
        raise HTTPException(status_code=429, detail=f'warehouse cap reached ({MAX_WAREHOUSES} max)')
    name = req.name
    executor_count = SIZES[req.size]
    log.info('Creating warehouse %s (size=%s, executors=%d)', name, req.size, executor_count)

    task_arn, task_ip, endpoint, executor_arns = ecs_tasks.launch_driver_with_executors(
        name, executor_count, GRPC_PORT
    )

    now = time.time()
    record = {
        'task_arn': task_arn,
        'executor_arns': executor_arns,
        'task_ip': task_ip,
        'endpoint': endpoint,
        'status': 'running',
        'size': req.size,
        'executor_count': executor_count,
        'created_at': now,
        # Metering: the session is billable from now; checkpoint now so the
        # first heartbeat tick bills only the delta since start.
        'session_started_at': now,
        'last_metered_at': now,
    }
    store.put_warehouse(name, record)
    return WarehouseResponse(
        name=name,
        task_arn=task_arn,
        endpoint=endpoint,
        status='running',
        size=req.size,
        executor_count=executor_count,
    )


@router.get('/{name}', response_model=WarehouseResponse)
def get_warehouse(name: str):
    s = store.get_warehouse(name)
    if not s:
        raise HTTPException(status_code=404, detail='warehouse not found')
    task_arn = s['task_arn']
    status = 'running' if (task_arn and ecs_tasks.is_running(task_arn)) else s['status']
    return WarehouseResponse(
        name=name,
        task_arn=task_arn or None,
        endpoint=s.get('endpoint'),
        status=status,
        size=s['size'],
        executor_count=s['executor_count'],
    )


@router.get('')
def list_warehouses_endpoint():
    records = store.list_warehouses()
    items = []
    for s in records:
        task_arn = s['task_arn']
        if task_arn and ecs_tasks.is_running(task_arn):
            status = 'running'
        else:
            status = s.get('status', 'suspended')
        items.append(
            {
                'name': s['name'],
                'status': status,
                'size': s['size'],
                'executor_count': s['executor_count'],
            }
        )
    return {'warehouses': items, 'count': len(items)}


@router.delete('/{name}', status_code=204)
def delete_warehouse(name: str):
    s = store.get_warehouse(name)
    if not s:
        raise HTTPException(status_code=404, detail='warehouse not found')

    spark_client.drop(name)
    if s.get('status') != 'suspended':
        meters.accrue_session(s)
    ecs_tasks.stop_tasks(s)
    store.delete_warehouse(name)
    log.info('Deleted warehouse %s (driver + %d executors stopped)', name, len(s['executor_arns']))


@router.post('/{name}/suspend', status_code=200)
def suspend_warehouse(name: str):
    s = store.get_warehouse(name)
    if not s:
        raise HTTPException(status_code=404, detail='warehouse not found')
    if s['status'] == 'suspended':
        return {'status': 'suspended'}

    spark_client.drop(name)
    meters.accrue_session(s)
    ecs_tasks.stop_tasks(s)
    store.update_warehouse_status(name, 'suspended', task_arn=None, executor_arns=[], task_ip=None)
    log.info('Suspended warehouse %s', name)
    return {'status': 'suspended'}


@router.post('/{name}/resume', status_code=200, response_model=WarehouseResponse)
def resume_warehouse(name: str):
    s = store.get_warehouse(name)
    if not s:
        raise HTTPException(status_code=404, detail='warehouse not found')
    if s['status'] == 'running':
        return WarehouseResponse(
            name=name,
            task_arn=s['task_arn'],
            endpoint=s.get('endpoint'),
            status='running',
            size=s['size'],
            executor_count=s['executor_count'],
        )

    size = s['size']
    executor_count = SIZES[size]
    log.info('Resuming warehouse %s (size=%s)', name, size)

    task_arn, task_ip, endpoint, executor_arns = ecs_tasks.launch_driver_with_executors(
        name, executor_count, GRPC_PORT
    )

    now = time.time()
    store.update_warehouse_status(
        name,
        'running',
        task_arn=task_arn,
        executor_arns=executor_arns,
        task_ip=task_ip,
        endpoint=endpoint,
        executor_count=executor_count,
        session_started_at=now,
        last_metered_at=now,
    )
    log.info('Resumed warehouse %s → driver %s', name, task_arn)
    return WarehouseResponse(
        name=name,
        task_arn=task_arn,
        endpoint=endpoint,
        status='running',
        size=size,
        executor_count=executor_count,
    )


@router.post('/{name}/resize', status_code=200, response_model=WarehouseResponse)
def resize_warehouse(name: str, req: ResizeRequest):
    s = store.get_warehouse(name)
    if not s:
        raise HTTPException(status_code=404, detail='warehouse not found')
    if s['status'] != 'running':
        raise HTTPException(status_code=409, detail='warehouse is not running')
    if req.size not in SIZES:
        raise HTTPException(status_code=400, detail=f'unknown size {req.size!r}')

    new_count = SIZES[req.size]
    current_count = s['executor_count']
    executor_arns: list[str] = list(s['executor_arns'])
    master_url = f'spark://{s["task_ip"]}:7077'

    if new_count > current_count:
        delta = new_count - current_count
        new_arns = ecs_tasks.run_executor_tasks(master_url, delta, name)
        executor_arns.extend(new_arns)
        log.info('Scaled warehouse %s up: +%d executors (Spot)', name, delta)
    elif new_count < current_count:
        delta = current_count - new_count
        to_stop = executor_arns[-delta:]
        executor_arns = executor_arns[:-delta]
        for arn in to_stop:
            try:
                ecs_tasks.ecs.stop_task(cluster=CLUSTER, task=arn)
            except Exception as exc:
                log.error('Failed to stop executor %s during resize: %s', arn, exc)
        log.info('Scaled warehouse %s down: -%d executors', name, delta)

    store.update_warehouse_status(
        name,
        'running',
        size=req.size,
        executor_count=new_count,
        executor_arns=executor_arns,
    )
    return WarehouseResponse(
        name=name,
        task_arn=s['task_arn'],
        endpoint=s['endpoint'],
        status='running',
        size=req.size,
        executor_count=new_count,
    )
