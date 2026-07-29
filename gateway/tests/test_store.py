from decimal import Decimal

from store import _from_ddb, _to_ddb


class TestToDdb:
    def test_float_converts_to_decimal(self):
        result = _to_ddb(3.14)
        assert isinstance(result, Decimal)
        assert float(result) == 3.14

    def test_int_passes_through(self):
        assert _to_ddb(42) == 42

    def test_string_passes_through(self):
        assert _to_ddb('hello') == 'hello'

    def test_none_passes_through(self):
        assert _to_ddb(None) is None

    def test_list_nested_floats(self):
        result = _to_ddb([1.5, 2.5, 3])
        assert isinstance(result[0], Decimal)
        assert isinstance(result[1], Decimal)
        assert result[2] == 3

    def test_dict_nested_floats(self):
        result = _to_ddb({'a': 1.0, 'b': 'str', 'c': 2})
        assert isinstance(result['a'], Decimal)
        assert result['b'] == 'str'
        assert result['c'] == 2

    def test_empty_list(self):
        assert _to_ddb([]) == []

    def test_empty_dict(self):
        assert _to_ddb({}) == {}


class TestFromDdb:
    def test_decimal_to_float(self):
        result = _from_ddb(Decimal('3.14'))
        assert isinstance(result, float)
        assert result == 3.14

    def test_decimal_integer_to_int(self):
        result = _from_ddb(Decimal(42))
        assert isinstance(result, int)
        assert result == 42

    def test_decimal_with_trailing_zeros_to_int(self):
        result = _from_ddb(Decimal('100.0'))
        assert isinstance(result, int)
        assert result == 100

    def test_string_passes_through(self):
        assert _from_ddb('hello') == 'hello'

    def test_none_passes_through(self):
        assert _from_ddb(None) is None

    def test_int_passes_through(self):
        assert _from_ddb(42) == 42

    def test_list_nested_decimals(self):
        result = _from_ddb([Decimal('1.5'), Decimal('2.0')])
        assert result == [1.5, 2]

    def test_dict_nested_decimals(self):
        result = _from_ddb({'a': Decimal('3.0'), 'b': Decimal('1.25')})
        assert result == {'a': 3, 'b': 1.25}

    def test_empty_list(self):
        assert _from_ddb([]) == []

    def test_empty_dict(self):
        assert _from_ddb({}) == {}


class TestRoundTrip:
    def test_float_round_trip(self):
        original = {'created_at': 1234567890.123}
        assert _from_ddb(_to_ddb(original)) == original

    def test_complex_nested(self):
        original = {
            'name': 'abc-123',
            'task_ip': '10.0.0.5',
            'created_at': 1717200000.0,
            'executor_arns': ['arn:1', 'arn:2'],
            'count': 3,
            'cost_usd': 0.042,
            'tags': {'env': 'dev', 'version': 1},
        }
        result = _from_ddb(_to_ddb(original))
        assert result == original


# ── DynamoDB operations (mocked table) ──────────────────────────

from unittest.mock import MagicMock

import store
from store import (
    delete_warehouse,
    get_warehouse,
    list_warehouses,
    put_warehouse,
    update_warehouse_status,
)


class TestPutSession:
    def test_writes_item_to_table(self, monkeypatch):
        mock_table = MagicMock()
        monkeypatch.setattr(store, '_table', lambda: mock_table)
        put_warehouse('s1', {'task_arn': 'arn:test', 'status': 'running'})
        mock_table.put_item.assert_called_once()
        item = mock_table.put_item.call_args.kwargs['Item']
        assert item['name'] == 's1'
        assert item['task_arn'] == 'arn:test'
        assert item['status'] == 'running'
        assert 'updated_at' in item


class TestUpdateSessionStatus:
    def test_updates_status_with_extras(self, monkeypatch):
        mock_table = MagicMock()
        monkeypatch.setattr(store, '_table', lambda: mock_table)
        update_warehouse_status('s1', 'suspended', task_arn=None, executor_arns=[], task_ip=None)
        mock_table.update_item.assert_called_once()
        kwargs = mock_table.update_item.call_args.kwargs
        assert kwargs['Key'] == {'name': 's1'}
        assert ':status' in kwargs['ExpressionAttributeValues']


class TestDeleteSession:
    def test_deletes_item(self, monkeypatch):
        mock_table = MagicMock()
        monkeypatch.setattr(store, '_table', lambda: mock_table)
        delete_warehouse('s1')
        mock_table.delete_item.assert_called_once_with(Key={'name': 's1'})


class TestGetSession:
    def test_returns_session_when_found(self, monkeypatch):
        from decimal import Decimal

        mock_table = MagicMock()
        mock_table.get_item.return_value = {
            'Item': {
                'name': 's1',
                'task_arn': 'arn:test',
                'status': 'running',
                'created_at': Decimal(1717200000),
            }
        }
        monkeypatch.setattr(store, '_table', lambda: mock_table)
        result = get_warehouse('s1')
        assert result is not None
        assert result['name'] == 's1'
        assert result['task_arn'] == 'arn:test'
        assert result['created_at'] == 1717200000

    def test_returns_none_when_not_found(self, monkeypatch):
        mock_table = MagicMock()
        mock_table.get_item.return_value = {}
        monkeypatch.setattr(store, '_table', lambda: mock_table)
        result = get_warehouse('s1')
        assert result is None


class TestListSessions:
    def test_returns_all_sessions(self, monkeypatch):
        mock_table = MagicMock()
        mock_table.scan.return_value = {
            'Items': [
                {'name': 's1', 'status': 'running'},
                {'name': 's2', 'status': 'suspended'},
            ]
        }
        monkeypatch.setattr(store, '_table', lambda: mock_table)
        result = list_warehouses()
        assert len(result) == 2
        assert result[0]['name'] == 's1'

    def test_returns_empty_list(self, monkeypatch):
        mock_table = MagicMock()
        mock_table.scan.return_value = {}
        monkeypatch.setattr(store, '_table', lambda: mock_table)
        result = list_warehouses()
        assert result == []
