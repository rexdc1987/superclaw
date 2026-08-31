"""Atomic UI operations for Hongguo comment automation."""

from __future__ import annotations

import html
import logging
import random
import re
import time
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional

from .device import call_with_timeout, connect_exact, get_screen_size, screenshot


logger = logging.getLogger("uvicorn.error")

APP_PACKAGE = "com.phoenix.read"
SHORT_SERIES_ACTIVITY = "com.dragon.read.component.shortvideo.impl.ShortSeriesActivity"
LIVE_LITE_ACTIVITY = "com.dragon.read.component.biz.impl.live.ui.LiveLiteActivity"
POLARIS_MULTI_TAB_ACTIVITY = "com.dragon.read.polaris.tab.PolarisMultiTabActivity"
COMMENT_BUTTON_ID = "com.phoenix.read:id/cdi"
COMMENT_BUTTON_IDS = (COMMENT_BUTTON_ID, "com.phoenix.read:id/cdw")
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
REWARD_RAIN_MARKERS = (
    "红包雨",
    "开启红包雨",
    "金币全归你",
    "一大波金币红包来了",
)
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

# Hongguo can publish a renamed drama under the new search title while the
# playback surface keeps rendering the original title. These mappings are
# explicit product identity mappings, not fuzzy title matching.
KNOWN_TITLE_ALIASES = {
    "胭脂念念不忘": "胭脂如梦如雨如尘",
}


