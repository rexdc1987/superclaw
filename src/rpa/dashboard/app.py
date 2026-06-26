"""
SuperClaw Web Dashboard

FastAPI + Jinja2 管控面板，提供指标概览和告警查看。

路由：
    GET /                    — 概览页面
    GET /douyin-comment      — 抖音自动评论页面
    GET /api/metrics         — JSON 指标端点
    GET /api/alerts          — 活跃告警
    GET /api/platforms       — 平台统计
    POST /api/douyin-comment — 执行抖音评论
    POST /api/douyin-comment/control — 执行控制
"""

import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from rpa.dashboard.routes_hongguo import router as hongguo_router

# ---- 全局状态 ----
_collector = None
_alert_engine = None

app = FastAPI(title="SuperClaw Dashboard", version="0.1.0")
app.include_router(hongguo_router)
TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def init_dashboard(collector=None, alert_engine=None):
    global _collector, _alert_engine
    _collector = collector
    _alert_engine = alert_engine


# ============================================================
# 请求模型（v2.0）
# ============================================================

class DouyinCommentRequest(BaseModel):
    """抖音自动评论请求体"""
    account_id: str = "default"
    keywords: List[str] = Field(default_factory=list, description="搜索关键词列表")
    time_range: int = Field(default=0, description="时间筛选: 0/1/7/30")
    sort_by: str = Field(default="general", description="排序: general/latest/hottest")
    video_count: int = Field(default=10, ge=1, le=100, description="评论视频数量")
    comment_interval: List[int] = Field(default=[1, 3], description="评论间隔范围 [min, max]")
    keyword_rotate_after: int = Field(default=10, ge=1, description="每N个视频换关键词")
    rest_after: int = Field(default=5, ge=1, description="每N次操作休息")
    rest_interval: List[int] = Field(default=[5, 10], description="休息间隔范围 [min, max]")
    comments: List[str] = Field(default_factory=list, description="评论内容列表")
    mention_user: str = Field(default="", description="@用户名")
    send_image: bool = False
    image_folder: str = ""
    filter_province: List[str] = Field(default_factory=list)
    filter_time: int = 0
    filter_keywords: List[str] = Field(default_factory=list)
    filter_count: int = 10
    actions: Dict[str, bool] = Field(default_factory=lambda: {"like": True, "follow": True, "favorite": True, "view": True})


class ControlRequest(BaseModel):
    """执行控制请求"""
    action: str = Field(description="pause/resume/stop")


# ============================================================
# HTML 页面
# ============================================================

@app.get("/", response_class=HTMLResponse)
async def overview(request: Request):
    metrics = _collector.get_summary() if _collector else _empty_summary()
    alerts = []
    if _alert_engine:
        alerts = [
            {"rule": a.rule_name, "severity": a.severity.value, "message": a.message,
             "value": a.current_value, "threshold": a.threshold, "time": a.timestamp}
            for a in _alert_engine.get_alert_history(limit=10)
        ]
    return templates.TemplateResponse(request, "overview.html", {
        "metrics": metrics, "alerts": alerts,
        "uptime": metrics.get("system", {}).get("uptime_seconds", 0),
    })


@app.get("/douyin-comment", response_class=HTMLResponse)
async def douyin_comment_page(request: Request):
    return templates.TemplateResponse(request, "douyin_comment.html", {})


@app.get("/hongguo", response_class=HTMLResponse)
async def hongguo_page(request: Request):
    return templates.TemplateResponse(request, "hongguo.html", {})


# ============================================================
# API 端点
# ============================================================

@app.get("/api/metrics")
async def api_metrics():
    if _collector:
        return JSONResponse(_collector.get_summary())
    return JSONResponse(_empty_summary())


@app.get("/api/alerts")
async def api_alerts(limit: int = 20):
    if _alert_engine:
        history = _alert_engine.get_alert_history(limit=limit)
        return JSONResponse([
            {"rule": a.rule_name, "severity": a.severity.value, "message": a.message,
             "value": a.current_value, "threshold": a.threshold, "time": a.timestamp}
            for a in history
        ])
    return JSONResponse([])


@app.get("/api/platforms")
async def api_platforms():
    if _collector:
        return JSONResponse(_collector.get_platform_stats())
    return JSONResponse({})


