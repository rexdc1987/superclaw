"""validators 单元测试"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from utils.validators import (
    validate_username, validate_platform, validate_task_name,
    validate_content, validate_keyword, validate_url,
    validate_positive_int, sanitize_text,
)


class TestValidateUsername:
    def test_valid(self):
        assert validate_username("test_user") == (True, "")
        assert validate_username("用户123") == (True, "")
        assert validate_username("ab") == (True, "")

    def test_empty(self):
        ok, msg = validate_username("")
        assert not ok
        assert "不能为空" in msg

    def test_too_short(self):
        ok, msg = validate_username("a")
        assert not ok
        assert "2-50" in msg

    def test_too_long(self):
        ok, msg = validate_username("a" * 51)
        assert not ok
        assert "2-50" in msg

    def test_special_chars(self):
        ok, msg = validate_username("user@name")
        assert not ok
        assert "只允许" in msg

    def test_whitespace_stripped(self):
        assert validate_username("  test  ") == (True, "")


class TestValidatePlatform:
    def test_valid_platforms(self):
        for p in ["douyin", "xiaohongshu", "kuaishou", "bilibili"]:
            assert validate_platform(p) == (True, "")

    def test_invalid(self):
        ok, msg = validate_platform("tiktok")
        assert not ok
        assert "不支持" in msg


class TestValidateContent:
    def test_valid(self):
        assert validate_content("hello world") == (True, "")

    def test_empty(self):
        assert validate_content("")[0] is False
        assert validate_content(None)[0] is False

    def test_too_long(self):
        ok, msg = validate_content("a" * 501)
        assert not ok
        assert "500" in msg

    def test_custom_max(self):
        ok, msg = validate_content("abcde", max_length=3)
        assert not ok


class TestValidateKeyword:
    def test_valid(self):
        assert validate_keyword("测试") == (True, "")

    def test_empty(self):
        assert validate_keyword("")[0] is False

    def test_too_long(self):
        assert validate_keyword("a" * 51)[0] is False


class TestValidateUrl:
    def test_valid(self):
        assert validate_url("https://example.com") == (True, "")
        assert validate_url("http://test.cn/path?q=1") == (True, "")

    def test_invalid(self):
        assert validate_url("not_a_url")[0] is False
        assert validate_url("")[0] is False


class TestValidatePositiveInt:
    def test_valid(self):
        assert validate_positive_int(1) == (True, "")
        assert validate_positive_int("10") == (True, "")

    def test_invalid(self):
        assert validate_positive_int(0)[0] is False
        assert validate_positive_int(-1)[0] is False
        assert validate_positive_int("abc")[0] is False


class TestSanitizeText:
    def test_basic(self):
        assert sanitize_text("  hello   world  ") == "hello world"

    def test_empty(self):
        assert sanitize_text("") == ""
        assert sanitize_text(None) == ""
