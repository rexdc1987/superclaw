"""helpers 单元测试"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from datetime import datetime, timedelta
from utils.helpers import (
    gen_short_id, format_datetime, time_ago, truncate,
    md5, ensure_dir, safe_json_loads, flatten_dict,
    chunk_list, format_number,
)


class TestGenShortId:
    def test_length(self):
        assert len(gen_short_id()) == 8
        assert len(gen_short_id(12)) == 12

    def test_uniqueness(self):
        ids = {gen_short_id() for _ in range(100)}
        assert len(ids) == 100  # all unique


class TestFormatDatetime:
    def test_valid(self):
        dt = datetime(2025, 6, 15, 14, 30, 0)
        assert format_datetime(dt) == "2025-06-15 14:30:00"

    def test_none(self):
        assert format_datetime(None) == ""

    def test_custom_format(self):
        dt = datetime(2025, 6, 15)
        assert format_datetime(dt, "%Y/%m/%d") == "2025/06/15"


class TestTruncate:
    def test_short_text(self):
        assert truncate("abc", 10) == "abc"

    def test_long_text(self):
        assert truncate("abcdefghij", 7) == "abcd..."

    def test_none(self):
        assert truncate(None) == ""

    def test_custom_suffix(self):
        assert truncate("abcdefgh", 5, "~") == "abcd~"


class TestMd5:
    def test_known(self):
        assert md5("test") == "098f6bcd4621d373cade4e832627b4f6"

    def test_empty(self):
        assert md5("") == "d41d8cd98f00b204e9800998ecf8427e"


class TestSafeJsonLoads:
    def test_valid(self):
        assert safe_json_loads('{"a": 1}') == {"a": 1}

    def test_invalid(self):
        assert safe_json_loads("not json") == {}

    def test_custom_default(self):
        assert safe_json_loads("bad", []) == []


class TestFlattenDict:
    def test_nested(self):
        d = {"a": 1, "b": {"c": 2, "d": {"e": 3}}}
        result = flatten_dict(d)
        assert result == {"a": 1, "b.c": 2, "b.d.e": 3}

    def test_flat(self):
        assert flatten_dict({"a": 1}) == {"a": 1}


class TestChunkList:
    def test_even(self):
        assert chunk_list([1, 2, 3, 4], 2) == [[1, 2], [3, 4]]

    def test_odd(self):
        assert chunk_list([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]

    def test_empty(self):
        assert chunk_list([], 3) == []


class TestFormatNumber:
    def test_small(self):
        assert format_number(999) == "999"

    def test_large(self):
        assert format_number(15000) == "1.5万"

    def test_exact_wan(self):
        assert format_number(10000) == "1.0万"
