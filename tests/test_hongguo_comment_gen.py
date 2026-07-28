"""Focused tests for Hongguo AI comment response handling."""

import json
from unittest.mock import patch

from rpa.hongguo.comment_gen import CommentGenerator


class _Response:
    def __init__(self, data):
        self._data = data

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps(self._data, ensure_ascii=False).encode("utf-8")


def test_extract_content_does_not_publish_reasoning_content():
    generator = CommentGenerator({})
    data = {
        "choices": [
            {
                "message": {
                    "content": "",
                    "reasoning_content": "用户要求我生成一条评论。",
                }
            }
        ]
    }

    assert generator._extract_content(data) == ""


def test_mimo_requests_disable_thinking():
    generator = CommentGenerator(
        {
            "enabled": True,
            "api_key": "test-key",
            "base_url": "https://example.test/v1",
            "model": "mimo-v2.5",
            "provider": "openai_compatible",
            "max_tokens": 80,
        }
    )
    response = {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"content": "这部短剧节奏紧凑，越看越上头！"},
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 12, "total_tokens": 22},
    }
    captured = {}

    def fake_urlopen(req, timeout):
        captured["payload"] = json.loads(req.data.decode("utf-8"))
        return _Response(response)

    with patch("rpa.hongguo.comment_gen.request.urlopen", side_effect=fake_urlopen):
        comment, _ = generator._generate_remote_comment("测试短剧")

    assert comment == "这部短剧节奏紧凑，越看越上头！"
    assert captured["payload"]["thinking"] == {"type": "disabled"}


def test_non_mimo_requests_do_not_send_thinking_parameter():
    generator = CommentGenerator(
        {
            "enabled": True,
            "api_key": "test-key",
            "base_url": "https://example.test/v1",
            "model": "gpt-4o-mini",
            "provider": "openai_compatible",
        }
    )
    response = {
        "choices": [{"message": {"content": "剧情很精彩，期待后面的发展！"}}],
        "usage": {},
    }
    captured = {}

    def fake_urlopen(req, timeout):
        captured["payload"] = json.loads(req.data.decode("utf-8"))
        return _Response(response)

    with patch("rpa.hongguo.comment_gen.request.urlopen", side_effect=fake_urlopen):
        generator._generate_remote_comment("测试短剧")

    assert "thinking" not in captured["payload"]
