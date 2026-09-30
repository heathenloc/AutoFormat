"""Small dependency-free concurrent load probe for repeatable local baselines."""

from __future__ import annotations

import asyncio
import math
import tracemalloc
from collections.abc import Awaitable, Callable
from time import perf_counter

from pydantic import Field

from brief_parser.domain.base import StrictModel


class LoadProbeConfig(StrictModel):
    request_count: int = Field(default=20, gt=0)
    concurrency: int = Field(default=2, gt=0)
    max_p95_ms: int = Field(default=30_000, gt=0)


class LoadProbeReport(StrictModel):
    report_version: str = "load-report/1.0"
    request_count: int = Field(ge=0)
    concurrency: int = Field(gt=0)
    succeeded: int = Field(ge=0)
    failed: int = Field(ge=0)
    p50_ms: float = Field(ge=0)
    p95_ms: float = Field(ge=0)
    max_ms: float = Field(ge=0)
    throughput_per_second: float = Field(ge=0)
    peak_traced_memory_bytes: int = Field(ge=0)
    max_p95_ms: int = Field(gt=0)
    passed: bool


async def run_load_probe(
    operation: Callable[[int], Awaitable[object]],
    config: LoadProbeConfig,
) -> LoadProbeReport:
    semaphore = asyncio.Semaphore(config.concurrency)
    durations = [0.0] * config.request_count
    failures = 0

    async def run_one(ordinal: int) -> None:
        nonlocal failures
        async with semaphore:
            started = perf_counter()
            try:
                await operation(ordinal)
            except Exception:
                failures += 1
            finally:
                durations[ordinal] = (perf_counter() - started) * 1_000

    already_tracing = tracemalloc.is_tracing()
    if not already_tracing:
        tracemalloc.start()
    started = perf_counter()
    await asyncio.gather(*(run_one(ordinal) for ordinal in range(config.request_count)))
    elapsed = max(perf_counter() - started, 1e-12)
    _, peak = tracemalloc.get_traced_memory()
    if not already_tracing:
        tracemalloc.stop()

    ordered = sorted(durations)
    p50 = _percentile(ordered, 0.50)
    p95 = _percentile(ordered, 0.95)
    succeeded = config.request_count - failures
    return LoadProbeReport(
        request_count=config.request_count,
        concurrency=config.concurrency,
        succeeded=succeeded,
        failed=failures,
        p50_ms=round(p50, 3),
        p95_ms=round(p95, 3),
        max_ms=round(max(ordered), 3),
        throughput_per_second=round(config.request_count / elapsed, 3),
        peak_traced_memory_bytes=peak,
        max_p95_ms=config.max_p95_ms,
        passed=failures == 0 and p95 <= config.max_p95_ms,
    )


def _percentile(ordered: list[float], ratio: float) -> float:
    index = max(0, math.ceil(len(ordered) * ratio) - 1)
    return ordered[index]
