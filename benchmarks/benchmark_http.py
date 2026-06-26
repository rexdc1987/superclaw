"""HTTP 客户端性能基准测试。

测量指标：
- 单次请求延迟
- 并发吞吐量（requests/sec）
- 连接池复用效果
- 中间件链开销

输出 JSON 格式结果，便于追踪。
"""

import asyncio
import json
import time
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# 确保项目根目录在 path 中
project_root = str(Path(__file__).parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import httpx
from rpa.http.client import HttpClient
from rpa.http.retry import RetryPolicy, ExponentialBackoff
from rpa.http.middleware import MiddlewareChain, UARotator, PlatformHeaders, RateLimiter, RequestLogger


async def bench_single_request(n=100):
    """单次请求延迟基准"""
    client = HttpClient()

    # Mock httpx
    async def mock_request(**kwargs):
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        return resp

    results = []
    with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
        for _ in range(n):
            t0 = time.monotonic()
            await client.get("https://api.test.com/data")
            elapsed = (time.monotonic() - t0) * 1000
            results.append(elapsed)

    return {
        "test": "single_request_latency",
        "iterations": n,
        "avg_ms": round(sum(results) / len(results), 2),
        "min_ms": round(min(results), 2),
        "max_ms": round(max(results), 2),
        "p50_ms": round(sorted(results)[len(results) // 2], 2),
        "p95_ms": round(sorted(results)[int(len(results) * 0.95)], 2),
    }


async def bench_concurrent_requests(n=50):
    """并发请求吞吐量基准"""
    client = HttpClient()
    results = []

    async def mock_request(**kwargs):
        await asyncio.sleep(0.001)  # 模拟 1ms 网络延迟
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        return resp

    with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
        t0 = time.monotonic()

        async def do_request():
            t_start = time.monotonic()
            await client.get("https://api.test.com/data")
            elapsed = (time.monotonic() - t_start) * 1000
            results.append(elapsed)

        tasks = [do_request() for _ in range(n)]
        await asyncio.gather(*tasks)
        total_time = (time.monotonic() - t0) * 1000

    throughput = n / (total_time / 1000) if total_time > 0 else 0

    return {
        "test": "concurrent_throughput",
        "concurrency": n,
        "total_time_ms": round(total_time, 2),
        "throughput_rps": round(throughput, 1),
        "avg_latency_ms": round(sum(results) / len(results), 2),
        "p95_latency_ms": round(sorted(results)[int(len(results) * 0.95)], 2),
    }


async def bench_middleware_chain(n=100):
    """中间件链开销基准"""
    chain = MiddlewareChain()
    chain.add(UARotator())
    chain.add(PlatformHeaders("douyin"))
    chain.add(RateLimiter(max_per_minute=10000))
    chain.add(RequestLogger())

    results = []
    for _ in range(n):
        t0 = time.monotonic()
        await chain.process_request("acc1", "https://api.douyin.com/test", "GET")
        elapsed = (time.monotonic() - t0) * 1000
        results.append(elapsed)

    return {
        "test": "middleware_chain_overhead",
        "iterations": n,
        "avg_ms": round(sum(results) / len(results), 3),
        "min_ms": round(min(results), 3),
        "max_ms": round(max(results), 3),
        "total_ms": round(sum(results), 2),
    }


async def bench_middleware_vs_plain(n=100):
    """中间件 vs 无中间件对比"""
    chain = MiddlewareChain()
    chain.add(UARotator())
    chain.add(PlatformHeaders("douyin"))

    mw_times = []
    plain_times = []

    for _ in range(n):
        # 有中间件
        t0 = time.monotonic()
        await chain.process_request("acc1", "https://api.douyin.com/test", "GET")
        mw_times.append((time.monotonic() - t0) * 1000)

        # 无中间件
        t0 = time.monotonic()
        _ = {"User-Agent": "test", "Referer": "https://x.com"}
        plain_times.append((time.monotonic() - t0) * 1000)

    mw_avg = sum(mw_times) / len(mw_times)
    plain_avg = sum(plain_times) / len(plain_times)

    return {
        "test": "middleware_vs_plain",
        "iterations": n,
        "middleware_avg_ms": round(mw_avg, 4),
        "plain_avg_ms": round(plain_avg, 4),
        "overhead_ms": round(mw_avg - plain_avg, 4),
        "overhead_pct": round((mw_avg / plain_avg - 1) * 100, 1) if plain_avg > 0 else 0,
    }


async def run_all():
    """运行所有基准测试"""
    print("Running HTTP benchmarks...")
    results = {}
    results["single_request"] = await bench_single_request()
    results["concurrent"] = await bench_concurrent_requests()
    results["middleware_overhead"] = await bench_middleware_chain()
    results["middleware_vs_plain"] = await bench_middleware_vs_plain()

    # 输出
    output_path = Path(__file__).parent / "results_http.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"Results saved to {output_path}")

    # 打印摘要
    for name, data in results.items():
        print(f"\n=== {name} ===")
        for k, v in data.items():
            if k != "test":
                print(f"  {k}: {v}")

    return results


if __name__ == "__main__":
    asyncio.run(run_all())
