"""Pydantic API models for the Flashpoint gateway."""

from pydantic import BaseModel, Field, field_validator


class CreateWarehouseRequest(BaseModel):
    name: str
    size: str = 'XS'

    @field_validator('name')
    @classmethod
    def name_must_not_be_blank(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError('warehouse name must not be blank')
        return trimmed


class WarehouseResponse(BaseModel):
    name: str
    task_arn: str | None = None
    endpoint: str | None = None
    status: str
    size: str = 'XS'
    executor_count: int = 1


class QueryRequest(BaseModel):
    sql: str


class ResizeRequest(BaseModel):
    size: str


class DagNode(BaseModel):
    id: int
    name: str
    duration_ms: int | None = None
    summary_metric: str | None = None
    metrics: dict[str, str] = {}
    is_shuffle: bool = False
    has_skew: bool = False
    has_spill: bool = False


class DagEdge(BaseModel):
    from_: int = Field(alias='from')
    to: int
    is_shuffle: bool = False

    model_config = {'populate_by_name': True}


class QueryProfile(BaseModel):
    nodes: list[DagNode]
    edges: list[DagEdge]


class QueryResponse(BaseModel):
    query_id: str
    columns: list[str]
    rows: list[list]
    duration_ms: int
    row_count: int
    profile: QueryProfile | None = None
