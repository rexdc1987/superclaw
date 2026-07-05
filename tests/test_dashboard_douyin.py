"""
SuperClaw Dashboard - 抖音评论页面单元测试

覆盖：
1. 页面加载与渲染
2. 表单元素完整性
3. API 参数校验
4. API 控制端点
5. 概览页未被破坏
"""

import sys
from pathlib import Path

import subprocess

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from fastapi.testclient import TestClient
from rpa.dashboard.app import app, DouyinCommentRequest, ControlRequest


client = TestClient(app)


# ============================================================
# 1. 页面加载
# ============================================================

class TestPageLoad:
    """页面基本加载"""

    def test_status_code(self):
        resp = client.get("/douyin-comment")
        assert resp.status_code == 200

    def test_content_type(self):
        resp = client.get("/douyin-comment")
        assert "text/html" in resp.headers["content-type"]

    def test_contains_title(self):
        resp = client.get("/douyin-comment")
        assert "抖音自动评论" in resp.text


# ============================================================
# 2. 表单元素完整性（9个区块）
# ============================================================

class TestFormElements:
    """表单元素检查"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.html = client.get("/douyin-comment").text

    # 区块1: 账号选择
    def test_account_list(self):
        assert "account-list" in self.html
        assert "acc-card" in self.html

    # 区块2: 搜索配置
    def test_keywords_input(self):
        assert 'id="keywords"' in self.html
        assert "香港移民" in self.html

    def test_time_range_select(self):
        assert 'id="time_range"' in self.html
        assert 'value="30"' in self.html  # 默认一个月内

    def test_sort_by_select(self):
        assert 'id="sort_by"' in self.html
        assert "综合排序" in self.html

    # 区块3: 节奏控制
    def test_video_count(self):
        assert 'id="video_count"' in self.html
        assert 'value="10"' in self.html

    def test_comment_interval(self):
        assert 'id="interval_min"' in self.html
        assert 'id="interval_max"' in self.html

    def test_keyword_rotate(self):
        assert 'id="keyword_rotate"' in self.html

    def test_rest_after(self):
        assert 'id="rest_after"' in self.html

    def test_rest_interval(self):
        assert 'id="rest_min"' in self.html
        assert 'id="rest_max"' in self.html

    # 区块4: 评论内容
    def test_comments_textarea(self):
        assert 'id="comments"' in self.html

    def test_mention_checkbox(self):
        assert 'id="use_mention"' in self.html
        assert 'id="mention_user"' in self.html

    def test_image_checkbox(self):
        assert 'id="use_image"' in self.html
        assert 'id="image_folder"' in self.html

    # 区块5: 过滤筛选
    def test_filter_province(self):
        assert 'id="use_province"' in self.html
        assert 'id="filter_province"' in self.html

    def test_filter_time(self):
        assert 'id="use_filter_time"' in self.html

    def test_filter_keywords(self):
        assert 'id="use_filter_kw"' in self.html
        assert 'id="filter_keywords"' in self.html

    def test_filter_count(self):
        assert 'id="filter_count"' in self.html

    # 区块6: 互动行为
    def test_action_checkboxes(self):
        assert 'id="act_like"' in self.html
        assert 'id="act_follow"' in self.html
        assert 'id="act_fav"' in self.html
        assert 'id="act_view"' in self.html

    # 区块7: 执行控制
    def test_control_buttons(self):
        assert 'id="btn-start"' in self.html
        assert 'id="btn-pause"' in self.html
        assert 'id="btn-stop"' in self.html

    # 区块8: 执行结果
    def test_log_panel(self):
        assert 'id="log-panel"' in self.html

    def test_screenshot_area(self):
        assert 'id="ss-area"' in self.html

    def test_result_detail(self):
        assert 'id="result-detail"' in self.html

    # 区块9: 执行历史
    def test_history_table(self):
        assert 'id="hist-body"' in self.html

    # 侧边栏
    def test_sidebar(self):
        assert 'class="sidebar"' in self.html
        assert 'href="/"' in self.html
        assert 'href="/douyin-comment"' in self.html


# ============================================================
# 3. API 参数校验
# ============================================================

class TestAPIValidation:
    """API 参数校验"""

    def test_empty_body(self):
        resp = client.post("/api/douyin-comment", json={})
        assert resp.status_code == 400
        data = resp.json()
        assert data["success"] is False

    def test_missing_keywords(self):
        resp = client.post("/api/douyin-comment", json={
            "keywords": [], "comments": ["好"]
        })
        assert resp.status_code == 400

    def test_missing_comments(self):
        resp = client.post("/api/douyin-comment", json={
            "keywords": ["test"], "comments": []
        })
        assert resp.status_code == 400

    def test_invalid_json(self):
        resp = client.post("/api/douyin-comment", content="not json",
                           headers={"Content-Type": "application/json"})
        assert resp.status_code == 400

    def test_valid_minimal(self):
        """最小合法请求（不实际执行命令，会超时或失败，但参数校验通过）"""
        # 使用 mock 避免实际 subprocess
        from unittest.mock import patch
        with patch("rpa.dashboard.app.subprocess") as mock_sub:
            mock_sub.TimeoutExpired = subprocess.TimeoutExpired
            exc = subprocess.TimeoutExpired(cmd="mock", timeout=600)
            mock_sub.run.side_effect = exc
            resp = client.post("/api/douyin-comment", json={
                "keywords": ["test"], "comments": ["hello"]
            })
            # 会返回 504 超时
            assert resp.status_code == 504


# ============================================================
# 4. 请求模型测试
# ============================================================

class TestRequestModel:
    """Pydantic 模型"""

    def test_defaults(self):
        req = DouyinCommentRequest()
        assert req.account_id == "default"
        assert req.video_count == 10
        assert req.time_range == 0
        assert req.sort_by == "general"
        assert req.actions["like"] is True
        assert req.actions["follow"] is True

    def test_custom_values(self):
        req = DouyinCommentRequest(
            keywords=["a", "b"], comments=["c1", "c2"],
            video_count=20, time_range=7, sort_by="latest",
            mention_user="豆包", send_image=True, image_folder="/imgs",
            actions={"like": False, "follow": True, "favorite": False, "view": True}
        )
        assert len(req.keywords) == 2
        assert req.video_count == 20
        assert req.mention_user == "豆包"
        assert req.actions["like"] is False

    def test_control_model(self):
        req = ControlRequest(action="pause")
        assert req.action == "pause"


# ============================================================
# 5. 控制端点测试
# ============================================================

class TestControlEndpoint:
    """执行控制 API"""

    def test_pause(self):
        resp = client.post("/api/douyin-comment/control", json={"action": "pause"})
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert resp.json()["action"] == "pause"

    def test_stop(self):
        resp = client.post("/api/douyin-comment/control", json={"action": "stop"})
        assert resp.status_code == 200
        assert resp.json()["action"] == "stop"

    def test_invalid_action(self):
        resp = client.post("/api/douyin-comment/control", json={"action": "invalid"})
        assert resp.status_code == 200  # Pydantic 不验证值，只验证字段存在

    def test_missing_action(self):
        resp = client.post("/api/douyin-comment/control", json={})
        assert resp.status_code == 400


# ============================================================
# 6. 概览页未被破坏
# ============================================================

class TestOverviewUnbroken:
    """确认概览页不受影响"""

    def test_overview_200(self):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_overview_has_metrics(self):
        resp = client.get("/")
        assert "总任务数" in resp.text

    def test_health_endpoint(self):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_metrics_endpoint(self):
        resp = client.get("/api/metrics")
        assert resp.status_code == 200
        assert "total_tasks" in resp.json()
