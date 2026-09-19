"""基本运行状态：启动时间与线程安全的请求计数，供监控采集。"""

from __future__ import annotations

import threading
import time


class Monitor:
    """线程安全的进程内监控状态。

    服务本身无业务可变状态（每次求值都是纯函数），请求之间天然
    互不串扰；这里只记录监控用的聚合计数。
    """

    def __init__(self) -> None:
        self._started_at = time.monotonic()
        self._lock = threading.Lock()
        self._requests_completed = 0
        self._errors = 0

    def record_request(self, *, is_error: bool = False) -> None:
        with self._lock:
            self._requests_completed += 1
            if is_error:
                self._errors += 1

    def snapshot(self) -> dict[str, float | int | bool]:
        with self._lock:
            completed = self._requests_completed
            errors = self._errors
        return {
            "status": "ok",
            "uptime_seconds": round(time.monotonic() - self._started_at, 6),
            "requests_completed": completed,
            "errors": errors,
            "stateless": True,
        }


monitor = Monitor()
