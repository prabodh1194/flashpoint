from routes_queries import _query_id


def test_query_id_is_16_chars():
    qid = _query_id('SELECT 1')
    assert len(qid) == 16
    assert all(c in '0123456789abcdef' for c in qid)


def test_query_id_deterministic():
    a = _query_id('SELECT * FROM users WHERE id = 1')
    b = _query_id('SELECT * FROM users WHERE id = 1')
    assert a == b


def test_query_id_case_insensitive():
    a = _query_id('SELECT 1')
    b = _query_id('select 1')
    assert a == b


def test_query_id_whitespace_normalized():
    a = _query_id('SELECT  1')
    b = _query_id('SELECT 1')
    assert a == b


def test_query_id_multiline_normalized():
    a = _query_id('SELECT\n*\nFROM users')
    b = _query_id('SELECT * FROM users')
    assert a == b


def test_query_id_different_sql_produces_different_id():
    a = _query_id('SELECT 1')
    b = _query_id('SELECT 2')
    assert a != b


def test_query_id_trailing_whitespace_ignored():
    a = _query_id('SELECT 1  ')
    b = _query_id('SELECT 1')
    assert a == b
