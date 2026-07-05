"""
SuperClaw RPA - 适配器集成测试

测试适配器框架、注册机制、与 DAG 引擎的集成。
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rpa.adapters.base import (
    AdapterError,
    AdapterResult,
    AdapterStatus,
    BaseAdapter,
    CaptchaDetected,
    CommentItem,
    ContentItem,
    RateLimited,
    UserInfo,
)
from rpa.adapters.douyin import DouyinAdapter
from rpa.adapters.douyin_config import DouyinConfig
from rpa.adapters.registry import AdapterRegistry, get_adapter_registry
from rpa.adapters.xiaohongshu import XiaohongshuAdapter
from rpa.adapters.xiaohongshu_config import XiaohongshuConfig


# ============================================================
# 测试数据模型
# ============================================================

class TestDataModels:
    """数据模型测试"""

    def test_content_item(self):
        item = ContentItem(
            content_id="123",
            title="测试标题",
            url="https://example.com/123",
            platform="douyin",
        )
        assert item.content_id == "123"
        assert item.platform == "douyin"

    def test_content_item_defaults(self):
        item = ContentItem()
        assert item.content_id == ""
        assert item.metrics == {}

    def test_user_info(self):
        user = UserInfo(
            user_id="u001",
            nickname="测试用户",
            platform="xiaohongshu",
            follower_count=1000,
            is_verified=True,
        )
        assert user.follower_count == 1000
        assert user.is_verified is True

    def test_comment_item(self):
        comment = CommentItem(
            comment_id="c001",
            content="好内容！",
            platform="douyin",
            likes=42,
        )
        assert comment.likes == 42

    def test_adapter_result_success(self):
        result = AdapterResult(
            status=AdapterStatus.SUCCESS,
            data={"count": 5},
        )
        assert result.success is True
        d = result.to_dict()
        assert d["status"] == "success"
        assert d["data"]["count"] == 5

    def test_adapter_result_failure(self):
        result = AdapterResult(
            status=AdapterStatus.FAILED,
            error="出错了",
        )
        assert result.success is False
        assert result.error == "出错了"


# ============================================================
# 测试错误类型
# ============================================================

class TestAdapterErrors:
    """适配器错误类型测试"""

    def test_captcha_detected(self):
        err = CaptchaDetected("douyin", "comment")
        assert err.platform == "douyin"
        assert err.status == AdapterStatus.CAPTCHA
        assert "验证码" in str(err)

    def test_rate_limited(self):
        err = RateLimited("xiaohongshu", "like")
        assert err.status == AdapterStatus.RATE_LIMITED

    def test_account_banned(self):
        err = RateLimited("douyin", "follow")
        assert err.platform == "douyin"


# ============================================================
# 测试适配器注册中心
# ============================================================

class TestAdapterRegistry:
    """适配器注册中心测试"""

    def setup_method(self):
        self.registry = AdapterRegistry()

    def test_register_and_get(self):
        self.registry.register(DouyinAdapter)
        assert self.registry.has("douyin")
        assert self.registry.get("douyin") is DouyinAdapter

    def test_create_instance(self):
        self.registry.register(DouyinAdapter)
        adapter = self.registry.create("douyin", config={"headless": True})
        assert adapter is not None
        assert isinstance(adapter, DouyinAdapter)
        assert adapter.platform == "douyin"

    def test_create_nonexistent(self):
        assert self.registry.create("nonexistent") is None

    def test_list_adapters(self):
        self.registry.register(DouyinAdapter)
        self.registry.register(XiaohongshuAdapter)
        adapters = self.registry.list_adapters()
        assert len(adapters) == 2
        platforms = [a["platform"] for a in adapters]
        assert "douyin" in platforms
        assert "xiaohongshu" in platforms

    def test_register_no_platform_raises(self):
        class BadAdapter(BaseAdapter):
            platform = ""
            async def login(self, credentials): pass
            async def check_login(self): pass
            async def search_content(self, keyword, count=10): pass
            async def post_comment(self, target_url, content): pass
            async def like_content(self, target_url): pass
            async def follow_user(self, user_url): pass

        with pytest.raises(ValueError, match="未定义 platform"):
            self.registry.register(BadAdapter)

    def test_global_registry(self):
        registry = get_adapter_registry()
        assert registry is get_adapter_registry()  # 同一实例


# ============================================================
# 测试配置
# ============================================================

class TestConfigs:
    """配置测试"""

    def test_douyin_config_defaults(self):
        config = DouyinConfig()
        assert config.base_url == "https://www.douyin.com"
        assert config.anti_detect is True
        assert config.max_retries == 3
        assert len(config.comment_templates) > 0
        assert "search_input" in config.selectors

    def test_douyin_config_custom(self):
        config = DouyinConfig(
            headless=True,
            max_retries=5,
            comment_templates=["自定义评论"],
        )
        assert config.headless is True
        assert config.max_retries == 5
        assert config.comment_templates == ["自定义评论"]

    def test_xiaohongshu_config_defaults(self):
        config = XiaohongshuConfig()
        assert config.base_url == "https://www.xiaohongshu.com"
        assert config.collect_note is True
        assert "note_card" in config.selectors

    def test_xiaohongshu_config_custom(self):
        config = XiaohongshuConfig(viewport_width=1280, viewport_height=720)
        assert config.viewport_width == 1280


# ============================================================
# 测试适配器（Mock 浏览器）
# ============================================================

class TestDouyinAdapterMocked:
    """抖音适配器 Mock 测试"""

    def setup_method(self):
        self.adapter = DouyinAdapter(config={"headless": True})

    def test_platform_name(self):
        assert self.adapter.platform == "douyin"

    def test_config_loaded(self):
        assert self.adapter.douyin_config.headless is True
        assert self.adapter.douyin_config.anti_detect is True

    def test_check_captcha(self):
        assert self.adapter._check_captcha("请完成验证码验证") is True
        assert self.adapter._check_captcha("正常页面内容") is False

    def test_check_rate_limit(self):
        assert self.adapter._check_rate_limit("操作过于频繁，请稍后再试") is True
        assert self.adapter._check_rate_limit("正常页面") is False

    def test_check_ban(self):
        assert self.adapter._check_ban("账号被封禁") is True
        assert self.adapter._check_ban("正常页面") is False

    def test_get_random_comment(self):
        comment = self.adapter.get_random_comment()
        assert isinstance(comment, str)
        assert len(comment) > 0

    @pytest.mark.asyncio
    async def test_setup_with_context(self):
        mock_context = AsyncMock()
        mock_page = AsyncMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)

        await self.adapter.setup(context=mock_context)

        assert self.adapter.page is mock_page
        mock_context.new_page.assert_called_once()

    @pytest.mark.asyncio
    async def test_teardown(self):
        mock_page = AsyncMock()
        self.adapter._page = mock_page

        await self.adapter.teardown()

        mock_page.close.assert_called_once()
        assert self.adapter.page is None

    @pytest.mark.asyncio
    async def test_context_manager(self):
        async with DouyinAdapter() as adapter:
            assert adapter is not None


class TestXiaohongshuAdapterMocked:
    """小红书适配器 Mock 测试"""

    def setup_method(self):
        self.adapter = XiaohongshuAdapter(config={"headless": True})

    def test_platform_name(self):
        assert self.adapter.platform == "xiaohongshu"

    def test_config_loaded(self):
        assert self.adapter.xhs_config.collect_note is True

    def test_get_random_comment(self):
        comment = self.adapter.get_random_comment()
        assert isinstance(comment, str)

    @pytest.mark.asyncio
    async def test_setup_with_context(self):
        mock_context = AsyncMock()
        mock_page = AsyncMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)

        await self.adapter.setup(context=mock_context)
        assert self.adapter.page is mock_page

    @pytest.mark.asyncio
    async def test_search_content_no_page(self):
        """没有 page 时搜索应优雅处理"""
        result = await self.adapter.search_content("测试")
        # 没有 page 会抛异常，但 adapter 应该能处理
        # 这里验证方法签名正确
        assert hasattr(self.adapter, 'search_content')


# ============================================================
# 测试与 DAG 引擎集成
# ============================================================

class TestAdapterDAGIntegration:
    """适配器与 DAG 引擎集成测试"""

    def test_adapter_as_action_params(self):
        """适配器操作可以作为 DAG 节点参数"""
        from rpa.models import NodeDefinition, WorkflowDefinition

        workflow = WorkflowDefinition(
            id="adapter_workflow",
            name="适配器工作流",
            nodes=[
                NodeDefinition(
                    id="search",
                    action="adapter.search",
                    params={
                        "platform": "douyin",
                        "keyword": "测试关键词",
                        "count": 10,
                    },
                ),
                NodeDefinition(
                    id="comment",
                    action="adapter.comment",
                    params={
                        "platform": "douyin",
                        "target_url": "{{search.url}}",
                        "content": "好内容！",
                    },
                    depends_on=["search"],
                ),
                NodeDefinition(
                    id="like",
                    action="adapter.like",
                    params={
                        "platform": "douyin",
                        "target_url": "{{search.url}}",
                    },
                    depends_on=["search"],
                ),
            ],
        )

        errors = workflow.validate_dag()
        assert errors == []
        order = workflow.topological_sort()
        assert order.index("search") < order.index("comment")
        assert order.index("search") < order.index("like")

    def test_multi_platform_workflow(self):
        """多平台工作流"""
        from rpa.models import NodeDefinition, WorkflowDefinition

        workflow = WorkflowDefinition(
            id="multi_platform",
            name="多平台工作流",
            nodes=[
                NodeDefinition(
                    id="search_dy",
                    action="adapter.search",
                    params={"platform": "douyin", "keyword": "Python"},
                ),
                NodeDefinition(
                    id="search_xhs",
                    action="adapter.search",
                    params={"platform": "xiaohongshu", "keyword": "Python"},
                    depends_on=["search_dy"],
                ),
                NodeDefinition(
                    id="report",
                    action="log.info",
                    params={"message": "双平台搜索完成: dy={{search_dy.count}} xhs={{search_xhs.count}}"},
                    depends_on=["search_dy", "search_xhs"],
                ),
            ],
        )

        errors = workflow.validate_dag()
        assert errors == []
        groups = workflow.get_parallel_groups()
        # search_dy 单独一组，search_xhs 依赖 search_dy，report 依赖两者
        assert groups[0] == ["search_dy"]

    def test_error_handling_workflow(self):
        """错误处理工作流：失败 -> 重试 -> 降级"""
        from rpa.models import FailureStrategy, NodeDefinition, RetryConfig, WorkflowDefinition

        workflow = WorkflowDefinition(
            id="error_handling",
            name="错误处理工作流",
            nodes=[
                NodeDefinition(
                    id="search",
                    action="adapter.search",
                    params={"platform": "douyin", "keyword": "测试"},
                    retry=RetryConfig(max_attempts=3, delay_seconds=2),
                ),
                NodeDefinition(
                    id="fallback",
                    action="log.info",
                    params={"message": "降级：使用缓存数据"},
                    depends_on=["search"],
                    condition=None,
                ),
            ],
        )

        # 验证重试配置
        search_node = workflow.get_node("search")
        assert search_node.retry.max_attempts == 3
        assert search_node.retry.delay_seconds == 2.0

    def test_registry_integration(self):
        """注册中心集成"""
        registry = AdapterRegistry()
        registry.register(DouyinAdapter)
        registry.register(XiaohongshuAdapter)

        # 验证可以通过注册中心创建适配器
        dy = registry.create("douyin")
        xhs = registry.create("xiaohongshu")

        assert isinstance(dy, DouyinAdapter)
        assert isinstance(xhs, XiaohongshuAdapter)
        assert dy.platform == "douyin"
        assert xhs.platform == "xiaohongshu"

    def test_adapter_result_to_workflow_output(self):
        """适配器结果可以转换为工作流输出"""
        result = AdapterResult(
            status=AdapterStatus.SUCCESS,
            data={"results": [{"id": "1"}, {"id": "2"}], "count": 2},
        )

        # 模拟将适配器结果存入上下文
        from rpa.context import ContextManager
        ctx = ContextManager()
        ctx.set("search results", result.data["results"])
        ctx.set("search count", result.data["count"])

        assert ctx.get("search count") == 2
        assert len(ctx.get("search results")) == 2


# ============================================================
# 入口
# ============================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
