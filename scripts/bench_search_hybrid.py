"""检索层微基准：对比 BM25 与 kNN 串行、并行两种实现的耗时。

不依赖真实 Elasticsearch：用注入固定延迟的桩函数替代 _bm25_search / _vector_search，
两路返回同一批候选，因此两组的差异只来自「是否并发」。
"""

from __future__ import annotations

import asyncio
import statistics
import time
from collections.abc import Awaitable, Callable
from typing import Any

from rag_app.config import Settings
from rag_app.services.elasticsearch import ElasticsearchStore

SIZE = 30
ROUNDS = 20
WARMUP = 3
SCENARIOS: list[tuple[str, float, float]] = [
    ("BM25 40ms / kNN 120ms", 40.0, 120.0),
    ("BM25 120ms / kNN 40ms", 120.0, 40.0),
    ("BM25 80ms / kNN 80ms", 80.0, 80.0),
    ("BM25 200ms / kNN 200ms", 200.0, 200.0),
]


def fake_hits(count: int) -> list[dict[str, Any]]:
    # 固定候选集，两路各取一半重叠，让 RRF 真正发生合并
    return [{"chunk_id": f"c{index % 20}", "score": 1.0 / (index + 1)} for index in range(count)]


async def serial_search(
    store: ElasticsearchStore,
    query: str,
    query_vector: list[float],
    size: int,
) -> list[dict[str, Any]]:
    # 改动前的实现：两路依次 await
    bm25_hits = await store._bm25_search(query, size)
    vector_hits = await store._vector_search(query_vector, size)
    return store._reciprocal_rank_fusion(bm25_hits, vector_hits)


async def parallel_search(
    store: ElasticsearchStore,
    query: str,
    query_vector: list[float],
    size: int,
) -> list[dict[str, Any]]:
    # 改动后的实现
    return await store.search_hybrid(query, query_vector=query_vector, size=size)


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(round((len(ordered) - 1) * fraction), len(ordered) - 1)
    return ordered[index]


async def measure(
    store: ElasticsearchStore,
    runner: Callable[..., Awaitable[list[dict[str, Any]]]],
    bm25_ms: float,
    knn_ms: float,
    subqueries: int,
) -> list[float]:

    async def bm25_stub(query: str, size: int) -> list[dict[str, Any]]:
        await asyncio.sleep(bm25_ms / 1000)
        return fake_hits(size)

    async def knn_stub(query_vector: list[float], size: int) -> list[dict[str, Any]]:
        await asyncio.sleep(knn_ms / 1000)
        return fake_hits(size)

    store._bm25_search = bm25_stub  # type: ignore[method-assign]
    store._vector_search = knn_stub  # type: ignore[method-assign]

    async def once() -> None:
        # 对应 nodes.retrieve 里对多个子问题并发 retrieve
        await asyncio.gather(
            *(
                runner(store, f"子问题{index}", [0.0] * 8, SIZE)
                for index in range(subqueries)
            )
        )

    for _ in range(WARMUP):
        await once()

    samples: list[float] = []
    for _ in range(ROUNDS):
        started = time.perf_counter()
        await once()
        samples.append((time.perf_counter() - started) * 1000)
    return samples


async def main() -> None:
    store = ElasticsearchStore(Settings())
    rows: list[str] = []
    try:
        for subqueries in (1, 3):
            rows.append(f"\n### 单次请求 {subqueries} 个子问题\n")
            rows.append("| 场景 | 串行 mean | 串行 p95 | 并行 mean | 并行 p95 | 节省 | 降幅 |")
            rows.append("| --- | --- | --- | --- | --- | --- | --- |")
            for name, bm25_ms, knn_ms in SCENARIOS:
                serial = await measure(store, serial_search, bm25_ms, knn_ms, subqueries)
                parallel = await measure(store, parallel_search, bm25_ms, knn_ms, subqueries)
                serial_mean = statistics.fmean(serial)
                parallel_mean = statistics.fmean(parallel)
                saved = serial_mean - parallel_mean
                rows.append(
                    f"| {name} | {serial_mean:.1f}ms | {percentile(serial, 0.95):.1f}ms "
                    f"| {parallel_mean:.1f}ms | {percentile(parallel, 0.95):.1f}ms "
                    f"| {saved:.1f}ms | {saved / serial_mean * 100:.1f}% |"
                )
    finally:
        await store.close()

    print("\n".join(rows))


if __name__ == "__main__":
    asyncio.run(main())
