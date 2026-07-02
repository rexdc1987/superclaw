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
PROMO_POPUP_MARKERS = (
    "点击观看",
    "爆剧续作",
    "聚宝仙盆",
    "杂灵根才是真BOSS",
    "看剧赚钱",
    "继续观看",
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


class HongguoOperations:
    def __init__(self, device: Any):
        self.d = device
        try:
            self.width, self.height = self.d.window_size()
        except Exception:
            self.width, self.height = 1080, 1920

    def launch_app(self, force_restart: bool = False) -> bool:
        try:
            if not force_restart and self._is_app_foreground() and self._wait_app_ready(2):
                self._close_popups()
                return True
            for attempt in range(2):
                self._stop_app()
                time.sleep(2)
                self._start_app()
                if self._wait_app_ready(12 if attempt == 0 else 8):
                    self._close_popups()
                    return True
                if self._foreground_app_active():
                    return True
            if self._foreground_app_usable():
                self._close_popups()
                return True
            return False
        except Exception:
            return False

    def ensure_app_ready(self, restart: bool = False, timeout: float = 12) -> bool:
        try:
            if restart:
                return self._restart_app(timeout=timeout)
            if self._is_app_foreground() and self._wait_app_ready(min(timeout, 4)):
                self._close_popups()
                return True
            if self._move_app_stack_to_default_display() and self._wait_app_ready(min(timeout, 4)):
                self._close_popups()
                return True
            self._start_app()
            if self._wait_app_ready(timeout):
                self._close_popups()
                return True
            if self._move_app_stack_to_default_display() and self._wait_app_ready(min(timeout, 4)):
                self._close_popups()
                return True
            return False
        except Exception:
            return False

    def check_login(self, close_popups: bool = True) -> Dict[str, Any]:
        try:
            if self._definitely_not_hongguo_surface():
                if not self.ensure_app_ready(restart=True, timeout=12):
                    return {"logged_in": False, "status": "unknown", "message": "红果未进入可识别页面"}
            if close_popups:
                self._close_popups()
            xml = self._xml()
            if self._follow_fans_page_visible(xml):
                self._back_from_follow_fans_page()
                xml = self._xml()
            quick_status = self._login_status_from_xml(xml)
            if quick_status:
                return quick_status
            if self._playback_visible(xml):
                return {"logged_in": False, "status": "playback_only", "message": "红果播放页可用，未确认账号登录"}
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
            status = self._login_status_from_xml(xml)
            if not status and self._follow_fans_page_visible(xml):
                self._back_from_follow_fans_page()
                xml = self._xml()
                status = self._login_status_from_xml(xml)
            if status:
                return status
            if self._playback_visible(xml):
                return {"logged_in": False, "status": "playback_only", "message": "红果播放页可用，未确认账号登录"}
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
            if not self._open_profile_tab():
                result["message"] = "未进入红果我的页面，未读取账号信息"
                return result
            xml = self._xml()
            if self._follow_fans_page_visible(xml):
                if self._back_from_follow_fans_page():
                    xml = self._xml()
            if not self._profile_visible(xml):
                result["message"] = "未进入红果我的页面，未读取账号信息"
                return result
            texts = self._extract_xml_texts(xml)
            hongguo_id = self._extract_hongguo_id(texts, xml)
            nickname = self._extract_account_nickname(texts)
            if self._is_promo_account_text(nickname) or self._is_promo_account_text(hongguo_id):
                hongguo_id = ""
                nickname = ""
            login_prompts = (
                "\u767b\u5f55",
                "\u624b\u673a\u53f7",
                "\u5fae\u4fe1\u767b\u5f55",
                "\u6296\u97f3\u767b\u5f55",
            )
            login_prompt_visible = any(prompt in xml for prompt in login_prompts)
            if login_prompt_visible:
                nickname = ""
            has_account_profile = "\u7f16\u8f91\u8d44\u6599" in xml and bool(nickname)
            logged_in_marker_visible = self._logged_in_marker_visible(xml)
            logged_in = bool(hongguo_id or (has_account_profile and not login_prompt_visible) or (logged_in_marker_visible and not login_prompt_visible))
            if not logged_in and login_prompt_visible:
                result["message"] = "\u7ea2\u679c\u672a\u767b\u5f55"
            elif logged_in:
                result["message"] = "\u5df2\u8bc6\u522b\u7ea2\u679c\u8d26\u53f7" if (nickname or hongguo_id) else "\u7ea2\u679c\u5df2\u767b\u5f55\uff0c\u8d26\u53f7\u4fe1\u606f\u672a\u8bc6\u522b"
            else:
                nickname = ""
            result.update(
                {
                    "logged_in": logged_in,
                    "nickname": nickname,
                    "hongguo_id": hongguo_id,
                }
            )
            return self.normalize_account_info(result)
        except Exception as exc:
            result["message"] = str(exc)
            return result
        finally:
            self._return_to_search_home()

    def search_drama(self, keyword: str, force_reset: bool = False, screenshot_dir: str = "") -> Dict[str, Any]:
        try:
            if not self._ensure_search_app_ready(restart=force_reset, timeout=12):
                if not self._ensure_search_app_ready(restart=True, timeout=12):
                    return self._search_app_not_ready_result(keyword, screenshot_dir, "search_start")
            self._close_popups()
            self._recover_from_account_subpage()
            self._recover_from_feed_ad_for_search()
            current_title = self._current_playing_title()
            if (
                not force_reset
                and current_title
                and keyword in current_title
                and not self._is_reserved_or_unplayable_context(self._xml())
            ):
                return {"success": True, "titles": [current_title], "message": "已在目标短剧页面"}
            self._return_to_search_home()
            if self._playback_visible():
                self.ensure_app_ready(restart=True, timeout=12)
                self._close_popups()
                self._return_to_search_home()
            if force_reset:
                self._reset_to_searchable_surface()
                self._recover_from_feed_ad_for_search()
                if not self._ensure_search_app_ready(restart=True, timeout=8):
                    return self._search_app_not_ready_result(keyword, screenshot_dir, "after_reset")
            if not self._open_search():
                self._recover_from_feed_ad_for_search()
                self._open_theater()
            if not self._open_search():
                self.ensure_app_ready(restart=True, timeout=12)
                self._recover_from_feed_ad_for_search()
                self._open_theater()
                if self._open_search():
                    return self._submit_search(keyword, screenshot_dir=screenshot_dir)
                self._stop_app()
                time.sleep(1)
                self._start_app()
                self._wait_app_ready(10)
                self._close_popups()
                self._recover_from_feed_ad_for_search()
                self._open_theater()
                if self._open_search():
                    return self._submit_search(keyword, screenshot_dir=screenshot_dir)
                if self._known_not_foreground():
                    return self._search_app_not_ready_result(keyword, screenshot_dir, "search_entry_missing")
                screenshot_path = self.take_screenshot("search_entry_missing", screenshot_dir) if screenshot_dir else ""
                current: Dict[str, Any] = {}
                try:
                    value = self.d.app_current()
                    if isinstance(value, dict):
                        current = value
                except Exception:
                    pass
                texts = self._extract_xml_texts(self._xml())[:8]
                return {
                    "success": False,
                    "keyword": keyword,
                    "titles": [],
                    "screenshot_path": screenshot_path,
                    "message": (
                        "未找到搜索入口: "
                        f"package={current.get('package') or 'unknown'}, "
                        f"activity={current.get('activity') or 'unknown'}, "
                        f"visible_texts={texts}"
                    ),
                }
            if self._known_not_foreground():
                return self._search_app_not_ready_result(keyword, screenshot_dir, "before_submit")
            return self._submit_search(keyword, screenshot_dir=screenshot_dir)
        except Exception as exc:
            return {"success": False, "keyword": keyword, "titles": [], "message": str(exc)}

    def _submit_search(self, keyword: str, screenshot_dir: str = "") -> Dict[str, Any]:
        try:
            if self._known_not_foreground():
                return self._search_app_not_ready_result(keyword, screenshot_dir, "submit_search")
            self._sleep(1.5, 2.5)
            inp = self.d(className="android.widget.EditText")
            if self._exists(inp, 3):
                inp.click()
                time.sleep(0.5)
                input_result = self._set_search_input_text(inp, keyword, verify=True)
            else:
                input_result = self._set_search_input_text(None, keyword, verify=True)
            if not input_result.get("success"):
                actual_text = input_result.get("actual_text") or ""
                actual_label = actual_text if actual_text else "<空>"
                screenshot_path = self.take_screenshot("search_input_failed", screenshot_dir) if screenshot_dir else ""
                return {
                    "success": False,
                    "keyword": keyword,
                    "input_text": actual_text,
                    "titles": [],
                    "screenshot_path": screenshot_path,
                    "input_method": input_result.get("method") or "",
                    "message": f"搜索框输入校验失败: 期望 {keyword}，实际 {actual_label}",
                }
            self._sleep(0.8, 1.5)
            submitted = self._submit_search_query()
            xml = self._xml()
            if not submitted and self._search_suggestion_page_visible(xml):
                forced = self._force_submit_search_button(xml)
                xml = self._xml()
                if forced or self._search_submitted_results_visible(xml):
                    submitted = True
            if not submitted and self._search_suggestion_page_visible(xml):
                if self._click_exact_search_suggestion(keyword, xml):
                    self._sleep(1.5, 2.5)
                    xml = self._xml()
                    if self._search_submitted_results_visible(xml) or not self._search_suggestion_page_visible(xml):
                        submitted = True
            if not submitted and self._search_suggestion_page_visible(xml):
                screenshot_path = self.take_screenshot("search_suggestion_not_submitted", screenshot_dir) if screenshot_dir else ""
                return {
                    "success": False,
                    "keyword": keyword,
                    "input_text": input_result.get("actual_text") or keyword,
                    "titles": [],
                    "screenshot_path": screenshot_path,
                    "input_method": input_result.get("method") or "",
                    "message": "点击搜索按钮后仍停留在搜索联想页，未进入综合搜索结果页",
                }
            if submitted and not self._search_results_visible(xml):
                current_title = self._current_playing_title(xml) or keyword
                return {
                    "success": True,
                    "keyword": keyword,
                    "input_text": input_result.get("actual_text") or keyword,
                    "input_method": input_result.get("method") or "",
                    "titles": [current_title],
                    "message": "已通过搜索建议进入短剧页面",
                }
            titles = self._extract_drama_titles()
            return {
                "success": bool(titles),
                "keyword": keyword,
                "input_text": input_result.get("actual_text") or keyword,
                "input_method": input_result.get("method") or "",
                "titles": titles,
                "message": "搜索完成" if titles else "未找到有效短剧标题",
            }
        except Exception as exc:
            return {"success": False, "keyword": keyword, "titles": [], "message": str(exc)}

    def _wait_for_search_results(self, attempts: int = 3) -> bool:
        for _ in range(max(1, attempts)):
            self._sleep(2, 3)
            xml = self._xml()
            if self._search_results_visible(xml):
                return True
            search_btn = self.d(text="搜索")
            if self._exists(search_btn, 1):
                search_btn.click()
            else:
                self.d.press("enter")
        return self._search_results_visible(self._xml())

    def _submit_search_query(self, attempts: int = 4) -> bool:
        for _ in range(max(1, attempts)):
            xml = self._xml()
            if self._search_submitted_results_visible(xml):
                return True
            if self._click_search_submit_button(xml):
                self._sleep(1.2, 2.0)
            else:
                self.d.press("enter")
                self._sleep(1.2, 2.0)
            xml = self._xml()
            if self._search_submitted_results_visible(xml):
                return True
        xml = self._xml()
        if self._search_suggestion_page_visible(xml):
            return self._force_submit_search_button(xml)
        return self._search_submitted_results_visible(self._xml())

    def _click_search_submit_button(self, xml: Optional[str] = None) -> bool:
        xml = xml or self._xml()
        bounds = self._search_submit_button_bounds(xml)
        if bounds:
            left, top, right, bottom = bounds
            self._tap((left + right) // 2, (top + bottom) // 2)
            time.sleep(0.5)
            return True
        search_btn = self.d(text="搜索")
        if self._exists(search_btn, 1):
            if not self._tap_selector(search_btn):
                search_btn.click()
            time.sleep(0.5)
            return True
        self._tap(int(self.width * 0.92), int(self.height * 0.06))
        time.sleep(0.5)
        return True

    def _search_submit_button_bounds(self, xml: Optional[str] = None) -> Optional[tuple[int, int, int, int]]:
        xml = xml or self._xml()
        candidates = []
        for node in self._xml_nodes(xml):
            if f'package="{APP_PACKAGE}"' not in node:
                continue
            text = html.unescape(self._xml_attr(node, "text")).strip()
            desc = html.unescape(self._xml_attr(node, "content-desc")).strip()
            if text != "搜索" and desc != "搜索":
                continue
            bounds = self._node_bounds(node)
            if not bounds:
                continue
            left, top, right, bottom = bounds
            if top > int(self.height * 0.14) or right < int(self.width * 0.55):
                continue
            candidates.append((top, -right, left, top, right, bottom))
        if not candidates:
            return None
        candidates.sort()
        _, _, left, top, right, bottom = candidates[0]
        return left, top, right, bottom

    def _force_submit_search_button(self, xml: Optional[str] = None) -> bool:
        bounds = self._search_submit_button_bounds(xml or self._xml())
        if not bounds:
            return False
        left, top, right, bottom = bounds
        x = (left + right) // 2
        y = (top + bottom) // 2
        for _ in range(3):
            self._tap(x, y)
            self._sleep(1.5, 2.2)
            current_xml = self._xml()
            if self._search_submitted_results_visible(current_xml):
                return True
            if not self._search_suggestion_page_visible(current_xml):
                return self._search_submitted_results_visible(current_xml)
        return self._search_submitted_results_visible(self._xml())

    def _set_search_input_text(self, inp: Any, text: str, verify: bool = False) -> Dict[str, Any]:
        actual_text = ""
        last_method = ""
        writers = []
        if inp is not None and hasattr(inp, "set_text"):
            writers.append(("控件写入", lambda value: inp.set_text(value)))
        writers.append(("整段输入", lambda value: self._type_text(value)))
        writers.append(("ADB输入", lambda value: self._adb_input_text(value)))

        for _ in range(2):
            for method, writer in writers:
                last_method = method
                self._focus_existing_input(inp)
                self._clear_input(inp)
                time.sleep(0.2)
                try:
                    written = writer(text)
                except Exception:
                    written = False
                if written is False:
                    continue
                time.sleep(0.8)
                actual_text = self._read_input_text(inp)
                if not verify or self._input_text_matches(text, actual_text):
                    return {"success": True, "method": method, "actual_text": actual_text or text}
        return {"success": False, "actual_text": actual_text, "method": last_method}

    def _click_exact_search_suggestion(self, keyword: str, xml: Optional[str] = None) -> bool:
        xml = xml or self._xml()
        expected_key = self._normalize_title_key(keyword)
        if not expected_key:
            return False
        matches = []
        for node in self._xml_nodes(xml):
            if f'package="{APP_PACKAGE}"' not in node or 'class="android.widget.EditText"' in node:
                continue
            text = html.unescape(self._xml_attr(node, "text")).strip()
            if self._normalize_title_key(text) != expected_key:
                continue
            bounds = self._node_bounds(node)
            if not bounds:
                continue
            left, top, right, bottom = bounds
            if top < int(self.height * 0.18):
                continue
            row_bounds = self._search_result_click_bounds(left, top, right, bottom, xml)
            row_top = row_bounds[1] if row_bounds else top
            matches.append((row_top, left, text, left, top, right, bottom, row_bounds))
        if not matches:
            return False
        matches.sort(key=lambda item: (item[0], item[1]))
        _, _, _, left, top, right, bottom, _ = matches[0]
        self.d.click((left + right) // 2, (top + bottom) // 2)
        time.sleep(1.5)
        return True

    def _reset_to_searchable_surface(self) -> None:
        self._recover_from_feed_ad_for_search()
        self.exit_fullscreen()
        for _ in range(4):
            xml = self._xml()
            if self._feed_ad_visible(xml):
                self.skip_feed_ad_if_visible(xml)
                time.sleep(1)
                continue
            if any(text in xml for text in ["首页", "剧场", "我的"]) or self._search_results_visible(xml):
                break
            self.d.press("back")
            time.sleep(1)
        self._open_theater()

    def _recover_from_feed_ad_for_search(self) -> bool:
        recovered = False
        for _ in range(3):
            xml = self._xml()
            if not self._feed_ad_visible(xml):
                return recovered
            if not self.skip_feed_ad_if_visible(xml):
                return recovered
            recovered = True
            time.sleep(1)
        return recovered

    def select_drama(self, title: str) -> Dict[str, Any]:
        try:
            current_title = self._current_playing_title()
            if current_title and (not title or title in current_title or current_title in title):
                return {"success": True, "drama_title": current_title, "playable": True}
            clicked = False
            clicked_title = ""
            if title:
                clicked_title = self._click_matching_title_card(title)
                if clicked_title:
                    clicked = True
                if not clicked:
                    search_xml = self._xml()
                    if self._search_results_visible(search_xml):
                        clicked_title = self._click_matching_title_suggestion(title, search_xml)
                        if clicked_title:
                            clicked = True
                        else:
                            return {
                                "success": False,
                                "drama_title": title,
                                "playable": False,
                                "message": f"未找到匹配短剧: {title}",
                            }
                for selector in (self.d(text=title), self.d(textContains=title[:8])):
                    if clicked:
                        break
                    if self._exists(selector, 2):
                        selector.click()
                        clicked = True
                        break
            if not clicked and self._click_first_search_suggestion():
                clicked = True
                if "SearchActivity" in self.d.app_current().get("activity", ""):
                    self._tap(int(self.width * 0.25), int(self.height * 0.38))
                    time.sleep(3)
            if not clicked:
                self._tap(int(self.width * 0.28), int(self.height * 0.38))
            xml = ""
            for _ in range(2):
                self._sleep(2, 3)
                xml = self._xml()
                if not self._search_results_visible(xml):
                    break
                if title:
                    retry_title = self._click_matching_title_card(title)
                    if retry_title:
                        clicked_title = retry_title
                        continue
                break
            if not xml:
                xml = self._xml()
            if clicked_title and self._search_results_visible(xml):
                retry_title = self._retry_search_from_clicked_result(clicked_title, title)
                if retry_title:
                    clicked_title = retry_title
                    self._sleep(2, 3)
                    xml = self._xml()
                    if not self._search_results_visible(xml):
                        drama_title = self._extract_detail_title(xml) or clicked_title or title
                        playable = self._playback_visible(xml) or self._has_playable_detail_context(xml)
                        return {
                            "success": True,
                            "drama_title": drama_title,
                            "playable": playable,
                            "clicked_title": clicked_title,
                        }
                return {
                    "success": True,
                    "drama_title": clicked_title or title,
                    "playable": False,
                    "clicked_title": clicked_title,
                    "message": f"点击了搜索结果 {clicked_title}，但仍停留在搜索结果页，未进入短剧详情",
                }
            drama_title = self._extract_detail_title(xml) or clicked_title or title
            if (
                title
                and clicked_title
                and drama_title
                and not self._loose_title_match(title, drama_title)
                and self._loose_title_match(title, clicked_title)
            ):
                drama_title = clicked_title
            if title and drama_title and not self._loose_title_match(title, drama_title):
                return {
                    "success": False,
                    "drama_title": drama_title,
                    "playable": False,
                    "message": f"选择结果不匹配: 目标 {title}，当前 {drama_title}",
                }
            playable = self._playback_visible(xml) or self._has_playable_detail_context(xml) or any(
                text in xml
                for text in ["观看", "播放", "看全集", "立即观看", "开始播放", "全屏观看", "合集", "第1集"]
            )
            if not playable and self._is_reserved_or_unplayable_context(xml):
                return {
                    "success": True,
                    "drama_title": drama_title,
                    "playable": False,
                    "clicked_title": clicked_title,
                    "message": self._blocked_playback_reason(xml),
                }
            if not playable and self._search_results_visible(xml):
                return {
                    "success": True,
                    "drama_title": drama_title,
                    "playable": False,
                    "clicked_title": clicked_title,
                    "message": f"仍停留在搜索结果页，未进入短剧详情: {drama_title}",
                }
            if not playable:
                return {
                    "success": True,
                    "drama_title": drama_title,
                    "playable": False,
                    "clicked_title": clicked_title,
                    "message": self._blocked_playback_reason(xml) or f"未找到播放入口: {drama_title}",
                }
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
                    self._open_episode_panel()
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
            if self._open_episode_panel():
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

    def _open_episode_panel(self) -> bool:
        if self._episode_panel_open():
            return True
        selector = self._episode_panel_selector()
        if selector is not None and self._exists(selector, 1):
            try:
                if not self._tap_selector(selector):
                    selector.click()
                self._sleep(1.0, 1.8)
                if self._episode_panel_open():
                    return True
            except Exception:
                pass

        xml = self._xml()
        candidates: List[tuple[int, int, int, int]] = []
        for node in self._xml_nodes(xml):
            if f'package="{APP_PACKAGE}"' not in node:
                continue
            text = html.unescape(self._xml_attr(node, "text")).strip()
            desc = html.unescape(self._xml_attr(node, "content-desc")).strip()
            if "选集" not in text and "合集" not in text and "选集" not in desc and "合集" not in desc:
                continue
            bounds = self._node_bounds(node)
            if not bounds:
                continue
            left, top, right, bottom = bounds
            if top < int(self.height * 0.55):
                continue
            candidates.append((left, top, right, bottom))

        for left, top, right, bottom in sorted(candidates, key=lambda item: (-item[1], item[0])):
            y = (top + bottom) // 2
            for x in ((left + right) // 2, int(self.width * 0.82)):
                self._tap(x, y)
                self._sleep(1.0, 1.8)
                if self._episode_panel_open():
                    return True
        return self._episode_panel_open()

    def _episode_panel_open(self, xml: Optional[str] = None) -> bool:
        xml = xml or self._xml()
        if not xml:
            return False
        if re.search(r'text="\d{1,3}-\d{1,3}"', xml) or re.search(r'content-desc="\d{1,3}-\d{1,3}"', xml):
            return True
        numbers = self._visible_episode_numbers()
        return len(numbers) >= 3

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

    def pause_playback_if_playing(self) -> bool:
        if not self._playback_visible():
            return False
        if self._paused_indicator_visible(strict=False):
            return True
        selectors = (
            self.d(descriptionContains="\u6682\u505c"),
            self.d(textContains="\u6682\u505c"),
        )
        for selector in selectors:
            if self._exists(selector, 0.5):
                try:
                    selector.click()
                    time.sleep(1)
                    return self._paused_indicator_visible(strict=False)
                except Exception:
                    continue
        self._reveal_playback_controls()
        for selector in selectors:
            if self._exists(selector, 0.5):
                try:
                    selector.click()
                    time.sleep(1)
                    return self._paused_indicator_visible(strict=False)
                except Exception:
                    continue
        self.d.click(int(self.width * 0.5), int(self.height * 0.44))
        time.sleep(1)
        return self._paused_indicator_visible(strict=False)

    def resume_playback_if_paused(self, allow_center_fallback: bool = False) -> bool:
        if not self._playback_visible():
            return False
        if not self._paused_indicator_visible(strict=True):
            return False
        for selector in (
            self.d(descriptionContains="继续播放"),
            self.d(textContains="继续播放"),
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

    def _paused_indicator_visible(self, xml: Optional[str] = None, strict: bool = False) -> bool:
        xml = xml or self._xml()
        if not xml:
            return False
        active_markers = (
            "\u6682\u505c",
            "pause",
        )
        lowered = xml.lower()
        if any(marker in lowered for marker in ("continue play", "resume")):
            return True
        if "\u7ee7\u7eed\u64ad\u653e" in xml and not any(marker in xml for marker in active_markers):
            return True
        if strict:
            return False
        if re.search(r'(?:text|content-desc)="\u64ad\u653e"', xml) and not any(marker in xml for marker in active_markers):
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
        if self._is_reserved_or_unplayable_context(xml):
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
        if len(numbers) == 1 and self._single_episode_number_is_playing(numbers[0], xml):
            return numbers[0]
        return 0

    def get_total_episodes(self) -> int:
        xml = self._xml()
        if not xml:
            return 0
        if self._is_reserved_or_unplayable_context(xml):
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
        if self._feed_ad_visible(xml):
            return False
        if self._is_reserved_or_unplayable_context(xml):
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

    def _single_episode_number_is_playing(self, episode_number: int, xml: str) -> bool:
        if episode_number <= 0 or not xml:
            return False
        if re.search(rf"(?:全|共|更新至|已更新至|完结|完結)\s*{episode_number}\s*集", xml):
            return False
        if re.search(rf"(?:全|共|更新至|已更新至|完结|完結)\s*第\s*{episode_number}\s*集", xml):
            return False
        playback_markers = (
            "正在播放",
            "当前播放",
            "续播至",
            "播放中",
            "观看中",
        )
        if any(marker in xml for marker in playback_markers):
            return True
        if COMMENT_BUTTON_ID in xml:
            return bool(
                re.search(
                    rf'text="第\s*{episode_number}\s*集"[^>]*bounds="\[\d+,\d+\]\[\d+,\d+\]"',
                    xml,
                )
            )
        return False

    def _episode_is_confirmed(self, episode_number: int) -> bool:
        if episode_number <= 0:
            return False
        return self.get_current_episode() == episode_number or self._is_episode_active(episode_number)

    def ensure_playback_page(self, episode_number: int) -> bool:
        try:
            if self._known_not_foreground():
                self.ensure_app_ready(restart=True, timeout=12)
            self.skip_feed_ad_if_visible()
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

    def skip_feed_ad_if_visible(self, xml: Optional[str] = None) -> bool:
        xml = xml or self._xml()
        if not self._feed_ad_visible(xml):
            return False
        for _ in range(2):
            self._swipe_up(0.55)
            time.sleep(1.2)
            next_xml = self._xml()
            if not self._feed_ad_visible(next_xml):
                return True
        try:
            self.d.press("back")
            time.sleep(1)
        except Exception:
            pass
        return not self._feed_ad_visible(self._xml())

    def _feed_ad_visible(self, xml: Optional[str] = None) -> bool:
        xml = xml or self._xml()
        if not xml:
            return False
        ad_markers = (
            "上滑继续观看短剧",
            "向上滑动可以继续观看",
            "向上滑动继续观看",
            "上滑可继续观看",
            "滑动继续观看",
            "继续观看短剧",
            "查看详情",
            "点击进入直播间",
            "广告",
            "直播间",
            "商家推荐",
            "精彩应用",
        )
        if any(marker in xml for marker in ("上滑继续观看短剧", "向上滑动可以继续观看", "向上滑动继续观看", "上滑可继续观看", "滑动继续观看", "继续观看短剧")):
            return True
        marker_count = sum(1 for marker in ad_markers if marker in xml)
        if marker_count >= 2 and not re.search(r"第\s*\d{1,4}\s*集", xml):
            return True
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

    def post_comment(self, content: str, episode_number: int = 0, screenshot_dir: str = "") -> Dict[str, Any]:
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
                    screenshot_path = ""
                    if screenshot_dir:
                        screenshot_path = self.take_screenshot(f"ep{episode_number or 'x'}_after_comment_panel", screenshot_dir)
                    self._close_comment_panel()
                    return {"success": True, "message": "评论已发送", "screenshot_path": screenshot_path}
            self.d.press("enter")
            self._sleep(2, 3)
            screenshot_path = ""
            if screenshot_dir:
                screenshot_path = self.take_screenshot(f"ep{episode_number or 'x'}_after_comment_panel", screenshot_dir)
            self._close_comment_panel()
            return {"success": True, "message": "已尝试回车发送", "screenshot_path": screenshot_path}
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    def verify_comment(self, content: str, episode_number: int = 0, screenshot_dir: str = "") -> Dict[str, Any]:
        screenshot_path = ""
        try:
            current_episode = self.get_current_episode() if episode_number else 0
            if episode_number and current_episode and current_episode > episode_number:
                return {
                    "verified": False,
                    "screenshot_path": screenshot_path,
                    "message": f"评论后已跳到第{current_episode}集，跳过回退验证",
                }
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
                current_episode = self.get_current_episode()
                if not current_episode or current_episode <= episode_number:
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
            if self._follow_fans_page_visible(xml):
                self._back_from_follow_fans_page()
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

    def _follow_fans_page_visible(self, xml: Optional[str] = None) -> bool:
        xml = xml or self._xml()
        if not xml:
            return False
        texts = self._extract_xml_texts(xml)
        if "关注" not in texts or "粉丝" not in texts:
            return False
        if any("暂无关注的用户" in text or "暂无粉丝" in text for text in texts):
            return True
        return bool(re.search(r'package="com\.phoenix\.read"[^>]*text="用户名[^"]*"', xml))

    def _back_from_follow_fans_page(self) -> bool:
        for _ in range(2):
            if not self._follow_fans_page_visible():
                return True
            self.d.press("back")
            time.sleep(1)
        return not self._follow_fans_page_visible()

    def _recover_from_account_subpage(self) -> bool:
        recovered = False
        if self._follow_fans_page_visible():
            recovered = self._back_from_follow_fans_page()
        return recovered

    def _return_to_search_home(self) -> bool:
        recovered = False
        try:
            for _ in range(5):
                xml = self._xml()
                if self._feed_ad_visible(xml):
                    if self.skip_feed_ad_if_visible(xml):
                        recovered = True
                        time.sleep(1)
                        continue
                if self._follow_fans_page_visible(xml):
                    if self._back_from_follow_fans_page():
                        recovered = True
                        time.sleep(1)
                        continue
                if self._profile_visible(xml):
                    if self._click_bottom_nav("首页", fallback_x_ratio=0.1):
                        recovered = True
                        time.sleep(1.5)
                        continue
                    if not self._press_back():
                        return recovered
                    recovered = True
                    time.sleep(1)
                    continue
                if self._search_results_visible(xml):
                    if not self._press_back():
                        return recovered
                    recovered = True
                    time.sleep(1)
                    continue
                if self._playback_visible(xml):
                    if self._leave_playback_for_search():
                        recovered = True
                        time.sleep(1)
                        continue
                    return recovered
                if self._bottom_nav_visible(xml):
                    return recovered
                if any(text in xml for text in ("首页", "剧场", "我的")):
                    return recovered
                if not self._press_back():
                    return recovered
                recovered = True
                time.sleep(1)
        except Exception:
            return recovered
        return recovered

    def _leave_playback_for_search(self) -> bool:
        recovered = False
        for _ in range(5):
            xml = self._xml()
            if not self._playback_visible(xml):
                return recovered
            if not self._press_back():
                return recovered
            recovered = True
            time.sleep(1)
        return recovered and not self._playback_visible()

    def _press_back(self) -> bool:
        try:
            self.d.press("back")
            return True
        except Exception:
            return False

    def _bottom_nav_visible(self, xml: Optional[str] = None) -> bool:
        texts = self._extract_xml_texts(xml or self._xml())
        nav = {"首页", "剧场", "商城", "赚钱", "我的"}
        return sum(1 for text in texts if text in nav) >= 2

    def _click_bottom_nav(self, text: str, fallback_x_ratio: float = 0.1) -> bool:
        xml = self._xml()
        matches = []
        for node in self._xml_nodes(xml):
            if f'package="{APP_PACKAGE}"' not in node:
                continue
            label = html.unescape(self._xml_attr(node, "text")).strip()
            desc = html.unescape(self._xml_attr(node, "content-desc")).strip()
            if label != text and desc != text:
                continue
            bounds = self._node_bounds(node)
            if not bounds:
                continue
            left, top, right, bottom = bounds
            if top < int(self.height * 0.70):
                continue
            matches.append((top, left, right, bottom))
        if matches:
            matches.sort(key=lambda item: (item[0], item[1]))
            top, left, right, bottom = matches[0]
            self._tap((left + right) // 2, (top + bottom) // 2)
            return True
        try:
            self._tap(int(self.width * fallback_x_ratio), int(self.height * 0.965))
            return True
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
        patterns = (
            r"\u7ea2\u679c\u53f7[:\uff1a\s]*([A-Za-z0-9_-]{3,32})",
            r"\b(?:ID|id)[:\uff1a]\s*([A-Za-z0-9_-]{3,32})",
        )
        haystacks = [xml] + texts
        for text in haystacks:
            for pattern in patterns:
                match = re.search(pattern, text)
                if match:
                    candidate = match.group(1).strip()
                    if self._valid_hongguo_id(candidate):
                        return candidate
        for idx, text in enumerate(texts[:-1]):
            if "\u7ea2\u679c\u53f7" in text:
                candidate = texts[idx + 1].strip()
                if self._valid_hongguo_id(candidate):
                    return candidate
        return ""

    def _login_status_from_xml(self, xml: str) -> Optional[Dict[str, Any]]:
        if self._login_prompt_visible(xml):
            return {"logged_in": False, "status": "not_logged_in", "message": "未登录"}
        if self._logged_in_marker_visible(xml):
            return {"logged_in": True, "status": "logged_in", "message": "已登录"}
        return None

    def _login_prompt_visible(self, xml: str) -> bool:
        return self._app_text_marker_visible(
            xml,
            ("立即登录", "手机号登录", "微信登录", "抖音登录", "登录/注册", "登录红果"),
        )

    def _logged_in_marker_visible(self, xml: str) -> bool:
        return self._app_text_marker_visible(xml, ("红果号", "编辑资料"))

    def _app_text_marker_visible(self, xml: str, markers: tuple[str, ...]) -> bool:
        xml = xml or ""
        if f'package="{APP_PACKAGE}"' in xml:
            for node in self._xml_nodes(xml):
                if f'package="{APP_PACKAGE}"' not in node:
                    continue
                text = html.unescape(self._xml_attr(node, "text")).strip()
                desc = html.unescape(self._xml_attr(node, "content-desc")).strip()
                if any(marker in text or marker in desc for marker in markers):
                    return True
            return False
        return any(marker in xml for marker in markers)

    def _valid_hongguo_id(self, candidate: str) -> bool:
        return self._valid_hongguo_id_value(candidate)

    @staticmethod
    def _valid_hongguo_id_value(candidate: str) -> bool:
        value = (candidate or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{3,32}", value):
            return False
        blocked = {"get", "app", "id", "user", "login", "phone"}
        if value.lower() in blocked:
            return False
        return True

    @staticmethod
    def _is_promo_account_text(text: str) -> bool:
        value = str(text or "").strip()
        if not value:
            return False
        lower = value.lower()
        promo_parts = (
            "\u514d\u8d39\u77ed\u5267",
            "\u5c3d\u5728\u7ea2\u679c",
            "\u4e3b\u6f14\u8bf4",
            "\u7acb\u5373\u767b\u5f55",
            "\u624b\u673a\u53f7\u767b\u5f55",
            "\u5fae\u4fe1\u767b\u5f55",
            "\u6296\u97f3\u767b\u5f55",
            "\u7acb\u5373\u9886\u53d6",
            "\u6253\u5f00\u7ea2\u679c",
            "\u4e0b\u8f7d\u7ea2\u679c",
        )
        if any(part in value for part in promo_parts):
            return True
        return bool(re.search(r"[\(\uff08]\s*get\s*[\)\uff09]", lower))

    @classmethod
    def normalize_account_info(cls, account: Dict[str, Any]) -> Dict[str, Any]:
        result = dict(account or {})
        nickname = str(result.get("nickname") or "").strip()
        hongguo_id = str(result.get("hongguo_id") or "").strip()
        promo_detected = cls._is_promo_account_text(nickname) or cls._is_promo_account_text(hongguo_id)
        if hongguo_id and not cls._valid_hongguo_id_value(hongguo_id):
            hongguo_id = ""
        if promo_detected:
            result.update(
                {
                    "logged_in": False,
                    "nickname": "",
                    "hongguo_id": "",
                    "message": "\u7ea2\u679c\u672a\u767b\u5f55",
                }
            )
            return result
        result["nickname"] = nickname
        result["hongguo_id"] = hongguo_id
        if not result.get("logged_in") and not result.get("message"):
            result["message"] = "\u7ea2\u679c\u672a\u767b\u5f55"
        return result

    def _extract_account_nickname(self, texts: List[str]) -> str:
        for idx, text in enumerate(texts):
            if "\u7ea2\u679c\u53f7" not in text:
                continue
            for candidate in reversed(texts[max(0, idx - 8) : idx]):
                value = candidate.strip()
                if self._valid_account_nickname_candidate(value):
                    return value
        for idx, text in enumerate(texts):
            if "\u7f16\u8f91\u8d44\u6599" not in text:
                continue
            for candidate in reversed(texts[max(0, idx - 10) : idx]):
                value = candidate.strip()
                if self._valid_account_nickname_candidate(value):
                    return value
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
            "\u514d\u8d39\u77ed\u5267",
            "\u5c3d\u5728\u7ea2\u679c",
            "get",
            "\u4e3b\u6f14\u8bf4",
            "\u5c55\u5f00",
            "\u7acb\u5373\u9886\u53d6",
            "\u5e7f\u544a",
            "\u8f6e\u64ad",
            "\u6e38\u620f\u4e2d\u5fc3",
            "\u6bcf\u65e5\u65b0\u53d1\u73b0",
            "avatar image",
        )
        for text in texts:
            value = text.strip()
            if not self._valid_account_nickname_candidate(value, blocked_parts=blocked_parts):
                continue
            return value
        return ""

    def _valid_account_nickname_candidate(self, value: str, blocked_parts: Optional[tuple[str, ...]] = None) -> bool:
        value = str(value or "").strip()
        if not value or len(value) > 24:
            return False
        blocked = blocked_parts or (
            "\u6211\u7684",
            "\u94b1\u5305",
            "\u89c2\u770b\u5386\u53f2",
            "\u7ea2\u679c\u53f7",
            "\u7f16\u8f91\u8d44\u6599",
            "\u5173\u6ce8",
            "\u7c89\u4e1d",
            "\u83b7\u8d5e",
            "avatar image",
        )
        if self._is_promo_account_text(value):
            return False
        if any(part in value for part in blocked):
            return False
        if re.fullmatch(r"[\d:：.\-\s]+", value):
            return False
        if re.search(r"\u7b2c\s*\d+\s*\u96c6|\d+\s*\u96c6", value):
            return False
        return True

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
        for _ in range(5):
            clicked = False
            xml = self._xml()
            if self._close_promo_popup(xml):
                time.sleep(1)
                clicked = True
            if clicked:
                continue
            for text in [
                "暂不",
                "暂不关联",
                "暂不绑定",
                "暂不授权",
                "稍后",
                "稍后再说",
                "以后再说",
                "跳过",
                "取消",
                "关闭",
                "我知道了",
                "知道了",
                "不同意",
                "拒绝",
                "同意",
            ]:
                el = self.d(textContains=text)
                if self._exists(el, 0.5):
                    el.click()
                    time.sleep(1)
                    clicked = True
                    break
            if clicked:
                continue
            if self._blocking_popup_visible(xml):
                self.d.press("back")
                time.sleep(1)
                clicked = True
            if not clicked:
                break

    def _close_promo_popup(self, xml: Optional[str] = None) -> bool:
        xml = xml or self._xml()
        if not self._promo_popup_visible(xml):
            return False
        close_markers = ("关闭", "关", "×", "X", "x")
        for node in self._xml_nodes(xml):
            text = html.unescape(self._xml_attr(node, "text")).strip()
            desc = html.unescape(self._xml_attr(node, "content-desc")).strip()
            if not any(marker in text or marker in desc for marker in close_markers):
                continue
            bounds = self._node_bounds(node)
            if not bounds:
                continue
            left, top, right, bottom = bounds
            cx = min(max((left + right) // 2, 1), max(1, self.width - 1))
            cy = min(max((top + bottom) // 2, 1), max(1, self.height - 1))
            self.d.click(cx, cy)
            return True
        # Promo cards often expose the CTA in XML but render the close X as a plain
        # image near the lower center. Click that safe area instead of the CTA.
        for x_ratio, y_ratio in ((0.5, 0.72), (0.5, 0.78), (0.93, 0.56)):
            self.d.click(int(self.width * x_ratio), int(self.height * y_ratio))
            time.sleep(0.5)
            if not self._promo_popup_visible(self._xml()):
                return True
        self.d.press("back")
        return True

    def _promo_popup_visible(self, xml: Optional[str] = None) -> bool:
        xml = xml or self._xml()
        return bool(xml and any(marker in xml for marker in PROMO_POPUP_MARKERS))

    def _blocking_popup_visible(self, xml: Optional[str] = None) -> bool:
        xml = xml or self._xml()
        if not xml:
            return False
        popup_markers = (
            "关联抖音",
            "绑定抖音",
            "抖音授权",
            "授权抖音",
            "抖音账号",
            "关联账号",
            "绑定账号",
            "授权登录",
            "权限申请",
            "允许",
        )
        return self._promo_popup_visible(xml) or any(marker in xml for marker in popup_markers)

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
                if current.get("package") != APP_PACKAGE:
                    time.sleep(1)
                    continue
                if self._move_app_stack_to_default_display():
                    time.sleep(1)
                    xml = self._xml()
                if f'package="{APP_PACKAGE}"' not in xml:
                    time.sleep(1)
                    continue
                if self._xml_definitely_not_hongguo(xml):
                    time.sleep(1)
                    continue
                if self._app_text_marker_visible(xml, tuple(ready_markers)):
                    return True
                if self._playback_ready(current, xml):
                    return True
            except Exception:
                pass
            time.sleep(1)
        return False

    def _playback_ready(self, current: Dict[str, Any], xml: str) -> bool:
        activity = str(current.get("activity") or "").lower()
        if not any(marker in activity for marker in ("shortseriesactivity", "shortvideo")):
            return False
        if self._blocking_popup_visible(xml):
            return False
        if self._playback_visible(xml):
            return True
        if self.get_current_episode() > 0:
            return True
        if self._current_playing_title():
            return True
        return bool(xml and len(xml) > 200)

    def _is_app_foreground(self) -> bool:
        try:
            current = self.d.app_current()
            return current.get("package") == APP_PACKAGE and not self._xml_definitely_not_hongguo(self._xml())
        except Exception:
            return False

    def _foreground_app_active(self) -> bool:
        try:
            if self._app_root_stack_on_non_default_display():
                return False
            current = self.d.app_current()
            if current.get("package") != APP_PACKAGE:
                return False
            if self._xml_definitely_not_hongguo(self._xml()):
                return False
            if not self._hongguo_ui_visible(allow_blank_splash=True):
                return False
            activity = str(current.get("activity") or "").lower()
            if any(marker in activity for marker in ("splash", "main", "home", "short", "search")):
                return True
            return bool(activity)
        except Exception:
            return False

    def _foreground_app_usable(self) -> bool:
        try:
            if self._app_root_stack_on_non_default_display():
                return False
            current = self.d.app_current()
            if current.get("package") != APP_PACKAGE:
                return False
            xml = self._xml()
            if self._xml_definitely_not_hongguo(xml):
                return False
            if not xml or len(xml) < 500:
                return False
            if self._blocking_popup_visible(xml):
                self._close_popups()
                xml = self._xml()
            if self._playback_ready(current, xml):
                return True
            texts = self._extract_xml_texts(xml)
            if any(text in {"首页", "剧场", "我的", "搜索"} for text in texts):
                return True
            activity = str(current.get("activity") or "").lower()
            return any(marker in activity for marker in ("splash", "main", "home", "short"))
        except Exception:
            return False

    def _hongguo_ui_visible(self, allow_blank_splash: bool = False) -> bool:
        try:
            try:
                current = self.d.app_current()
            except Exception:
                current = {}
            package = current.get("package") if isinstance(current, dict) else None
            if package and package != APP_PACKAGE:
                return False
            if self._app_root_stack_on_non_default_display():
                return False
            activity = str(current.get("activity") or "").lower()
            xml = self._xml()
            if self._xml_definitely_not_hongguo(xml):
                return False
            if self._feed_ad_visible(xml):
                return True
            if any(text in xml for text in ("首页", "剧场", "我的", "搜索", "红果号", "全屏观看", "合集")):
                return True
            if self._login_prompt_visible(xml) or self._playback_visible(xml):
                return True
            if self._playback_ready(current, xml):
                return True
            if "splash" in activity and allow_blank_splash:
                return True
            return False
        except Exception:
            return False

    def _definitely_not_hongguo_surface(self) -> bool:
        try:
            current = self.d.app_current()
            if isinstance(current, dict):
                package = current.get("package")
                if package and package != APP_PACKAGE:
                    return True
        except Exception:
            pass
        if self._app_root_stack_on_non_default_display():
            return True
        return self._xml_definitely_not_hongguo(self._xml())

    def _xml_definitely_not_hongguo(self, xml: Optional[str] = None) -> bool:
        xml = xml or self._xml()
        if not xml:
            return False
        launcher_visible = self._launcher_visible(xml)
        hongguo_visible = self._hongguo_surface_visible(xml)
        if launcher_visible and hongguo_visible:
            if self._app_root_stack_on_non_default_display():
                return True
            if self._app_root_stack_on_default_display() and self._hongguo_strong_surface_visible(xml):
                return False
            if self._hongguo_profile_surface_visible(xml):
                return False
            if self._hongguo_active_feed_surface_visible(xml):
                return False
            if self._hongguo_active_playback_surface_visible(xml):
                return False
            if self._hongguo_strong_surface_visible(xml) and not self._launcher_content_dominates(xml):
                return False
            if self._launcher_content_dominates(xml):
                return True
            if self._has_active_playback_context(xml) or self._search_results_visible(xml):
                return False
            focused_package = self._focused_window_package()
            if focused_package and focused_package != APP_PACKAGE:
                return True
            return True
        if self._launcher_visible(xml):
            return True
        if hongguo_visible:
            return False
        packages = set(re.findall(r'package="([^"]+)"', xml))
        non_system_packages = {
            package
            for package in packages
            if package
            and package != "com.android.systemui"
            and not package.startswith("android")
        }
        return bool(non_system_packages)

    def _hongguo_strong_surface_visible(self, xml: Optional[str] = None) -> bool:
        xml = xml or self._xml()
        if not xml or f'package="{APP_PACKAGE}"' not in xml:
            return False
        strong_markers = (
            "首页",
            "剧场",
            "我的",
            "红果号",
            "全屏观看",
            "合集",
            "选集",
            "评论",
            "有趣评论",
            "说点什么",
        )
        for node in self._xml_nodes(xml):
            if f'package="{APP_PACKAGE}"' not in node:
                continue
            text = html.unescape(self._xml_attr(node, "text")).strip()
            desc = html.unescape(self._xml_attr(node, "content-desc")).strip()
            resource_id = self._xml_attr(node, "resource-id")
            haystack = f"{text} {desc} {resource_id}"
            if COMMENT_BUTTON_ID in resource_id:
                return True
            if any(marker in haystack for marker in strong_markers):
                return True
            if re.search(r"第\s*\d{1,4}\s*集", haystack) and self._has_active_playback_context(xml):
                return True
        return False

    def _hongguo_active_feed_surface_visible(self, xml: Optional[str] = None) -> bool:
        xml = xml or self._xml()
        if not xml or f'package="{APP_PACKAGE}"' not in xml:
            return False
        app_texts: List[str] = []
        for node in self._xml_nodes(xml):
            if f'package="{APP_PACKAGE}"' not in node:
                continue
            text = html.unescape(self._xml_attr(node, "text")).strip()
            desc = html.unescape(self._xml_attr(node, "content-desc")).strip()
            combined = " ".join(part for part in (text, desc) if part)
            if combined:
                app_texts.append(combined)
        if not app_texts:
            return False

        joined = "\n".join(app_texts)
        nav_count = sum(1 for marker in ("首页", "剧场", "商城", "赚钱", "我的") if marker in app_texts)
        has_episode = any(re.search(r"第\s*\d{1,4}\s*集", text) for text in app_texts)
        has_feed_action = any(marker in joined for marker in ("观看完整短剧", "全屏观看", "看全集", "立即观看"))
        has_feed_context = any(marker in joined for marker in ("爆剧", "热评", "作者声明", "展开"))
        tag_count = sum(1 for marker in TAG_KEYWORDS if marker in app_texts)
        return bool(nav_count >= 2 and (has_feed_action or has_episode) and (has_feed_context or tag_count >= 2))

    def _hongguo_active_playback_surface_visible(self, xml: Optional[str] = None) -> bool:
        xml = xml or self._xml()
        if not xml or f'package="{APP_PACKAGE}"' not in xml:
            return False
        app_texts: List[str] = []
        for node in self._xml_nodes(xml):
            if f'package="{APP_PACKAGE}"' not in node:
                continue
            text = html.unescape(self._xml_attr(node, "text")).strip()
            desc = html.unescape(self._xml_attr(node, "content-desc")).strip()
            combined = " ".join(part for part in (text, desc) if part)
            if combined:
                app_texts.append(combined)
        if not app_texts:
            return False

        joined = "\n".join(app_texts)
        has_episode = any(re.search(r"第\s*\d{1,4}\s*集", text) for text in app_texts)
        if not has_episode:
            return False
        has_fullscreen = any("全屏观看" in text for text in app_texts)
        has_selection = any("选集" in text or "合集" in text for text in app_texts)
        has_speed = any("倍速" in text for text in app_texts)
        has_total = bool(re.search(r"(?:全|共|已完结\s*·\s*全)\s*\d{1,4}\s*集", joined))
        has_comment_context = any(marker in joined for marker in ("热评", "评论", "说点什么", "作者声明", "展开"))
        has_title_candidate = any(self._active_playback_title_candidate(text) for text in app_texts)
        if has_fullscreen and has_selection:
            return True
        return bool(has_selection and (has_speed or has_total) and (has_comment_context or has_title_candidate))

    def _active_playback_title_candidate(self, text: str) -> bool:
        value = str(text or "").strip()
        if not value or len(value) < 4 or len(value) > 36:
            return False
        blocked_parts = (
            "搜索",
            "全屏观看",
            "选集",
            "合集",
            "倍速",
            "热评",
            "作者声明",
            "展开",
            "首页",
            "剧场",
            "商城",
            "赚钱",
            "我的",
            "广告",
            "轮播",
        )
        if any(part in value for part in blocked_parts):
            return False
        if re.search(r"第\s*\d{1,4}\s*集|\d+\s*集|^\d+[:：.]?\d*$", value):
            return False
        return bool(re.search(r"[\u4e00-\u9fff]", value))

    def _hongguo_profile_surface_visible(self, xml: Optional[str] = None) -> bool:
        xml = xml or self._xml()
        if not xml or f'package="{APP_PACKAGE}"' not in xml:
            return False
        return self._app_text_marker_visible(xml, ("红果号", "编辑资料")) or self._follow_fans_page_visible(xml)

    def _launcher_content_dominates(self, xml: Optional[str] = None) -> bool:
        xml = xml or self._xml()
        texts = self._extract_xml_texts(xml)[:80]
        if not texts:
            return False
        foreground_markers = (
            "首页",
            "剧场",
            "我的",
            "红果号",
            "全屏观看",
            "合集",
            "选集",
            "评论",
            "有趣评论",
            "说点什么",
            "观看完整短剧",
            "热评",
        )
        launcher_markers = (
            "应用宝",
            "Play 商店",
            "Play 游戏",
            "游戏中心",
            "通讯录",
            "设置",
            "小红书",
            "微信",
            "抖音",
            "红果免费短剧",
            "傲游浏览器",
            "豌豆荚",
            "UC浏览器",
            "ATX",
            "热血江湖",
            "时空猎人",
            "三国志",
            "鹅鸭杀",
            "神迹觉醒",
            "大航海时代",
            "龙族",
        )
        first_foreground_index: Optional[int] = None
        first_launcher_index: Optional[int] = None
        for index, text in enumerate(texts):
            if any(marker in text for marker in foreground_markers) or re.search(r"第\s*\d{1,4}\s*集", text):
                first_foreground_index = index
                break
        for index, text in enumerate(texts):
            if any(marker in text for marker in launcher_markers):
                first_launcher_index = index
                break
        if first_foreground_index is not None and (
            first_launcher_index is None or first_foreground_index < first_launcher_index
        ):
            return False
        limit = first_foreground_index if first_foreground_index is not None else min(12, len(texts))
        leading_launcher_count = sum(
            1 for text in texts[:limit] for marker in launcher_markers if marker in text
        )
        marker_count = sum(1 for text in texts for marker in launcher_markers if marker in text)
        if leading_launcher_count >= 3:
            return True
        if marker_count >= 5:
            return True
        if first_foreground_index is not None:
            return False
        return marker_count >= 3

    def _focused_window_package(self) -> str:
        try:
            output = self.d.shell("dumpsys window")
        except Exception:
            return ""
        if not isinstance(output, str):
            output = str(getattr(output, "output", "") or output or "")
        if not output:
            return ""
        matches = re.findall(r"(?:Window\{[^}]*\s|ActivityRecord\{[^}]*\s)([a-zA-Z0-9_.]+)/", output)
        for package in reversed(matches):
            if package:
                return package
        return ""

    def _hongguo_surface_visible(self, xml: Optional[str] = None) -> bool:
        xml = xml or self._xml()
        if not xml or f'package="{APP_PACKAGE}"' not in xml:
            return False
        if self._follow_fans_page_visible(xml):
            return True
        markers = (
            "首页",
            "剧场",
            "我的",
            "搜索",
            "红果号",
            "全屏观看",
            "合集",
            "选集",
            "评论",
            "有趣评论",
            "说点什么",
        )
        for node in self._xml_nodes(xml):
            if f'package="{APP_PACKAGE}"' not in node:
                continue
            text = html.unescape(self._xml_attr(node, "text")).strip()
            desc = html.unescape(self._xml_attr(node, "content-desc")).strip()
            resource_id = self._xml_attr(node, "resource-id")
            haystack = f"{text} {desc} {resource_id}"
            if COMMENT_BUTTON_ID in resource_id:
                return True
            if any(marker in haystack for marker in markers):
                return True
            if re.search(r"第\s*\d{1,4}\s*集", haystack):
                return True
        return False

    def _launcher_visible(self, xml: Optional[str] = None) -> bool:
        xml = xml or self._xml()
        if not xml:
            return False
        launcher_packages = (
            'package="app.lawnchair"',
            'resource-id="app.lawnchair:',
            'package="com.android.launcher',
            'resource-id="com.android.launcher',
            'package="com.mumu.launcher"',
            'resource-id="com.mumu.launcher:',
        )
        if any(marker in xml for marker in launcher_packages):
            return True
        launcher_markers = (
            "应用宝",
            "Play 商店",
            "Play 游戏",
            "游戏中心",
            "通讯录",
            "设置",
            "小红书",
            "微信",
            "抖音",
            "红果免费短剧",
            "每日新发现",
            "热血江湖",
            "时空猎人",
            "三国志",
            "鹅鸭杀",
            "神迹觉醒",
            "大航海时代",
            "龙族",
        )
        marker_count = sum(1 for marker in launcher_markers if marker in xml)
        return marker_count >= 3 and "剧场" not in xml and "红果号" not in xml

    def _restart_app(self, timeout: float = 12) -> bool:
        self._stop_app()
        time.sleep(2)
        self._start_app()
        if self._wait_app_ready(timeout):
            self._close_popups()
            return True
        if self._move_app_stack_to_default_display() and self._wait_app_ready(min(timeout, 4)):
            self._close_popups()
            return True
        if self._foreground_app_active():
            self._close_popups()
            return True
        if self._launch_from_launcher_icon():
            self._close_popups()
            return True
        return False

    def _move_app_stack_to_default_display(self) -> bool:
        stack_id = self._app_root_stack_on_non_default_display()
        if not stack_id:
            return False
        try:
            self._shell(f"am display move-stack {stack_id} 0", timeout=8)
        except Exception:
            return False
        time.sleep(1)
        try:
            current = self.d.app_current()
            if (
                isinstance(current, dict)
                and current.get("package") == APP_PACKAGE
                and not self._xml_definitely_not_hongguo(self._xml())
            ):
                return True
        except Exception:
            pass
        return not self._xml_definitely_not_hongguo(self._xml())

    def _app_root_stack_on_default_display(self) -> bool:
        return self._app_root_stack_display() == "0"

    def _app_root_stack_on_non_default_display(self) -> str:
        stack_id, display_id = self._app_root_stack_info()
        if stack_id and display_id and display_id != "0":
            return stack_id
        return ""

    def _app_root_stack_display(self) -> str:
        _, display_id = self._app_root_stack_info()
        return display_id

    def _app_root_stack_info(self) -> tuple[str, str]:
        try:
            output = self._shell("am stack list", timeout=8)
        except Exception:
            return "", ""
        if not isinstance(output, str):
            output = str(getattr(output, "output", "") or output or "")
        if not output:
            return "", ""
        current_stack = ""
        current_display = ""
        for line in output.splitlines():
            root_match = re.search(r"RootTask id=(\d+).*displayId=(\d+)", line)
            if root_match:
                current_stack, current_display = root_match.groups()
                continue
            if APP_PACKAGE in line and current_stack and current_display and current_display != "0":
                return current_stack, current_display
            if APP_PACKAGE in line and current_stack and current_display:
                return current_stack, current_display
        return "", ""

    def _launch_from_launcher_icon(self) -> bool:
        if not self._launcher_visible(self._xml()):
            return False
        self._stop_app()
        time.sleep(1)
        if not self._click_launcher_app_icon():
            return False
        return self._wait_app_ready(15) or self._foreground_app_active()

    def _click_launcher_app_icon(self) -> bool:
        xml = self._xml()
        for node in self._xml_nodes(xml):
            if "红果免费短剧" not in html.unescape(self._xml_attr(node, "text")).strip():
                continue
            bounds = self._node_bounds(node)
            if not bounds:
                continue
            left, top, right, bottom = bounds
            self.d.click((left + right) // 2, (top + bottom) // 2)
            time.sleep(2)
            return True
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
        self._recover_from_feed_ad_for_search()
        for _ in range(3):
            xml = self._xml()
            if self._feed_ad_visible(xml):
                self.skip_feed_ad_if_visible(xml)
                time.sleep(1)
                continue
            if any(text in xml for text in ["首页", "剧场", "我的"]):
                break
            self.d.press("back")
            time.sleep(1)
        if not self._click_bottom_nav("剧场", fallback_x_ratio=0.3):
            try:
                self.d.click(int(self.width * 0.3), int(self.height * 0.965))
            except Exception:
                pass
        time.sleep(2)
        self._close_popups()

    def _open_search(self) -> bool:
        moved_to_default = self._move_app_stack_to_default_display()
        self._recover_from_account_subpage()
        if self._known_not_foreground():
            return False
        self._close_popups()
        self._recover_from_account_subpage()
        if self._known_not_foreground() or not self._hongguo_ui_visible(allow_blank_splash=False):
            return False
        for resource_id in (
            "com.phoenix.read:id/hds",
            "com.phoenix.read:id/hgb",
            "com.phoenix.read:id/ekk",
        ):
            try:
                resource_selector = self.d(resourceId=resource_id)
                if self._exists(resource_selector, 1):
                    if not self._tap_selector(resource_selector):
                        resource_selector.click()
                    time.sleep(1)
                    if self._search_entry_opened():
                        return True
            except Exception:
                pass
        xml = self._xml()
        if self._click_hongguo_text_node("搜索", xml):
            return True
        if f'package="{APP_PACKAGE}"' in xml and self._launcher_visible(xml):
            return False
        try:
            selectors = (self.d(textContains="搜索"), self.d(descriptionContains="搜索"))
        except Exception:
            selectors = ()
        for selector in selectors:
            if self._exists(selector, 1):
                if not self._tap_selector(selector):
                    selector.click()
                time.sleep(1)
                if self._search_entry_opened():
                    return True
        self._close_popups()
        for x_ratio in (0.94, 0.35):
            try:
                self._tap(int(self.width * x_ratio), int(self.height * 0.055))
            except Exception:
                continue
            time.sleep(1)
            if self._search_entry_opened():
                return True
        # The deep link opens SearchActivity on some versions, but it behaves as a
        # suggestion-only surface where the top-right Search button does not submit.
        # Keep search entry on the real in-app UI route.
        return False

    def _search_entry_opened(self) -> bool:
        try:
            if "SearchActivity" in str(self.d.app_current().get("activity", "")):
                return True
        except Exception:
            pass
        try:
            input_box = self.d(className="android.widget.EditText")
        except Exception:
            input_box = None
        if input_box is not None and self._exists(input_box, 2):
            return True
        xml = self._xml()
        return "android.widget.EditText" in xml or self._search_results_visible(xml)

    def _open_search_deeplink(self) -> bool:
        try:
            self._shell(f"am start -a android.intent.action.VIEW -d dragon8662://search {APP_PACKAGE}", timeout=8)
        except Exception:
            return False
        time.sleep(2)
        activity = ""
        package = ""
        try:
            current = self.d.app_current()
            if isinstance(current, dict):
                package = str(current.get("package") or "")
                activity = str(current.get("activity") or "")
        except Exception:
            activity = ""
        if package and package != APP_PACKAGE:
            return False
        if "SearchActivity" in activity:
            return True
        if self._known_not_foreground():
            return False
        xml = self._xml()
        return "android.widget.EditText" in xml or self._search_results_visible(xml)

    def _click_hongguo_text_node(self, keyword: str, xml: Optional[str] = None) -> bool:
        xml = xml or self._xml()
        for node in self._xml_nodes(xml):
            if f'package="{APP_PACKAGE}"' not in node:
                continue
            text = html.unescape(self._xml_attr(node, "text")).strip()
            desc = html.unescape(self._xml_attr(node, "content-desc")).strip()
            if keyword not in text and keyword not in desc:
                continue
            bounds = self._node_bounds(node)
            if not bounds:
                continue
            left, top, right, bottom = bounds
            self.d.click((left + right) // 2, (top + bottom) // 2)
            time.sleep(1)
            return True
        return False

    def _ensure_search_app_ready(self, restart: bool = False, timeout: float = 8) -> bool:
        try:
            try:
                current = self.d.app_current()
            except Exception:
                return True
            package = current.get("package") if isinstance(current, dict) else None
            if not package:
                return True
            if package == APP_PACKAGE and not restart and self._feed_ad_visible():
                return True
            if package == APP_PACKAGE and not restart and self._recover_from_account_subpage():
                return True
            if package == APP_PACKAGE and not restart and self._hongguo_ui_visible(allow_blank_splash=False):
                return True
            if restart:
                return self.ensure_app_ready(restart=True, timeout=timeout)
            self._start_app()
            return self._wait_app_ready(timeout)
        except Exception:
            return False

    def _known_not_foreground(self) -> bool:
        try:
            current = self.d.app_current()
        except Exception:
            return self._xml_definitely_not_hongguo(self._xml())
        package = current.get("package") if isinstance(current, dict) else None
        if package and package != APP_PACKAGE:
            return True
        return self._xml_definitely_not_hongguo(self._xml())

    def _search_app_not_ready_result(self, keyword: str, screenshot_dir: str = "", tag: str = "search") -> Dict[str, Any]:
        current: Dict[str, Any] = {}
        try:
            value = self.d.app_current()
            if isinstance(value, dict):
                current = value
        except Exception:
            pass
        screenshot_path = self.take_screenshot(f"{tag}_app_not_ready", screenshot_dir) if screenshot_dir else ""
        package = current.get("package") or "unknown"
        activity = current.get("activity") or "unknown"
        return {
            "success": False,
            "keyword": keyword,
            "titles": [],
            "screenshot_path": screenshot_path,
            "message": f"红果未在前台，无法搜索: package={package}, activity={activity}",
        }

    def _click_first_search_suggestion(self) -> bool:
        xml = self._xml()
        if "即将上线" not in xml and "万热度" not in xml and "播放" not in xml:
            return False
        # The first playable suggestion sits below the search bar. Avoid the second row, which
        # often represents a reserved/upcoming season.
        self._tap(int(self.width * 0.38), int(self.height * 0.105))
        time.sleep(1)
        return True

    def _click_matching_title_card(self, title: str) -> str:
        xml = self._xml()
        match = self._find_matching_title_node(title, xml)
        if not match:
            return ""
        found_title, left, top, right, bottom = match
        if self._search_results_visible(xml):
            cx, cy = self._search_result_card_tap_point(left, top, right, bottom, xml)
        else:
            cx = min(max((left + right) // 2, 1), max(1, self.width - 1))
            cy = max(1, top - int(self.height * 0.18))
            if top < int(self.height * 0.28):
                cy = (top + bottom) // 2
        cy = min(cy, max(1, self.height - 1))
        self._tap(cx, cy)
        time.sleep(1.5)
        return found_title

    def _search_result_click_bounds(
        self, left: int, top: int, right: int, bottom: int, xml: Optional[str] = None
    ) -> Optional[tuple[int, int, int, int]]:
        xml = xml or self._xml()
        candidates: List[tuple[int, int, int, int, int]] = []
        for node in self._xml_nodes(xml):
            if f'package="{APP_PACKAGE}"' not in node or 'clickable="true"' not in node:
                continue
            bounds = self._node_bounds(node)
            if not bounds:
                continue
            node_left, node_top, node_right, node_bottom = bounds
            if node_left <= left and node_top <= top and node_right >= right and node_bottom >= bottom:
                area = max(1, (node_right - node_left) * (node_bottom - node_top))
                if node_top >= int(self.height * 0.09) and node_bottom <= int(self.height * 0.95):
                    candidates.append((area, node_left, node_top, node_right, node_bottom))
        if candidates:
            candidates.sort(key=lambda item: item[0])
            _, node_left, node_top, node_right, node_bottom = candidates[0]
            return node_left, node_top, node_right, node_bottom
        return None

    def _search_result_card_tap_point(
        self, left: int, top: int, right: int, bottom: int, xml: Optional[str] = None
    ) -> tuple[int, int]:
        card_bounds = self._search_result_click_bounds(left, top, right, bottom, xml)
        if card_bounds:
            click_left, click_top, click_right, click_bottom = card_bounds
            card_width = click_right - click_left
            card_height = click_bottom - click_top
            if card_width >= int(self.width * 0.18) and card_height >= int(self.height * 0.12):
                cover_bottom = min(top - 8, click_bottom)
                if cover_bottom > click_top:
                    cover_height = cover_bottom - click_top
                    return (click_left + click_right) // 2, click_top + max(1, int(cover_height * 0.50))
                return (click_left + click_right) // 2, (click_top + click_bottom) // 2
        return self._search_result_fallback_click_point(left, top, right, bottom)

    def _search_result_fallback_click_point(self, left: int, top: int, right: int, bottom: int) -> tuple[int, int]:
        if left < int(self.width * 0.45):
            cx = int(self.width * 0.25)
            cy = max(1, top - int(self.height * 0.18))
        elif left > int(self.width * 0.45):
            cx = int(self.width * 0.75)
            cy = max(1, top - int(self.height * 0.16))
        else:
            cx = self.width // 2
            cy = max(1, top + int(self.height * 0.035))
        cx = max(1, min(self.width - 1, cx))
        cy = max(int(self.height * 0.14), min(self.height - 1, cy))
        return cx, cy

    def _click_matching_title_suggestion(self, title: str, xml: Optional[str] = None) -> str:
        xml = xml or self._xml()
        expected_key = self._normalize_title_key(title)
        if not expected_key:
            return ""
        matches = []
        for node in self._xml_nodes(xml):
            if f'package="{APP_PACKAGE}"' not in node or 'class="android.widget.EditText"' in node:
                continue
            text = html.unescape(self._xml_attr(node, "text")).strip()
            if not text or not self._is_title_candidate(text):
                continue
            actual_key = self._normalize_title_key(text)
            if actual_key != expected_key:
                actual_season = self._season_marker(actual_key, expected_key)
                if not (actual_key.startswith(expected_key) and self._season_equivalent("", actual_season)):
                    continue
            bounds = self._node_bounds(node)
            if not bounds:
                continue
            left, top, right, bottom = bounds
            if top < int(self.height * 0.16):
                continue
            rank = 0 if actual_key == expected_key else 2
            actual_season = self._season_marker(actual_key, expected_key)
            if actual_key != expected_key and actual_key.startswith(expected_key) and self._season_equivalent("", actual_season):
                rank = 1
            matches.append((rank, top, left, text, left, top, right, bottom))
        if not matches:
            return ""
        matches.sort(key=lambda item: (item[0], item[1], item[2]))
        _, _, _, text, left, top, right, bottom = matches[0]
        self._tap((left + right) // 2, (top + bottom) // 2)
        time.sleep(1.5)
        return text

    def _retry_search_from_clicked_result(self, clicked_title: str, original_title: str = "") -> str:
        clicked_title = str(clicked_title or "").strip()
        if not clicked_title:
            return ""
        xml = self._xml()
        if not self._search_results_visible(xml):
            return ""
        inp = self.d(className="android.widget.EditText")
        input_result = self._set_input_text(inp if self._exists(inp, 1) else None, clicked_title, verify=True)
        if not input_result.get("success"):
            return ""
        search_btn = self.d(text="搜索")
        if self._exists(search_btn, 1):
            if not self._tap_selector(search_btn):
                search_btn.click()
        else:
            self.d.press("enter")
        self._sleep(2, 3)
        xml = self._xml()
        retry_title = self._click_exact_playable_result_card(clicked_title, xml)
        if retry_title:
            return retry_title
        if not self._search_results_visible(xml):
            return clicked_title
        return self._click_matching_title_card(clicked_title)

    def _click_exact_playable_result_card(self, title: str, xml: Optional[str] = None) -> str:
        xml = xml or self._xml()
        expected_key = self._normalize_title_key(title)
        if not expected_key:
            return ""
        matches = []
        for node in self._xml_nodes(xml):
            if f'package="{APP_PACKAGE}"' not in node or 'class="android.widget.EditText"' in node:
                continue
            text = html.unescape(self._xml_attr(node, "text")).strip()
            if self._normalize_title_key(text) != expected_key:
                continue
            bounds = self._node_bounds(node)
            if not bounds:
                continue
            left, top, right, bottom = bounds
            if top < int(self.height * 0.10):
                continue
            context = self._xml_context_around_bounds(left, top, right, bottom, padding=150, xml=xml)
            if not self._playable_result_hint(context):
                context = self._xml_result_row_context(top, bottom, xml=xml)
            if not self._playable_result_hint(context):
                continue
            matches.append((top, left, text, left, top, right, bottom))
        if not matches:
            return ""
        matches.sort(key=lambda item: (item[0], item[1]))
        _, _, text, left, top, right, bottom = matches[0]
        cx, cy = self._search_result_card_tap_point(left, top, right, bottom, xml)
        self._tap(cx, cy)
        time.sleep(1.5)
        return text

    def _xml_vertical_context(self, top: int, bottom: int, padding: int = 150, xml: Optional[str] = None) -> str:
        nearby: List[str] = []
        for node in self._xml_nodes(xml):
            bounds = self._node_bounds(node)
            if not bounds:
                continue
            node_top, node_bottom = bounds[1], bounds[3]
            if node_bottom < top - padding or node_top > bottom + padding:
                continue
            nearby.append(node)
        return "\n".join(nearby)

    def _xml_result_row_context(self, top: int, bottom: int, xml: Optional[str] = None) -> str:
        nearby: List[str] = []
        for node in self._xml_nodes(xml):
            bounds = self._node_bounds(node)
            if not bounds:
                continue
            node_top, node_bottom = bounds[1], bounds[3]
            if node_bottom < top - 24 or node_top > bottom + 120:
                continue
            nearby.append(node)
        return "\n".join(nearby)

    def _find_matching_title_node(self, title: str, xml: Optional[str] = None) -> Optional[tuple[str, int, int, int, int]]:
        matches = []
        xml = xml or self._xml()
        search_results_visible = self._search_results_visible(xml)
        for node in self._xml_nodes(xml):
            text = html.unescape(self._xml_attr(node, "text")).strip()
            if not text or not self._is_title_candidate(text) or not self._loose_title_match(title, text):
                continue
            bounds = self._node_bounds(node)
            if not bounds:
                continue
            left, top, right, bottom = bounds
            min_top = int(self.height * (0.10 if search_results_visible else 0.16))
            if top < min_top:
                continue
            if 'class="android.widget.EditText"' in node:
                continue
            node_context = self._xml_context_around_bounds(left, top, right, bottom, padding=150, xml=xml)
            if self._is_reserved_or_unplayable_context(node_context):
                continue
            score = 0
            expected_key = self._normalize_title_key(title)
            actual_key = self._normalize_title_key(text)
            playable_hint = self._playable_result_hint(node_context)
            if search_results_visible and not playable_hint:
                continue
            if expected_key == actual_key:
                score += 60
            elif expected_key in actual_key:
                score += 20
                if actual_key.startswith(expected_key):
                    score -= min(12, max(0, len(actual_key) - len(expected_key)))
            elif actual_key in expected_key:
                score += 12
            expected_season = self._season_marker(expected_key)
            actual_season = self._season_marker(actual_key, expected_key)
            if expected_season == actual_season:
                score += 10
            elif expected_season or actual_season:
                score -= 12
            if playable_hint:
                score += 6
            if left <= int(self.width * 0.12):
                score += 4
            score -= top / max(1, self.height)
            matches.append((score, text, left, top, right, bottom))
        if not matches:
            return None
        matches.sort(key=lambda item: (-item[0], item[3], item[2]))
        _, text, left, top, right, bottom = matches[0]
        return text, left, top, right, bottom

    def _xml_context_around_bounds(
        self,
        left: int,
        top: int,
        right: int,
        bottom: int,
        padding: int = 260,
        xml: Optional[str] = None,
    ) -> str:
        nearby: List[str] = []
        for node in self._xml_nodes(xml):
            bounds = self._node_bounds(node)
            if not bounds:
                continue
            node_left, node_top, node_right, node_bottom = bounds
            if node_bottom < top - padding or node_top > bottom + padding:
                continue
            horizontal_overlap = min(right, node_right) - max(left, node_left)
            if horizontal_overlap <= 0:
                continue
            nearby.append(node)
        return "\n".join(nearby)

    def _is_reserved_or_unplayable_context(self, xml: str) -> bool:
        xml = xml or ""
        blocked_markers = (
            "\u9884\u7ea6",
            "\u7acb\u5373\u9884\u7ea6",
            "\u4e0a\u7ebf",
            "\u5373\u5c06\u4e0a\u7ebf",
            "\u4e07\u4eba\u9884\u7ea6",
        )
        if not any(marker in xml for marker in blocked_markers):
            return False
        if self._search_results_visible(xml):
            return False
        if self._has_playable_detail_context(xml):
            return False
        return True

    def _blocked_playback_reason(self, xml: str) -> str:
        if self._is_reserved_or_unplayable_context(xml):
            return "\u5f53\u524d\u7ed3\u679c\u662f\u9884\u7ea6/\u672a\u4e0a\u7ebf\u5185\u5bb9\uff0c\u6682\u4e0d\u53ef\u64ad\u653e"
        return ""

    def _has_active_playback_context(self, xml: str) -> bool:
        xml = xml or ""
        if not xml or self._feed_ad_visible(xml):
            return False
        active_markers = (
            "\u5168\u5c4f\u89c2\u770b",
            "\u9009\u96c6",
            "\u5408\u96c6",
            "\u500d\u901f",
            "\u6709\u8da3\u8bc4\u8bba",
            "\u8bf4\u70b9\u4ec0\u4e48",
        )
        if any(marker in xml for marker in active_markers):
            return True
        if COMMENT_BUTTON_ID in xml and re.search(r"\u7b2c\s*\d{1,4}\s*\u96c6", xml):
            return True
        return bool(
            re.search(
                r"(?:\u6b63\u5728\u64ad\u653e|\u5f53\u524d\u64ad\u653e|\u7eed\u64ad\u81f3|\u64ad\u653e\u4e2d|\u89c2\u770b\u4e2d)\s*\u7b2c?\s*\d{1,4}",
                xml,
            )
        )

    def _has_playable_detail_context(self, xml: str) -> bool:
        xml = xml or ""
        if not xml:
            return False
        if self._has_active_playback_context(xml):
            return True
        playable_markers = (
            "\u89c2\u770b",
            "\u64ad\u653e",
            "\u770b\u5168\u96c6",
            "\u7acb\u5373\u89c2\u770b",
            "\u5f00\u59cb\u64ad\u653e",
            "\u64ad\u653e\u5168\u90e8",
            "\u7ee7\u7eed\u89c2\u770b",
        )
        if any(marker in xml for marker in playable_markers):
            return True
        return bool(
            re.search(
                r"(?:\u5168|\u5171|\u66f4\u65b0\u81f3|\u5df2\u66f4\u65b0\u81f3|\u5b8c\u7ed3|\u5b8c\u7d50)\s*\d{1,4}\s*\u96c6",
                xml,
            )
        )

    def _playable_result_hint(self, xml: str) -> bool:
        xml = xml or ""
        return bool(
            "\u4e07\u70ed\u5ea6" in xml
            or "\u64ad\u653e" in xml
            or "\u89c2\u770b" in xml
            or re.search(r"(?:\u5168|\u5171|\u66f4\u65b0\u81f3|\u5df2\u66f4\u65b0\u81f3)\s*\d{1,4}\s*\u96c6", xml)
        )

    def _search_results_visible(self, xml: Optional[str] = None) -> bool:
        xml = xml or self._xml()
        if not xml:
            return False
        if "android.widget.EditText" not in xml:
            return False
        if any(tab in xml for tab in ["综合", "漫剧", "社区", "影视", "小说"]):
            return True
        if f'package="{APP_PACKAGE}"' not in xml:
            return False
        if 'text="搜索"' not in xml and 'content-desc="搜索"' not in xml:
            return False
        result_title_count = 0
        result_hint_count = 0
        for node in self._xml_nodes(xml):
            if f'package="{APP_PACKAGE}"' not in node or 'class="android.widget.EditText"' in node:
                continue
            text = html.unescape(self._xml_attr(node, "text")).strip()
            if not text:
                continue
            bounds = self._node_bounds(node)
            if bounds and bounds[1] < int(self.height * 0.16):
                continue
            if self._is_title_candidate(text):
                result_title_count += 1
            if self._playable_result_hint(node) or any(marker in text for marker in ("预约", "上线", "第")):
                result_hint_count += 1
        return result_title_count >= 1

    def _search_submitted_results_visible(self, xml: Optional[str] = None) -> bool:
        xml = xml or self._xml()
        return self._search_results_visible(xml) and any(tab in xml for tab in ["综合", "漫剧", "社区", "影视", "小说"])

    def _search_suggestion_page_visible(self, xml: Optional[str] = None) -> bool:
        xml = xml or self._xml()
        if not self._search_results_visible(xml):
            return False
        if self._search_submitted_results_visible(xml):
            return False
        texts = self._extract_xml_texts(xml)
        if any(tab in texts for tab in ["综合", "漫剧", "社区", "影视", "小说"]):
            return False
        return any("搜索" in text for text in texts[:5])

    def _current_playing_title(self, xml: Optional[str] = None) -> str:
        xml = xml or self._xml()
        if self._search_results_visible(xml):
            return ""
        if self._is_reserved_or_unplayable_context(xml):
            return ""
        for pattern in [
            r"合集 · ([^·\n<\"]+) ·",
            r'text="([^"<>\n]{2,40})\s*(?:[>＞]|&gt;)"',
        ]:
            match = re.search(pattern, xml)
            if match:
                title = match.group(1).strip("《》 ")
                if self._looks_like_drama_title(title):
                    return title
        candidates: List[tuple[int, str]] = []
        for node in self._xml_nodes(xml):
            text = html.unescape(self._xml_attr(node, "text")).strip("《》 ")
            if not self._looks_like_drama_title(text):
                continue
            bounds = self._node_bounds(node)
            if not bounds:
                continue
            left, top, right, bottom = bounds
            if top < int(self.height * 0.18):
                continue
            context = self._xml_context_around_bounds(left, top, right, bottom, padding=220)
            if not re.search(r"全\d+集|第\d+季|(?:共)?\d+万人?在追|观看完整短剧", context):
                continue
            score = 0
            if bottom > int(self.height * 0.55):
                score += 8
            if left <= int(self.width * 0.2):
                score += 4
            if 4 <= len(text) <= 24:
                score += 4
            if re.search(r"[，。！？!?.…]{2,}", text):
                score -= 4
            if text.endswith(("，", "。", "！", "?", "？", "…")):
                score -= 2
            if any(marker in text for marker in ("首页", "剧场", "商城", "我的", "热评", "作者声明", "主演说")):
                continue
            candidates.append((score, text))
        if candidates:
            candidates.sort(key=lambda item: (-item[0], len(item[1]), item[1]))
            return candidates[0][1]
        return ""

    def _looks_like_drama_title(self, value: str) -> bool:
        text = str(value or "").strip()
        if not text:
            return False
        if re.match(r"^[@＠][\w\u4e00-\u9fff·.-]{1,24}$", text):
            return False
        text_key = re.sub(r"[\s\u00b7,，。:：\-_/\\]+", "", text)
        if re.fullmatch(r"(?:已完结|连载中|更新至)?全\d+集", text_key):
            return False
        if not re.search(r"[\u4e00-\u9fff]{2,}", text_key):
            return False
        if any(marker in text for marker in ("首页", "剧场", "商城", "赚钱", "我的", "热评", "观看完整短剧", "观看完整漫剧", "观看完整", "作者声明", "主演说", "选集", "合集", "短剧号")):
            return False
        if re.search(r"^(?:第\d+集|第[一二三四五六七八九十]+季|全\d+集|\d+\.?\d*万|立即预约|展开|选集)$", text):
            return False
        if len(text) > 32:
            return False
        return bool(re.search(r"[\u4e00-\u9fff]", text))

    def _loose_title_match(self, expected: str, actual: str) -> bool:
        expected_key = self._normalize_title_key(expected)
        actual_key = self._normalize_title_key(actual)
        if not expected_key or not actual_key:
            return False
        expected_season = self._season_marker(expected_key)
        expected_base = self._strip_season_marker(expected_key)
        actual_season = self._season_marker(actual_key, expected_base)
        if actual_season and not self._season_equivalent(expected_season, actual_season):
            return False
        if expected_key in actual_key or actual_key in expected_key:
            return True
        actual_base = self._strip_season_marker(actual_key)
        if len(expected_base) >= 4 and expected_base in actual_base:
            return True
        return any(part in actual_base for part in self._title_core_parts(expected_base))

    def _normalize_title_key(self, value: str) -> str:
        cleaned = re.sub(r"[\u200b-\u200f\u202a-\u202e\ufeff]", "", str(value or ""))
        return re.sub(r"[\s《》<>:：·,，。.!！?？\-_/\\]+", "", cleaned.lower())

    def _strip_season_marker(self, value: str) -> str:
        text = re.sub(r"第[一二三四五六七八九十\d]+季", "", value or "")
        return re.sub(r"(?<=[\u4e00-\u9fff])\d+$", "", text)

    def _season_marker(self, value: str, base: str = "") -> str:
        match = re.search(r"第([一二三四五六七八九十\d]+)季", value or "")
        if match:
            return match.group(1)
        if base:
            suffix = re.match(rf"{re.escape(base)}(\d+)(?:$|[\u4e00-\u9fff])", value or "")
            if suffix:
                return suffix.group(1)
        suffix = re.match(r"[\u4e00-\u9fff]{2,}(\d+)$", value or "")
        if suffix:
            return suffix.group(1)
        return ""

    def _season_equivalent(self, expected: str, actual: str) -> bool:
        expected_value = self._normalize_season_value(expected)
        actual_value = self._normalize_season_value(actual)
        if not expected_value and actual_value == "1":
            return True
        if expected_value == "1" and not actual_value:
            return True
        return expected_value == actual_value

    def _title_core_parts(self, value: str) -> List[str]:
        parts: List[str] = []
        text = self._strip_season_marker(value)
        if len(text) >= 4:
            parts.append(text)
        for size in range(min(6, len(text)), 3, -1):
            for idx in range(0, len(text) - size + 1):
                part = text[idx : idx + size]
                if part not in parts:
                    parts.append(part)
        return parts[:8]

    def _normalize_season_value(self, value: str) -> str:
        text = str(value or "").strip().lower()
        numerals = {
            "一": "1",
            "二": "2",
            "两": "2",
            "三": "3",
            "四": "4",
            "五": "5",
            "六": "6",
            "七": "7",
            "八": "8",
            "九": "9",
            "十": "10",
        }
        return numerals.get(text, text)

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
        for _ in range(7):
            if self._click_visible_episode_node(episode_number):
                return True
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
                            bounds = info.get("bounds", {}) or {}
                            y = bounds.get("top", 0)
                            bottom = bounds.get("bottom", y)
                            if y > self.height * 0.25 and bottom < self.height * 0.92:
                                els[i].click()
                                return True
                    except Exception:
                        els.click()
                        return True
            if self._click_estimated_episode_cell(episode_number):
                return True
            visible = self._visible_episode_numbers()
            if visible:
                if episode_number > max(visible):
                    self._swipe_up(0.28)
                elif episode_number < min(visible):
                    self._swipe_down(0.28)
                else:
                    self._swipe_up(0.18)
            elif current_episode and current_episode > episode_number:
                self._swipe_down(0.35)
            else:
                self._swipe_up(0.35)
            time.sleep(1)
        return False

    def _click_visible_episode_node(self, episode_number: int) -> bool:
        candidates: List[tuple[int, int, int, int]] = []
        for node in self._xml_nodes():
            text = html.unescape(self._xml_attr(node, "text")).strip()
            if text not in {str(episode_number), f"第{episode_number}集"}:
                continue
            bounds = self._node_bounds(node)
            if not bounds:
                continue
            left, top, right, bottom = bounds
            if top < self.height * 0.25 or bottom > self.height * 0.98:
                continue
            candidates.append((left, top, right, bottom))
        if not candidates:
            return False
        left, top, right, bottom = sorted(candidates, key=lambda item: (item[1], item[0]))[0]
        cy = (top + bottom) // 2
        if cy > self.height * 0.92:
            self._swipe_up(0.16)
            time.sleep(0.8)
            return False
        self.d.click((left + right) // 2, cy)
        time.sleep(1)
        return True

    def _visible_episode_numbers(self) -> List[int]:
        xml = self._xml()
        numbers: List[int] = []
        for node in self._xml_nodes(xml):
            text = html.unescape(self._xml_attr(node, "text")).strip()
            if not re.fullmatch(r"\d{1,4}", text):
                continue
            bounds = self._node_bounds(node)
            if not bounds:
                continue
            _, top, _, bottom = bounds
            if top < self.height * 0.25 or bottom > self.height * 0.94:
                continue
            numbers.append(int(text))
        return sorted(set(numbers))

    def _click_estimated_episode_cell(self, episode_number: int) -> bool:
        cells: List[tuple[int, int, int, int, int]] = []
        for node in self._xml_nodes():
            text = html.unescape(self._xml_attr(node, "text")).strip()
            if not re.fullmatch(r"\d{1,4}", text):
                continue
            bounds = self._node_bounds(node)
            if not bounds:
                continue
            left, top, right, bottom = bounds
            if top < self.height * 0.25 or bottom > self.height * 0.94:
                continue
            cells.append((int(text), left, top, right, bottom))
        if not cells:
            return False
        for number, left, top, right, bottom in cells:
            if number != episode_number:
                continue
            cy = (top + bottom) // 2
            if cy >= self.height * 0.92:
                self._swipe_up(0.16)
                time.sleep(0.8)
                return False
            self.d.click((left + right) // 2, cy)
            time.sleep(1)
            return True
        columns = sorted({(left + right) // 2 for _, left, _, right, _ in cells})
        rows = sorted({(top + bottom) // 2 for _, _, top, _, bottom in cells})
        columns = self._cluster_positions(columns)
        rows = self._cluster_positions(rows)
        if not columns or not rows:
            return False
        first = min(cells, key=lambda item: (item[2], item[1]))[0]
        col_count = max(1, len(columns))
        offset = episode_number - first
        if offset < 0:
            return False
        row_idx = offset // col_count
        col_idx = offset % col_count
        if row_idx >= len(rows) or col_idx >= len(columns):
            return False
        x = columns[col_idx]
        y = rows[row_idx]
        if y > self.height * 0.88:
            self._swipe_up(0.22)
            time.sleep(0.8)
            return False
        self.d.click(x, y)
        time.sleep(1)
        return True

    def _cluster_positions(self, values: List[int], tolerance: int = 24) -> List[int]:
        clusters: List[List[int]] = []
        for value in sorted(values):
            if not clusters or abs(value - clusters[-1][-1]) > tolerance:
                clusters.append([value])
            else:
                clusters[-1].append(value)
        return [sum(cluster) // len(cluster) for cluster in clusters]

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
        playable_titles = []
        playable_seen = set()
        xml = self._xml()
        nodes = self._xml_nodes(xml)
        if f'package="{APP_PACKAGE}"' in xml:
            nodes = [node for node in nodes if f'package="{APP_PACKAGE}"' in node]
        min_top = int(self.height * (0.10 if self._search_results_visible(xml) else 0.16))
        for node in nodes:
            if 'class="android.widget.EditText"' in node:
                continue
            text = html.unescape(self._xml_attr(node, "text")).strip()
            if not text:
                continue
            bounds = self._node_bounds(node)
            if bounds and bounds[1] < min_top:
                continue
            if self._is_title_candidate(text) and text not in seen:
                titles.append(text)
                seen.add(text)
                context = ""
                if bounds:
                    left, top, right, bottom = bounds
                    context = self._xml_context_around_bounds(left, top, right, bottom, padding=150, xml=xml)
                    if not self._playable_result_hint(context):
                        context = self._xml_result_row_context(top, bottom, xml=xml)
                if self._playable_result_hint(context) and text not in playable_seen:
                    playable_titles.append(text)
                    playable_seen.add(text)
        if playable_titles:
            return playable_titles
        return titles

    def _extract_detail_title(self, xml: Optional[str] = None) -> str:
        xml = xml or self._xml()
        current_title = self._current_playing_title(xml)
        if current_title:
            return current_title
        for pattern in [
            r'text="([^"]{4,25})"[^>]*bounds="\[24,\d+\]\[\d+,\d+\]"',
            r'text="([^"]{4,25})"',
        ]:
            for candidate in re.findall(pattern, xml):
                if self._looks_like_description(candidate):
                    continue
                if self._is_title_candidate(candidate):
                    return candidate
        return ""

    def _looks_like_description(self, text: str) -> bool:
        text = (text or "").strip()
        if not text:
            return False
        if "…" in text or "..." in text:
            return True
        return len(text) >= 18 and not any(marker in text for marker in ("第", "季", "：", ":"))

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
            "百度",
            "凤凰",
            "天猫",
            "京东",
            "淘宝",
            "头条",
            "导航",
            "我的站点",
            "添加",
            "Unsplash",
        }
        if any(word in text for word in skip_words):
            return False
        if any(word in text for word in TAG_KEYWORDS) and len(text) <= 8:
            return False
        if text in {"历史古代", "历史", "古代", "都市", "现代"}:
            return False
        if re.fullmatch(r"第[一二三四五六七八九十\d]+[季集]", text):
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
            if inp is not None and hasattr(inp, "set_text"):
                inp.set_text("")
                return
        except Exception:
            pass
        try:
            if inp is not None:
                inp.clear_text()
                return
        except Exception:
            pass
        try:
            self.d.clear_text()
        except Exception:
            pass

    def _type_text(self, text: str) -> bool:
        try:
            self.d.send_keys(text)
            return True
        except Exception:
            return False

    def _set_input_text(self, inp: Any, text: str, verify: bool = False) -> Dict[str, Any]:
        actual_text = ""
        last_method = ""
        writers = []
        if inp is not None and hasattr(inp, "set_text"):
            writers.append(("控件写入", lambda value: inp.set_text(value)))
        writers.append(("整段输入", lambda value: self._type_text(value)))
        writers.append(("ADB输入", lambda value: self._adb_input_text(value)))

        for _ in range(2):
            for method, writer in writers:
                last_method = method
                self._focus_existing_input(inp)
                self._clear_input(inp)
                time.sleep(0.2)
                try:
                    written = writer(text)
                except Exception:
                    written = False
                if written is False:
                    continue
                time.sleep(0.5)
                actual_text = self._read_input_text(inp)
                if not verify or self._input_text_matches(text, actual_text):
                    return {"success": True, "method": method, "actual_text": actual_text or text}
        return {"success": False, "actual_text": actual_text, "method": last_method}

    def _focus_existing_input(self, inp: Any = None) -> None:
        try:
            if inp is not None:
                inp.click()
                return
        except Exception:
            pass
        try:
            current = self.d(className="android.widget.EditText")
            if self._exists(current, 0.5):
                current.click()
        except Exception:
            pass

    def _adb_input_text(self, text: str) -> bool:
        try:
            escaped = str(text or "").replace("\\", "\\\\").replace(" ", "%s")
            self.d.shell(f"input text {escaped}")
            return True
        except Exception:
            return False

    def _tap(self, x: int, y: int) -> bool:
        x = min(max(int(x), 1), max(1, self.width - 1))
        y = min(max(int(y), 1), max(1, self.height - 1))
        try:
            self.d.shell(f"input -d 0 tap {x} {y}")
            return True
        except Exception:
            try:
                self.d.click(x, y)
                return True
            except Exception:
                return False

    def _tap_selector(self, selector: Any) -> bool:
        try:
            info = getattr(selector, "info", None) or {}
            bounds = info.get("bounds") if isinstance(info, dict) else None
            if isinstance(bounds, dict):
                left = int(bounds.get("left", 0))
                top = int(bounds.get("top", 0))
                right = int(bounds.get("right", 0))
                bottom = int(bounds.get("bottom", 0))
                if right > left and bottom > top:
                    return self._tap((left + right) // 2, (top + bottom) // 2)
        except Exception:
            pass
        return False

    def _read_input_text(self, inp: Any = None) -> str:
        candidates: List[str] = []
        if inp is not None:
            try:
                get_text = getattr(inp, "get_text", None)
                if callable(get_text):
                    candidates.append(str(get_text() or ""))
            except Exception:
                pass
            try:
                info = getattr(inp, "info", None) or {}
                if isinstance(info, dict):
                    candidates.append(str(info.get("text") or ""))
                    candidates.append(str(info.get("contentDescription") or ""))
            except Exception:
                pass
        xml = self._xml()
        nodes = re.findall(r"<node\b[^>]*>", xml)
        edit_nodes = [node for node in nodes if 'class="android.widget.EditText"' in node]
        focused_nodes = [node for node in edit_nodes if 'focused="true"' in node]
        for node in focused_nodes + edit_nodes:
            value = self._xml_attr(node, "text") or self._xml_attr(node, "content-desc")
            if value:
                candidates.append(value)
        for value in candidates:
            value = html.unescape(value).strip()
            if value:
                return value
        return ""

    def _xml_attr(self, node: str, name: str) -> str:
        match = re.search(rf'{re.escape(name)}="([^"]*)"', node)
        return match.group(1) if match else ""

    def _xml_nodes(self, xml: Optional[str] = None) -> List[str]:
        return re.findall(r"<node\b[^>]*>", xml or self._xml())

    def _node_bounds(self, node: str) -> Optional[tuple[int, int, int, int]]:
        match = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', node)
        if not match:
            return None
        return tuple(int(value) for value in match.groups())

    def _input_text_matches(self, expected: str, actual: str) -> bool:
        expected_key = re.sub(r"\s+", "", str(expected or ""))
        actual_key = re.sub(r"\s+", "", str(actual or ""))
        return bool(expected_key) and expected_key == actual_key

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

    def _shell(self, command: str, timeout: float = 10) -> Any:
        try:
            return self.d.shell(command, timeout=timeout)
        except TypeError:
            return self.d.shell(command)

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