class HongguoOperations:
    def __init__(self, device: Any):
        self.d = device
        self._ad_swipe_pending = False
        # Search results may expose a renamed drama as "原名：旧标题" while
        # the playback page still renders the old title.
        self._search_title_aliases: Dict[str, str] = dict(KNOWN_TITLE_ALIASES)
        try:
            self.width, self.height = get_screen_size(self.d)
        except Exception:
            self.width, self.height = 1080, 1920

    def launch_app(self) -> bool:
        try:
            current = self._safe_app_current()
            if self._is_app_foreground() or (
                current.get("package") == APP_PACKAGE and bool(current.get("activity"))
            ):
                self._close_popups()
                return True
            for attempt in range(3):
                if attempt:
                    current = self._safe_app_current()
                    if current.get("package") != APP_PACKAGE:
                        self._stop_app()
                        time.sleep(2)
                self._start_app()
                current = self._safe_app_current()
                if (
                    self._wait_app_ready(18 if attempt == 0 else 12)
                    or self._is_app_foreground()
                    or (current.get("package") == APP_PACKAGE and bool(current.get("activity")))
                ):
                    self._close_popups()
                    return True
            current = self._safe_app_current()
            return self._is_app_foreground() or (
                current.get("package") == APP_PACKAGE and bool(current.get("activity"))
            )
        except Exception:
            return False

    def bring_to_foreground(self) -> bool:
        try:
            self._start_app()
            time.sleep(1.5)
            self._close_popups_quick()
            return self._is_app_foreground() or self._wait_app_ready(5)
        except Exception:
            return False

    def restart_app(self) -> bool:
        try:
            self._stop_app()
            time.sleep(1.5)
            self._start_app()
            return self._wait_app_ready(30)
        except Exception:
            return False

    def check_login(self) -> Dict[str, Any]:
        try:
            self._close_popups_quick()
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
            current = self._safe_app_current()
            if current.get("package") == APP_PACKAGE:
                return {
                    "logged_in": True,
                    "status": "in_app",
                    "message": "红果APP前台可用，未发现登录入口",
                }
            return {"logged_in": False, "status": "unknown", "message": "无法确认登录状态"}
        except Exception as exc:
            return {"logged_in": False, "status": "error", "message": str(exc)}

    def get_device_info(self) -> Dict[str, Any]:
        info: Dict[str, Any] = {}
        device_info: Dict[str, Any] = {}
        current: Dict[str, Any] = {}
        try:
            value = call_with_timeout(lambda: self.d.info, 3, "device info")
            if isinstance(value, dict):
                info = value
        except Exception:
            pass
        try:
            value = call_with_timeout(lambda: self.d.device_info, 3, "device info detail")
            if callable(value):
                value = call_with_timeout(value, 3, "device info detail call")
            if isinstance(value, dict):
                device_info = value
        except Exception:
            pass
        try:
            value = call_with_timeout(lambda: self.d.app_current(), 7, "device app current")
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
            if not self._open_profile_tab():
                return result
            xml = self._xml()
            if not self._profile_visible(xml):
                return result
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
            login_prompt_visible = any(prompt in xml for prompt in login_prompts)
            strong_profile_groups = (
                ("\u63d0\u73b0", "\u8ba2\u5355", "\u6d88\u606f"),
                ("\u6211\u7684\u94b1\u5305", "\u89c2\u770b\u5386\u53f2"),
                ("\u7f16\u8f91\u8d44\u6599", "\u6536\u85cf"),
            )
            strong_profile_visible = any(all(marker in xml for marker in group) for group in strong_profile_groups)
            profile_logged_in = bool(
                not login_prompt_visible
                and (hongguo_id or strong_profile_visible or nickname)
            )
            logged_in = bool(profile_logged_in)
            if not logged_in and login_prompt_visible:
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
            if not self._wait_app_foreground():
                self.bring_to_foreground()
                if not self._wait_app_foreground():
                    return {"success": False, "keyword": keyword, "titles": [], "message": "红果不在前台，取消搜索"}
            if self._short_series_activity_active() or self._playback_visible():
                opened_main = self._open_main_activity()
                if not opened_main:
                    self.d.press("back")
                    self._sleep(1.2, 1.8)
                    opened_main = self._open_main_activity()
                if not opened_main:
                    return {"success": False, "keyword": keyword, "titles": [], "message": "无法从播放页返回红果主页面"}
                if not self._wait_app_foreground() and not self._refresh_connection() and not self._wait_app_foreground():
                    return {"success": False, "keyword": keyword, "titles": [], "message": "退出播放页后设备连接刷新失败"}
            current_title = self._current_playing_title()
            if current_title and keyword and keyword in current_title:
                return {
                    "success": True,
                    "already_on_target": True,
                    "titles": [current_title],
                    "message": "已在目标短剧页面",
                }
            for recovery_attempt in range(2):
                for attempt in range(3):
                    if attempt == 0:
                        self._open_theater()
                    elif attempt == 1:
                        self._tap_bottom_tab("剧场", 0.37)
                    else:
                        self._tap_bottom_tab("首页", 0.14)
                    if self._open_search():
                        self._sleep(1.5, 2.5)
                        return {
                            "success": True,
                            "keyword": keyword,
                            "input_visible": self._exists(self.d(className="android.widget.EditText"), 1),
                            "message": "已进入搜索框",
                        }

                if recovery_attempt == 0:
                    # Activity can be foreground while uiautomator still exposes an
                    # empty hierarchy. Refresh that session before cold-starting once.
                    hierarchy_empty = self._hierarchy_empty(self._xml())
                    uia_restarted = self._restart_uiautomator_server() if hierarchy_empty else False
                    self._stop_app()
                    time.sleep(1.5)
                    self._start_app()
                    app_ready = self._wait_app_ready(25)
                    self._wait_app_foreground(5)
                    self._close_popups()
                    logger.info(
                        "Hongguo search entry recovery: addr=%s hierarchy_empty=%s "
                        "uiautomator_restarted=%s app_ready=%s",
                        getattr(self.d, "serial", None) or getattr(self.d, "_serial", ""),
                        hierarchy_empty,
                        uia_restarted,
                        app_ready,
                    )

            current = self._safe_app_current()
            xml = self._xml()
            return {
                "success": False,
                "keyword": keyword,
                "titles": [],
                "message": "未找到搜索入口",
                "diagnostics": {
                    "package": current.get("package", ""),
                    "activity": current.get("activity", ""),
                    "hierarchy_empty": self._hierarchy_empty(xml),
                },
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
            return {
                "success": True,
                "keyword": keyword,
                "input_text": input_text,
                "message": f"关键词已填入: 期望 {keyword}，实际 {input_text or '空'}",
            }
        except Exception as exc:
            return {"success": False, "keyword": keyword, "input_text": "", "message": str(exc)}

    def submit_search(self, keyword: str) -> Dict[str, Any]:
        try:
            # A device may be reused for another drama. Do not let an alias
            # from the previous search authorize a later playback page.
            self._search_title_aliases = dict(KNOWN_TITLE_ALIASES)
            submit = self._submit_search(keyword)
            if not submit.get("success"):
                return {
                    "success": False,
                    "keyword": keyword,
                    "titles": [],
                    "submit": submit,
                    "message": submit.get("message") or "搜索未进入结果页",
                }
            if not self._refresh_connection():
                return {
                    "success": False,
                    "keyword": keyword,
                    "titles": [],
                    "submit": submit,
                    "message": "搜索结果页已打开，但设备连接刷新失败",
                }
            titles = self._extract_drama_titles()
            message = submit.get("message") or "搜索完成"
            message = "搜索完成" if titles else "未找到有效短剧标题"
            return {
                "success": bool(submit.get("tabs_visible")) and bool(titles),
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
                "selected_title": "",
                "selected": {},
                "drama_title": "",
                "playable": False,
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

    def select_drama(
        self,
        title: str,
        keyword: str = "",
        prefer_exact_title: bool = False,
        prefer_result_card: bool = False,
        expected_total: int = 0,
    ) -> Dict[str, Any]:
        try:
            if not self._is_app_foreground():
                return {"success": False, "drama_title": title, "playable": False, "message": "红果不在前台，取消选择短剧"}
            expected = keyword or title
            detail_title = self._verified_detail_title(expected)
            if detail_title:
                return self._drama_detail_result(detail_title, expected)
            xml = self._xml()
            if expected and self._search_candidate_page_visible(xml):
                return {
                    "success": False,
                    "drama_title": title,
                    "playable": False,
                    "message": "未进入搜索结果页 tabs，仍停留在搜索候选页，取消选择短剧",
                }
            clicked_card = False
            if prefer_result_card:
                clicked_card = self._click_matching_result_card(title, expected) if title else False
                clicked = clicked_card
                if not clicked:
                    clicked = self._click_matching_title(title, expected) if title else False
            elif prefer_exact_title:
                clicked = self._click_matching_title(title, expected) if title else False
            else:
                clicked = self._click_matching_title(title, expected) if title else False
                if not clicked:
                    clicked_card = self._click_matching_result_card(title, expected) if title else False
                    clicked = clicked_card
            if not clicked:
                poster_result = self._try_unlabeled_poster_results(expected)
                if poster_result:
                    return poster_result
                return {"success": False, "drama_title": title, "playable": False, "message": f"未找到可点击的匹配短剧: {title}"}
            self._sleep(2, 3)
            self._dismiss_launcher_widget_dialog()
            if not self._is_app_foreground() and not self._refresh_connection():
                return {
                    "success": False,
                    "drama_title": title,
                    "playable": False,
                    "message": "点击短剧结果后设备连接刷新失败",
                }
            self._pause_selected_playback_quickly()
            if expected and self._still_on_search_selection_page():
                return {
                    "success": False,
                    "drama_title": title,
                    "playable": False,
                    "message": f"点击短剧结果后未进入详情页: 期望 {expected}",
                }
            wrong_collection = self._mismatched_collection_title(expected)
            if wrong_collection and clicked_card:
                self.d.press("back")
                self._sleep(1.2, 2)
                retried = self._click_matching_title(title, expected) if title else False
                if retried:
                    self._sleep(2, 3)
                    self._dismiss_launcher_widget_dialog()
                    self._pause_selected_playback_quickly()
                if not retried or self._still_on_search_selection_page():
                    return {
                        "success": False,
                        "drama_title": title,
                        "playable": False,
                        "message": f"目标卡片误入非目标合集 {wrong_collection}，精确标题重试未进入详情页",
                    }
                wrong_collection = self._mismatched_collection_title(expected)
            if wrong_collection:
                return {
                    "success": False,
                    "drama_title": title,
                    "playable": False,
                    "message": f"进入的合集与目标短剧不匹配: 期望 {expected}，实际 {wrong_collection}",
                }
            current_after_click = self._safe_app_current()
            if current_after_click.get("package") and current_after_click.get("package") != APP_PACKAGE:
                return {"success": False, "drama_title": title, "playable": False, "message": "选择后离开红果 App，已取消"}
            if self._ad_continue_visible():
                self.skip_ad_if_present()
                time.sleep(3)
            drama_title = self._wait_selected_drama_title(
                expected,
                title,
                expected_total=expected_total,
            )
            if expected and not drama_title:
                return {
                    "success": False,
                    "drama_title": title,
                    "playable": False,
                    "message": f"未确认进入目标短剧详情或标题不匹配: 期望 {expected}",
                }
            return self._drama_detail_result(drama_title, expected)
        except Exception as exc:
            return {"success": False, "drama_title": title, "playable": False, "message": str(exc)}

    def pause_playback_quickly(self) -> bool:
        """Pause playback with one direct tap, avoiding slow hierarchy reads."""
        current = self._safe_app_current()
        if current.get("package") != APP_PACKAGE or current.get("activity") != SHORT_SERIES_ACTIVITY:
            return False
        try:
            call_with_timeout(
                lambda: self.d.click(int(self.width * 0.5), int(self.height * 0.42)),
                3,
                "pause selected hongguo playback",
            )
            return True
        except Exception:
            return False

    def _pause_selected_playback_quickly(self) -> bool:
        """Keep a resumed final episode from ending while selection is verified."""
        return self.pause_playback_quickly()

    def _dismiss_launcher_widget_dialog(self) -> bool:
        xml = self._xml()
        if "\u6dfb\u52a0\u5230\u4e3b\u5c4f\u5e55" not in xml or "\u7ea2\u679c\u514d\u8d39\u77ed\u5267" not in xml:
            return False
        cancel = self.d(text="\u53d6\u6d88")
        if self._exists(cancel, 1):
            cancel.click()
        else:
            self.d.press("back")
        time.sleep(1.5)
        return True

    def _wait_selected_drama_title(
        self,
        expected: str,
        clicked_title: str,
        attempts: int = 8,
        expected_total: int = 0,
    ) -> str:
        """Wait for the Surface player metadata to settle after opening a result."""
        fallback_confirmations = 0
        for attempt in range(max(1, attempts)):
            current = self._safe_app_current()
            xml = self._xml()
            drama_title = self._verified_detail_title(expected, xml=xml, current=current)
            if drama_title:
                return drama_title
            if self._mismatched_collection_title(expected, xml):
                fallback_confirmations = 0
                if attempt + 1 < attempts:
                    self._sleep(1, 1.5)
                    continue
                return ""
            if clicked_title and self._strict_title_matches(expected, clicked_title):
                observed_title = self._extract_detail_title(xml=xml)
                if observed_title and not self._strict_title_matches(expected, observed_title):
                    return ""
                current_episode = self.get_current_episode(xml, assume_foreground=True)
                total_episodes = self.get_total_episodes(xml, assume_foreground=True)
                total_matches = not expected_total or total_episodes == expected_total
                playback_context = (
                    current.get("package") == APP_PACKAGE
                    and current.get("activity") == SHORT_SERIES_ACTIVITY
                    and total_matches
                    and (
                        (current_episode > 0 and total_episodes >= current_episode)
                        or self._playback_visible(xml, short_series_active=True)
                    )
                )
                fallback_confirmations = fallback_confirmations + 1 if playback_context else 0
                required_confirmations = 1 if expected_total and total_episodes == expected_total else 2
                if fallback_confirmations >= required_confirmations:
                    return clicked_title
            if attempt + 1 < attempts:
                self._sleep(1, 1.5)
        return ""

    def _verified_detail_title(
        self,
        expected: str,
        allow_clicked_title: bool = False,
        xml: Optional[str] = None,
        current: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Return the real title only when the target detail/playback page is visible."""
        current = current if current is not None else self._safe_app_current()
        if current.get("package") != APP_PACKAGE or current.get("activity") != SHORT_SERIES_ACTIVITY:
            return ""
        xml = self._xml() if xml is None else xml
        if self._search_results_visible(xml) or self._search_candidate_page_visible(xml):
            return ""
        drama_title = self._extract_detail_title(expected, xml)
        if drama_title and self._strict_title_matches(expected, drama_title):
            return drama_title if self._detail_markers_visible(xml) else ""
        observed_title = self._extract_detail_title(xml=xml)
        if observed_title and (
            not allow_clicked_title or self._looks_like_explicit_drama_title(observed_title)
        ):
            return ""
        if (
            allow_clicked_title
            and expected
            and self._detail_markers_visible(xml)
            and self._playback_visible(xml, short_series_active=True)
            and self.get_total_episodes(xml, assume_foreground=True) > 0
        ):
            return expected
        return ""

    def _looks_like_comment_text(self, text: str) -> bool:
        value = html.unescape(str(text or "")).strip()
        return bool(re.search(r"[\[\]【】]|(?:哈哈|呵呵|哭|笑|呜|哇)", value))

    def _looks_like_explicit_drama_title(self, text: str) -> bool:
        value = html.unescape(str(text or "")).strip()
        return bool(re.search(r"[:：]|第[一二三四五六七八九十\d]+[季部篇]|[上下续前后]篇", value))

    def _current_collection_title(self, xml: Optional[str] = None) -> str:
        xml = xml if xml is not None else self._xml()
        playing_title = self._current_playing_title(xml)
        if playing_title:
            return playing_title
        texts: List[str] = []
        for node in self._visible_hongguo_nodes(xml):
            text_match = re.search(r'text="([^"]+)"', node)
            if text_match:
                text = html.unescape(text_match.group(1)).strip()
                if text:
                    texts.append(text)
        sources = [*texts, " ".join(texts)]
        pattern = re.compile(
            r"合集\s*[·•・:：-]*\s*(.{2,40}?)\s*[·•・:：-]*\s*更新至\s*\d+\s*集"
        )
        for source in sources:
            match = pattern.search(source)
            if match:
                return match.group(1).strip(" ·•・:：-")
        return ""

    def _mismatched_collection_title(self, expected: str, xml: Optional[str] = None) -> str:
        collection_title = self._current_collection_title(xml)
        if collection_title and expected and not self._strict_title_matches(expected, collection_title):
            return collection_title
        return ""

    def _refresh_connection(self) -> bool:
        serial = getattr(self.d, "serial", None) or getattr(self.d, "_serial", None)
        if not serial:
            return True
        try:
            self.d = connect_exact(serial)
            self.width, self.height = get_screen_size(self.d)
            return True
        except Exception:
            return False

    def _wait_app_foreground(self, attempts: int = 3) -> bool:
        for attempt in range(max(1, attempts)):
            current = self._safe_app_current()
            if current.get("package") == APP_PACKAGE and current.get("activity"):
                return True
            if self._is_app_foreground():
                return True
            if attempt + 1 < attempts:
                time.sleep(1)
        return False

    def _open_main_activity(self) -> bool:
        try:
            call_with_timeout(
                lambda: self.d.shell(
                    f"am start -n {APP_PACKAGE}/com.dragon.read.pages.main.MainFragmentActivity"
                ),
                5,
                "open hongguo main activity",
            )
        except Exception:
            return False
        time.sleep(2)
        current = self._safe_app_current()
        if current.get("package") == APP_PACKAGE and current.get("activity") == "com.dragon.read.pages.main.MainFragmentActivity":
            return True

        # Android may reuse the existing short-series task even though am
        # start reports success. Cold-start Hongguo and wait for the real main
        # activity before looking for search controls.
        self._stop_app()
        time.sleep(1)
        self._start_app()
        for _ in range(15):
            current = self._safe_app_current()
            if current.get("package") == APP_PACKAGE and current.get("activity") == "com.dragon.read.pages.main.MainFragmentActivity":
                return True
            time.sleep(1)
        return False

    def _still_on_search_selection_page(self) -> bool:
        current = self._safe_app_current()
        if current.get("activity") == "com.dragon.read.component.biz.impl.SearchActivity":
            return True
        xml = self._xml()
        return self._search_results_visible(xml) or self._search_candidate_page_visible(xml)

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
        if not playable and drama_title:
            current = self._safe_app_current()
            current_episode = self.get_current_episode()
            total_episodes = self.get_total_episodes()
            playable = bool(
                current.get("package") == APP_PACKAGE
                and current.get("activity") == SHORT_SERIES_ACTIVITY
                and current_episode > 0
                and total_episodes >= current_episode
            )
        detail_visible = bool(drama_title and re.search(r"全\d+集", xml))
        return {
            "success": bool(playable or detail_visible),
            "drama_title": drama_title,
            "playable": playable,
            "detail_visible": detail_visible,
            "message": "已进入短剧详情" if (playable or detail_visible) else "短剧不可播放",
        }

    def _detail_markers_visible(self, xml: Optional[str] = None) -> bool:
        xml = " ".join(self._hongguo_nodes(self._xml() if xml is None else xml))
        return bool(re.search(r"全\d+集|第\d+集", xml) or any(marker in xml for marker in ("剧情简介", "剧评", "选集")))

    def play_episode(self, episode_number: int) -> bool:
        try:
            xml = self._xml()
            if self._launcher_visible(xml) and not self._short_series_activity_active():
                return False
            current_episode = self.get_current_episode()
            if current_episode == episode_number:
                if self._episode_list_panel_open():
                    return self._close_episode_list_panel(episode_number)
                return True
            if self._episode_list_panel_open(xml):
                if self._click_episode_number(episode_number):
                    self._sleep(2, 3)
                    for _ in range(6):
                        if self._episode_is_confirmed(episode_number):
                            return self._close_episode_list_panel(episode_number)
                        time.sleep(1)
                return self._episode_is_confirmed(episode_number) and self._close_episode_list_panel(episode_number)
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
                        current_episode = self.get_current_episode()
                        if self._episode_is_confirmed(1):
                            return True
                    if current_episode <= 0 and self._click_first_play_button():
                        self._sleep(2, 3)
                        current_episode = self.get_current_episode()
                        if self._episode_is_confirmed(1):
                            return True
                return self._episode_is_confirmed(1)
            self.exit_fullscreen()
            selector = self._episode_panel_selector()
            if selector is None and self._short_series_activity_active():
                self._reveal_playback_controls()
                time.sleep(0.8)
                selector = self._episode_panel_selector()
            if selector is not None and self._exists(selector, 3):
                selector.click()
                self._sleep(1.5, 2.5)
                if self._click_episode_number(episode_number):
                    for _ in range(6):
                        if self.get_current_episode() == episode_number:
                            return self._close_episode_list_panel(episode_number)
                        time.sleep(1)
            return self._episode_is_confirmed(episode_number) and self._close_episode_list_panel(episode_number)
        except Exception:
            return False

    def set_playback_speed(self, speed: str) -> bool:
        target = self._normalize_speed_label(speed)
        if not target:
            return False
        xml = self._xml()
        if self._launcher_visible(xml) and not self._has_large_hongguo_window(xml):
            return False
        if self._current_speed_matches(target, xml):
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
                after_xml = self._xml()
                if self._current_speed_matches(target, after_xml):
                    return True
                if not self._speed_panel_open(after_xml) and self._short_series_activity_active():
                    return True
            if self._speed_panel_open():
                self.d.click(int(self.width * 0.5), int(self.height * 0.28))
            time.sleep(0.8)
        return self._current_speed_matches(target)

    def _episode_panel_selector(self) -> Optional[Any]:
        for selector in (self.d(textContains="选集"), self.d(textContains="合集")):
            if self._exists(selector, 1):
                return selector
        return None

    def _episode_list_panel_open(self, xml: Optional[str] = None) -> bool:
        xml = self._xml() if xml is None else xml
        if not xml:
            return False
        text = html.unescape(xml)
        has_detail_tabs = "简介" in text and "选集" in text
        has_range_tab = bool(re.search(r'(?:text|content-desc)="\d{1,4}-\d{1,4}"', text))
        tile_count = 0
        for node in self._hongguo_nodes(text):
            labels = [
                html.unescape(value).strip()
                for value in re.findall(r'(?:text|content-desc)="([^"]*)"', node)
            ]
            if not any(re.fullmatch(r"\d{1,4}", label) for label in labels):
                continue
            bounds = self._node_bounds(node)
            if not bounds:
                continue
            left, top, right, bottom = bounds
            width = right - left
            height = bottom - top
            if width >= self.width * 0.08 and height >= self.height * 0.04 and top > self.height * 0.18:
                tile_count += 1
                if tile_count >= 8:
                    break
        return bool(has_range_tab and (has_detail_tabs or tile_count >= 8))

    def _close_episode_list_panel(self, episode_number: int = 0) -> bool:
        for attempt in range(6):
            if not self._episode_list_panel_open():
                if episode_number <= 0:
                    return self._playback_visible()
                current = self.get_current_episode()
                return current == episode_number and self._playback_visible()
            if attempt == 0 and self._tap_episode_panel_collapse_control():
                time.sleep(1.2)
                continue
            if attempt == 1:
                self.d.press("back")
            elif attempt == 2:
                self.d.click(int(self.width * 0.06), int(self.height * 0.055))
            elif attempt == 3:
                self.d.click(int(self.width * 0.06), int(self.height * 0.09))
            elif attempt == 4:
                self.d.click(int(self.width * 0.06), int(self.height * 0.13))
            else:
                self.d.swipe(
                    int(self.width * 0.5),
                    int(self.height * 0.22),
                    int(self.width * 0.5),
                    int(self.height * 0.82),
                    0.25,
                )
            time.sleep(1.2)
        return not self._episode_list_panel_open()

    def _tap_episode_panel_collapse_control(self) -> bool:
        xml = self._xml()
        candidates: List[tuple[int, int, int, int]] = []
        for node in self._hongguo_nodes(xml):
            bounds = self._node_bounds(node)
            if not bounds:
                continue
            left, top, right, bottom = bounds
            if left > self.width * 0.22 or top > self.height * 0.18:
                continue
            width = right - left
            height = bottom - top
            labels = [
                html.unescape(value).strip()
                for value in re.findall(r'(?:text|content-desc)="([^"]*)"', node)
            ]
            label_hint = any(label in {"收起", "关闭", "返回"} for label in labels)
            icon_hint = "ImageView" in node or 'clickable="true"' in node
            if label_hint or (icon_hint and 18 <= width <= self.width * 0.18 and 18 <= height <= self.height * 0.12):
                candidates.append(bounds)
        if candidates:
            candidates.sort(key=lambda item: (item[1], item[0]))
            for left, top, right, bottom in candidates[:3]:
                self.d.click((left + right) // 2, (top + bottom) // 2)
                time.sleep(0.8)
                if not self._episode_list_panel_open():
                    return True
        # Newer Hongguo builds show the episode picker as a bottom sheet with
        # only a small handle near the sheet top. Tapping/dragging that handle
        # is more reliable than Back, which can leave playback or open Launcher.
        for x_ratio, y_ratio in ((0.5, 0.445), (0.5, 0.47), (0.5, 0.43)):
            x = int(self.width * x_ratio)
            y = int(self.height * y_ratio)
            self.d.click(x, y)
            time.sleep(0.7)
            if not self._episode_list_panel_open():
                return True
            self.d.swipe(x, y, x, int(self.height * 0.82), 0.25)
            time.sleep(0.8)
            if not self._episode_list_panel_open():
                return True
        for x_ratio, y_ratio in (
            (0.06, 0.055),
            (0.06, 0.09),
            (0.06, 0.13),
            (0.1, 0.055),
            (0.1, 0.09),
        ):
            self.d.click(int(self.width * x_ratio), int(self.height * y_ratio))
            time.sleep(0.7)
            if not self._episode_list_panel_open():
                return True
        return False

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

    def is_playback_paused(
        self,
        xml: Optional[str] = None,
        short_series_active: Optional[bool] = None,
    ) -> bool:
        if short_series_active is None:
            short_series_active = self._short_series_activity_active()
        if not short_series_active:
            return False
        return self._center_play_overlay_visible(xml)

    def pause_playback_if_playing(self) -> bool:
        if not self._short_series_activity_active():
            return False
        if self.is_playback_paused():
            return True
        try:
            self.d.shell("input keyevent 127")
            time.sleep(1)
            if self.is_playback_paused():
                return True
        except Exception:
            pass
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
            time.sleep(1.5)
        except Exception:
            pass
        for _ in range(3):
            if self._center_play_overlay_visible():
                break
            time.sleep(0.6)
        if self._center_play_overlay_visible():
            try:
                self.d.click(int(self.width * 0.5), int(self.height * 0.42))
                for _ in range(4):
                    time.sleep(0.6)
                    if not self._center_play_overlay_visible():
                        return True
                return False
            except Exception:
                return False
        return not self._center_play_overlay_visible()

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
            for y_ratio in (0.46, 0.42, 0.50):
                self.d.click(int(self.width * 0.5), int(self.height * y_ratio))
                time.sleep(1)
                if not self.is_playback_paused():
                    return True
        return False

    def _click_play_overlay(self) -> bool:
        xml = self._xml()
        candidates = self._center_play_candidates(xml)
        explicit_play = [bounds for bounds, semantic in candidates if semantic is True]
        if explicit_play:
            left, top, right, bottom = min(
                explicit_play,
                key=lambda item: (item[2] - item[0]) * (item[3] - item[1]),
            )
            self.d.click((left + right) // 2, (top + bottom) // 2)
            return True
        if any(semantic is False for _, semantic in candidates):
            return False

        unlabeled_bounds = [bounds for bounds, semantic in candidates if semantic is None]
        unlabeled_bounds.sort(key=lambda item: (item[2] - item[0]) * (item[3] - item[1]))
        for left, top, right, bottom in unlabeled_bounds:
            if self._center_play_icon_visible_by_screenshot((left, top, right, bottom)):
                self.d.click((left + right) // 2, (top + bottom) // 2)
                return True
        if self._center_play_icon_visible_by_screenshot():
            self.d.click(int(self.width * 0.5), int(self.height * 0.46))
            return True
        return False

    def skip_ad_if_present(self) -> bool:
        if not self._ad_continue_visible():
            return False
        if self._ad_swipe_pending:
            return False

        self._ad_swipe_pending = True
        # Wait for the ad's continuation countdown before the single swipe.
        # A fixed delay was too short for ads that start with a 7-second gate.
        raw_xml = self._xml()
        xml = html.unescape(raw_xml) if isinstance(raw_xml, str) else ""
        countdown = re.search(r"(\d{1,2})\s*\u79d2\s*\u540e", xml)
        ready_wait = max(8, min(16, int(countdown.group(1)) + 1)) if countdown else 15
        time.sleep(ready_wait)
        if not self._ad_continue_visible():
            return True
        xml = self._xml()
        if "点击重播" in xml or "重播" in xml:
            try:
                self.d.click(int(self.width * 0.5), int(self.height * 0.66))
                time.sleep(0.8)
            except Exception:
                pass
        if self._ad_play_overlay_visual_visible():
            self.d.click(int(self.width * 0.5), int(self.height * 0.45))
            time.sleep(1)

        self._swipe_up_continue_ad()
        time.sleep(4)
        return not self._ad_continue_visible()

    def _ad_play_overlay_visual_visible(self) -> bool:
        try:
            image = self.d.screenshot().convert("RGB")
        except Exception:
            return False
        crop = image.crop(
            (
                int(self.width * 0.42),
                int(self.height * 0.40),
                int(self.width * 0.58),
                int(self.height * 0.55),
            )
        )
        pixels = list(crop.getdata())
        if not pixels:
            return False
        dark_ratio = sum(1 for pixel in pixels if max(pixel) <= 65) / len(pixels)
        white_ratio = sum(1 for pixel in pixels if min(pixel) >= 235) / len(pixels)
        return dark_ratio >= 0.75 and white_ratio >= 0.02

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

    def get_current_episode(self, xml: Optional[str] = None, assume_foreground: bool = False) -> int:
        if not assume_foreground and not self._is_app_foreground():
            return 0

        xml = xml if xml is not None else self._xml()
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

        for node in self._hongguo_nodes(xml):
            text_match = re.search(r'text="\u7b2c\s*(\d{1,4})\s*\u96c6"', node)
            bounds = self._node_bounds(node)
            if not text_match or not bounds:
                continue
            try:
                if bounds[1] <= int(self.height * 0.14) and self._episode_number_context_visible(xml):
                    return int(text_match.group(1))
            except (TypeError, ValueError):
                continue

        numbers = self._extract_episode_numbers(xml)
        for episode in numbers:
            if self._is_episode_active(episode, xml):
                return episode
        if len(numbers) == 1 and self._episode_number_context_visible(xml):
            return numbers[0]
        return 0

    def confirm_current_episode(self, expected_episode: int = 0) -> int:
        """Read the active episode after making hidden playback controls visible."""
        if not self._short_series_activity_active():
            return 0

        for attempt in range(3):
            current = self.get_current_episode()
            if current > 0:
                return current
            self._reveal_playback_controls()
            time.sleep(0.8)
            if attempt == 1:
                self.exit_fullscreen()
                self._reveal_playback_controls()
                time.sleep(0.8)

        trigger = self._episode_panel_selector()
        if trigger is None:
            return 0
        try:
            trigger.click()
            time.sleep(1.2)
            current = self.get_current_episode()
        except Exception:
            current = 0
        finally:
            self._close_episode_list_panel(current or expected_episode)
        return current

    def get_total_episodes(self, xml: Optional[str] = None, assume_foreground: bool = False) -> int:
        if not assume_foreground and not self._is_app_foreground():
            return 0

        xml = xml if xml is not None else self._xml()
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

    def _playback_visible(
        self,
        xml: Optional[str] = None,
        short_series_active: Optional[bool] = None,
    ) -> bool:
        xml = self._xml() if xml is None else xml
        if short_series_active is None:
            short_series_active = self._short_series_activity_active()
        if not xml:
            return bool(short_series_active)
        if self._episode_list_panel_open(xml):
            return False
        if self._ad_continue_visible(xml):
            return True
        if COMMENT_BUTTON_ID in xml:
            return True
        if short_series_active:
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
        xml = self._xml() if xml is None else xml
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
        xml = self._xml() if xml is None else xml
        candidates = self._center_play_candidates(xml)
        if any(semantic is True for _, semantic in candidates):
            return True
        if any(semantic is False for _, semantic in candidates):
            return False
        candidates.sort(key=lambda item: abs(((item[0][0] + item[0][2]) // 2) - self.width // 2))
        for bounds, _ in candidates:
            if self._center_play_icon_visible_by_screenshot(bounds):
                return True
        return self._center_play_icon_visible_by_screenshot()

    def _center_play_candidates(
        self,
        xml: str,
    ) -> List[tuple[tuple[int, int, int, int], Optional[bool]]]:
        candidates: List[tuple[tuple[int, int, int, int], Optional[bool]]] = []
        for node in self._hongguo_nodes(xml):
            if 'clickable="true"' not in node:
                continue
            bounds = self._node_bounds(node)
            if not bounds:
                continue
            left, top, right, bottom = bounds
            width = right - left
            height = bottom - top
            center_x = (left + right) // 2
            center_y = (top + bottom) // 2
            if width < 40 or height < 40:
                continue
            if abs(center_x - self.width // 2) > self.width * 0.18:
                continue
            if not self.height * 0.28 <= center_y <= self.height * 0.58:
                continue
            candidates.append((bounds, self._playback_control_semantic(node)))
        return candidates

    @staticmethod
    def _playback_control_semantic(node: str) -> Optional[bool]:
        labels = {
            re.sub(r"\s+", "", html.unescape(value)).lower()
            for value in re.findall(r'(?:text|content-desc)="([^"]*)"', node)
            if value.strip()
        }
        playing_labels = {"暂停", "点击暂停", "暂停播放", "播放中", "正在播放"}
        paused_labels = {"播放", "点击播放", "继续播放", "恢复播放", "播放按钮"}
        if labels & playing_labels:
            return False
        if labels & paused_labels:
            return True
        return None

    def _center_play_icon_visible_by_screenshot(self, bounds: Optional[tuple[int, int, int, int]] = None) -> bool:
        try:
            image = self.d.screenshot().convert("RGB")
        except Exception:
            return False
        if bounds is None:
            left = int(self.width * 0.40)
            right = int(self.width * 0.60)
            top = int(self.height * 0.34)
            bottom = int(self.height * 0.56)
        else:
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
        white_points = {
            (index % crop.width, index // crop.width)
            for index, (red, green, blue) in enumerate(crop.getdata())
            if red >= 235 and green >= 235 and blue >= 235
        }
        if len(white_points) < 180:
            return False
        if len(white_points) > crop.width * crop.height * 0.48:
            return False

        remaining = set(white_points)
        while remaining:
            seed = remaining.pop()
            stack = [seed]
            component = [seed]
            while stack:
                x, y = stack.pop()
                for neighbor_y in (y - 1, y, y + 1):
                    for neighbor_x in (x - 1, x, x + 1):
                        neighbor = (neighbor_x, neighbor_y)
                        if neighbor not in remaining:
                            continue
                        remaining.remove(neighbor)
                        stack.append(neighbor)
                        component.append(neighbor)
            if len(component) >= 180 and self._white_component_looks_like_play(
                component,
                crop.width,
                crop.height,
            ):
                return True
        return False

    @staticmethod
    def _white_component_looks_like_play(
        white_points: List[tuple[int, int]],
        crop_width: int,
        crop_height: int,
    ) -> bool:
        min_x = min(point[0] for point in white_points)
        max_x = max(point[0] for point in white_points)
        min_y = min(point[1] for point in white_points)
        max_y = max(point[1] for point in white_points)
        icon_width = max_x - min_x + 1
        icon_height = max_y - min_y + 1
        if icon_width < 18 or icon_height < 18:
            return False
        if icon_width > crop_width * 0.72 or icon_height > crop_height * 0.72:
            return False
        ratio = icon_width / max(1, icon_height)
        if not 0.55 <= ratio <= 1.60:
            return False

        center_x = (min_x + max_x) / 2
        center_y = (min_y + max_y) / 2
        if abs(center_x - crop_width / 2) > crop_width * 0.28:
            return False
        if abs(center_y - crop_height / 2) > crop_height * 0.28:
            return False

        occupancy = len(white_points) / max(1, icon_width * icon_height)
        if not 0.12 <= occupancy <= 0.78:
            return False

        row_max_x: Dict[int, int] = {}
        for x, y in white_points:
            row_max_x[y] = max(x, row_max_x.get(y, x))

        # A right-facing play triangle reaches its furthest-right point in the middle band.
        band_max_x: List[List[int]] = [[], [], []]
        for y, max_row_x in row_max_x.items():
            relative_y = (y - min_y) / max(1, icon_height - 1)
            band = 0 if relative_y < 0.30 else 2 if relative_y > 0.70 else 1
            band_max_x[band].append(max_row_x)
        if any(not values for values in band_max_x):
            return False

        averages = [sum(values) / len(values) for values in band_max_x]
        tip_bulge = min(averages[1] - averages[0], averages[1] - averages[2])
        return tip_bulge >= icon_width * 0.14

    def _ad_continue_visible(self, xml: Optional[str] = None) -> bool:
        # A stale hierarchy may retain an ad prompt after the app has returned
        # to the launcher. Never swipe unless Hongguo is visibly foreground.
        text = html.unescape(self._xml() if xml is None else xml)
        normal_episode_visible = bool(
            re.search(r"\u7b2c\s*\d{1,4}\s*\u96c6", text)
            or COMMENT_BUTTON_ID in text
            or "选集" in text
            or "倍速" in text
            or "说点什么" in text
        )
        if self._episode_list_panel_open(text):
            return self._track_ad_visibility(False)
        short_series_active = self._short_series_activity_active()
        has_swipe_hint = any(marker in text for marker in ("上滑", "滑动"))
        has_continue_hint = any(marker in text for marker in ("继续观看", "继续看"))
        has_prompt_marker = any(marker in text for marker in AD_CONTINUE_PROMPT_MARKERS)
        has_ad_marker = any(marker in text for marker in AD_PAGE_MARKERS)
        has_exact_ad_badge = bool(re.search(r'(?:text|content-desc)="广告"', text))
        if short_series_active:
            if normal_episode_visible:
                return self._track_ad_visibility(False)
            visible = bool(
                has_prompt_marker
                or has_exact_ad_badge
                or (has_ad_marker and has_swipe_hint and has_continue_hint and "短剧" in text)
            )
            if not visible and not self._has_hongguo_business_nodes(text):
                visible = self._surface_ad_prompt_visual_visible()
            return self._track_ad_visibility(visible)
        current = self._safe_app_current()
        if not current.get("package") and not current.get("activity"):
            return self._track_ad_visibility(False)
        if normal_episode_visible:
            return self._track_ad_visibility(False)
        first_package = self._first_visible_package(text)
        if self._launcher_visible(text):
            return self._track_ad_visibility(False)
        if first_package and first_package != APP_PACKAGE and not self._has_large_hongguo_window(text):
            return self._track_ad_visibility(False)
        current = self._safe_app_current()
        if current.get("package") and current.get("package") != APP_PACKAGE:
            return self._track_ad_visibility(False)
        visible = bool(
            has_prompt_marker
            or (has_ad_marker and has_swipe_hint and has_continue_hint and "短剧" in text)
        )
        return self._track_ad_visibility(visible)

    def _track_ad_visibility(self, visible: bool) -> bool:
        if not visible:
            self._ad_swipe_pending = False
        return visible

    def _surface_ad_prompt_visual_visible(self) -> bool:
        current = self._safe_app_current()
        if current.get("package") and current.get("package") != APP_PACKAGE:
            return False
        if current.get("activity") and current.get("activity") != SHORT_SERIES_ACTIVITY:
            return False

        image = None
        serial = getattr(self.d, "serial", None) or getattr(self.d, "_serial", None)
        if serial:
            try:
                import adbutils

                image = call_with_timeout(
                    lambda: adbutils.adb.device(serial).screenshot(),
                    8,
                    f"surface ad prompt screenshot {serial}",
                )
            except Exception:
                image = None
        try:
            image = (image or self.d.screenshot()).convert("RGB")
        except Exception:
            return False

        x1 = int(self.width * 0.18)
        x2 = int(self.width * 0.82)
        upper_pixels = list(image.crop((x1, int(self.height * 0.88), x2, int(self.height * 0.93))).getdata())
        footer_pixels = list(image.crop((x1, int(self.height * 0.93), x2, int(self.height * 0.995))).getdata())
        if not upper_pixels or not footer_pixels:
            return False

        upper_dark_ratio = sum(1 for pixel in upper_pixels if max(pixel) <= 65) / len(upper_pixels)
        footer_dark_ratio = sum(1 for pixel in footer_pixels if max(pixel) <= 65) / len(footer_pixels)
        footer_muted_text_ratio = sum(1 for pixel in footer_pixels if min(pixel) >= 120) / len(footer_pixels)
        footer_bright_text_ratio = sum(1 for pixel in footer_pixels if min(pixel) >= 170) / len(footer_pixels)

        # Surface live ads render the continuation prompt into the video, so
        # hierarchy text is empty. Their prompt is muted gray on a black footer;
        # normal episode selectors use bright white text and are rejected.
        return bool(
            upper_dark_ratio >= 0.30
            and footer_dark_ratio >= 0.90
            and 0.02 <= footer_muted_text_ratio <= 0.08
            and footer_bright_text_ratio <= 0.01
        )

    def _ad_continue_visual_visible(self) -> bool:
        current = self._safe_app_current()
        if current.get("package") and current.get("package") != APP_PACKAGE:
            return False
        if current.get("activity") and current.get("activity") != SHORT_SERIES_ACTIVITY:
            return False
        image = None
        serial = getattr(self.d, "serial", None) or getattr(self.d, "_serial", None)
        if serial:
            try:
                import adbutils

                image = call_with_timeout(
                    lambda: adbutils.adb.device(serial).screenshot(),
                    8,
                    f"ad visual screenshot {serial}",
                )
            except Exception:
                image = None
        try:
            image = (image or self.d.screenshot()).convert("RGB")
        except Exception:
            return False
        x1 = int(self.width * 0.18)
        x2 = int(self.width * 0.82)
        upper = image.crop((x1, int(self.height * 0.88), x2, int(self.height * 0.93)))
        footer = image.crop((x1, int(self.height * 0.93), x2, int(self.height * 0.995)))
        upper_pixels = list(upper.getdata())
        footer_pixels = list(footer.getdata())
        if not upper_pixels or not footer_pixels:
            return False
        global_crop = image.crop(
            (
                int(self.width * 0.05),
                int(self.height * 0.10),
                int(self.width * 0.95),
                int(self.height * 0.88),
            )
        )
        global_pixels = list(global_crop.getdata())
        if not global_pixels:
            return False
        upper_dark_ratio = sum(1 for pixel in upper_pixels if max(pixel) <= 65) / len(upper_pixels)
        footer_dark_ratio = sum(1 for pixel in footer_pixels if max(pixel) <= 65) / len(footer_pixels)
        footer_bright_ratio = sum(1 for pixel in footer_pixels if min(pixel) >= 170) / len(footer_pixels)
        global_dark_ratio = sum(1 for pixel in global_pixels if max(pixel) <= 65) / len(global_pixels)
        # Live ads place a dark continuation prompt below an already dimmed ad
        # surface. A normal episode can also have a black episode-selector
        # footer, but the video band immediately above it remains brighter.
        has_dark_footer_prompt = (
            footer_dark_ratio >= 0.78
            and upper_dark_ratio >= 0.50
            and footer_bright_ratio >= 0.01
        )
        has_large_bright_prompt = footer_dark_ratio >= 0.55 and footer_bright_ratio >= 0.18
        has_dark_ad_page = global_dark_ratio >= 0.94 and footer_bright_ratio >= 0.01
        return has_dark_footer_prompt or has_large_bright_prompt or has_dark_ad_page

    def _is_episode_active(self, episode_number: int, xml: Optional[str] = None) -> bool:
        if episode_number <= 0:
            return False
        xml = self._xml() if xml is None else xml
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
            if self._close_live_lite_page():
                time.sleep(1)
            if self._comment_panel_open():
                self._close_comment_panel()
                time.sleep(1)
            if self._launcher_visible(self._xml()) and not self._short_series_activity_active():
                return False
            current = self.get_current_episode()
            if episode_number <= 0:
                return self._playback_visible()
            if (
                episode_number == 1
                and not current
                and self._short_series_activity_active()
                and self._playback_visible()
                and self.get_total_episodes() > 0
            ):
                return True
            if current == episode_number and self._playback_visible():
                if self._episode_list_panel_open():
                    return self._close_episode_list_panel(episode_number)
                return True
            if self.play_episode(episode_number):
                return self._episode_is_confirmed(episode_number)
            return self._episode_is_confirmed(episode_number)
        except Exception:
            return False

    def _live_lite_activity_active(self) -> bool:
        current = self._safe_app_current()
        return current.get("package") == APP_PACKAGE and current.get("activity") == LIVE_LITE_ACTIVITY

    def _close_live_lite_page(self) -> bool:
        if not self._live_lite_activity_active():
            return False
        for x_ratio, y_ratio in (
            (0.07, 0.07),
            (0.94, 0.04),
            (0.94, 0.07),
            (0.90, 0.05),
        ):
            try:
                self.d.click(int(self.width * x_ratio), int(self.height * y_ratio))
                time.sleep(1)
                if not self._live_lite_activity_active():
                    return True
            except Exception:
                pass
        try:
            self.d.press("back")
            time.sleep(1)
            return not self._live_lite_activity_active()
        except Exception:
            return False

    def _reward_rain_page_active(self, xml: Optional[str] = None) -> bool:
        xml = self._xml() if xml is None else xml
        if any(marker in (xml or "") for marker in REWARD_RAIN_MARKERS):
            return True
        current = self._safe_app_current()
        return (
            current.get("package") == APP_PACKAGE
            and current.get("activity") == POLARIS_MULTI_TAB_ACTIVITY
        )

    def _dismiss_reward_rain_page(self) -> bool:
        if not self._reward_rain_page_active():
            return False

        for selector in (
            {"description": "关闭"},
            {"descriptionContains": "关闭"},
            {"text": "关闭"},
        ):
            try:
                close_button = self.d(**selector)
                if not self._exists(close_button, 0.4):
                    continue
                close_button.click()
                time.sleep(0.8)
                if not self._reward_rain_page_active():
                    return True
            except Exception:
                pass

        # The reward-rain close icon is surface-rendered and absent from the
        # hierarchy on some app versions. Its observed position is stable.
        try:
            self.d.click(int(self.width * 0.5), int(self.height * 0.936))
            time.sleep(0.8)
            if not self._reward_rain_page_active():
                return True
        except Exception:
            pass

        try:
            self.d.press("back")
            time.sleep(1)
            return not self._reward_rain_page_active()
        except Exception:
            return False

    def _open_comment_panel(self, timeout: float = 2, prefer_coordinate: bool = False) -> bool:
        self._recover_anr_dialog()
        if self._reward_rain_page_active():
            self._dismiss_reward_rain_page()
        self._close_xiaoguo_ai_panel()
        if self._comment_panel_open():
            return True
        if prefer_coordinate and self._open_comment_panel_by_coordinate():
            return True
        for resource_id in COMMENT_BUTTON_IDS:
            comment_btn = self.d(resourceId=resource_id)
            if self._exists(comment_btn, timeout):
                comment_btn.click()
                for _ in range(4):
                    time.sleep(0.5)
                    self._recover_anr_dialog()
                    xml = self._xml()
                    if self._xiaoguo_ai_panel_open(xml):
                        self._close_xiaoguo_ai_panel(xml)
                        break
                    if self._comment_panel_open(xml):
                        return True
        if (self._playback_visible() or self._short_series_activity_active()) and self._open_comment_panel_by_coordinate():
            return True
        return False

    def _open_comment_panel_by_coordinate(self) -> bool:
        # Surface-rendered playback pages do not always expose the comment
        # bubble in the hierarchy. Try its stable right-side positions first.
        xml = self._xml()
        if self._comment_button_obstructed(xml):
            return self._open_comment_after_layout_toggle()
        if self._comment_action_rail_hidden(xml):
            toggle_point = self._player_layout_toggle_point(xml)
            if not toggle_point:
                return False
            self.d.click(*toggle_point)
            time.sleep(0.8)
            xml = self._xml()
            if self._comment_action_rail_hidden(xml):
                return False

        comment_point = self._comment_button_point(xml)
        if comment_point:
            self.d.click(*comment_point)
            for _ in range(4):
                time.sleep(0.4)
                xml = self._xml()
                if self._xiaoguo_ai_panel_open(xml):
                    self._close_xiaoguo_ai_panel(xml)
                    break
                if self._comment_panel_open(xml):
                    return True
        y_ratios = (0.60, 0.64, 0.67) if self.width <= 760 else (0.67, 0.64, 0.60)
        for y_ratio in y_ratios:
            self.d.click(int(self.width * 0.94), int(self.height * y_ratio))
            for _ in range(3):
                time.sleep(0.4)
                self._recover_anr_dialog()
                xml = self._xml()
                if self._xiaoguo_ai_panel_open(xml):
                    self._close_xiaoguo_ai_panel(xml)
                    break
                if self._comment_panel_open(xml):
                    return True
        return False

    def _comment_button_obstructed(self, xml: Optional[str] = None) -> bool:
        xml = self._xml() if xml is None else xml
        if not isinstance(xml, str):
            return False
        for node in re.findall(r"<node\b[^>]+>", xml or ""):
            if "androidx.compose.ui.viewinterop.ViewFactoryHolder" not in node:
                continue
            bounds = self._node_bounds(node)
            if not bounds:
                continue
            left, top, right, bottom = bounds
            if (
                right >= self.width * 0.88
                and left <= self.width * 0.94
                and top <= self.height * 0.64
                and bottom >= self.height * 0.60
            ):
                return True
        return False

    def _comment_button_point(self, xml: Optional[str] = None) -> Optional[tuple[int, int]]:
        xml = self._xml() if xml is None else xml
        if not isinstance(xml, str):
            return None
        for node in re.findall(r"<node\b[^>]+>", xml or ""):
            if not any(f'resource-id="{resource_id}"' in node for resource_id in COMMENT_BUTTON_IDS):
                continue
            bounds = self._node_bounds(node)
            if bounds:
                left, top, right, bottom = bounds
                return ((left + right) // 2, (top + bottom) // 2)
        return None

    def _comment_action_rail_hidden(self, xml: Optional[str] = None) -> bool:
        xml = self._xml() if xml is None else xml
        if not isinstance(xml, str) or not xml or any(resource_id in xml for resource_id in COMMENT_BUTTON_IDS):
            return False
        return self._player_layout_toggle_point(xml) is not None

    def _open_comment_after_layout_toggle(self) -> bool:
        # The reward widget can install a transparent Compose touch layer over
        # the comment bubble. Rebuilding the player layout can clear it. Back
        # is unsafe here because it exits ShortSeriesActivity to SearchActivity.
        toggle_point = self._player_layout_toggle_point()
        if not toggle_point:
            toggle_point = (int(self.width * 0.92), int(self.height * 0.955))
        self.d.click(*toggle_point)
        time.sleep(0.5)
        self.d.click(*toggle_point)
        time.sleep(0.5)

        xml = self._xml()
        comment_point = self._comment_button_point(xml)
        points = [comment_point] if comment_point else []
        points.extend(
            (int(self.width * 0.925), int(self.height * y_ratio))
            for y_ratio in (0.58, 0.60, 0.64, 0.67)
        )
        for point in points:
            if point is None:
                continue
            self.d.click(*point)
            for _ in range(4):
                time.sleep(0.4)
                xml = self._xml()
                if self._xiaoguo_ai_panel_open(xml):
                    self._close_xiaoguo_ai_panel(xml)
                    break
                if self._comment_panel_open(xml):
                    return True
        return False

    def _player_layout_toggle_point(self, xml: Optional[str] = None) -> Optional[tuple[int, int]]:
        xml = self._xml() if xml is None else xml
        for node in re.findall(r"<node\b[^>]+>", xml or ""):
            if 'resource-id="com.phoenix.read:id/e_o"' not in node:
                continue
            bounds = self._node_bounds(node)
            if not bounds:
                continue
            left, top, right, bottom = bounds
            if left >= self.width * 0.75 and top >= self.height * 0.82:
                return ((left + right) // 2, (top + bottom) // 2)
        return None

    def like_current_episode(self) -> Dict[str, Any]:
        return self._set_current_episode_engagement("like")

    def favorite_current_episode(self) -> Dict[str, Any]:
        return self._set_current_episode_engagement("favorite")

    def inspect_current_episode_engagement(self, action: str) -> Dict[str, Any]:
        labels = {"like": "点赞", "favorite": "收藏"}
        label = labels.get(action)
        if not label:
            return {"success": False, "selected": None, "message": "不支持的互动动作"}
        try:
            xml = self._xml()
            if (
                not self._short_series_activity_active()
                or not self._playback_visible(xml)
                or self._ad_continue_visible(xml)
            ):
                return {
                    "success": False,
                    "selected": None,
                    "message": f"当前不在可复核{label}的播放页",
                }
            point = self._engagement_control_point(action, xml)
            selected = self._engagement_selected_from_xml(action, xml)
            source = "控件"
            if selected is None:
                selected = self._engagement_selected_visual(action, point)
                source = "截图"
            if selected is None:
                detail = str(getattr(self, "_last_engagement_visual_error", "") or "")
                message = f"{label}状态不可读"
                if detail:
                    message = f"{message}: {detail}"
                return {"success": False, "selected": None, "message": message}
            return {
                "success": True,
                "selected": selected,
                "message": f"已通过{source}确认{label}{'已生效' if selected else '未生效'}",
            }
        except Exception as exc:
            return {"success": False, "selected": None, "message": f"复核{label}失败: {exc}"}

    def _set_current_episode_engagement(self, action: str) -> Dict[str, Any]:
        labels = {"like": "点赞", "favorite": "收藏"}
        label = labels.get(action)
        if not label:
            return {"success": False, "verified": False, "message": "不支持的互动动作"}
        click_sent = False
        try:
            if self._comment_panel_open():
                self._close_comment_panel()
                time.sleep(0.6)
            xml = self._xml()
            if (
                not self._short_series_activity_active()
                or not self._playback_visible(xml)
                or self._ad_continue_visible(xml)
            ):
                return {"success": False, "verified": False, "message": f"当前不在可{label}的播放页"}

            point = self._engagement_control_point(action, xml)
            selected = self._engagement_selected_from_xml(action, xml)
            if selected is None:
                selected = self._engagement_selected_visual(action, point)
            if selected is True:
                return {
                    "success": True,
                    "verified": True,
                    "already_active": True,
                    "message": "当前短剧已经收藏" if action == "favorite" else "当前视频已经点赞",
                }

            self.d.click(*point)
            click_sent = True
            after_xml = ""
            after_selected: Optional[bool] = None
            for _ in range(3):
                time.sleep(1)
                after_xml = self._xml()
                after_selected = self._engagement_selected_from_xml(action, after_xml)
                if after_selected is not True and self._engagement_selected_visual(action, point) is True:
                    after_selected = True
                if after_selected is True:
                    return {
                        "success": True,
                        "verified": True,
                        "already_active": False,
                        "click_sent": True,
                        "message": f"{label}成功",
                    }

            current = self._safe_app_current()
            still_playing = bool(
                current.get("package") == APP_PACKAGE
                and current.get("activity") == SHORT_SERIES_ACTIVITY
                and self._playback_visible(after_xml)
            )
            if after_selected is None and still_playing:
                detail = str(getattr(self, "_last_engagement_visual_error", "") or "")
                suffix = f": {detail}" if detail else ""
                return {
                    "success": True,
                    "verified": False,
                    "already_active": False,
                    "click_sent": True,
                    "message": f"{label}点击已发送，控件状态不可读{suffix}",
                }
            return {
                "success": False,
                "verified": False,
                "click_sent": True,
                "message": f"{label}后未检测到生效状态",
            }
        except Exception as exc:
            return {
                "success": False,
                "verified": False,
                "click_sent": click_sent,
                "message": f"{label}失败: {exc}",
            }

    def _engagement_control_point(self, action: str, xml: str) -> tuple[int, int]:
        markers = ("点赞", "赞") if action == "like" else ("收藏",)
        candidates: List[tuple[int, int, int, int]] = []
        for node in self._visible_hongguo_nodes(xml):
            values = " ".join(
                html.unescape(value)
                for value in re.findall(r'(?:text|content-desc|resource-id)="([^"]*)"', node)
            ).lower()
            if not any(marker in values for marker in markers):
                continue
            bounds = self._node_bounds(node)
            if not bounds:
                continue
            left, top, right, bottom = bounds
            center_x = (left + right) // 2
            center_y = (top + bottom) // 2
            if center_x < self.width * 0.72 or not self.height * 0.25 <= center_y <= self.height * 0.82:
                continue
            candidates.append(bounds)
        if candidates:
            target_y = self.height * (0.70 if action == "like" else 0.48)
            left, top, right, bottom = min(
                candidates,
                key=lambda bounds: abs(((bounds[1] + bounds[3]) // 2) - target_y),
            )
            return (left + right) // 2, (top + bottom) // 2
        return int(self.width * 0.925), int(self.height * (0.70 if action == "like" else 0.48))

    def _engagement_selected_from_xml(self, action: str, xml: str) -> Optional[bool]:
        selected_markers = ("取消点赞", "已点赞") if action == "like" else ("取消收藏", "已收藏")
        unselected_markers = ("点赞", "点赞按钮") if action == "like" else ("收藏", "收藏按钮")
        for node in self._visible_hongguo_nodes(xml):
            bounds = self._node_bounds(node)
            if not bounds or (bounds[0] + bounds[2]) // 2 < self.width * 0.72:
                continue
            values = {
                re.sub(r"\s+", "", html.unescape(value))
                for value in re.findall(r'(?:text|content-desc)="([^"]*)"', node)
                if value.strip()
            }
            if any(marker in value for marker in selected_markers for value in values):
                return True
            if any(value in unselected_markers for value in values):
                return False
        return None

    def _engagement_selected_visual(self, action: str, point: tuple[int, int]) -> Optional[bool]:
        image = None
        errors: List[str] = []
        self._last_engagement_visual_error = ""
        serial = getattr(self.d, "serial", None) or getattr(self.d, "_serial", None)
        if serial:
            try:
                import adbutils

                image = call_with_timeout(
                    lambda: adbutils.adb.device(serial).screenshot(),
                    8,
                    f"{action} adb state screenshot {serial}",
                )
            except Exception as exc:
                errors.append(f"ADB截图失败={exc}")
                image = None
        try:
            if image is None:
                image = call_with_timeout(
                    lambda: self.d.screenshot(),
                    8,
                    f"{action} uiautomator state screenshot",
                )
            image = image.convert("RGB")
        except Exception as exc:
            errors.append(f"uiautomator截图失败={exc}")
            self._last_engagement_visual_error = "；".join(errors)
            return None
        image_width, image_height = image.size
        center_x = int(point[0] * image_width / max(1, self.width))
        center_y = int(point[1] * image_height / max(1, self.height))
        radius_x = max(24, int(image_width * 0.055))
        radius_y = max(24, int(image_height * 0.035))
        crop = image.crop(
            (
                max(0, center_x - radius_x),
                max(0, center_y - radius_y),
                min(image_width, center_x + radius_x),
                min(image_height, center_y + radius_y),
            )
        )
        pixels = list(crop.getdata())
        if not pixels:
            return None
        bright_neutral = sum(
            1
            for red, green, blue in pixels
            if min(red, green, blue) >= 180
            and max(red, green, blue) - min(red, green, blue) <= 35
        )
        if action == "like":
            colored = sum(
                1 for red, green, blue in pixels
                if red >= 175 and green <= 145 and blue <= 165 and red - green >= 55
            )
        else:
            colored = sum(
                1 for red, green, blue in pixels
                if red >= 175 and green >= 105 and blue <= 125 and red - blue >= 65
            )
        # The video behind a white icon can itself be red or orange. A selected
        # control replaces the bright-white icon with color, so color must
        # dominate the neutral icon pixels instead of merely being present.
        return colored >= 18 and colored > bright_neutral

    def exit_fullscreen(self) -> bool:
        if not self._short_series_activity_active():
            return False
        xml = self._xml()
        if self._non_fullscreen_playback_controls_visible(xml):
            return False
        # A second Back can leave Hongguo entirely when controls do not appear
        # in the UI hierarchy immediately after exiting fullscreen.
        self.d.press("back")
        time.sleep(2)
        return True

    def _non_fullscreen_playback_controls_visible(self, xml: Optional[str] = None) -> bool:
        xml = xml or self._xml()
        if not xml:
            return False
        if any(resource_id in xml for resource_id in COMMENT_BUTTON_IDS):
            return True
        return any(marker in xml for marker in ("全屏观看", "选集", "合集", "有趣评论", "说点什么"))

    def prepare_comment_window(self, episode_number: int = 0) -> bool:
        if self._ad_continue_visible():
            self.skip_ad_if_present()
            time.sleep(2)
            if self._ad_continue_visible():
                if self._live_lite_activity_active():
                    self._close_live_lite_page()
                return False
        if self._live_lite_activity_active():
            if not self._close_live_lite_page():
                return False
            time.sleep(1)
        if self._episode_list_panel_open():
            if not self._close_episode_list_panel(episode_number):
                return False
        # Open the panel immediately so a near-complete episode cannot roll
        # into an ad while slower hierarchy checks are running.
        if self._open_comment_panel(0.5, prefer_coordinate=True):
            return True
        if self._ad_continue_visible():
            return False
        if episode_number:
            current = self.get_current_episode()
            if current and current != episode_number:
                return False
        self.pause_playback_if_playing()
        if self._open_comment_panel(3):
            return True
        if self._ad_continue_visible():
            return False
        if episode_number:
            current = self.get_current_episode()
            if current and current != episode_number:
                return False

        # Under multi-instance load the first coordinate tap can only reveal
        # Surface controls. Normalize the layout and make one final panel try.
        self.exit_fullscreen()
        self._reveal_playback_controls()
        time.sleep(0.8)
        if episode_number:
            current = self.get_current_episode()
            if current and current != episode_number:
                return False
        return self._open_comment_panel(5, prefer_coordinate=True)

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
                if self._login_prompt_visible():
                    return {"success": False, "message": "当前红果实例未登录，评论时已弹出登录页"}
                return {"success": False, "message": "未找到评论按钮"}
            self._sleep(2, 3)
            if self._login_prompt_visible():
                return {"success": False, "message": "当前红果实例未登录，评论时已弹出登录页"}
            if not self._comment_panel_open():
                return {"success": False, "message": "评论面板未打开"}
            input_found = self._focus_comment_input()
            if not input_found:
                return {"success": False, "message": "未找到评论输入框"}
            time.sleep(0.5)
            input_result: Dict[str, Any] = {"success": False, "actual_text": ""}
            try:
                inp = self.d(className="android.widget.EditText")
                if self._exists(inp, 1):
                    input_result = self._set_input_text(inp, content)
            except Exception:
                input_result = {"success": False, "actual_text": ""}
            if not input_result.get("success"):
                self._type_text(content)
                try:
                    inp = self.d(className="android.widget.EditText")
                    actual_text = self._read_input_text(inp)
                except Exception:
                    actual_text = ""
                if actual_text and not self._input_text_matches(content, actual_text):
                    return {"success": False, "message": f"评论输入不一致: {actual_text}"}
            self._sleep(0.8, 1.5)
            for text in ["发送", "发布", "发表"]:
                el = self.d(text=text)
                if self._exists(el, 2):
                    el.click()
                    self._sleep(2, 3)
                    if self._login_prompt_visible():
                        return {"success": False, "message": "当前红果实例未登录，评论发送被登录页拦截"}
                    return {"success": True, "message": "评论已发送"}
            return {"success": False, "message": "未找到评论发送按钮"}
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    def verify_comment(self, content: str, episode_number: int = 0, screenshot_dir: str = "") -> Dict[str, Any]:
        screenshot_path = ""
        try:
            if self._login_prompt_visible():
                return {
                    "verified": False,
                    "screenshot_path": screenshot_path,
                    "message": "当前红果实例未登录，无法验证评论",
                }
            panel_ready = self._comment_panel_open()
            if episode_number and not panel_ready and not self.ensure_playback_page(episode_number):
                time.sleep(1)
                if not self.ensure_playback_page(episode_number):
                    return {
                        "verified": False,
                        "screenshot_path": screenshot_path,
                        "message": f"未回到第{episode_number}集播放页",
                    }
            if not panel_ready and not self.prepare_comment_window(episode_number):
                return {"verified": False, "screenshot_path": "", "message": "未找到评论按钮"}
            self._sleep(2, 3)
            search_key = content[:8] if len(content) > 8 else content
            for attempt in range(4):
                if self._exists(self.d(textContains=search_key), 2) or search_key in self._xml():
                    if screenshot_dir:
                        screenshot_path = self.take_screenshot(
                            f"ep{episode_number or 'x'}_comment_list_verified",
                            screenshot_dir,
                        )
                    return {"verified": True, "screenshot_path": screenshot_path}
                if screenshot_dir:
                    screenshot_path = self.take_screenshot(f"ep{episode_number or 'x'}_comment_panel_scan", screenshot_dir)
                if attempt + 1 < 4:
                    self._close_comment_panel()
                    time.sleep(2)
                    if not self.prepare_comment_window(episode_number):
                        continue
                    self._sleep(2.5, 4)
            return {"verified": False, "screenshot_path": screenshot_path}
        except Exception as exc:
            return {"verified": False, "screenshot_path": screenshot_path, "message": str(exc)}
        finally:
            self._close_comment_panel()
            if episode_number and not self._login_prompt_visible():
                self.ensure_playback_page(episode_number)

    def take_screenshot(self, tag: str, screenshot_dir: str) -> str:
        ts = int(time.time() * 1000)
        safe_tag = re.sub(r"[^A-Za-z0-9_.-]+", "_", tag).strip("_") or "screen"
        path = Path(screenshot_dir) / f"{ts}_{safe_tag}.png"
        try:
            return screenshot(self.d, str(path))
        except Exception as exc:
            message = str(exc).lower()
            serial = getattr(self.d, "serial", None) or getattr(self.d, "_serial", None)
            if serial and any(marker in message for marker in ("offline", "timeout", "closed", "disconnect")):
                self.d = connect_exact(serial)
                self.width, self.height = self.d.window_size()
                time.sleep(1)
                return screenshot(self.d, str(path))
            raise

    def _open_profile_tab(self) -> bool:
        try:
            self._close_popups_quick()
            xml = self._xml()
            if self._hierarchy_empty(xml):
                if self._restart_uiautomator_server():
                    xml = self._xml()
            if self._profile_visible(xml):
                return True
            started_on_playback = self._short_series_activity_active()
            if started_on_playback:
                if not self._open_main_activity():
                    return False
                time.sleep(1)
            if not started_on_playback and not self._open_main_tabs():
                return False
            for _ in range(3):
                self._tap_bottom_tab("\u6211\u7684", 0.9)
                time.sleep(1)
                if self._profile_visible():
                    return True
            return self._profile_visible()
        except Exception:
            return False

    @staticmethod
    def _hierarchy_empty(xml: str) -> bool:
        value = str(xml or "").strip()
        return not value or "<node " not in value

    def _restart_uiautomator_server(self) -> bool:
        serial = str(getattr(self.d, "serial", "") or getattr(self.d, "_serial", "")).strip()
        if not serial or serial.startswith("<"):
            return False

        def restart() -> bool:
            response = self.d.shell(["ps", "-A", "-o", "PID,ARGS"], timeout=5)
            output = str(getattr(response, "output", response) or "")
            pids = []
            for line in output.splitlines():
                if "com.wetest.uia2.Main" not in line:
                    continue
                match = re.match(r"\s*(\d+)\s+", line)
                if match and match.group(1) not in pids:
                    pids.append(match.group(1))
            if pids:
                self.d.shell(["kill", "-9", *pids], timeout=5)
            time.sleep(0.5)
            self.d = connect_exact(serial)
            return True

        try:
            logger.warning("Hongguo uiautomator hierarchy empty; restarting server: addr=%s", serial)
            return bool(call_with_timeout(restart, 20, f"restart uiautomator {serial}"))
        except Exception as exc:
            logger.warning("Hongguo uiautomator restart failed: addr=%s error=%s", serial, exc)
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
        hongguo_xml = " ".join(self._visible_hongguo_nodes(xml))
        if any(marker in hongguo_xml for marker in markers):
            return True
        if not any(marker in xml for marker in markers):
            return False
        current = self._safe_app_current()
        return not current.get("activity") or current.get("activity") == "com.dragon.read.pages.main.MainFragmentActivity"

    def _open_main_tabs(self) -> bool:
        for _ in range(5):
            xml = self._xml()
            if any(label in xml for label in ("\u9996\u9875", "\u5267\u573a", "\u6211\u7684")):
                return True
            try:
                self.d.press("back")
            except Exception:
                pass
            time.sleep(1)
        try:
            self._start_app()
            time.sleep(2)
            xml = self._xml()
            return any(label in xml for label in ("\u9996\u9875", "\u5267\u573a", "\u6211\u7684"))
        except Exception:
            return False

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
        hongguo_pattern = r"\u7ea2\u679c\u53f7[:\uff1a\s]*([A-Za-z0-9_-]{5,32})"
        for text in [xml] + texts:
            match = re.search(hongguo_pattern, text)
            if match:
                return match.group(1).strip()
        for text in texts:
            match = re.fullmatch(r"(?:ID|id)[:\uff1a\s]*([A-Za-z0-9_-]{5,32})", text.strip())
            if match:
                return match.group(1).strip()
        for idx, text in enumerate(texts[:-1]):
            if "\u7ea2\u679c\u53f7" in text:
                candidate = texts[idx + 1].strip()
                if re.fullmatch(r"[A-Za-z0-9_-]{5,32}", candidate):
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
            "\u514d\u8d39",
            "\u77ed\u5267",
            "\u7ea2\u679c",
            "\u5c3d\u5728",
            "\u5b97\u5e08",
            "\u4e0b\u8f7d",
            "\u663e\u5361",
            "\u62bd",
            "\u770b\u5267",
            "get",
            "APP",
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
            if self._recover_anr_dialog():
                continue
            clicked = False
            for text in ["关闭", "跳过", "取消", "暂不加入", "以后再说", "我知道了", "同意"]:
                el = self.d(text=text) if text == "关闭" else self.d(textContains=text)
                if self._exists(el, 0.5):
                    el.click()
                    time.sleep(1)
                    clicked = True
                    break
            if not clicked:
                break
        if self._anr_dialog_visible():
            self._stop_app()
            time.sleep(2)
            self._start_app()
            self._wait_app_ready(20)

    def _close_popups_quick(self) -> None:
        xml = self._xml()
        if "没有响应" in xml or "isn't responding" in xml:
            self._recover_anr_dialog(timeout=5)
            xml = self._xml()
        for text in ["关闭", "跳过", "取消", "暂不加入", "以后再说", "我知道了", "同意"]:
            if text not in xml:
                continue
            el = self.d(text=text) if text == "关闭" else self.d(textContains=text)
            if self._exists(el, 0.3):
                el.click()
                time.sleep(0.6)
                return

    def _anr_dialog_visible(self) -> bool:
        wait_button = self.d(text="等待")
        if self._exists(wait_button, 0.5):
            return True
        wait_button = self.d(text="Wait")
        if self._exists(wait_button, 0.5):
            return True
        xml = self._xml()
        return "没有响应" in xml or "isn't responding" in xml

    def _recover_anr_dialog(self, timeout: float = 15) -> bool:
        """Keep Hongguo alive when Android reports an application-not-responding dialog."""
        wait_button = self.d(text="等待")
        if not self._exists(wait_button, 1):
            wait_button = self.d(text="Wait")
        wait_visible = self._exists(wait_button, 1)
        xml = self._xml()
        if not wait_visible and "没有响应" not in xml and "isn't responding" not in xml:
            return False
        if wait_visible:
            wait_button.click()
        deadline = time.time() + max(1, timeout)
        while time.time() < deadline:
            time.sleep(1)
            xml = self._xml()
            if "没有响应" not in xml and "isn't responding" not in xml:
                break
        return True

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
                current = self._safe_app_current()
                xml = self._xml()
                app_visible = self._first_visible_package(xml) == APP_PACKAGE or self._has_large_hongguo_window(xml)
                if current.get("package") == APP_PACKAGE and app_visible and any(text in xml for text in ready_markers):
                    return True
                if current.get("package") == APP_PACKAGE and (
                    app_visible or bool(current.get("activity"))
                ):
                    return True
            except Exception:
                pass
            time.sleep(1)
        return False

    def _is_app_foreground(self) -> bool:
        try:
            current = self._safe_app_current()
            xml = self._xml()
            return self._is_app_foreground_from_state(current, xml)
        except Exception:
            return False

    def _is_app_foreground_from_state(self, current: Dict[str, Any], xml: str) -> bool:
        if current.get("package") and current.get("package") != APP_PACKAGE:
            return False
        first_package = self._first_visible_package(xml)
        if current.get("package") == APP_PACKAGE:
            if (
                self._launcher_visible(xml)
                and current.get("activity") != SHORT_SERIES_ACTIVITY
                and not self._has_large_hongguo_window(xml)
            ):
                return False
            if current.get("activity"):
                return True
            if first_package == APP_PACKAGE:
                return True
            return self._has_large_hongguo_window(xml) or self._has_hongguo_business_nodes(xml)
        if first_package == APP_PACKAGE:
            return True
        if self._has_large_hongguo_window(xml):
            return True
        if first_package and first_package != APP_PACKAGE:
            return False
        if not current.get("package") and not first_package and any(
            marker in xml for marker in ("正在播放", "当前播放", "更新至", "第")
        ):
            return True
        return self._has_hongguo_business_nodes(xml) and self._hongguo_visible_area_ratio(xml) >= 0.2

    def _safe_app_current(self) -> Dict[str, Any]:
        try:
            return call_with_timeout(lambda: self.d.app_current() or {}, 7, "app current")
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
        for node in self._visible_hongguo_nodes(xml):
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
        for node in self._visible_hongguo_nodes(xml):
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
            call_with_timeout(lambda: self.d.app_start(APP_PACKAGE), 5, "app start")
        except Exception:
            pass
        try:
            call_with_timeout(
                lambda: self.d.shell(f"am start -n {APP_PACKAGE}/com.dragon.read.pages.splash.SplashActivity"),
                5,
                "am start",
            )
        except Exception:
            pass
        try:
            call_with_timeout(
                lambda: self.d.shell(f"monkey -p {APP_PACKAGE} -c android.intent.category.LAUNCHER 1"),
                5,
                "monkey start",
            )
        except Exception:
            pass

    def _stop_app(self) -> None:
        try:
            call_with_timeout(lambda: self.d.app_stop(APP_PACKAGE), 5, "app stop")
        except Exception:
            pass
        try:
            call_with_timeout(lambda: self.d.shell(f"am force-stop {APP_PACKAGE}"), 5, "am force-stop")
        except Exception:
            pass

    def _open_theater(self) -> None:
        for _ in range(3):
            xml = self._xml()
            if any(text in xml for text in ["首页", "剧场", "我的"]):
                break
            self.d.press("back")
            time.sleep(1)
        self._tap_bottom_tab("剧场", 0.37)
        time.sleep(2)
        self._close_popups_quick()

    def _tap_bottom_tab(self, label: str, x_ratio: float) -> None:
        selector = self.d(text=label)
        clicked = False
        if self._exists(selector, 1):
            try:
                selector.click()
                clicked = True
            except Exception:
                clicked = False
        if not clicked:
            self.d.click(int(self.width * x_ratio), int(self.height * 0.965))
        time.sleep(1.2)
        self._close_popups_quick()

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
        for x_ratio, y_ratio in (
            (0.35, 0.04),
            (0.50, 0.06),
            (0.90, 0.06),
            (0.94, 0.38),
        ):
            self.d.click(int(self.width * x_ratio), int(self.height * y_ratio))
            time.sleep(1)
            if self._exists(self.d(className="android.widget.EditText"), 2):
                return True
        return False

    def _click_first_search_suggestion(self) -> bool:
        xml = self._xml()
        if "即将上线" not in xml and "万热度" not in xml and "播放" not in xml:
            return False
        # The first playable suggestion sits below the search bar. Avoid the second row, which
        # often represents a reserved/upcoming season.
        self.d.click(int(self.width * 0.38), int(self.height * 0.105))
        time.sleep(1)
        return True

    def _current_playing_title(self, xml: Optional[str] = None) -> str:
        xml = xml if xml is not None else self._xml()
        for pattern in [
            r"合集 · ([^·\n<\"]+) ·",
        ]:
            match = re.search(pattern, xml)
            if match:
                return match.group(1).strip("《》 ")
        return ""

    def _click_first_play_button(self) -> bool:
        for text in ["立即观看", "开始播放", "播放全部", "看全集"]:
            for el in (self.d(text=text), self.d(textContains=text)):
                if not self._exists(el, 1):
                    continue
                try:
                    count = el.count
                    for i in range(count):
                        info = el[i].info
                        bounds = info.get("bounds", {}) or {}
                        top = int(bounds.get("top", 0) or 0)
                        bottom = int(bounds.get("bottom", 0) or 0)
                        left = int(bounds.get("left", 0) or 0)
                        right = int(bounds.get("right", 0) or 0)
                        if bottom <= self.height * 0.12 or top >= self.height * 0.92:
                            continue
                        if right <= self.width * 0.12 or left >= self.width * 0.96:
                            continue
                        el[i].click()
                        return True
                except Exception:
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
            bounds = self._node_bounds(node)
            if bounds and bounds[3] <= self.height * 0.12:
                continue
            if 'class="android.widget.EditText"' in node:
                continue
            text = html.unescape(text_match.group(1)).strip()
            if self._is_title_candidate(text) and text not in seen:
                titles.append(text)
                seen.add(text)
        aliases = self._title_aliases_from_search_titles(titles)
        if aliases:
            # Result-page extraction can run more than once while the UI is
            # settling. Preserve a discovered alias if a later hierarchy
            # snapshot temporarily omits the "原名" row.
            self._search_title_aliases.update(aliases)
        return titles

    def _title_aliases_from_search_titles(self, titles: List[str]) -> Dict[str, str]:
        aliases: Dict[str, str] = {}
        for index, value in enumerate(titles):
            match = re.match(r"原名\s*[:：]\s*(.+)$", str(value or "").strip())
            if not match:
                continue
            alias_key = self._normalize_title_key(match.group(1))
            if not alias_key:
                continue
            canonical = ""
            for candidate in reversed(titles[:index]):
                candidate = str(candidate or "").strip()
                if candidate and not re.match(r"原名\s*[:：]", candidate):
                    canonical = candidate
                    break
            canonical_key = self._normalize_title_key(canonical)
            if canonical_key:
                aliases[alias_key] = canonical_key
        return aliases

    def _hongguo_nodes(self, xml: str) -> List[str]:
        return [node for node in re.findall(r"<node\b[^>]+>", xml or "") if f'package="{APP_PACKAGE}"' in node]

    def _visible_hongguo_nodes(self, xml: str) -> List[str]:
        return [node for node in self._hongguo_nodes(xml) if 'visible-to-user="false"' not in node]

    def _click_matching_title(self, title: str, expected: str = "") -> bool:
        target = str(title or "").strip("《》 ")
        if not target:
            return False
        target_key = self._normalize_title_key(target)
        xml = self._xml()
        matches: List[tuple[int, int, int, int, str]] = []
        for node in self._visible_hongguo_nodes(xml):
            if 'class="android.widget.EditText"' in node:
                continue
            text_match = re.search(r'text="([^"]*)"', node)
            bounds_match = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', node)
            if not text_match or not bounds_match:
                continue
            node_text = html.unescape(text_match.group(1)).strip()
            if not node_text:
                continue
            if self._normalize_title_key(node_text) != target_key:
                continue
            left, top, right, bottom = (int(value) for value in bounds_match.groups())
            if top < self.height * 0.18:
                continue
            if bottom <= top or right <= left or top >= self.height or left >= self.width:
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
        self.d.click((left + right) // 2, (top + bottom) // 2)
        return True

    def _result_card_bounds(
        self, title_bounds: tuple[int, int, int, int], xml: str
    ) -> Optional[tuple[int, int, int, int]]:
        """Find the poster/card immediately associated with one visible result title."""
        candidates: List[tuple[tuple[int, int, int], tuple[int, int, int, int]]] = []
        title_left, title_top, title_right, _ = title_bounds
        for node in self._visible_hongguo_nodes(xml):
            if "ImageView" not in node and "FrameLayout" not in node:
                continue
            bounds = self._node_bounds(node)
            if not bounds:
                continue
            left, top, right, bottom = bounds
            width = right - left
            height = bottom - top
            if width < self.width * 0.15 or width > self.width * 0.62 or height < self.height * 0.16:
                continue
            horizontal_overlap = max(0, min(right, title_right) - max(left, title_left))
            if horizontal_overlap / max(1, min(width, title_right - title_left)) < 0.6:
                continue
            vertical_gap = title_top - bottom
            if vertical_gap < -80 or vertical_gap > self.height * 0.18:
                continue
            candidates.append(((abs(vertical_gap), -height, left), bounds))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0])
        return candidates[0][1]

    def _click_matching_result_card(self, title: str, expected: str = "") -> bool:
        target = str(title or "").strip("銆娿€?")
        expected_key = self._normalize_title_key(expected or target)
        if not target and not expected_key:
            return False
        xml = self._xml()
        matches: List[tuple[int, int, int, int, str]] = []
        for node in self._hongguo_nodes(xml):
            text_match = re.search(r'text="([^"]*)"', node)
            bounds = self._node_bounds(node)
            if not text_match or not bounds:
                continue
            node_text = html.unescape(text_match.group(1)).strip()
            if not node_text:
                continue
            if expected and not self._strict_title_matches(expected, node_text):
                continue
            if target and node_text != target and target not in node_text and not self._title_matches(expected or target, node_text):
                continue
            left, top, right, bottom = bounds
            if bottom <= self.height * 0.12:
                continue
            matches.append((left, top, right, bottom, node_text))
        if not matches:
            return False
        matches.sort(
            key=lambda item: (
                self._normalize_title_key(item[4]) != self._normalize_title_key(target),
                not self._normalize_title_key(item[4]).startswith(expected_key),
                item[1],
            )
        )
        left, top, right, bottom, _ = matches[0]
        card_bounds = self._result_card_bounds((left, top, right, bottom), xml)
        if card_bounds:
            card_left, card_top, card_right, card_bottom = card_bounds
            self.d.click(
                (card_left + card_right) // 2,
                int(card_top + (card_bottom - card_top) * 0.45),
            )
            time.sleep(0.8)
            if not self._search_results_visible(self._xml()):
                return True
        y = (top + bottom) // 2
        click_points = [
            ((left + right) // 2, y),
            (max(40, left - int(self.width * 0.08)), y),
            (int(self.width * 0.18), y),
            (int(self.width * 0.32), y),
        ]
        for x, y_pos in click_points:
            self.d.click(max(10, min(self.width - 10, x)), max(10, min(self.height - 10, y_pos)))
            time.sleep(0.8)
            if not self._search_results_visible(self._xml()):
                return True
        return True

    def _try_unlabeled_poster_results(self, expected: str) -> Optional[Dict[str, Any]]:
        candidates = self._unlabeled_poster_candidates(expected)
        if not candidates:
            return None
        for candidate in candidates[:6]:
            xml = self._xml()
            if not self._search_results_visible(xml):
                return None
            left, top, right, bottom = candidate["bounds"]
            self.d.click((left + right) // 2, int(top + (bottom - top) * 0.45))
            self._sleep(2.5, 4)
            if not self._is_app_foreground():
                return {
                    "success": False,
                    "drama_title": "",
                    "playable": False,
                    "message": "点击无文字海报后离开红果 App，已取消",
                }
            drama_title = self._extract_detail_title(expected)
            if drama_title and self._strict_title_matches(expected, drama_title):
                result = self._drama_detail_result(drama_title, expected)
                result["message"] = "已通过无文字海报进入短剧详情"
                result["poster_fallback"] = True
                result["poster_bounds"] = candidate["bounds"]
                return result
            self.d.press("back")
            self._sleep(1.2, 2)
        return None

    def _unlabeled_poster_candidates(self, expected: str) -> List[Dict[str, Any]]:
        expected_key = self._normalize_title_key(expected)
        if not expected_key or self._season_marker(expected_key) or self._has_variant_marker(expected_key):
            return []
        xml = self._xml()
        if not self._search_results_visible(xml):
            return []
        nodes = self._hongguo_nodes(xml)
        text_items: List[tuple[str, tuple[int, int, int, int]]] = []
        heat_items: List[tuple[float, tuple[int, int, int, int]]] = []
        for node in nodes:
            bounds = self._node_bounds(node)
            if not bounds:
                continue
            text_match = re.search(r'text="([^"]*)"', node)
            text = html.unescape(text_match.group(1)).strip() if text_match else ""
            if not text:
                continue
            text_items.append((text, bounds))
            heat_match = re.fullmatch(r"(\d+(?:\.\d+)?)万热度", text)
            if heat_match:
                heat_items.append((float(heat_match.group(1)), bounds))

        raw_bounds: List[tuple[int, int, int, int]] = []
        for node in nodes:
            if "ImageView" not in node and "FrameLayout" not in node:
                continue
            bounds = self._node_bounds(node)
            if not bounds:
                continue
            left, top, right, bottom = bounds
            width = right - left
            height = bottom - top
            if top < self.height * 0.28:
                continue
            if width < self.width * 0.32 or width > self.width * 0.62:
                continue
            if height < self.height * 0.24:
                continue
            raw_bounds.append(bounds)

        deduped: List[tuple[int, int, int, int]] = []
        seen = set()
        for bounds in sorted(raw_bounds, key=lambda item: ((item[2] - item[0]) * (item[3] - item[1]), item[1]), reverse=True):
            key = tuple(round(value / 8) for value in bounds)
            if key in seen:
                continue
            seen.add(key)
            if any(self._bounds_overlap_ratio(bounds, old) > 0.9 for old in deduped):
                continue
            deduped.append(bounds)

        candidates: List[Dict[str, Any]] = []
        for bounds in deduped:
            left, top, right, bottom = bounds
            related_texts = [
                text
                for text, text_bounds in text_items
                if self._horizontal_overlap_ratio(bounds, text_bounds) >= 0.35
                and top - 80 <= text_bounds[1] <= bottom + 160
            ]
            visible_titles = [text for text in related_texts if self._looks_like_specific_title(text)]
            if visible_titles:
                continue
            related_heat = [
                (value, heat_bounds)
                for value, heat_bounds in heat_items
                if self._horizontal_overlap_ratio(bounds, heat_bounds) >= 0.35
                and top <= heat_bounds[1] <= bottom + 30
            ]
            if not related_heat:
                continue
            tag_bonus = any(text in {"爆剧", "热播", "独家", "新剧"} for text in related_texts)
            max_heat = max(value for value, _ in related_heat)
            candidates.append(
                {
                    "bounds": bounds,
                    "score": (0 if tag_bonus else 1, -max_heat, top, left),
                    "texts": related_texts,
                }
            )
        candidates.sort(key=lambda item: item["score"])
        return candidates

    def _horizontal_overlap_ratio(self, a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
        overlap = max(0, min(a[2], b[2]) - max(a[0], b[0]))
        return overlap / max(1, min(a[2] - a[0], b[2] - b[0]))

    def _bounds_overlap_ratio(self, a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
        left = max(a[0], b[0])
        top = max(a[1], b[1])
        right = min(a[2], b[2])
        bottom = min(a[3], b[3])
        overlap = max(0, right - left) * max(0, bottom - top)
        area = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
        return overlap / max(1, area)

    def _extract_detail_title(self, expected: str = "", xml: Optional[str] = None) -> str:
        xml = xml if xml is not None else self._xml()
        current_title = self._current_playing_title(xml)
        if current_title and (not expected or self._title_matches(expected, current_title)):
            return current_title
        # On the playback surface the current collection title is exposed as
        # id/d4, while the same hierarchy may also contain a next-season
        # recommendation. Prefer the current title node before parsing
        # recommendation text such as "即将播放下一季《...2...》".
        for node in self._visible_hongguo_nodes(xml):
            if 'resource-id="com.phoenix.read:id/d4"' not in node:
                continue
            text_match = re.search(r'text="([^"]+)"', node)
            if not text_match:
                continue
            candidate = html.unescape(text_match.group(1)).strip()
            if self._is_title_candidate(candidate) and (
                not expected or self._title_matches(expected, candidate)
            ):
                return candidate
        candidates: List[str] = []
        seen = set()
        node_text = " ".join(
            node
            for node in self._hongguo_nodes(xml)
            if "同系列剧" not in html.unescape(node)
        )
        for candidate in re.findall(r"\u300a([^\u300b]{2,25})\u300b", node_text):
            candidate = html.unescape(candidate).strip()
            if "即将播放下一季" in node_text:
                continue
            if self._is_title_candidate(candidate) and candidate not in seen:
                candidates.append(candidate)
                seen.add(candidate)
        for pattern in [
            r'text="([^"]{2,25})"[^>]*bounds="\[24,\d+\]\[\d+,\d+\]"',
            r'text="([^"]{4,25})"',
        ]:
            for candidate in re.findall(pattern, node_text):
                candidate = html.unescape(candidate).strip()
                if "即将播放下一季" in candidate:
                    continue
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
        keyword_has_variant = bool(self._season_marker(keyword_key) or self._has_variant_marker(keyword_key))
        exact = [title for title in matches if self._normalize_title_key(title) == keyword_key]
        extended = [
            title
            for title in matches
            if self._normalize_title_key(title).startswith(keyword_key)
            and self._normalize_title_key(title) != keyword_key
            and self._looks_like_specific_title(title)
        ]
        if keyword_has_variant:
            canonical = [
                title
                for title in matches
                if re.search(r"第[一二三四五六七八九十\d]+季", self._normalize_title_key(title))
                and self._season_marker(self._normalize_title_key(title)) == self._season_marker(keyword_key)
                and self._title_stem(self._normalize_title_key(title)) == self._title_stem(keyword_key)
            ]
            if canonical:
                return min(canonical, key=lambda value: len(self._normalize_title_key(value)))
            if extended:
                return max(extended, key=lambda value: len(self._normalize_title_key(value)))
            if exact:
                return exact[0]
            return matches[0]
        if exact:
            return exact[0]

        ranked: List[tuple[tuple[int, int, int], str]] = []
        for index, title in enumerate(matches):
            title_key = self._normalize_title_key(title)
            if not title_key.startswith(keyword_key):
                continue
            suffix = title_key[len(keyword_key) :]
            numeric_installment = re.match(r"(\d+)", suffix)
            if numeric_installment:
                if int(numeric_installment.group(1)) != 1:
                    continue
                rank = 1
                ranked.append(((rank, index, -len(title_key)), title))
                continue
            season = self._season_marker(title_key)
            has_variant = self._has_variant_marker(title_key)
            if season and season != "1":
                continue
            if season == "1":
                rank = 1
            elif has_variant:
                rank = 3
            else:
                rank = 2
            ranked.append(((rank, index, -len(title_key)), title))
        if ranked:
            ranked.sort(key=lambda item: item[0])
            return ranked[0][1]
        return ""

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
        if self._search_title_aliases.get(title_key) == keyword_key:
            return True
        if keyword_key == title_key:
            return True
        if title_key.startswith(keyword_key):
            if keyword_key[-1:].isdigit() and title_key[len(keyword_key) : len(keyword_key) + 1].isdigit():
                return False
            return True
        season = self._season_marker(keyword_key)
        if season:
            if self._season_marker(title_key) != season:
                return False
            return self._season_stem_matches(keyword_key, title_key)
        if self._has_variant_marker(keyword_key) and not self._has_variant_marker(title_key):
            return False
        return title_key in keyword_key and len(title_key) >= 4

    def _strict_title_matches(self, keyword: str, title: str) -> bool:
        if self._looks_like_non_drama_result(title):
            return False
        keyword_key = self._normalize_title_key(keyword)
        title_key = self._normalize_title_key(title)
        if not keyword_key or not title_key:
            return False
        if self._search_title_aliases.get(title_key) == keyword_key:
            return True
        if self._season_marker(keyword_key):
            return self._title_matches(keyword, title)
        if self._has_variant_marker(keyword_key):
            if title_key == keyword_key:
                return True
            if title_key.startswith(keyword_key):
                if keyword_key[-1:].isdigit() and title_key[len(keyword_key) : len(keyword_key) + 1].isdigit():
                    return False
                return True
            return False
        title_season = self._season_marker(title_key)
        if title_season:
            return title_season == "1" and title_key.startswith(keyword_key)
        if title_key.startswith(keyword_key) and len(title_key) > len(keyword_key):
            suffix = title_key[len(keyword_key) :]
            if suffix[:1].isdigit():
                return suffix[:1] == "1" and not suffix[1:2].isdigit()
        if self._has_variant_marker(title_key):
            return False
        if title_key.startswith(keyword_key) and len(title_key) > len(keyword_key):
            suffix = title_key[len(keyword_key) :]
        return self._title_matches(keyword, title)

    def _normalize_title_key(self, value: str) -> str:
        text = unicodedata.normalize("NFKC", str(value or "")).replace("⻣", "骨")
        return re.sub(r"[\s《》<>:：·,，。.!！?？\-_/\\]+", "", text.lower())

    def _looks_like_non_drama_result(self, text: str) -> bool:
        text = html.unescape(str(text or "")).strip()
        if len(text) > 32:
            return True
        if "#" in text:
            return True
        if "《" in text and "》" in text:
            before, remainder = text.split("《", 1)
            _, after = remainder.split("》", 1)
            if before.strip() or after.strip():
                return True
        non_drama_markers = (
            "即将上线",
            "预告",
            "预约",
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
        if match:
            return self._canonical_season_number(match.group(1))
        shorthand = re.search(r"(.+?)([1-9])$", value)
        return shorthand.group(2) if shorthand else ""

    def _season_stem_matches(self, keyword_key: str, title_key: str) -> bool:
        keyword_stem = self._title_stem(keyword_key)
        title_stem = self._title_stem(title_key)
        if not keyword_stem or not title_stem:
            return False
        return keyword_stem in title_stem or title_stem in keyword_stem

    def _title_stem(self, value: str) -> str:
        stem = re.sub(r"第[一二三四五六七八九十\d]+季", "", value)
        return re.sub(r"([^\d])([1-9])$", r"\1", stem)

    def _canonical_season_number(self, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        if text.isdigit():
            return str(int(text))
        digits = {
            "零": 0,
            "一": 1,
            "二": 2,
            "两": 2,
            "三": 3,
            "四": 4,
            "五": 5,
            "六": 6,
            "七": 7,
            "八": 8,
            "九": 9,
        }
        if text == "十":
            return "10"
        if text.startswith("十") and len(text) == 2:
            return str(10 + digits.get(text[1], 0))
        if text.endswith("十") and len(text) == 2:
            return str(digits.get(text[0], 0) * 10)
        if "十" in text and len(text) == 3:
            return str(digits.get(text[0], 0) * 10 + digits.get(text[2], 0))
        if len(text) == 1 and text in digits:
            return str(digits[text])
        return text

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

    def _xiaoguo_ai_panel_open(self, xml: Optional[str] = None) -> bool:
        xml = self._xml() if xml is None else xml
        return "小果AI" in xml and any(marker in xml for marker in ("还想了解什么", "发送"))

    def _close_xiaoguo_ai_panel(self, xml: Optional[str] = None) -> bool:
        xml = self._xml() if xml is None else xml
        if not self._xiaoguo_ai_panel_open(xml):
            return False
        try:
            self.d.press("back")
            time.sleep(0.8)
        except Exception:
            return False
        return not self._xiaoguo_ai_panel_open()

    def _comment_panel_open(self, xml: Optional[str] = None) -> bool:
        xml = self._xml() if xml is None else xml
        if self._xiaoguo_ai_panel_open(xml):
            return False
        return any(text in xml for text in ["有趣评论", "说点什么", "条评论", "写评论"])

    def _login_prompt_visible(self, xml: Optional[str] = None) -> bool:
        current = self._safe_app_current()
        if current.get("activity") == "com.dragon.read.component.biz.impl.mine.LoginActivity":
            return True
        xml = xml if xml is not None else self._xml()
        markers = ("请输入您的手机号", "获取验证码", "微信登录", "抖音登录")
        return any(marker in xml for marker in markers)

    def _close_comment_panel(self) -> bool:
        if not self._comment_panel_open():
            return False
        self.d.press("back")
        time.sleep(1)
        return True

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
            ("tap_search_button", lambda: self.d.click(int(self.width * 0.93), int(self.height * 0.042))),
            ("press_enter", lambda: self.d.press("enter")),
            ("keyevent_enter", lambda: self.d.shell("input keyevent 66")),
            ("press_search", lambda: self.d.press("search")),
            ("keyevent_search", lambda: self.d.shell("input keyevent 84")),
            ("tap_search_icon", lambda: self.d.click(int(self.width * 0.9), int(self.height * 0.042))),
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
            "success": False,
            "actions": actions,
            "app_foreground": self._is_app_foreground(),
            "tabs_visible": self._search_results_visible(xml),
            "candidate_visible": candidate_visible,
            "message": "已展示搜索候选结果，但未进入搜索结果页 tabs" if candidate_visible else "已填写关键词，但未进入搜索结果页",
        }

    def _wait_search_results_page(self, keyword: str, timeout: float = 8) -> Dict[str, Any]:
        deadline = time.time() + timeout
        last_xml = ""
        foreground_misses = 0
        while time.time() < deadline:
            if not self._is_app_foreground():
                foreground_misses += 1
                if foreground_misses >= 4:
                    current = self._safe_app_current()
                    package = str(current.get("package") or "unknown")
                    return {
                        "success": False,
                        "app_foreground": False,
                        "current_package": package,
                        "message": f"提交搜索后离开红果 App，当前包={package}",
                    }
                time.sleep(0.5)
                continue
            foreground_misses = 0
            last_xml = self._xml()
            if self._search_results_visible(last_xml):
                return {"success": True, "app_foreground": True, "tabs_visible": True, "message": "已进入搜索结果页"}
            time.sleep(0.5)
        candidate_visible = self._candidate_results_visible(keyword, last_xml)
        return {
            "success": False,
            "app_foreground": self._is_app_foreground(),
            "tabs_visible": self._search_results_visible(last_xml),
            "candidate_visible": candidate_visible,
            "message": "已展示搜索候选结果，但未进入搜索结果页 tabs" if candidate_visible else "提交搜索后未看到结果页 tabs",
        }

    def _search_results_visible(self, xml: str = "") -> bool:
        text = " ".join(self._visible_hongguo_nodes(xml or self._xml()))
        tab_hits = sum(1 for marker in ("综合", "短剧", "影视", "用户") if marker in text)
        return tab_hits >= 2 and any(marker in text for marker in ("搜索", "剧场", "播放", "热度", "全部"))

    def _candidate_results_visible(self, keyword: str, xml: str = "") -> bool:
        if not keyword:
            return False
        text = xml or self._xml()
        if not self._is_app_foreground():
            return False
        return bool(self._choose_title(keyword, self._extract_drama_titles_from_xml(text)))

    def _search_candidate_page_visible(self, xml: str = "") -> bool:
        text = " ".join(self._visible_hongguo_nodes(xml or self._xml()))
        if self._search_results_visible(text):
            return False
        has_input = 'class="android.widget.EditText"' in text
        has_top_search_button = False
        for node in re.findall(r"<node\b[^>]+>", text):
            if 'text="搜索"' not in node:
                continue
            bounds = self._node_bounds(node)
            if bounds and bounds[0] >= self.width * 0.65 and bounds[3] <= self.height * 0.18:
                has_top_search_button = True
                break
        return has_input and has_top_search_button

    def _click_visible_search_button(self) -> None:
        xml = self._xml()
        for node in re.findall(r"<node\b[^>]+>", xml):
            if (
                'package="com.phoenix.read"' not in node
                or 'visible-to-user="false"' in node
                or 'text="搜索"' not in node
            ):
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
        if self._paste_text(value):
            return
        for char in value:
            try:
                self.d.send_keys(char, clear=False)
            except TypeError:
                try:
                    self.d.send_keys(char)
                except Exception:
                    if not self._paste_text(char):
                        raise
            except Exception:
                if not self._paste_text(char):
                    raise
            time.sleep(random.uniform(0.02, 0.08))

    def _paste_text(self, text: str) -> bool:
        value = str(text or "")
        if not value:
            return True
        try:
            self.d.set_clipboard(value)
            time.sleep(0.2)
            try:
                self.d.shell("input keyevent 279")
            except Exception:
                self.d.press("paste")
            time.sleep(0.3)
            return True
        except Exception:
            return False

    def _exists(self, el: Any, timeout: float = 3) -> bool:
        try:
            # A selector timeout does not bound a wedged uiautomator HTTP call.
            return bool(
                call_with_timeout(
                    lambda: el.exists(timeout=timeout),
                    max(1.0, float(timeout) + 2.0),
                    "element exists",
                )
            )
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
            return call_with_timeout(lambda: self.d.dump_hierarchy(), 5, "dump hierarchy")
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
        start_y = int(self.height * 0.96)
        end_y = int(self.height * 0.18)
        self.d.swipe(cx, start_y, cx + random.randint(-8, 8), end_y, duration=0.75)

    def _swipe_up_continue_ad_shell(self) -> None:
        cx = self.width // 2 + random.randint(-20, 20)
        start_y = int(self.height * 0.92)
        end_y = int(self.height * 0.16)
        try:
            self.d.shell(f"input swipe {cx} {start_y} {cx + random.randint(-8, 8)} {end_y} 650")
        except Exception:
            pass

    def _swipe_down(self, distance: float = 0.5) -> None:
        cx = self.width // 2 + random.randint(-30, 30)
        start_y = int(self.height * 0.35)
        end_y = min(self.height - 50, int(start_y + self.height * distance))
        self.d.swipe(cx, start_y, cx + random.randint(-10, 10), end_y, duration=0.4)
