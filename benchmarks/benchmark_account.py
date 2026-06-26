"""Account 模块性能基准测试。

测量指标：
- AccountPool 选策略延迟
- Token Manager 读写延迟
- HealthScorer 评分延迟
- ContextFactory 上下文创建延迟

输出 JSON 格式结果。
"""

import asyncio
import json
import sys
import time
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

project_root = str(Path(__file__).parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from rpa.account.models import AccountInfo, AccountStatus, HealthMetrics
from rpa.account.account_pool import AccountPool
from rpa.account.health_scorer import HealthScorer
from rpa.account.context_factory import ContextFactory
from rpa.auth.token_manager import TokenManager, TokenInfo


def bench_account_pool_selection(n=1000):
    """账号池选择延迟"""
    strategies = ["round_robin", "health_first", "random", "least_used"]
    results = {}

    for strategy in strategies:
        pool = AccountPool(strategy=strategy)
        for i in range(100):
            pool.add_account(AccountInfo(
                account_id=f"acc_{i}",
                platform="douyin",
                health_score=float(100 - i),
                use_count=i,
            ))

        times = []
        for _ in range(n):
            candidates = pool.get_available()
            t0 = time.monotonic()
            pool._select(candidates)
            times.append((time.monotonic() - t0) * 1000)

        avg = sum(times) / len(times)
        results[strategy] = {
            "iterations": n,
            "avg_us": round(avg * 1000, 2),  # 转微秒
            "min_us": round(min(times) * 1000, 2),
            "max_us": round(max(times) * 1000, 2),
        }

    return {
        "test": "account_pool_selection",
        "pool_size": 100,
        "strategies": results,
    }


def bench_health_scorer(n=1000):
    """健康度评分延迟"""
    scorer = HealthScorer()
    metrics = HealthMetrics(
        login_success=90, login_failure=10,
        action_success=180, action_failure=20,
        captcha_triggered=3, ban_count=0,
        last_check=time.time(),
    )

    times = []
    for _ in range(n):
        t0 = time.monotonic()
        scorer.calculate(metrics)
        times.append((time.monotonic() - t0) * 1000)

    avg = sum(times) / len(times)
    return {
        "test": "health_scorer",
        "iterations": n,
        "avg_us": round(avg * 1000, 2),
        "min_us": round(min(times) * 1000, 2),
        "max_us": round(max(times) * 1000, 2),
    }


def bench_token_manager_rw(n=1000):
    """Token Manager 读写延迟"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tm = TokenManager(storage_dir=tmpdir)

        # 写入延迟
        write_times = []
        for i in range(n):
            token = TokenInfo(
                access_token=f"token_{i}",
                refresh_token=f"refresh_{i}",
                expires_at=time.time() + 3600,
            )
            t0 = time.monotonic()
            tm.save(f"acc_{i}", token)
            write_times.append((time.monotonic() - t0) * 1000)

        # 读取延迟
        read_times = []
        for i in range(n):
            t0 = time.monotonic()
            tm.get(f"acc_{i}")
            read_times.append((time.monotonic() - t0) * 1000)

    write_avg = sum(write_times) / len(write_times)
    read_avg = sum(read_times) / len(read_times)

    return {
        "test": "token_manager_rw",
        "iterations": n,
        "write": {
            "avg_us": round(write_avg * 1000, 2),
            "min_us": round(min(write_times) * 1000, 2),
            "max_us": round(max(write_times) * 1000, 2),
        },
        "read": {
            "avg_us": round(read_avg * 1000, 2),
            "min_us": round(min(read_times) * 1000, 2),
            "max_us": round(max(read_times) * 1000, 2),
        },
    }


async def bench_context_factory(n=50):
    """上下文工厂创建延迟"""
    mock_context = AsyncMock()
    mock_context.storage_state = AsyncMock(return_value={"cookies": []})
    mock_context.close = AsyncMock()

    mock_browser = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)

    factory = ContextFactory(mock_browser, storage_dir=tempfile.mkdtemp(), max_contexts=n + 10)

    times = []
    for i in range(n):
        t0 = time.monotonic()
        await factory.create_context(f"acc_{i}", anti_detect=False)
        times.append((time.monotonic() - t0) * 1000)

    await factory.close_all(save=False)

    avg = sum(times) / len(times)
    return {
        "test": "context_factory_create",
        "iterations": n,
        "avg_ms": round(avg, 3),
        "min_ms": round(min(times), 3),
        "max_ms": round(max(times), 3),
    }


async def run_all():
    """运行所有基准测试"""
    print("Running Account benchmarks...")
    results = {}
    results["pool_selection"] = bench_account_pool_selection()
    results["health_scorer"] = bench_health_scorer()
    results["token_rw"] = bench_token_manager_rw()
    results["context_factory"] = await bench_context_factory()

    output_path = Path(__file__).parent / "results_account.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"Results saved to {output_path}")

    for name, data in results.items():
        print(f"\n=== {name} ===")
        print(json.dumps(data, indent=2))

    return results


if __name__ == "__main__":
    asyncio.run(run_all())
