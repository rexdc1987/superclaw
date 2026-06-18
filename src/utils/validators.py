"""SuperClaw 输入验证工具"""
import re
from typing import Tuple


def validate_username(username: str) -> Tuple[bool, str]:
    """验证用户名：非空，2-50字符，只允许字母数字下划线中文"""
    if not username or not username.strip():
        return False, "用户名不能为空"
    username = username.strip()
    if len(username) < 2 or len(username) > 50:
        return False, "用户名长度需在2-50个字符之间"
    if not re.match(r'^[\w\u4e00-\u9fff]+$', username):
        return False, "用户名只允许字母、数字、下划线和中文"
    return True, ""


def validate_platform(platform: str) -> Tuple[bool, str]:
    """验证平台名称"""
    valid = ["douyin", "xiaohongshu", "kuaishou", "bilibili"]
    if platform not in valid:
        return False, f"不支持的平台: {platform}，可选: {', '.join(valid)}"
    return True, ""


def validate_task_name(name: str) -> Tuple[bool, str]:
    """验证任务名称"""
    if not name or not name.strip():
        return False, "任务名称不能为空"
    name = name.strip()
    if len(name) > 100:
        return False, "任务名称不能超过100个字符"
    return True, ""


def validate_content(content: str, max_length: int = 500) -> Tuple[bool, str]:
    """验证评论/消息内容"""
    if not content or not content.strip():
        return False, "内容不能为空"
    content = content.strip()
    if len(content) > max_length:
        return False, f"内容不能超过{max_length}个字符"
    return True, ""


def validate_keyword(keyword: str) -> Tuple[bool, str]:
    """验证关键词"""
    if not keyword or not keyword.strip():
        return False, "关键词不能为空"
    keyword = keyword.strip()
    if len(keyword) > 50:
        return False, "关键词不能超过50个字符"
    return True, ""


def validate_url(url: str) -> Tuple[bool, str]:
    """验证URL格式"""
    if not url:
        return False, "URL不能为空"
    pattern = r'^https?://[\w\-]+(\.[\w\-]+)+([\w\-.,@?^=%&:/~+#]*[\w\-@?^=%&/~+#])?$'
    if not re.match(pattern, url):
        return False, "URL格式不正确"
    return True, ""


def validate_positive_int(value, name: str = "值") -> Tuple[bool, str]:
    """验证正整数"""
    try:
        v = int(value)
        if v <= 0:
            return False, f"{name}必须是正整数"
        return True, ""
    except (ValueError, TypeError):
        return False, f"{name}必须是整数"


def sanitize_text(text: str) -> str:
    """清理文本：去除首尾空白、合并连续空格"""
    if not text:
        return ""
    text = text.strip()
    text = re.sub(r'\s+', ' ', text)
    return text
