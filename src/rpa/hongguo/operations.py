"""Atomic UI operations for Hongguo comment automation."""

from __future__ import annotations

import html
import random
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .device import screenshot


APP_PACKAGE = "com.phoenix.read"
COMMENT_BUTTON_ID = "com.phoenix.read:id/cdi"
PLAYBACK_SPEED_OPTIONS = ("0.75x", "1.0x", "1.25x", "1.5x", "2.0x", "3.0x")
TAG_KEYWORDS = {
    "玄幻",
    "传统",
    "都市",
    "甜宠",
    "逆袭",
    "悬疑",
    "搞笑",
    "古装",
    "现代",
    "仙侠",
    "武侠",
    "异界",
    "脑洞",
    "新剧",
    "热榜",
}


class HongguoOperations:
    def __init__(self, device: Any):
        self.d = device
        try:
            self.width, self.height = self.d.window_size()
        except Exception:
            self.width, self.height = 1080, 1920

    def launch_app(self) -> bool:
        try:
            for attempt in range(2):
                self._stop_app()
                time.sleep(2)
                self._start_app()
                if self._is_app_foreground() or self._wait_app_ready(12 if attempt == 0 else 8):
                    self._close_popups()
                    return True
            return self._is_app_foreground()
        except Exception:
            return False

    def check_login(self) -> Dict[str, Any]:
        try:
            self._close_popups()
            xml = self._xml()
            if self._playback_visible(xml):
                return {"logged_in": True, "status": "in_app", "message": "红果播放页可用"}
            for text in ["我的", "我的tab"]:
                el = self.d(text=text)
                if self._exists(el, 1):
                    el.click()
                    time.sleep(2)
                    break
            else:
                self.d.click(int(self.width * 0.9), int(self.height * 0.95))
                time.sleep(2)

            xml = self._xml()
            logged_in_markers = ["我的钱包", "观看历史", "红果号", "编辑资料", "提现", "收藏"]
            if any(text in xml for text in logged_in_markers):
                return {"logged_in": True, "status": "logged_in", "message": "已登录"}
            if self._playback_visible(xml):
                return {"logged_in": True, "status": "in_app", "message": "红果播放页可用"}
            if any(text in xml for text in ["登录", "手机号", "微信登录", "抖音登录"]):
                return {"logged_in": False, "status": "not_logged_in", "message": "未登录"}
            return {"logged_in": False, "status": "unknown", "message": "无法确认登录状态"}
        except Exception as exc:
            return {"logged_in": False, "status": "error", "message": str(exc)}

    def get_device_info(self) -> Dict[str, Any]:
        info: Dict[str, Any] = {}
        device_info: Dict[str, Any] = {}
        current: Dict[str, Any] = {}
        try:
            value = self.d.info
            if isinstance(value, dict):
                info = value
        except Exception:
            pass
        try:
            value = self.d.device_info
            if callable(value):
                value = value()
            if isinstance(value, dict):
                device_info = value
        except Exception:
            pass
        try:
            value = self.d.app_current()
            if isinstance(value, dict):
                current = value
        except Exception:
            pass

        serial = self._safe_text(getattr(self.d, "serial", "") or getattr(self.d, "_serial", ""))
        model = self._first_text(
            device_info.get("model"),
            device_info.get("productName"),
            info.get("model"),
            info.get("productName"),
        )
        brand = self._first_text(device_info.get("brand"), info.get("brand"), info.get("manufacturer"))
        product = self._first_text(device_info.get("product"), device_info.get("productName"), info.get("productName"))
        sdk = self._first_text(device_info.get("sdk"), device_info.get("sdkInt"), info.get("sdkInt"))
        android_version = self._first_text(device_info.get("version"), info.get("androidVersion"), info.get("version"))

        return {
            "serial": serial,
            "emulator": self._guess_emulator_name(serial, model, product, brand),
            "model": model,
            "brand": brand,
            "product": product,
            "sdk": sdk,
            "android_version": android_version,
            "resolution": f"{self.width}x{self.height}",
            "current_package": self._safe_text(current.get("package")),
            "current_activity": self._safe_text(current.get("activity")),
        }

    def get_account_info(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "logged_in": False,
            "nickname": "",
            "hongguo_id": "",
            "message": "\u672a\u8bc6\u522b\u7ea2\u679c\u8d26\u53f7\u4fe1\u606f",
        }
        try:
            self._open_profile_tab()
            xml = self._xml()
            texts = self._extract_xml_texts(xml)
            hongguo_id = self._extract_hongguo_id(texts, xml)
            nickname = self._extract_account_nickname(texts)
            logged_in_markers = (
                "\u6211\u7684\u94b1\u5305",
                "\u89c2\u770b\u5386\u53f2",
                "\u7ea2\u679c\u53f7",
                "\u7f16\u8f91\u8d44\u6599",
                "\u63d0\u73b0",
                "\u6536\u85cf",
            )
            login_prompts = (
                "\u767b\u5f55",
                "\u624b\u673a\u53f7",
                "\u5fae\u4fe1\u767b\u5f55",
                "\u6296\u97f3\u767b\u5f55",
            )
            logged_in = bool(hongguo_id or nickname or any(marker in xml for marker in logged_in_markers))
            if not logged_in and any(prompt in xml for prompt in login_prompts):
                result["message"] = "\u7ea2\u679c\u672a\u767b\u5f55"
            elif logged_in:
                result["message"] = "\u5df2\u8bc6\u522b\u7ea2\u679c\u8d26\u53f7" if (nickname or hongguo_id) else "\u7ea2\u679c\u5df2\u767b\u5f55\uff0c\u8d26\u53f7\u4fe1\u606f\u672a\u8bc6\u522b"
            result.update(
                {
                    "logged_in": logged_in,
                    "nickname": nickname,
                    "hongguo_id": hongguo_id,
                }
            )
            return result
        except Exception as exc:
            result["message"] = str(exc)
            return result

    def search_drama(self, keyword: str) -> Dict[str, Any]:
        try:
            self._close_popups()
            current_title = self._current_playing_title()
            if current_title and keyword in current_title:
                return {"success": True, "titles": [current_title], "message": "已在目标短剧页面"}
            self._open_theater()
            if not self._open_search():
                return {"success": False, "titles": [], "message": "未找到搜索入口"}
            self._sleep(1.5, 2.5)
            inp = self.d(className="android.widget.EditText")
            if self._exists(inp, 3):
                inp.click()
                time.sleep(0.5)
                self._clear_input(inp)
                self._type_text(keyword)
            else:
                self.d.send_keys(keyword)
            self._sleep(0.8, 1.5)
            search_btn = self.d(text="搜索")
            if self._exists(search_btn, 2):
                search_btn.click()
            else:
                self.d.press("enter")
            self._sleep(3, 5)
            titles = self._extract_drama_titles()
            return {
                "success": bool(titles),
                "keyword": keyword,
                "titles": titles,
                "message": "搜索完成" if titles else "未找到有效短剧标题",
            }
        except Exception as exc:
            return {"success": False, "keyword": keyword, "titles": [], "message": str(exc)}

    def select_drama(self, title: str) -> Dict[str, Any]:
        try:
            current_title = self._current_playing_title()
            if current_title and (not title or title in current_title or current_title in title):
                return {"success": True, "drama_title": current_title, "playable": True}
            clicked = False
            if title:
                if self._click_first_search_suggestion():
                    clicked = True
                    if "SearchActivity" in self.d.app_current().get("activity", ""):
                        self.d.click(int(self.width * 0.25), int(self.height * 0.38))
                        time.sleep(3)
                card_title = self.d(resourceId="com.phoenix.read:id/title", textContains=title.strip("《》 "))
                if not clicked and self._exists(card_title, 2):
                    card_title.click()
                    clicked = True
                for selector in (self.d(text=title), self.d(textContains=title[:8])):
                    if clicked:
                        break
                    if self._exists(selector, 2):
                        selector.click()
                        clicked = True
                        break
            if not clicked:
                self.d.click(int(self.width * 0.28), int(self.height * 0.38))
            self._sleep(3, 5)
            drama_title = self._extract_detail_title() or title
            xml = self._xml()
            playable = any(
                text in xml
                for text in ["观看", "播放", "看全集", "立即观看", "开始播放", "全屏观看", "合集", "第1集"]
            )
            return {"success": True, "drama_title": drama_title, "playable": playable}
        except Exception as exc:
            return {"success": False, "drama_title": title, "playable": False, "message": str(exc)}

    def play_episode(self, episode_number: int) -> bool:
        try:
            self.exit_fullscreen()
            current_episode = self.get_current_episode()
            if current_episode == episode_number:
                return True
            if current_episode <= 0:
                for _ in range(2):
                    if not self._click_first_play_button():
                        break
                    self._sleep(3, 5)
                    self.exit_fullscreen()
                    current_episode = self.get_current_episode()
                    if episode_number <= 1 and self._episode_is_confirmed(1):
                        return True
            if episode_number <= 1:
                if self._episode_is_confirmed(1):
                    return True
                for _ in range(2):
                    selector = self._episode_panel_selector()
                    if selector is not None and self._exists(selector, 3):
                        selector.click()
                        self._sleep(1.5, 2.5)
                    if self._click_episode_number(1):
                        self._sleep(2, 3)
                        self.exit_fullscreen()
                        current_episode = self.get_current_episode()
                        if self._episode_is_confirmed(1):
                            return True
                    if current_episode <= 0 and self._click_first_play_button():
                        self._sleep(2, 3)
                        self.exit_fullscreen()
                        current_episode = self.get_current_episode()
                        if self._episode_is_confirmed(1):
                            return True
                return self._episode_is_confirmed(1)
            selector = self._episode_panel_selector()
            if selector is not None and self._exists(selector, 3):
                selector.click()
                self._sleep(1.5, 2.5)
                if self._click_episode_number(episode_number):
                    for _ in range(6):
                        if self.get_current_episode() == episode_number:
                            return True
                        time.sleep(1)
            return self._episode_is_confirmed(episode_number)
        except Exception:
            return False

    def set_playback_speed(self, speed: str) -> bool:
        target = self._normalize_speed_label(speed)
        if not target:
            return False
        self.exit_fullscreen()
        if self._current_speed_matches(target):
            return True
        for _ in range(2):
            if not self._speed_panel_open():
                trigger = self._speed_trigger_selector()
                if trigger is None:
                    self._reveal_playback_controls()
                    trigger = self._speed_trigger_selector()
                if trigger is None:
                    continue
                trigger.click()
                self._sleep(0.8, 1.5)
            if not self._speed_panel_open():
                continue
            if self._click_speed_option(target):
                self._sleep(0.8, 1.5)
                if self._current_speed_matches(target):
                    return True
            self.d.press("back")
            time.sleep(0.8)
        return self._current_speed_matches(target)

    def _episode_panel_selector(self) -> Optional[Any]:
        for selector in (self.d(textContains="选集"), self.d(textContains="合集")):
            if self._exists(selector, 1):
                return selector
        return None

    def _speed_trigger_selector(self) -> Optional[Any]:
        selectors = [
            self.d(textContains="倍速"),
            self.d(descriptionContains="倍速"),
        ]
        for label in PLAYBACK_SPEED_OPTIONS:
            selectors.append(self.d(text=label))
            selectors.append(self.d(textContains=label))
        for selector in selectors:
            if self._exists(selector, 1):
                return selector
        return None

    def _speed_panel_open(self, xml: Optional[str] = None) -> bool:
        xml = xml or self._xml()
        if not xml:
            return False
        visible_options = sum(1 for label in PLAYBACK_SPEED_OPTIONS if label in xml)
        return visible_options >= 3 and "倍速" in xml

    def _current_speed_matches(self, speed: str, xml: Optional[str] = None) -> bool:
        xml = xml or self._xml()
        if not xml:
            return False
        target = self._normalize_speed_label(speed)
        if not target:
            return False
        escaped = re.escape(target)
        state_patterns = (
            rf'text="{escaped}"[^>]*(?:selected|checked|focused)="true"',
            rf'content-desc="{escaped}"[^>]*(?:selected|checked|focused)="true"',
            rf'text="{escaped}"[^>]*resource-id="[^"]*(?:selected|current|checked)[^"]*"',
        )
        if any(re.search(pattern, xml, re.IGNORECASE) for pattern in state_patterns):
            return True
        if self._speed_panel_open(xml):
            if target == "1.0x" and target in xml and "默认" in xml:
                return True
            return False
        return target in xml

    def _click_speed_option(self, speed: str) -> bool:
        target = self._normalize_speed_label(speed)
        if not target:
            return False
        for selector in (self.d(text=target), self.d(textContains=target)):
            if self._exists(selector, 1):
                try:
                    count = selector.count
                    for i in range(count):
                        info = selector[i].info
                        top = info.get("bounds", {}).get("top", 0)
                        if top > self.height * 0.1:
                            selector[i].click()
                            return True
                except Exception:
                    selector.click()
                    return True
        return False

    def _reveal_playback_controls(self) -> None:
        self.d.click(int(self.width * 0.5), int(self.height * 0.5))
        time.sleep(0.6)

    def resume_playback_if_paused(self, allow_center_fallback: bool = False) -> bool:
        if not self._playback_visible():
            return False
        for selector in (
            self.d(descriptionContains="继续播放"),
            self.d(descriptionContains="播放"),
            self.d(textContains="继续播放"),
            self.d(textContains="播放"),
        ):
            if self._exists(selector, 0.5):
                try:
                    selector.click()
                    time.sleep(1)
                    return True
                except Exception:
                    continue
        if allow_center_fallback:
            self.d.click(int(self.width * 0.5), int(self.height * 0.44))
            time.sleep(1)
            return True
        return False

    def _normalize_speed_label(self, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip().lower().replace(" ", "")
        if not text:
            return None
        if text.endswith("x"):
            text = text[:-1]
        aliases = {
            "0.75": "0.75x",
            "1": "1.0x",
            "1.0": "1.0x",
            "1.25": "1.25x",
            "1.5": "1.5x",
            "2": "2.0x",
            "2.0": "2.0x",
            "3": "3.0x",
            "3.0": "3.0x",
        }
        return aliases.get(text)

    def get_current_episode(self) -> int:
        xml = self._xml()
        if not xml:
            return 0

        weighted_matches: List[tuple[int, int, int]] = []
        patterns = (
            (120, r"(?:\u6b63\u5728\u64ad\u653e|\u5f53\u524d\u64ad\u653e|\u7eed\u64ad\u81f3)\s*\u7b2c\s*(\d{1,4})\s*\u96c6"),
            (110, r"\u7b2c\s*(\d{1,4})\s*\u96c6[^\n<\"]{0,12}(?:\u64ad\u653e\u4e2d|\u70ed\u64ad\u4e2d|\u89c2\u770b\u4e2d)"),
            (100, r"(?:\u64ad\u653e\u5230|EP)\s*(\d{1,4})"),
        )
        for weight, pattern in patterns:
            for match in re.finditer(pattern, xml, re.IGNORECASE):
                try:
                    weighted_matches.append((weight, int(match.group(1)), match.start()))
                except (TypeError, ValueError):
                    continue
        if weighted_matches:
            weighted_matches.sort(key=lambda item: (-item[0], item[2]))
            return weighted_matches[0][1]

        header_match = re.search(
            r'text="\u7b2c\s*(\d{1,4})\s*\u96c6"[^>]*package="com\.phoenix\.read"[^>]*bounds="\[\d+,(\d+)\]\[\d+,\d+\]"',
            xml,
        )
        if header_match and COMMENT_BUTTON_ID in xml:
            try:
                if int(header_match.group(2)) <= int(self.height * 0.12):
                    return int(header_match.group(1))
            except (TypeError, ValueError):
                pass

        numbers = self._extract_episode_numbers(xml)
        for episode in numbers:
            if self._is_episode_active(episode, xml):
                return episode
        if len(numbers) == 1:
            return numbers[0]
        return 0

    def get_total_episodes(self) -> int:
        xml = self._xml()
        if not xml:
            return 0

        totals: List[int] = []
        for pattern in (
            r"(?:\u5168|\u5171)\s*(\d{1,4})\s*\u96c6",
            r"(?:\u66f4\u65b0\u81f3|\u5df2\u66f4\u65b0\u81f3)\s*(\d{1,4})\s*\u96c6",
            r"(?:\u5b8c\u7ed3|\u5b8c\u7d50)\s*(\d{1,4})\s*\u96c6",
        ):
            totals.extend(int(value) for value in re.findall(pattern, xml))

        episode_numbers = self._extract_episode_numbers(xml)
        if episode_numbers:
            totals.append(max(episode_numbers))
        return max(totals) if totals else 0

    def _playback_visible(self, xml: Optional[str] = None) -> bool:
        xml = xml or self._xml()
        if not xml:
            return False
        if COMMENT_BUTTON_ID in xml:
            return True
        markers = (
            "\u5168\u5c4f\u89c2\u770b",
            "\u9009\u96c6",
            "\u5408\u96c6",
            "\u500d\u901f",
            "\u8bc4\u8bba",
            "\u6709\u8da3\u8bc4\u8bba",
            "\u8bf4\u70b9\u4ec0\u4e48",
        )
        if any(marker in xml for marker in markers):
            return True
        return bool(re.search(r"\u7b2c\s*\d{1,4}\s*\u96c6", xml))

    def _is_episode_active(self, episode_number: int, xml: Optional[str] = None) -> bool:
        if episode_number <= 0:
            return False
        xml = xml or self._xml()
        if not xml:
            return False

        labels = (str(episode_number), f"\u7b2c{episode_number}\u96c6")
        for label in labels:
            escaped = re.escape(label)
            state_patterns = (
                rf'text="{escaped}"[^>]*(?:selected|checked|focused)="true"',
                rf'content-desc="{escaped}"[^>]*(?:selected|checked|focused)="true"',
                rf'text="{escaped}"[^>]*resource-id="[^"]*(?:tv_selected|selected|current)[^"]*"',
            )
            if any(re.search(pattern, xml, re.IGNORECASE) for pattern in state_patterns):
                return True
        return False

    def _episode_is_confirmed(self, episode_number: int) -> bool:
        if episode_number <= 0:
            return False
        return self.get_current_episode() == episode_number or self._is_episode_active(episode_number)

    def ensure_playback_page(self, episode_number: int) -> bool:
        try:
            self.exit_fullscreen()
            current = self.get_current_episode()
            if episode_number <= 0:
                return self._playback_visible()
            if current == episode_number and self._playback_visible():
                return True
            if self.play_episode(episode_number):
                return self._episode_is_confirmed(episode_number)
            return self._episode_is_confirmed(episode_number)
        except Exception:
            return False

    def _open_comment_panel(self, timeout: float = 2) -> bool:
        comment_btn = self.d(resourceId=COMMENT_BUTTON_ID)
        if self._exists(comment_btn, timeout):
            comment_btn.click()
            return True
        if self._playback_visible():
            # Fallback for app versions where the comment bubble has no stable resource-id.
            self.d.click(int(self.width * 0.94), int(self.height * 0.67))
            time.sleep(1)
            return self._comment_panel_open()
        return False

    def exit_fullscreen(self) -> bool:
        exited = False
        for _ in range(2):
            if self.d(resourceId=COMMENT_BUTTON_ID).exists(timeout=2):
                return exited
            self.d.press("back")
            exited = True
            time.sleep(2)
        return exited

    def post_comment(self, content: str, episode_number: int = 0) -> Dict[str, Any]:
        try:
            if episode_number:
                current = self.get_current_episode()
                if current and current != episode_number:
                    return {
                        "success": False,
                        "message": f"当前已到第{current}集，取消第{episode_number}集评论发布",
                    }
            self.exit_fullscreen()
            if not self._open_comment_panel(3):
                return {"success": False, "message": "未找到评论按钮"}
            self._sleep(2, 3)
            if not self._comment_panel_open():
                return {"success": False, "message": "评论面板未打开"}
            input_found = self._focus_comment_input()
            if not input_found:
                return {"success": False, "message": "未找到评论输入框"}
            time.sleep(0.5)
            self._type_text(content)
            self._sleep(0.8, 1.5)
            for text in ["发送", "发布", "发表"]:
                el = self.d(text=text)
                if self._exists(el, 2):
                    el.click()
                    self._sleep(2, 3)
                    self._close_comment_panel()
                    return {"success": True, "message": "评论已发送"}
            self.d.press("enter")
            self._sleep(2, 3)
            self._close_comment_panel()
            return {"success": True, "message": "已尝试回车发送"}
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    def verify_comment(self, content: str, episode_number: int = 0, screenshot_dir: str = "") -> Dict[str, Any]:
        screenshot_path = ""
        try:
            if episode_number and not self.ensure_playback_page(episode_number):
                return {
                    "verified": False,
                    "screenshot_path": screenshot_path,
                    "message": f"未回到第{episode_number}集播放页",
                }
            self.exit_fullscreen()
            if not self._open_comment_panel(2):
                return {"verified": False, "screenshot_path": "", "message": "未找到评论按钮"}
            self._sleep(2, 3)
            if screenshot_dir:
                screenshot_path = self.take_screenshot(f"ep{episode_number or 'x'}_comment_panel", screenshot_dir)
            search_key = content[:8] if len(content) > 8 else content
            for _ in range(3):
                if self._exists(self.d(textContains=search_key), 2) or search_key in self._xml():
                    return {"verified": True, "screenshot_path": screenshot_path}
                self._swipe_up(0.45)
                time.sleep(1.5)
                if screenshot_dir:
                    screenshot_path = self.take_screenshot(f"ep{episode_number or 'x'}_comment_panel_scan", screenshot_dir)
            return {"verified": False, "screenshot_path": screenshot_path}
        except Exception as exc:
            return {"verified": False, "screenshot_path": screenshot_path, "message": str(exc)}
        finally:
            self._close_comment_panel()
            if episode_number:
                self.ensure_playback_page(episode_number)

    def take_screenshot(self, tag: str, screenshot_dir: str) -> str:
        ts = int(time.time() * 1000)
        safe_tag = re.sub(r"[^A-Za-z0-9_.-]+", "_", tag).strip("_") or "screen"
        path = Path(screenshot_dir) / f"{ts}_{safe_tag}.png"
        return screenshot(self.d, str(path))

    def _open_profile_tab(self) -> bool:
        try:
            self._close_popups()
            xml = self._xml()
            if self._profile_visible(xml):
                return True
            if self._playback_visible(xml):
                self.exit_fullscreen()
                time.sleep(1)
            for _ in range(3):
                for selector in (
                    self.d(text="\u6211\u7684"),
                    self.d(textContains="\u6211\u7684"),
                    self.d(descriptionContains="\u6211\u7684"),
                    self.d(text="\u6211\u7684tab"),
                ):
                    if self._exists(selector, 0.8):
                        selector.click()
                        time.sleep(1.5)
                        if self._profile_visible():
                            return True
                self.d.click(int(self.width * 0.9), int(self.height * 0.95))
                time.sleep(1.5)
                if self._profile_visible():
                    return True
                self.d.press("back")
                time.sleep(0.8)
            return self._profile_visible()
        except Exception:
            return False

    def _profile_visible(self, xml: Optional[str] = None) -> bool:
        xml = xml or self._xml()
        markers = (
            "\u6211\u7684\u94b1\u5305",
            "\u89c2\u770b\u5386\u53f2",
            "\u7ea2\u679c\u53f7",
            "\u7f16\u8f91\u8d44\u6599",
            "\u63d0\u73b0",
            "\u6536\u85cf",
        )
        return any(marker in xml for marker in markers)

    def _extract_xml_texts(self, xml: str) -> List[str]:
        values: List[str] = []
        seen = set()
        for attr in ("text", "content-desc"):
            for match in re.finditer(rf'{attr}="([^"]*)"', xml or ""):
                value = html.unescape(match.group(1)).strip()
                if value and value not in seen:
                    values.append(value)
                    seen.add(value)
        return values

    def _extract_hongguo_id(self, texts: List[str], xml: str) -> str:
        patterns = (
            r"\u7ea2\u679c\u53f7[:\uff1a\s]*([A-Za-z0-9_-]{3,32})",
            r"(?:ID|id)[:\uff1a\s]*([A-Za-z0-9_-]{3,32})",
        )
        haystacks = [xml] + texts
        for text in haystacks:
            for pattern in patterns:
                match = re.search(pattern, text)
                if match:
                    return match.group(1).strip()
        for idx, text in enumerate(texts[:-1]):
            if "\u7ea2\u679c\u53f7" in text:
                candidate = texts[idx + 1].strip()
                if re.fullmatch(r"[A-Za-z0-9_-]{3,32}", candidate):
                    return candidate
        return ""

    def _extract_account_nickname(self, texts: List[str]) -> str:
        blocked_parts = (
            "\u6211\u7684",
            "\u94b1\u5305",
            "\u89c2\u770b\u5386\u53f2",
            "\u7ea2\u679c\u53f7",
            "\u7f16\u8f91\u8d44\u6599",
            "\u63d0\u73b0",
            "\u6536\u85cf",
            "\u767b\u5f55",
            "\u624b\u673a\u53f7",
            "\u5fae\u4fe1",
            "\u6296\u97f3",
            "\u8bbe\u7f6e",
            "\u5ba2\u670d",
            "\u6d88\u606f",
            "\u5173\u6ce8",
            "\u7c89\u4e1d",
        )
        for text in texts:
            value = text.strip()
            if not value or len(value) > 24:
                continue
            if any(part in value for part in blocked_parts):
                continue
            if re.fullmatch(r"[\d:：.\-\s]+", value):
                continue
            if re.search(r"\u7b2c\s*\d+\s*\u96c6|\d+\s*\u96c6", value):
                continue
            return value
        return ""

    @staticmethod
    def _safe_text(value: Any) -> str:
        if value is None:
            return ""
        try:
            if callable(value):
                value = value()
        except Exception:
            return ""
        return str(value).strip()

    def _first_text(self, *values: Any) -> str:
        for value in values:
            text = self._safe_text(value)
            if text:
                return text
        return ""

    def _guess_emulator_name(self, serial: str, model: str, product: str, brand: str) -> str:
        text = " ".join([serial, model, product, brand]).lower()
        if serial.startswith("emulator-"):
            return "MuMu \u6a21\u62df\u5668"
        if re.match(r"^(?:192\.168\.|10\.|172\.(?:1[6-9]|2\d|3[0-1])\.)", serial):
            return "\u771f\u673a/\u7f51\u7edc ADB"
        if "mumu" in text or "netease" in text:
            return "MuMu \u6a21\u62df\u5668"
        if "leidian" in text or "ldplayer" in text:
            return "\u96f7\u7535\u6a21\u62df\u5668"
        if serial == "127.0.0.1:5555":
            return "\u96f7\u7535\u6a21\u62df\u5668"
        if "sdk_gphone" in text:
            return "Android Emulator"
        if "7555" in serial:
            return "\u6a21\u62df\u5668(7555)"
        if "5555" in serial:
            return "\u6a21\u62df\u5668(5555)"
        return "\u672a\u8bc6\u522b\u6a21\u62df\u5668"

    def _close_popups(self) -> None:
        for _ in range(3):
            clicked = False
            for text in ["关闭", "跳过", "取消", "以后再说", "我知道了", "同意"]:
                el = self.d(textContains=text)
                if self._exists(el, 0.5):
                    el.click()
                    time.sleep(1)
                    clicked = True
                    break
            if not clicked:
                break

    def _wait_app_ready(self, timeout: float = 30) -> bool:
        deadline = time.time() + timeout
        ready_markers = [
            "首页",
            "剧场",
            "我的",
            "全屏观看",
            "合集",
            "搜索",
            "红果号",
        ]
        while time.time() < deadline:
            try:
                current = self.d.app_current()
                xml = self._xml()
                if current.get("package") == APP_PACKAGE and any(text in xml for text in ready_markers):
                    return True
            except Exception:
                pass
            time.sleep(1)
        return False

    def _is_app_foreground(self) -> bool:
        try:
            current = self.d.app_current()
            return current.get("package") == APP_PACKAGE
        except Exception:
            return False

    def _start_app(self) -> None:
        try:
            self.d.app_start(APP_PACKAGE)
        except Exception:
            pass
        try:
            self.d.shell(f"am start -n {APP_PACKAGE}/com.dragon.read.pages.splash.SplashActivity")
        except Exception:
            pass

    def _stop_app(self) -> None:
        try:
            self.d.app_stop(APP_PACKAGE)
        except Exception:
            pass
        try:
            self.d.shell(f"am force-stop {APP_PACKAGE}")
        except Exception:
            pass

    def _open_theater(self) -> None:
        for _ in range(3):
            xml = self._xml()
            if any(text in xml for text in ["首页", "剧场", "我的"]):
                break
            self.d.press("back")
            time.sleep(1)
        theater = self.d(text="剧场")
        if self._exists(theater, 1):
            theater.click()
        else:
            self.d.click(int(self.width * 0.3), int(self.height * 0.965))
        time.sleep(2)
        self._close_popups()

    def _open_search(self) -> bool:
        selectors = (
            self.d(resourceId="com.phoenix.read:id/hds"),
            self.d(textContains="搜索"),
            self.d(descriptionContains="搜索"),
        )
        for selector in selectors:
            if self._exists(selector, 1):
                selector.click()
                return True
        self.d.click(int(self.width * 0.35), int(self.height * 0.04))
        time.sleep(1)
        return self._exists(self.d(className="android.widget.EditText"), 2)

    def _click_first_search_suggestion(self) -> bool:
        xml = self._xml()
        if "即将上线" not in xml and "万热度" not in xml and "播放" not in xml:
            return False
        # The first playable suggestion sits below the search bar. Avoid the second row, which
        # often represents a reserved/upcoming season.
        self.d.click(int(self.width * 0.38), int(self.height * 0.105))
        time.sleep(1)
        return True

    def _current_playing_title(self) -> str:
        xml = self._xml()
        for pattern in [
            r"合集 · ([^·\n<\"]+) ·",
            r"第\d+集 \| ([^<\"]+)",
        ]:
            match = re.search(pattern, xml)
            if match:
                return match.group(1).strip("《》 ")
        return ""

    def _click_first_play_button(self) -> bool:
        for text in ["立即观看", "开始播放", "播放全部", "观看", "看全集"]:
            el = self.d(textContains=text)
            if self._exists(el, 2):
                el.click()
                return True
        return False

    def _click_episode_number(self, episode_number: int) -> bool:
        current_episode = self.get_current_episode()
        self._click_episode_range_tab(episode_number)
        for _ in range(5):
            for els in (
                self.d(text=str(episode_number)),
                self.d(text=f"第{episode_number}集"),
                self.d(textContains=f"第{episode_number}集"),
            ):
                if self._exists(els, 1):
                    try:
                        count = els.count
                        for i in range(count):
                            info = els[i].info
                            y = info.get("bounds", {}).get("top", 0)
                            if y > self.height * 0.25:
                                els[i].click()
                                return True
                    except Exception:
                        els.click()
                        return True
            if current_episode and current_episode > episode_number:
                self._swipe_down(0.35)
            else:
                self._swipe_up(0.35)
            time.sleep(1)
        return False

    def _episode_range_label(self, episode_number: int, page_size: int = 30) -> Optional[str]:
        if episode_number <= 0 or page_size <= 0:
            return None
        start = ((episode_number - 1) // page_size) * page_size + 1
        end = start + page_size - 1
        return f"{start}-{end}"

    def _click_episode_range_tab(self, episode_number: int) -> bool:
        label = self._episode_range_label(episode_number)
        if not label:
            return False
        for selector in (self.d(text=label), self.d(textContains=label)):
            if self._exists(selector, 1):
                try:
                    selector.click()
                    self._sleep(0.8, 1.3)
                    return True
                except Exception:
                    continue
        xml = self._xml()
        escaped = re.escape(label)
        for pattern in (
            rf'text="{escaped}"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
            rf'content-desc="{escaped}"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
        ):
            match = re.search(pattern, xml)
            if not match:
                continue
            left, top, right, bottom = (int(value) for value in match.groups())
            self.d.click((left + right) // 2, (top + bottom) // 2)
            self._sleep(0.8, 1.3)
            return True
        return False

    def _extract_episode_numbers(self, xml: str) -> List[int]:
        numbers: List[int] = []
        seen: set[int] = set()
        for pattern in (
            r"\u7b2c\s*(\d{1,4})\s*\u96c6",
            r"(?:\u5168|\u66f4\u65b0\u81f3|\u5df2\u66f4\u65b0\u81f3)\s*(\d{1,4})\s*\u96c6",
        ):
            for value in re.findall(pattern, xml):
                try:
                    episode = int(value)
                except (TypeError, ValueError):
                    continue
                if episode <= 0 or episode in seen:
                    continue
                seen.add(episode)
                numbers.append(episode)
        return numbers

    def _extract_drama_titles(self) -> List[str]:
        titles = []
        seen = set()
        xml = self._xml()
        for text in re.findall(r'resource-id="com\.phoenix\.read:id/title"[^>]*text="([^"]+)"', xml):
            if self._is_title_candidate(text) and text not in seen:
                titles.append(text)
                seen.add(text)
        for text in re.findall(r'text="([^"]{2,30})"', xml):
            if self._is_title_candidate(text) and text not in seen:
                titles.append(text)
                seen.add(text)
        return titles

    def _extract_detail_title(self) -> str:
        xml = self._xml()
        current_title = self._current_playing_title()
        if current_title:
            return current_title
        for pattern in [
            r'text="([^"]{4,25})"[^>]*bounds="\[24,\d+\]\[\d+,\d+\]"',
            r'text="([^"]{4,25})"',
        ]:
            for candidate in re.findall(pattern, xml):
                if self._is_title_candidate(candidate):
                    return candidate
        return ""

    def _is_title_candidate(self, text: str) -> bool:
        text = text.strip()
        if len(text) < 2:
            return False
        if re.fullmatch(r"\d{1,2}:\d{2}", text):
            return False
        if re.fullmatch(r"[\d\s:：/\\.-]+", text):
            return False
        skip_words = {
            "搜索",
            "综合",
            "漫剧",
            "社区",
            "影视",
            "小说",
            "听书",
            "用户",
            "热度",
            "收藏",
            "全屏",
            "倍速",
            "选集",
            "已完结",
            "作者声明",
            "播放",
            "观看",
        }
        if any(word in text for word in skip_words):
            return False
        if any(word in text for word in TAG_KEYWORDS) and len(text) <= 8:
            return False
        if re.fullmatch(r"[\d.万亿共集热度]+", text):
            return False
        return True

    def _comment_panel_open(self) -> bool:
        xml = self._xml()
        return any(text in xml for text in ["有趣评论", "说点什么", "条评论", "写评论"])

    def _close_comment_panel(self) -> bool:
        closed = False
        for _ in range(3):
            if not self._comment_panel_open():
                return closed
            self.d.press("back")
            closed = True
            time.sleep(1)
        return closed

    def _focus_comment_input(self) -> bool:
        for hint in ["有趣评论千千万", "说点什么", "写评论", "发条友善"]:
            el = self.d(textContains=hint)
            if self._exists(el, 2):
                el.click()
                return True
        inp = self.d(className="android.widget.EditText")
        if self._exists(inp, 2):
            inp.click()
            return True
        return False

    def _clear_input(self, inp: Any) -> None:
        try:
            inp.clear_text()
        except Exception:
            try:
                self.d.clear_text()
            except Exception:
                pass

    def _type_text(self, text: str) -> None:
        try:
            self.d.clear_text()
        except Exception:
            pass
        for char in text:
            self.d.send_keys(char)
            time.sleep(random.uniform(0.02, 0.08))

    def _exists(self, el: Any, timeout: float = 3) -> bool:
        try:
            return bool(el.exists(timeout=timeout))
        except TypeError:
            start = time.time()
            while time.time() - start < timeout:
                try:
                    if el.exists:
                        return True
                except Exception:
                    return False
                time.sleep(0.2)
            return False
        except Exception:
            return False

    def _xml(self) -> str:
        try:
            return self.d.dump_hierarchy()
        except Exception:
            return ""

    def _sleep(self, lo: float, hi: float) -> None:
        time.sleep(random.uniform(lo, hi))

    def _swipe_up(self, distance: float = 0.5) -> None:
        cx = self.width // 2 + random.randint(-30, 30)
        start_y = int(self.height * 0.65)
        end_y = max(50, int(start_y - self.height * distance))
        self.d.swipe(cx, start_y, cx + random.randint(-10, 10), end_y, duration=0.4)

    def _swipe_down(self, distance: float = 0.5) -> None:
        cx = self.width // 2 + random.randint(-30, 30)
        start_y = int(self.height * 0.35)
        end_y = min(self.height - 50, int(start_y + self.height * distance))
        self.d.swipe(cx, start_y, cx + random.randint(-10, 10), end_y, duration=0.4)
