"""最小运行状态采集：请求计数、错误计数、累计时延与运行时长。

计数器带锁，供并发请求安全累加；服务本身无每请求可变状态，
这里是唯一的进程内共享写点，且不参与任何窗口计算。
"""

from __future__ import annotations

import threading
import time


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.started_at_monotonic = time.monotonic()
        self.requests_total = 0
        self.errors_total = 0
        self.latency_seconds_sum = 0.0

    def record_request(self, latency_s: float, *, is_error: bool) -> None:
        with self._lock:
            self.requests_total += 1
            self.latency_seconds_sum += latency_s
            if is_error:
                self.errors_total += 1

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            requests_total = self.requests_total
            errors_total = self.errors_total
            latency_sum = self.latency_seconds_sum
        uptime = time.monotonic() - self.started_at_monotonic
        avg = latency_sum / requests_total if requests_total else 0.0
        return {
            "requests_total": requests_total,
            "errors_total": errors_total,
            "uptime_s": uptime,
            "latency_seconds_sum": latency_sum,
            "latency_seconds_avg": avg,
        }