@app.get("/api/health")
async def api_health():
    return JSONResponse({"status": "ok", "timestamp": time.time()})


def _empty_summary() -> dict:
    return {
        "total_tasks": 0, "success": 0, "failure": 0, "success_rate": None,
        "active_accounts": 0, "queue_depth": 0, "platforms": {},
        "system": {"uptime_seconds": 0, "cpu_percent": 0, "memory_mb": 0},
    }


# ============================================================
# 抖音自动评论 API（v2.0）
# ============================================================

import subprocess
import json as _json


@app.post("/api/douyin-comment")
async def api_douyin_comment(request: Request):
    """执行抖音自动评论任务（v2.0）"""
    start_time = time.time()

    try:
        body = await request.json()
        req = DouyinCommentRequest(**body)
    except Exception as e:
        return JSONResponse({"success": False, "error": f"参数错误: {e}"}, status_code=400)

    if not req.keywords or not req.comments:
        return JSONResponse({"success": False, "error": "关键词和评论内容不能为空"}, status_code=400)

    # 构建 OpenClaw 消息
    time_labels = {0: "不限时间", 1: "一天内", 7: "一周内", 30: "一个月内"}
    time_label = time_labels.get(req.time_range, f"{req.time_range}天内")
    sort_labels = {"general": "综合排序", "latest": "最新", "hottest": "最热"}
    sort_label = sort_labels.get(req.sort_by, "综合排序")
    kw_str = "、".join(req.keywords)
    cmt_preview = req.comments[0] if req.comments else ""

    parts = [
        f"执行douyin-zidong-pinglun技能",
        f"搜索关键词：{kw_str}",
        f"筛选{time_label}视频，{sort_label}",
        f"评论{req.video_count}个视频",
        f"评论内容示例：{cmt_preview}",
    ]
    if req.mention_user:
        parts.append(f"同时@用户：{req.mention_user}")
    if req.send_image and req.image_folder:
        parts.append(f"发送图片：{req.image_folder}")
    if req.filter_keywords:
        parts.append(f"评论区关键词筛选：{' '.join(req.filter_keywords)}")
    action_tags = [k for k, v in req.actions.items() if v]
    if action_tags:
        parts.append(f"互动行为：{'、'.join(action_tags)}")

    message = "，".join(parts)

    cmd = [
        "cmd.exe", "/c",
        "set OPENCLAW_STATE_DIR=E:\\Openclaw\\.openclaw&& "
        "set OPENCLAW_CONFIG_PATH=E:\\Openclaw\\.openclaw\\openclaw.json&& "
        f"E:\\Openclaw\\npm-global\\openclaw.cmd agent --agent zhaoyun --json --timeout 600 -m \"{message}\""
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600, cwd="E:\\Openclaw")
        duration = round(time.time() - start_time, 1)

        if result.returncode == 0:
            try:
                output = _json.loads(result.stdout)
                payloads = output.get("result", {}).get("payloads", [{}])
                if payloads:
                    text = payloads[0].get("text", "")
                    media_urls = payloads[0].get("mediaUrls", [])
                    screenshot = media_urls[0] if media_urls else None
                    video_title = ""
                    match = re.search(r'"([^"]+)"\s*@', text)
                    if match:
                        video_title = match.group(1)
                    return JSONResponse({
                        "success": True, "video_title": video_title,
                        "screenshot": screenshot, "duration": f"{duration}秒", "detail": text,
                    })
            except _json.JSONDecodeError:
                pass
            return JSONResponse({"success": True, "duration": f"{duration}秒", "detail": result.stdout[:500]})
        else:
            return JSONResponse({"success": False, "error": result.stderr[:500] or "执行失败", "duration": f"{duration}秒"})

    except subprocess.TimeoutExpired:
        return JSONResponse({"success": False, "error": "执行超时（超过600秒）"}, status_code=504)
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@app.post("/api/douyin-comment/control")
async def api_douyin_comment_control(request: Request):
    """执行控制：pause/resume/stop"""
    try:
        body = await request.json()
        ctrl = ControlRequest(**body)
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=400)

    # 暂存控制状态（内存中，生产环境应持久化）
    global _control_state
    _control_state = ctrl.action
    return JSONResponse({"success": True, "action": ctrl.action})


_control_state: Optional[str] = None
