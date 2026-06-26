"""AI-backed comment generation for Hongguo drama tasks."""

from __future__ import annotations

import json
import random
import re
from typing import Any, Dict, Iterable, List, Tuple
from urllib import request
from urllib.error import HTTPError, URLError


class CommentGenerationError(RuntimeError):
    """Raised when AI comment generation fails and fallback is disabled."""


class CommentGenerator:
    """Generate short, natural Chinese comments from an AI API with local fallback."""

    DEFAULT_COMMENT_SCOPE = "根据当前标题生成一个AI内容"

    GENRE_COMMENTS = {
        "重生": [
            "重生回来这次不会再犯同样的错了",
            "重生开挂就是爽，这剧情看着过瘾",
            "这种重生逆袭的剧情太上头了",
            "上辈子太惨了，这辈子必须翻盘",
        ],
        "穿越": [
            "穿越过去改变命运，这设定绝了",
            "穿越剧永远看不腻",
            "现代人穿越回去降维打击太爽了",
        ],
        "逆袭": [
            "从最弱到最强，这逆袭我给满分",
            "逆袭打脸的剧情百看不厌",
            "就喜欢看这种逆袭的剧情",
        ],
        "复仇": [
            "复仇的火一旦点燃就停不下来了",
            "这次一定要让那些人付出代价",
            "看着复仇成功真的好爽",
        ],
        "甜宠": [
            "这也太甜了吧，磕到了磕到了",
            "好甜好甜，姨母笑根本停不下来",
            "这对CP我锁死了",
        ],
        "修仙": [
            "修仙之路虽然漫长但精彩",
            "这个修仙设定很有意思",
            "一步一步修炼变强的过程太爽了",
        ],
    }

    GENERIC_COMMENTS = [
        "这剧真的好看，一口气看了好几集停不下来",
        "剧情很紧凑不拖沓，好评！",
        "演员演技在线，剧情也很吸引人",
        "这剧情也太上头了吧，根本停不下来",
        "不错不错，继续追下去",
        "这编剧可以啊，剧情很精彩",
        "熬夜也要看完的剧",
        "推荐推荐，越看越好看",
        "这剧比想象中好看多了",
        "追了追了，期待后面的剧情",
        "剧情反转太精彩了，意想不到",
    ]

    def __init__(self, ai_config: Dict[str, Any] | None = None):
        self.ai_config = dict(ai_config or {})
        self.last_usage: Dict[str, Any] = {}

    def generate_ai_comment(self, title: str) -> str:
        comment, _ = self.generate_ai_comment_with_usage(title)
        return comment

    def generate_ai_comment_with_usage(self, title: str) -> Tuple[str, Dict[str, Any]]:
        self.last_usage = {}
        if self._ai_enabled():
            try:
                comment, usage = self._generate_remote_comment(title)
                self.last_usage = usage
                return comment, usage
            except Exception as exc:
                if not self.ai_config.get("fallback_to_local", True):
                    raise CommentGenerationError(str(exc)) from exc
                self.last_usage = {}
        return self._generate_local_comment(title), {}

    def pick_template(self, templates: Iterable[str]) -> str:
        cleaned = [str(t).strip() for t in templates if str(t).strip()]
        if not cleaned:
            return self._generate_local_comment("")
        return random.choice(cleaned)

    def generate(
        self,
        title: str,
        content_source: str,
        templates: Iterable[str] | None = None,
    ) -> Tuple[str, str]:
        content, source, _ = self.generate_with_usage(title, content_source, templates)
        return content, source

    def generate_with_usage(
        self,
        title: str,
        content_source: str,
        templates: Iterable[str] | None = None,
    ) -> Tuple[str, str, Dict[str, Any]]:
        self.last_usage = {}
        source = content_source if content_source in {"ai", "template", "mixed"} else "ai"
        if source == "mixed":
            source = random.choice(["ai", "template"])
        if source == "template":
            return self.pick_template(templates or []), "template", {}
        comment, usage = self.generate_ai_comment_with_usage(title)
        return comment, "ai", usage

    def _ai_enabled(self) -> bool:
        return bool(self.ai_config.get("enabled", False) and self.ai_config.get("api_key"))

    def _comment_scope(self, title: str) -> str:
        scope = str(self.ai_config.get("comment_scope") or "").strip()
        if scope:
            return scope
        return f"{self.DEFAULT_COMMENT_SCOPE}：{title or '红果短剧'}"

    def _generate_remote_comment(self, title: str) -> Tuple[str, Dict[str, Any]]:
        base_url = str(self.ai_config.get("base_url") or "https://api.openai.com/v1").rstrip("/")
        model = str(self.ai_config.get("model") or "gpt-4o-mini")
        provider = str(self.ai_config.get("provider") or "openai_compatible")
        timeout = float(self.ai_config.get("timeout") or 30)
        scope = self._comment_scope(title)
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是短剧评论生成器。只输出一条可直接发布的中文评论正文。"
                        "不要输出解释、分析、前言、编号、引号、Markdown 或自我说明。"
                        "语气自然，像真实观众随手写的一句话。"
                        "如果提示里给了评论范围，就围绕范围写；如果没有，就围绕标题写。"
                        "不要出现“首先”“用户要求我”“作为短剧评论助手”等说明性文字。"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"短剧名称：{title or '红果短剧'}。\n"
                        f"评论范围：{scope}\n"
                        "请只生成一条中文评论正文。"
                    ),
                },
            ],
            "temperature": float(self.ai_config.get("temperature") or 0.8),
            "max_tokens": int(self.ai_config.get("max_tokens") or 80),
        }
        req = request.Request(
            f"{base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.ai_config['api_key']}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            raise CommentGenerationError(f"AI API HTTP {exc.code}: {body[:200]}") from exc
        except URLError as exc:
            raise CommentGenerationError(f"AI API connection failed: {exc.reason}") from exc

        content = self._extract_content(data)
        usage_data = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        usage = {
            "provider": provider,
            "model": model,
            "base_url": base_url,
            "source": "ai",
            "prompt_tokens": int(usage_data.get("prompt_tokens") or 0),
            "completion_tokens": int(usage_data.get("completion_tokens") or 0),
            "total_tokens": int(usage_data.get("total_tokens") or 0),
        }
        if not usage["total_tokens"]:
            usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
        return self._clean_comment(content, data), usage

    def _extract_content(self, data: Dict[str, Any]) -> str:
        choices = data.get("choices") if isinstance(data, dict) else None
        choice = choices[0] if isinstance(choices, list) and choices else {}
        if not isinstance(choice, dict):
            return self._content_to_text(data.get("content") or data.get("text"))

        message = choice.get("message")
        candidates: List[Any] = []
        if isinstance(message, dict):
            candidates.extend(
                [
                    message.get("content"),
                    message.get("reasoning_content"),
                    message.get("text"),
                ]
            )
        candidates.extend(
            [
                choice.get("text"),
                choice.get("content"),
                data.get("text"),
                data.get("content"),
            ]
        )

        for candidate in candidates:
            text = self._content_to_text(candidate)
            if text.strip():
                return text.strip()
        return ""

    def _content_to_text(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    value = item.get("text") or item.get("content")
                    if isinstance(value, str):
                        parts.append(value)
                    elif isinstance(value, dict) and isinstance(value.get("value"), str):
                        parts.append(value["value"])
            return "".join(parts)
        if isinstance(content, dict):
            value = content.get("text") or content.get("content") or content.get("value")
            return value if isinstance(value, str) else ""
        return ""

    def _generate_local_comment(self, title: str) -> str:
        matched: List[str] = []
        for keyword, comments in self.GENRE_COMMENTS.items():
            if keyword in (title or ""):
                matched.extend(comments)
        return random.choice(matched or self.GENERIC_COMMENTS)

    def _strip_preamble(self, content: str) -> str:
        text = (content or "").strip()
        if not text:
            return text

        for prefix in (
            "首先，",
            "首先：",
            "首先,",
            "用户要求我",
            "作为短剧评论助手",
            "作为评论助手",
            "根据当前标题",
            "根据用户要求",
            "根据您的要求",
            "我会根据",
            "我将根据",
            "以下是",
        ):
            if text.startswith(prefix):
                text = text[len(prefix) :].lstrip("：:，,。 \t")

        if "：" in text:
            head, tail = text.split("：", 1)
            if any(key in head for key in ("评论助手", "用户要求", "根据", "作为", "生成", "短剧评论")) and tail.strip():
                text = tail.strip()
        elif ":" in text:
            head, tail = text.split(":", 1)
            if any(key in head for key in ("comment", "user", "assistant", "generate")) and tail.strip():
                text = tail.strip()

        return text.strip()

    def _clean_comment(self, content: str, raw_data: Dict[str, Any] | None = None) -> str:
        content = re.sub(r'^[\"\'“”‘’\s]+|[\"\'“”‘’\s]+$', "", content or "")
        content = re.sub(r"^\d+[.、:：\s]*", "", content)
        content = re.sub(r"\s+", "", content)
        content = self._strip_preamble(content)
        if not content:
            raise CommentGenerationError(self._empty_response_message(raw_data or {}))
        if not re.search(r"[\u4e00-\u9fff]", content):
            raise CommentGenerationError("AI API returned non-Chinese comment")
        if self._looks_like_prompt_leak(content):
            raise CommentGenerationError("AI API returned prompt text instead of comment")
        if len(content) > 36:
            content = content[:36]
        return content

    def _looks_like_prompt_leak(self, content: str) -> bool:
        text = re.sub(r"\s+", "", content or "").lower()
        if not text:
            return True
        blocked = (
            "\u7528\u6237\u6307\u4ee4",
            "\u7cfb\u7edf\u63d0\u793a",
            "\u77ed\u5267\u8bc4\u8bba\u751f\u6210\u5668",
            "\u53ea\u8f93\u51fa\u4e00\u6761",
            "\u53ef\u76f4\u63a5\u53d1\u5e03",
            "\u8bc4\u8bba\u6b63\u6587",
            "\u4e0d\u8981\u8f93\u51fa",
            "\u4e0d\u8981\u51fa\u73b0",
            "userinstruction",
            "systemprompt",
            "assistant",
            "markdown",
        )
        return any(token in text for token in blocked)

    def _empty_response_message(self, data: Dict[str, Any]) -> str:
        choice: Dict[str, Any] = {}
        choices = data.get("choices") if isinstance(data, dict) else None
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            choice = choices[0]
        message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
        finish_reason = choice.get("finish_reason") or data.get("finish_reason")
        fields = sorted(message.keys()) if message else sorted(choice.keys())
        detail = f" finish_reason={finish_reason}" if finish_reason else ""
        if fields:
            detail += f" fields={','.join(fields)}"
        return f"AI API returned empty comment.{detail}".strip()
