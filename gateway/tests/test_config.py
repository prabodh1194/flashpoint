import pytest
from config import SIZES


def test_sizes_default_to_xs():
    assert SIZES["XS"] == 1
    assert SIZES["S"] == 2
    assert SIZES["M"] == 4
    assert SIZES["L"] == 8
    assert SIZES["XL"] == 16


def test_sizes_all_valid():
    assert len(SIZES) == 5
    assert all(isinstance(v, int) and v > 0 for v in SIZES.values())


@pytest.mark.parametrize("size,expected", [
    ("XS", 1),
    ("S", 2),
    ("M", 4),
    ("L", 8),
    ("XL", 16),
])
def test_sizes_mapping(size, expected):
    assert SIZES[size] == expected


def test_unknown_size_raises():
    error = None
    try:
        _ = SIZES["XXL"]
    except KeyError:
        error = True
    assert error
