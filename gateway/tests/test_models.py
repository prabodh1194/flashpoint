import pytest
from pydantic import ValidationError
from models import (
    CreateWarehouseRequest,
    QueryRequest,
    ResizeRequest,
    WarehouseResponse,
    QueryResponse,
    QueryProfile,
    DagNode,
    DagEdge,
)


class TestCreateWarehouseRequest:
    def test_default_size_is_xs(self):
        req = CreateWarehouseRequest()
        assert req.size == "XS"

    def test_custom_size(self):
        req = CreateWarehouseRequest(size="L")
        assert req.size == "L"

    def test_invalid_size_does_not_reject(self):
        req = CreateWarehouseRequest(size="XXL")
        assert req.size == "XXL"


class TestQueryRequest:
    def test_valid_sql(self):
        req = QueryRequest(sql="SELECT 1")
        assert req.sql == "SELECT 1"

    def test_empty_sql(self):
        req = QueryRequest(sql="")
        assert req.sql == ""


class TestResizeRequest:
    def test_valid_size(self):
        req = ResizeRequest(size="M")
        assert req.size == "M"


class TestWarehouseResponse:
    def test_minimal_response(self):
        resp = WarehouseResponse(warehouse_id="abc", status="running")
        assert resp.warehouse_id == "abc"
        assert resp.status == "running"
        assert resp.task_arn is None
        assert resp.endpoint is None

    def test_full_response(self):
        resp = WarehouseResponse(
            warehouse_id="xyz", task_arn="arn:xxx", endpoint="sc://10.0.0.1:15002",
            status="running", size="M", executor_count=4, name="my-warehouse",
        )
        assert resp.warehouse_id == "xyz"
        assert resp.task_arn == "arn:xxx"
        assert resp.endpoint == "sc://10.0.0.1:15002"
        assert resp.size == "M"
        assert resp.executor_count == 4
        assert resp.name == "my-warehouse"


class TestQueryProfile:
    def test_empty_profile(self):
        profile = QueryProfile(nodes=[], edges=[])
        assert profile.nodes == []
        assert profile.edges == []

    def test_profile_with_nodes(self):
        node = DagNode(id=1, name="WholeStageCodegen")
        profile = QueryProfile(nodes=[node], edges=[])
        assert len(profile.nodes) == 1
        assert profile.nodes[0].name == "WholeStageCodegen"


class TestDagNode:
    def test_minimal_node(self):
        node = DagNode(id=1, name="Scan")
        assert node.id == 1
        assert node.name == "Scan"
        assert node.duration_ms is None
        assert node.is_shuffle is False
        assert node.has_skew is False
        assert node.has_spill is False

    def test_node_with_metrics(self):
        node = DagNode(id=2, name="Exchange", duration_ms=390, is_shuffle=True)
        assert node.duration_ms == 390
        assert node.is_shuffle is True


class TestDagEdge:
    def test_edge_from_to(self):
        edge = DagEdge(from_=1, to=2)
        assert edge.from_ == 1
        assert edge.to == 2
        assert edge.is_shuffle is False

    def test_edge_from_alias(self):
        edge = DagEdge(**{"from": 3, "to": 4, "is_shuffle": True})
        assert edge.from_ == 3
        assert edge.to == 4
        assert edge.is_shuffle is True


class TestQueryResponse:
    def test_response_without_profile(self):
        resp = QueryResponse(
            query_id="deadbeef", columns=["a"], rows=[[1]],
            duration_ms=100, row_count=1, profile=None,
        )
        assert resp.query_id == "deadbeef"
        assert resp.profile is None

    def test_response_with_profile(self):
        node = DagNode(id=1, name="Scan")
        profile = QueryProfile(nodes=[node], edges=[])
        resp = QueryResponse(
            query_id="abc123", columns=["x", "y"], rows=[["1", "2"]],
            duration_ms=50, row_count=1, profile=profile,
        )
        assert resp.profile is not None
        assert resp.profile.nodes[0].name == "Scan"
