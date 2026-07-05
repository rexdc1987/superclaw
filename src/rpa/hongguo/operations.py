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
SHORT_SERIES_ACTIVITY = "com.dragon.read.component.shortvideo.impl.ShortSeriesActivity"
COMMENT_BUTTON_ID = "com.phoenix.read:id/cdi"
PLAYBACK_SPEED_OPTIONS = ("0.75x", "1.0x", "1.25x", "1.5x", "2.0x", "3.0x")
AD_CONTINUE_PROMPT_MARKERS = (
    "上滑继续观看短剧",
    "上滑继续看短剧",
    "上滑继续观看",
    "上滑继续看",
    "滑动继续观看短剧",
    "滑动继续看短剧",
    "滑动继续观看",
    "滑动继续看",
)
AD_PAGE_MARKERS = (
    "广告",
    "免费演示",
    "点击进入直播间",
    "直播中",
    "讲解中",
    "优选服务",
    "Kuaizi",
    "筷子科技",
    "降低剪辑成本",
    "短视频商家",
    "官方正规接口",
    "私域",
    "矩阵账号",
    "高效管理",
)
AD_SWIPE_CONTEXT_MARKERS = ("上滑", "滑动", "继续观看", "继续看", "短剧")
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

    def bring_to_foreground(self) -> bool:
        try:
            self._start_app()
            time.sleep(1.5)
            self._close_popups()
            return self._is_app_foreground() or self._wait_app_ready(5)
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
            opened = self.open_search_page(keyword)
            if not opened.get("success"):
                return {"success": False, "keyword": keyword, "titles": [], **opened}
            if opened.get("already_on_target"):
                return {
                    "success": True,
                    "keyword": keyword,
                    "titles": opened.get("titles") or [],
                    "message": opened.get("message") or "已在目标短剧页面",
                }
            input_result = self.input_search_keyword(keyword)
            if not input_result.get("success"):
                return {
                    "success": False,
                    "keyword": keyword,
                    "titles": [],
                    "input_text": input_result.get("input_text") or "",
                    "message": input_result.get("message") or "搜索框关键词不一致",
                }
            submit_result = self.submit_search(keyword)
            return {
                "success": bool(submit_result.get("success")),
                "keyword": keyword,
                "input_text": input_result.get("input_text") or "",
                "submit": submit_result.get("submit") or {},
                "titles": submit_result.get("titles") or [],
                "message": submit_result.get("message") or "搜索完成",
            }
        except Exception as exc:
            return {"success": False, "keyword": keyword, "titles": [], "message": str(exc)}

    def open_search_page(self, keyword: str = "") -> Dict[str, Any]:
        try:
            self._close_popups()
            if not self._is_app_foreground():
                return {"success": False, "keyword": keyword, "titles": [], "message": "红果不在前台，取消搜索"}
            current_title = self._current_playing_title()
            if current_title and keyword and keyword in current_title:
                return {
                    "success": True,
                    "already_on_target": True,
                    "titles": [current_title],
                    "message": "已在目标短剧页面",
                }
            self._open_theater()
            if not self._open_search():
                return {"success": False, "keyword": keyword, "titles": [], "message": "未找到搜索入口"}
            self._sleep(1.5, 2.5)
            return {
                "success": True,
                "keyword": keyword,
                "input_visible": self._exists(self.d(className="android.widget.EditText"), 1),
                "message": "已进入搜索框",
            }
        except Exception as exc:
            return {"success": False, "keyword": keyword, "titles": [], "message": str(exc)}

    def input_search_keyword(self, keyword: str) -> Dict[str, Any]:
        try:
            input_text = ""
            inp = self.d(className="android.widget.EditText")
            if self._exists(inp, 3):
                input_result = self._set_input_text(inp, keyword)
                input_text = str(input_result.get("actual_text") or "")
                if not input_result.get("success"):
                    return {
                        "success": False,
                        "keyword": keyword,
                        "input_text": input_text,
                        "message": f"搜索框关键词不一致: 期望 {keyword}，实际 {input_text or '空'}",
                    }
            else:
                self._type_text(keyword)
                input_text = keyword
            self._sleep(0.8, 1.5)
            return {"success": True, "keyword": keyword, "input_text": input_text, "message": "关键词已填入"}
        except Exception as exc:
            return {"success": False, "keyword": keyword, "input_text": "", "message": str(exc)}

    def submit_search(self, keyword: str) -> Dict[str, Any]:
        try:
            submit = self._submit_search(keyword)
            if not submit.get("success"):
                return {
                    "success": False,
                    "keyword": keyword,
                    "titles": [],
                    "submit": submit,
                    "message": submit.get("message") or "搜索未进入结果页",
                }
            titles = self._extract_drama_titles()
            message = submit.get("message") or "搜索完成"
            if not submit.get("candidate_visible"):
                message = "搜索完成" if titles else "未找到有效短剧标题"
            return {
                "success": bool(titles),
                "keyword": keyword,
                "submit": submit,
                "titles": titles,
                "message": message,
            }
        except Exception as exc:
            return {"success": False, "keyword": keyword, "titles": [], "message": str(exc)}

    def find_drama(self, keyword: str) -> Dict[str, Any]:
        search = self.search_drama(keyword)
        titles = search.get("titles") or []
        if not search.get("success"):
            return {
                "success": False,
                "keyword": keyword,
                "titles": titles,
                "search": search,
                "message": search.get("message") or "搜索短剧失败",
            }

        selected_title = self._choose_title(keyword, titles)
        if not selected_title:
            return {
                "success": False,
                "keyword": keyword,
                "titles": titles,
                "search": search,
                "message": "没有匹配任务短剧名称的搜索结果",
            }

        selected = self.select_drama(selected_title, keyword=keyword)
        success = bool(selected.get("success") and selected.get("playable"))
        if success:
            message = selected.get("message") or "已进入短剧详情"
        elif selected.get("message"):
            message = selected.get("message")
        elif selected.get("success") and not selected.get("playable"):
            message = "短剧不可播放: 未看到播放入口"
        else:
            message = "选择短剧失败"
        return {
            "success": success,
            "keyword": keyword,
            "titles": titles,
            "search": search,
            "selected_title": selected_title,
            "selected": selected,
            "drama_title": selected.get("drama_title") or selected_title,
            "playable": bool(selected.get("playable")),
            "message": message,
        }

    def select_drama(self, title: str, keyword: str = "") -> Dict[str, Any]:
        try:
            if not self._is_app_foreground():
                return {"success": False, "drama_title": title, "playable": False, "message": "红果不在前台，取消选择短剧"}
            current_title = self._current_playing_title()
            expected = keyword or title
            if current_title and self._title_matches(expected, current_title):
                return {"success": True, "drama_title": current_title, "playable": True}
            detail_title = self._extract_detail_title(expected)
            if detail_title and self._title_matches(expected, detail_title) and self._detail_markers_visible():
                return self._drama_detail_result(detail_title, expected)
            clicked = False
            if title:
                clicked = self._click_matching_title(title, expected)
                for selector in (self.d(text=title), self.d(textContains=title)):
                    if clicked:
                        break
                    if self._exists(selector, 2):
                        selector.click()
                        clicked = True
                        break
            if not clicked:
                return {"success": False, "drama_title": title, "playable": False, "message": f"未找到可点击的匹配短剧: {title}"}
            self._sleep(3, 5)
            if not self._is_app_foreground():
                return {"success": False, "drama_title": title, "playable": False, "message": "选择后离开红果 App，已取消"}
            drama_title = self._extract_detail_title(expected) or title
            if expected and not self._title_matches(expected, drama_title):
                return {
                    "success": False,
                    "drama_title": drama_title,
                    "playable": False,
                    "message": f"进入的短剧不匹配: 期望 {expected}，实际 {drama_title}",
                }
            return self._drama_detail_result(drama_title, expected)
        except Exception as exc:
            return {"success": False, "drama_title": title, "playable": False, "message": str(exc)}

    def _drama_detail_result(self, drama_title: str, expected: str = "") -> Dict[str, Any]:
        xml = " ".join(self._hongguo_nodes(self._xml()))
        playable = any(
            text in xml
            for text in ["观看", "播放", "看全集", "立即观看", "开始播放", "全屏观看", "合集", "选集"]
        )
        if not playable and re.search(r"第\d+集", xml) and re.search(r"全\d+集", xml):
            playable = True
        if not playable and drama_title and re.search(r"第\d+集", xml):
            current = self._safe_app_current()
            playable = current.get("activity") == SHORT_SERIES_ACTIVITY
        detail_visible = bool(drama_title and re.search(r"全\d+集", xml))
        return {
            "success": bool(playable or detail_visible),
            "drama_title": drama_title,
            "playable": playable,
            "detail_visible": detail_visible,
            "message": "已进入短剧详情" if (playable or detail_visible) else "短剧不可播放",
        }

    def _detail_markers_visible(self) -> bool:
        xml = " ".join(self._hongguo_nodes(self._xml()))
        return bool(re.search(r"全\d+集|第\d+集", xml) or any(marker in xml for marker in ("剧情简介", "剧评", "选集")))

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

    def is_playback_paused(self) -> bool:
        if not self._short_series_activity_active():
            return False
        return self._center_play_overlay_visible()

    def pause_playback_if_playing(self) -> bool:
        if not self._short_series_activity_active():
            return False
        if self.is_playback_paused():
            return True
        self.d.click(int(self.width * 0.5), int(self.height * 0.42))
        time.sleep(0.8)
        return self.is_playback_paused()

    def resume_playback_safely(self) -> bool:
        if not self._short_series_activity_active():
            return False
        if self.skip_ad_if_present():
            return True
        try:
            self.d.shell("input keyevent 126")
            time.sleep(1)
        except Exception:
            pass
        if self._center_play_overlay_visible():
            try:
                self.d.click(int(self.width * 0.5), int(self.height * 0.42))
                time.sleep(1)
                return True
            except Exception:
                return False
        return True

    def resume_playback_if_paused(self, allow_center_fallback: bool = False) -> bool:
        if self.skip_ad_if_present():
            return True
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
                    return not self.is_playback_paused()
                except Exception:
                    continue
        if self._click_play_overlay():
            time.sleep(1)
            return not self.is_playback_paused()
        if allow_center_fallback:
            self.d.click(int(self.width * 0.5), int(self.height * 0.42))
            time.sleep(1)
            return not self.is_playback_paused()
        return False

    def _click_play_overlay(self) -> bool:
        xml = self._xml()
        overlay_bounds: List[tuple[int, int, int, int]] = []
        for node in self._hongguo_nodes(xml):
            if 'clickable="true"' not in node:
                continue
            bounds_match = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', node)
            if not bounds_match:
                continue
            left, top, right, bottom = (int(value) for value in bounds_match.groups())
            width = right - left
            height = bottom - top
            center_x = (left + right) // 2
            center_y = (top + bottom) // 2
            if width < 40 or height < 40:
                continue
            if abs(center_x - self.width // 2) <= self.width * 0.18 and self.height * 0.28 <= center_y <= self.height * 0.58:
                overlay_bounds.append((left, top, right, bottom))
        if not overlay_bounds:
            return False
        overlay_bounds.sort(key=lambda item: (item[2] - item[0]) * (item[3] - item[1]))
        left, top, right, bottom = overlay_bounds[0]
        self.d.click((left + right) // 2, (top + bottom) // 2)
        return True

    def skip_ad_if_present(self, attempts: int = 2) -> bool:
        if not self._ad_continue_visible():
            return False
        for _ in range(max(1, attempts)):
            self._swipe_up_continue_ad()
            time.sleep(1.2)
            if not self._ad_continue_visible():
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
        if not self._is_app_foreground():
            return 0

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
        if len(numbers) == 1 and self._episode_number_context_visible(xml):
            return numbers[0]
        return 0

    def get_total_episodes(self) -> int:
        if not self._is_app_foreground():
            return 0

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
        if self._ad_continue_visible(xml):
            return True
        if COMMENT_BUTTON_ID in xml:
            return True
        if self._short_series_activity_active():
            return True
        markers = (
            "\u5168\u5c4f\u89c2\u770b",
            "\u9009\u96c6",
            "\u5408\u96c6",
            "\u500d\u901f",
            "\u6709\u8da3\u8bc4\u8bba",
            "\u8bf4\u70b9\u4ec0\u4e48",
        )
        if any(marker in xml for marker in markers):
            return True
        return self._center_play_overlay_visible(xml)

    def _episode_number_context_visible(self, xml: Optional[str] = None) -> bool:
        xml = xml or self._xml()
        if not xml:
            return False
        if COMMENT_BUTTON_ID in xml:
            return True
        if self._short_series_activity_active():
            return True
        markers = (
            "\u5168\u5c4f\u89c2\u770b",
            "\u9009\u96c6",
            "\u5408\u96c6",
            "\u500d\u901f",
            "\u6709\u8da3\u8bc4\u8bba",
            "\u8bf4\u70b9\u4ec0\u4e48",
        )
        return any(marker in xml for marker in markers)

    def _center_play_overlay_visible(self, xml: Optional[str] = None) -> bool:
        xml = xml or self._xml()
        candidate_bounds: List[tuple[int, int, int, int]] = []
        for node in self._hongguo_nodes(xml):
            if 'clickable="true"' not in node:
                continue
            bounds_match = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', node)
            if not bounds_match:
                continue
            left, top, right, bottom = (int(value) for value in bounds_match.groups())
            width = right - left
            height = bottom - top
            center_x = (left + right) // 2
            center_y = (top + bottom) // 2
            if width < 40 or height < 40:
                continue
            if abs(center_x - self.width // 2) <= self.width * 0.18 and self.height * 0.28 <= center_y <= self.height * 0.58:
                candidate_bounds.append((left, top, right, bottom))
        if not candidate_bounds:
            return False
        candidate_bounds.sort(key=lambda item: abs(((item[0] + item[2]) // 2) - self.width // 2))
        return self._center_play_icon_visible_by_screenshot(candidate_bounds[0])

    def _center_play_icon_visible_by_screenshot(self, bounds: tuple[int, int, int, int]) -> bool:
        try:
            image = self.d.screenshot().convert("RGB")
        except Exception:
            return False
        left, top, right, bottom = bounds
        pad_x = max(8, int((right - left) * 0.15))
        pad_y = max(8, int((bottom - top) * 0.15))
        crop = image.crop(
            (
                max(0, left - pad_x),
                max(0, top - pad_y),
                min(self.width, right + pad_x),
                min(self.height, bottom + pad_y),
            )
        )
        white_pixels = 0
        for red, green, blue in crop.getdata():
            if red >= 235 and green >= 235 and blue >= 235:
                white_pixels += 1
        return white_pixels >= 900

    def _ad_continue_visible(self, xml: Optional[str] = None) -> bool:
        text = html.unescape(xml or self._xml())
        normal_episode_visible = bool(
            re.search(r"\u7b2c\s*\d{1,4}\s*\u96c6", text)
            or COMMENT_BUTTON_ID in text
            or "选集" in text
            or "倍速" in text
            or "说点什么" in text
        )
        if normal_episode_visible:
            return False
        if any(marker in text for marker in AD_CONTINUE_PROMPT_MARKERS):
            return True
        if self._short_series_activity_active() and any(marker in text for marker in AD_PAGE_MARKERS):
            return True
        has_swipe_hint = any(marker in text for marker in ("上滑", "滑动"))
        has_continue_hint = any(marker in text for marker in ("继续观看", "继续看"))
        return has_swipe_hint and has_continue_hint and "短剧" in text

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
        if not self._short_series_activity_active():
            return exited
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
            search_key = content[:8] if len(content) > 8 else content
            for _ in range(3):
                if self._exists(self.d(textContains=search_key), 2) or search_key in self._xml():
                    if screenshot_dir:
                        screenshot_path = self.take_screenshot(
                            f"ep{episode_number or 'x'}_comment_list_verified",
                            screenshot_dir,
                        )
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
                app_visible = self._first_visible_package(xml) == APP_PACKAGE or self._has_large_hongguo_window(xml)
                if current.get("package") == APP_PACKAGE and app_visible and any(text in xml for text in ready_markers):
                    return True
            except Exception:
                pass
            time.sleep(1)
        return False

    def _is_app_foreground(self) -> bool:
        try:
            current = self.d.app_current()
            if current.get("package") != APP_PACKAGE:
                return False
            xml = self._xml()
            first_package = self._first_visible_package(xml)
            if first_package == APP_PACKAGE:
                return True
            if self._has_large_hongguo_window(xml):
                return True
            if first_package and first_package != APP_PACKAGE:
                return False
            return self._has_hongguo_business_nodes(xml) and self._hongguo_visible_area_ratio(xml) >= 0.2
        except Exception:
            return False

    def _safe_app_current(self) -> Dict[str, Any]:
        try:
            return self.d.app_current() or {}
        except Exception:
            return {}

    def _short_series_activity_active(self) -> bool:
        current = self._safe_app_current()
        return current.get("package") == APP_PACKAGE and current.get("activity") == SHORT_SERIES_ACTIVITY

    def _first_visible_package(self, xml: str) -> str:
        for node in re.findall(r"<node\b[^>]+>", xml or ""):
            if 'visible-to-user="false"' in node:
                continue
            package_match = re.search(r'package="([^"]+)"', node)
            if package_match:
                return package_match.group(1)
        return ""

    def _node_bounds(self, node: str) -> Optional[tuple[int, int, int, int]]:
        match = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', node)
        if not match:
            return None
        left, top, right, bottom = (int(value) for value in match.groups())
        if right <= left or bottom <= top:
            return None
        return left, top, right, bottom

    def _has_large_hongguo_window(self, xml: str) -> bool:
        screen_area = max(1, self.width * self.height)
        for node in self._hongguo_nodes(xml):
            bounds = self._node_bounds(node)
            if not bounds:
                continue
            left, top, right, bottom = bounds
            node_width = right - left
            node_height = bottom - top
            area_ratio = (node_width * node_height) / screen_area
            if node_width >= self.width * 0.55 and node_height >= self.height * 0.25 and area_ratio >= 0.18:
                return True
            if left <= self.width * 0.08 and right >= self.width * 0.92 and node_height >= self.height * 0.45:
                return True
        return False

    def _launcher_visible(self, xml: str) -> bool:
        launcher_packages = ("app.lawnchair", "com.android.launcher", "com.android.launcher3")
        screen_area = max(1, self.width * self.height)
        for node in re.findall(r"<node\b[^>]+>", xml or ""):
            package_match = re.search(r'package="([^"]+)"', node)
            if not package_match or package_match.group(1) not in launcher_packages:
                continue
            bounds = self._node_bounds(node)
            if not bounds:
                continue
            left, top, right, bottom = bounds
            if ((right - left) * (bottom - top)) / screen_area >= 0.5:
                return True
        return False

    def _hongguo_visible_area_ratio(self, xml: str) -> float:
        max_area = 0
        for node in self._hongguo_nodes(xml):
            bounds = self._node_bounds(node)
            if not bounds:
                continue
            left, top, right, bottom = bounds
            max_area = max(max_area, (right - left) * (bottom - top))
        return max_area / max(1, self.width * self.height)

    def _has_hongguo_business_nodes(self, xml: str) -> bool:
        nodes = self._hongguo_nodes(xml)
        if len(nodes) < 3:
            return False
        text = " ".join(nodes)
        return any(marker in text for marker in ("搜索", "选集", "全", "第", "播放", "热度", "剧评", "简介", "关注"))

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
        for _ in range(8):
            clipped_target_visible = False
            for els in (
                self.d(text=str(episode_number)),
                self.d(text=f"第{episode_number}集"),
                self.d(textContains=f"第{episode_number}集"),
                self.d(description=str(episode_number)),
                self.d(description=f"第{episode_number}集"),
                self.d(descriptionContains=f"第{episode_number}集"),
            ):
                if self._exists(els, 1):
                    try:
                        count = els.count
                        for i in range(count):
                            info = els[i].info
                            bounds = info.get("bounds", {}) or {}
                            top = int(bounds.get("top", 0) or 0)
                            bottom = int(bounds.get("bottom", 0) or 0)
                            if bottom and bottom >= self.height * 0.94:
                                clipped_target_visible = True
                                continue
                            if top > self.height * 0.12:
                                els[i].click()
                                return True
                    except Exception:
                        els.click()
                        return True
            if clipped_target_visible:
                self._swipe_up(0.25)
                time.sleep(0.8)
                continue
            xml_click = self._click_episode_number_from_xml(episode_number)
            if xml_click is True:
                return True
            if xml_click is False:
                time.sleep(0.8)
                continue
            if current_episode and current_episode > episode_number:
                self._swipe_down(0.35)
            else:
                self._swipe_up(0.35)
            time.sleep(1)
        return False

    def _click_episode_number_from_xml(self, episode_number: int) -> Optional[bool]:
        labels = {str(episode_number), f"第{episode_number}集"}
        xml = self._xml()
        candidates: List[tuple[int, int, int, int]] = []
        clipped_candidates: List[tuple[int, int, int, int]] = []
        for node in self._hongguo_nodes(xml):
            node_labels = [
                html.unescape(value).strip()
                for value in re.findall(r'(?:text|content-desc)="([^"]*)"', node)
            ]
            if not node_labels:
                continue
            if not any(label in labels for label in node_labels):
                continue
            bounds = self._node_bounds(node)
            if not bounds:
                continue
            left, top, right, bottom = bounds
            if bottom <= self.height * 0.12:
                continue
            if bottom >= self.height * 0.94:
                clipped_candidates.append((left, top, right, bottom))
                continue
            candidates.append((left, top, right, bottom))
        if not candidates and clipped_candidates:
            self._swipe_up(0.25)
            return False
        if not candidates:
            return None
        candidates.sort(key=lambda item: (item[1], item[0]))
        left, top, right, bottom = candidates[0]
        self.d.click((left + right) // 2, (top + bottom) // 2)
        return True

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

    def _extract_episode_numbers(self, xml: str, include_totals: bool = False) -> List[int]:
        numbers: List[int] = []
        seen: set[int] = set()
        patterns = [r"\u7b2c\s*(\d{1,4})\s*\u96c6"]
        if include_totals:
            patterns.append(r"(?:\u5168|\u66f4\u65b0\u81f3|\u5df2\u66f4\u65b0\u81f3)\s*(\d{1,4})\s*\u96c6")

        for pattern in patterns:
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
        return self._extract_drama_titles_from_xml(self._xml())

    def _extract_drama_titles_from_xml(self, xml: str) -> List[str]:
        titles = []
        seen = set()
        hongguo_nodes = self._hongguo_nodes(xml)
        for node in hongguo_nodes:
            if 'resource-id="com.phoenix.read:id/title"' not in node:
                continue
            text_match = re.search(r'text="([^"]+)"', node)
            if not text_match:
                continue
            text = html.unescape(text_match.group(1)).strip()
            if self._is_title_candidate(text) and text not in seen:
                titles.append(text)
                seen.add(text)
        for node in hongguo_nodes:
            text_match = re.search(r'text="([^"]{2,30})"', node)
            if not text_match:
                continue
            text = html.unescape(text_match.group(1)).strip()
            if self._is_title_candidate(text) and text not in seen:
                titles.append(text)
                seen.add(text)
        return titles

    def _hongguo_nodes(self, xml: str) -> List[str]:
        return [node for node in re.findall(r"<node\b[^>]+>", xml or "") if f'package="{APP_PACKAGE}"' in node]

    def _click_matching_title(self, title: str, expected: str = "") -> bool:
        target = str(title or "").strip("《》 ")
        if not target:
            return False
        xml = self._xml()
        matches: List[tuple[int, int, int, int, str]] = []
        for node in re.findall(r"<node\b[^>]+>", xml):
            if 'package="com.phoenix.read"' not in node:
                continue
            text_match = re.search(r'text="([^"]*)"', node)
            bounds_match = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', node)
            if not text_match or not bounds_match:
                continue
            node_text = html.unescape(text_match.group(1)).strip()
            if not node_text:
                continue
            if node_text != target and target not in node_text and not self._title_matches(expected or target, node_text):
                continue
            left, top, right, bottom = (int(value) for value in bounds_match.groups())
            if bottom <= self.height * 0.08:
                continue
            matches.append((left, top, right, bottom, node_text))
        if not matches:
            return False
        expected_key = self._normalize_title_key(expected or target)
        matches.sort(
            key=lambda item: (
                self._normalize_title_key(item[4]) != self._normalize_title_key(target),
                not self._normalize_title_key(item[4]).startswith(expected_key),
                item[1],
            )
        )
        left, top, right, bottom, _ = matches[0]
        x = max((left + right) // 2, int(self.width * 0.24))
        y = (top + bottom) // 2
        self.d.click(x, y)
        return True

    def _extract_detail_title(self, expected: str = "") -> str:
        xml = self._xml()
        current_title = self._current_playing_title()
        if current_title:
            return current_title
        candidates: List[str] = []
        seen = set()
        node_text = " ".join(self._hongguo_nodes(xml))
        for pattern in [
            r'text="([^"]{4,25})"[^>]*bounds="\[24,\d+\]\[\d+,\d+\]"',
            r'text="([^"]{4,25})"',
        ]:
            for candidate in re.findall(pattern, node_text):
                candidate = html.unescape(candidate).strip()
                if self._is_title_candidate(candidate) and candidate not in seen:
                    candidates.append(candidate)
                    seen.add(candidate)
        if expected:
            for candidate in candidates:
                if self._title_matches(expected, candidate):
                    return candidate
            return ""
        return candidates[0] if candidates else ""

    def _choose_title(self, keyword: str, titles: List[str]) -> str:
        matches = [title for title in titles if self._title_matches(keyword, title)]
        if not matches:
            return ""
        keyword_key = self._normalize_title_key(keyword)
        extended = [
            title
            for title in matches
            if self._normalize_title_key(title).startswith(keyword_key)
            and self._normalize_title_key(title) != keyword_key
            and self._looks_like_specific_title(title)
        ]
        if extended:
            return max(extended, key=lambda value: len(self._normalize_title_key(value)))
        for title in matches:
            if self._normalize_title_key(title) == keyword_key:
                return title
        return matches[0]

    def _looks_like_specific_title(self, title: str) -> bool:
        text = str(title or "").strip()
        if not self._is_title_candidate(text):
            return False
        if self._looks_like_non_drama_result(text):
            return False
        if re.fullmatch(r"[\d.]+分", text):
            return False
        if any(word in text for word in TAG_KEYWORDS) and len(text) <= 8:
            return False
        return len(self._normalize_title_key(text)) >= 4

    def _choose_first_matching_title(self, keyword: str, titles: List[str]) -> str:
        for title in titles:
            if self._title_matches(keyword, title):
                return title
        return ""

    def _title_matches(self, keyword: str, title: str) -> bool:
        if self._looks_like_non_drama_result(title):
            return False
        keyword_key = self._normalize_title_key(keyword)
        title_key = self._normalize_title_key(title)
        if not keyword_key or not title_key:
            return False
        if keyword_key == title_key:
            return True
        if title_key.startswith(keyword_key):
            if keyword_key[-1:].isdigit() and title_key[len(keyword_key) : len(keyword_key) + 1].isdigit():
                return False
            return True
        season = self._season_marker(keyword_key)
        if season and self._season_marker(title_key) != season:
            return False
        if self._has_variant_marker(keyword_key) and not self._has_variant_marker(title_key):
            return False
        return title_key in keyword_key and len(title_key) >= 4

    def _normalize_title_key(self, value: str) -> str:
        return re.sub(r"[\s《》<>:：·,，。.!！?？\-_/\\]+", "", str(value or "").lower())

    def _looks_like_non_drama_result(self, text: str) -> bool:
        text = html.unescape(str(text or "")).strip()
        if len(text) > 32:
            return True
        if "#" in text:
            return True
        non_drama_markers = (
            "水墨山海",
            "共庆半周年",
            "官方正规接口",
            "矩阵账号",
            "免费演示",
            "点击进入直播间",
            "Kuaizi",
            "筷子科技",
            "视频神器",
        )
        return any(marker in text for marker in non_drama_markers)

    def _season_marker(self, value: str) -> str:
        match = re.search(r"第([一二三四五六七八九十\d]+)季", value)
        return match.group(1) if match else ""

    def _has_variant_marker(self, value: str) -> bool:
        return bool(re.search(r"\d+|第[一二三四五六七八九十\d]+[季部篇]|[上下续前后]篇", value))

    def _is_title_candidate(self, text: str) -> bool:
        text = html.unescape(str(text or "")).strip()
        if len(text) < 2:
            return False
        if re.fullmatch(r"\d{1,2}:\d{2}", text):
            return False
        if re.fullmatch(r"\d+(?:\.\d+)?分", text):
            return False
        if re.fullmatch(r"(?:全|共|更新至|已更新至)?\s*\d{1,4}\s*集", text):
            return False
        if re.fullmatch(r"\d+(?:\.\d+)?(?:万|亿)?(?:热度|播放|人在看|人气)?", text):
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

    def _set_input_text(self, inp: Any, text: str) -> Dict[str, Any]:
        value = str(text or "")
        try:
            inp.click()
        except Exception:
            pass
        time.sleep(0.3)
        for writer in ("set_text", "send_keys"):
            try:
                method = getattr(inp, writer)
            except Exception:
                method = None
            if callable(method):
                try:
                    method(value)
                    actual = self._read_input_text(inp)
                    if self._input_text_matches(value, actual):
                        return {"success": True, "actual_text": actual}
                except TypeError:
                    pass
                except Exception:
                    pass
        self._clear_input(inp)
        time.sleep(0.2)
        self._type_text(value)
        actual = self._read_input_text(inp)
        return {"success": self._input_text_matches(value, actual), "actual_text": actual}

    def _read_input_text(self, inp: Any) -> str:
        candidates = [inp]
        try:
            candidates.insert(0, self.d(className="android.widget.EditText"))
        except Exception:
            pass
        for candidate in candidates:
            try:
                info = getattr(candidate, "info", {}) or {}
                text = str(info.get("text") or "").strip()
                if text:
                    return text
            except Exception:
                pass
        xml = self._xml()
        match = re.search(r'class="android\.widget\.EditText"[^>]*text="([^"]*)"', xml)
        if match:
            return html.unescape(match.group(1)).strip()
        return ""

    def _input_text_matches(self, expected: str, actual: str) -> bool:
        if not expected:
            return True
        if not actual:
            return False
        return self._normalize_title_key(expected) == self._normalize_title_key(actual)

    def _submit_search(self, keyword: str) -> Dict[str, Any]:
        actions = []
        for action_name, action in (
            ("click_search_button", self._click_visible_search_button),
            ("tap_search_button", lambda: self.d.click(int(self.width * 0.93), int(self.height * 0.083))),
            ("press_enter", lambda: self.d.press("enter")),
            ("keyevent_enter", lambda: self.d.shell("input keyevent 66")),
            ("press_search", lambda: self.d.press("search")),
            ("keyevent_search", lambda: self.d.shell("input keyevent 84")),
            ("tap_search_icon", lambda: self.d.click(int(self.width * 0.9), int(self.height * 0.055))),
        ):
            try:
                action()
                actions.append(action_name)
                result = self._wait_search_results_page(keyword)
                if result.get("success"):
                    result["action"] = action_name
                    result["actions"] = actions
                    return result
                if result.get("app_foreground") is False:
                    result["action"] = action_name
                    result["actions"] = actions
                    return result
            except Exception:
                pass
        for action_name, selector in (
            ("click_text_search", self.d(text="搜索")),
            ("click_desc_search", self.d(descriptionContains="搜索")),
            ("click_search_resource", self.d(resourceId="com.phoenix.read:id/hds")),
        ):
            if self._exists(selector, 1):
                try:
                    selector.click()
                    actions.append(action_name)
                    result = self._wait_search_results_page(keyword)
                    if result.get("success"):
                        result["action"] = action_name
                        result["actions"] = actions
                        return result
                    if result.get("app_foreground") is False:
                        result["action"] = action_name
                        result["actions"] = actions
                        return result
                except Exception:
                    pass
        xml = self._xml()
        candidate_visible = self._candidate_results_visible(keyword, xml)
        return {
            "success": candidate_visible,
            "actions": actions,
            "app_foreground": self._is_app_foreground(),
            "tabs_visible": self._search_results_visible(xml),
            "candidate_visible": candidate_visible,
            "message": "已展示搜索候选结果，可直接进入目标剧集" if candidate_visible else "已填写关键词，但未进入搜索结果页",
        }

    def _wait_search_results_page(self, keyword: str, timeout: float = 6) -> Dict[str, Any]:
        deadline = time.time() + timeout
        last_xml = ""
        while time.time() < deadline:
            if not self._is_app_foreground():
                return {"success": False, "app_foreground": False, "message": "提交搜索后离开红果 App"}
            last_xml = self._xml()
            if self._search_results_visible(last_xml):
                return {"success": True, "app_foreground": True, "tabs_visible": True, "message": "已进入搜索结果页"}
            time.sleep(0.5)
        candidate_visible = self._candidate_results_visible(keyword, last_xml)
        return {
            "success": candidate_visible,
            "app_foreground": self._is_app_foreground(),
            "tabs_visible": self._search_results_visible(last_xml),
            "candidate_visible": candidate_visible,
            "message": "已展示搜索候选结果，可直接进入目标剧集" if candidate_visible else "提交搜索后未看到结果页 tabs",
        }

    def _search_results_visible(self, xml: str = "") -> bool:
        text = " ".join(self._hongguo_nodes(xml or self._xml()))
        tab_hits = sum(1 for marker in ("综合", "短剧", "影视", "用户") if marker in text)
        return tab_hits >= 2 and any(marker in text for marker in ("搜索", "剧场", "播放", "热度", "全部"))

    def _candidate_results_visible(self, keyword: str, xml: str = "") -> bool:
        if not keyword:
            return False
        text = xml or self._xml()
        if not self._is_app_foreground():
            return False
        return bool(self._choose_title(keyword, self._extract_drama_titles_from_xml(text)))

    def _click_visible_search_button(self) -> None:
        xml = self._xml()
        for node in re.findall(r"<node\b[^>]+>", xml):
            if 'package="com.phoenix.read"' not in node or 'text="搜索"' not in node:
                continue
            bounds_match = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', node)
            if not bounds_match:
                continue
            left, top, right, bottom = (int(value) for value in bounds_match.groups())
            if left < self.width * 0.65 or bottom > self.height * 0.18:
                continue
            self.d.click((left + right) // 2, (top + bottom) // 2)
            return
        raise RuntimeError("未找到右上角搜索按钮")

    def _type_text(self, text: str) -> None:
        value = str(text or "")
        if not value:
            return
        try:
            self.d.send_keys(value)
            return
        except TypeError:
            pass
        except Exception:
            pass
        for char in value:
            try:
                self.d.send_keys(char, clear=False)
            except TypeError:
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

    def _swipe_up_continue_ad(self) -> None:
        cx = self.width // 2 + random.randint(-20, 20)
        start_y = int(self.height * 0.88)
        end_y = int(self.height * 0.28)
        self.d.swipe(cx, start_y, cx + random.randint(-8, 8), end_y, duration=0.35)

    def _swipe_down(self, distance: float = 0.5) -> None:
        cx = self.width // 2 + random.randint(-30, 30)
        start_y = int(self.height * 0.35)
        end_y = min(self.height - 50, int(start_y + self.height * distance))
        self.d.swipe(cx, start_y, cx + random.randint(-10, 10), end_y, duration=0.4)
