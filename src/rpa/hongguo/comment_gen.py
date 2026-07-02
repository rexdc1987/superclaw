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

    DEFAULT_COMMENT_SCOPE = "根据当前标题生成一条自然短评"
    DEFAULT_PERSONA = "普通红果短剧观众，口语化，像刷剧时顺手发一句真实感受"

    GROUNDED_COMMENTS = [
        "这集有点东西，越看越想追",
        "这段真挺上头的，停不下来",
        "女主这口气终于顺了，看着舒服",
        "男主这下支棱起来了，等反打",
        "这反转可以，下一集得接着看",
        "说真的，比我想的好看不少",
        "这剧情不拖，刷起来挺顺",
        "这集节奏可以，越看越带劲",
        "这波操作看爽了，继续追",
        "有一说一，这剧还挺下饭",
        "这段演得挺有味儿，入戏了",
        "后面别掉链子，我先追着看",
    ]

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

    SEASON_COMMENTS = [
        "这一季节奏很稳，越看越上头",
        "这季剧情比前面更带感了",
        "这一季追起来太顺了，根本停不下来",
        "后面的剧情赶紧跟上，太想继续看了",
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

    def pick_template(self, templates: Iterable[str], title: str = "") -> str:
        cleaned = [str(t).strip() for t in templates if str(t).strip()]
        if not cleaned:
            return self._generate_local_comment(title)
        comment = random.choice(cleaned)
        try:
            return self._clean_comment(comment, title=title)
        except CommentGenerationError:
            return self._generate_local_comment(title)

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
            return self.pick_template(templates or [], title), "template", {}
        comment, usage = self.generate_ai_comment_with_usage(title)
        return comment, "ai", usage

    def _ai_enabled(self) -> bool:
        return bool(self.ai_config.get("enabled", False) and self.ai_config.get("api_key"))

    def _comment_scope(self, title: str) -> str:
        scope = str(self.ai_config.get("comment_scope") or "").strip()
        if scope:
            return scope
        return f"{self.DEFAULT_COMMENT_SCOPE}: {title or '红果短剧'}"

    def _comment_style(self) -> str:
        persona = self.ai_config.get("comment_persona") if isinstance(self.ai_config.get("comment_persona"), dict) else {}
        return str(persona.get("style") or self.ai_config.get("comment_style") or "grounded").strip()

    def _persona_text(self) -> str:
        persona = self.ai_config.get("comment_persona") if isinstance(self.ai_config.get("comment_persona"), dict) else {}
        account = self.ai_config.get("account_info") if isinstance(self.ai_config.get("account_info"), dict) else {}
        text = str(persona.get("persona") or self.ai_config.get("default_persona") or self.DEFAULT_PERSONA).strip()
        nickname = str(account.get("nickname") or "").strip()
        if nickname:
            return f"{text}。当前账号昵称: {nickname}"
        return text

    def _style_instruction(self, style: str) -> str:
        styles = {
            "grounded": "接地气短评，像真人随手发，不端着",
            "funny": "轻吐槽，有生活感，但不要阴阳怪气",
            "plot": "嗑剧情和人物反转，别写成影评",
            "update": "追更口吻，可以期待后续，但不要催当前季",
            "immersive": "代入观众情绪，像正在边看边发",
        }
        return styles.get(style, style or styles["grounded"])

    def _generate_remote_comment(self, title: str) -> Tuple[str, Dict[str, Any]]:
        base_url = str(self.ai_config.get("base_url") or "https://api.openai.com/v1").rstrip("/")
        model = str(self.ai_config.get("model") or "gpt-4o-mini")
        provider = str(self.ai_config.get("provider") or "openai_compatible")
        timeout = float(self.ai_config.get("timeout") or 30)
        scope = self._comment_scope(title)
        style = self._comment_style()
        persona = self._persona_text()
        max_tokens = min(int(self.ai_config.get("max_tokens") or 80), 120)
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你只输出一条可直接发布到红果短剧评论区的中文短评。"
                        "像真实用户刷剧时顺手发一句，口语化、接地气、有情绪，但不过度夸张。"
                        "优先 12 到 28 个中文字符，最多 36 个字符。"
                        "不要解释、分析、前言、编号、引号、Markdown、自我说明或提示词内容。"
                        "不要出现“用户要求”“系统提示”“短剧评论生成器”“只输出一条”等提示词痕迹。"
                        "不要写官方宣传、影评腔、营销腔，不要编造具体剧情细节。"
                        "如果短剧名称已包含第几季，不要催更或安排当前这一季。"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"短剧名称: {title or '红果短剧'}\n"
                        f"评论范围: {scope}\n"
                        f"账号人设: {persona}\n"
                        f"评论风格: {self._style_instruction(style)}\n"
                        "只返回评论正文，不要带任何说明。"
                    ),
                },
            ],
            "temperature": float(self.ai_config.get("temperature") or 0.8),
            "max_tokens": max_tokens,
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
        return self._clean_comment(content, data, title=title), usage

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
        next_season = self._next_season_marker(title)
        if next_season:
            matched.append(f"{next_season}赶紧安排上，这一季真的太上头了")
            matched.append(f"这一季越看越过瘾，已经开始期待{next_season}了")
        elif self._season_marker(title):
            matched.extend(self.SEASON_COMMENTS)
        for keyword, comments in self.GENRE_COMMENTS.items():
            if keyword in (title or ""):
                matched.extend(comments)
        comment = random.choice(matched or self.GROUNDED_COMMENTS or self.GENERIC_COMMENTS)
        if self._asks_for_current_season(comment, title):
            return random.choice(self.SEASON_COMMENTS)
        return comment

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

    def _clean_comment(
        self,
        content: str,
        raw_data: Dict[str, Any] | None = None,
        title: str = "",
    ) -> str:
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
        if self._asks_for_current_season(content, title):
            raise CommentGenerationError("AI API returned stale current-season request")
        content = self._trim_comment(content)
        return content

    def _trim_comment(self, content: str, max_len: int = 36) -> str:
        content = (content or "").strip()
        if len(content) <= max_len:
            return content
        for punct in ("。", "！", "？", "!", "?", "~", "～"):
            idx = content.rfind(punct, 0, max_len + 1)
            if idx >= 12:
                return content[: idx + 1]
        for punct in ("，", ",", "、", "；", ";"):
            idx = content.rfind(punct, 0, max_len)
            if idx >= 16:
                return content[:idx].rstrip() + "！"
        trimmed = content[: max_len - 1].rstrip("，,、；;：:的了在把被和与又太")
        return (trimmed or content[: max_len - 1]) + "！"

    def _looks_like_prompt_leak(self, content: str) -> bool:
        text = re.sub(r"\s+", "", content or "").lower()
        if not text:
            return True
        blocked = (
            "\u7528\u6237\u6307\u4ee4",
            "\u7528\u6237\u8981\u6c42",
            "\u7528\u6237\u60f3\u8981",
            "\u7cfb\u7edf\u63d0\u793a",
            "\u77ed\u5267\u8bc4\u8bba\u751f\u6210\u5668",
            "\u53ea\u8f93\u51fa\u4e00\u6761",
            "\u8f93\u51fa\u4e00\u6761",
            "\u53ef\u76f4\u63a5\u53d1\u5e03",
            "\u8bc4\u8bba\u6b63\u6587",
            "\u4e0d\u8981\u8f93\u51fa",
            "\u4e0d\u8981\u51fa\u73b0",
            "\u8fd4\u56de\u8bc4\u8bba",
            "\u751f\u6210\u4e00\u6761",
            "\u4e2d\u6587\u77ed\u8bc4",
            "\u81ea\u7136\u77ed\u8bc4",
            "\u53e3\u8bed\u5316",
            "\u63a5\u5730\u6c14",
            "\u6709\u60c5\u7eea",
            "\u4e0d\u8fc7\u5ea6\u5938\u5f20",
            "\u4f18\u514812",
            "\u4e2d\u6587\u5b57\u7b26",
            "\u4e0d\u8981\u89e3\u91ca",
            "\u4e0d\u8981\u5e26\u4efb\u4f55\u8bf4\u660e",
            "\u8bc4\u8bba\u98ce\u683c",
            "\u8d26\u53f7\u4eba\u8bbe",
            "\u8bc4\u8bba\u8303\u56f4",
            "\u7ea2\u679c\u77ed\u5267\u8bc4\u8bba\u533a",
            "userinstruction",
            "systemprompt",
            "assistant",
            "markdown",
        )
        return any(token in text for token in blocked)

    def _asks_for_current_season(self, content: str, title: str) -> bool:
        season = self._season_marker(title)
        if not season:
            return False
        text = re.sub(r"\s+", "", content or "")
        if not text or season not in text:
            return False
        request_words = (
            "求更",
            "快更",
            "更新",
            "赶紧",
            "安排",
            "快出",
            "什么时候出",
            "期待",
            "等不及",
            "续上",
        )
        return any(word in text for word in request_words)

    def _season_marker(self, value: str) -> str:
        text = str(value or "")
        match = re.search(r"第([一二三四五六七八九十百\d]+)季", text)
        if match:
            return f"第{match.group(1)}季"
        match = re.search(r"([一二三四五六七八九十百\d]+)季", text)
        return f"第{match.group(1)}季" if match else ""

    def _next_season_marker(self, value: str) -> str:
        season = self._season_marker(value)
        match = re.search(r"第([一二三四五六七八九十百\d]+)季", season)
        if not match:
            return ""
        number = self._season_number(match.group(1))
        if number <= 0:
            return ""
        return f"第{self._season_number_text(number + 1)}季"

    def _season_number(self, text: str) -> int:
        if text.isdigit():
            return int(text)
        digits = {
            "一": 1,
            "二": 2,
            "三": 3,
            "四": 4,
            "五": 5,
            "六": 6,
            "七": 7,
            "八": 8,
            "九": 9,
            "十": 10,
        }
        if text in digits:
            return digits[text]
        if text.startswith("十") and len(text) == 2:
            return 10 + digits.get(text[1], 0)
        if text.endswith("十") and len(text) == 2:
            return digits.get(text[0], 0) * 10
        if "十" in text and len(text) == 3:
            return digits.get(text[0], 0) * 10 + digits.get(text[2], 0)
        return 0

    def _season_number_text(self, number: int) -> str:
        digits = "零一二三四五六七八九"
        if number <= 0:
            return str(number)
        if number < 10:
            return digits[number]
        if number == 10:
            return "十"
        if number < 20:
            return "十" + digits[number % 10]
        if number < 100:
            tens, ones = divmod(number, 10)
            return digits[tens] + "十" + (digits[ones] if ones else "")
        return str(number)

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
