"""带类型的结构化错误。

四类非法输入各自有独立、稳定的 error code，上游可以据此区分处理，
服务绝不抛出未捕获异常或返回空值。
"""

from __future__ import annotations

from typing import Any


class CubicServiceError(Exception):
    """所有业务校验错误的基类。"""

    error_code: str = "invalid_input"
    http_status: int = 422

    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.field = field

    def to_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "error": {
                "code": self.error_code,
                "message": self.message,
            }
        }
        if self.field is not None:
            body["error"]["field"] = self.field
        return body


class InvalidWmaxError(CubicServiceError):
    """峰值窗口 W_max <= 0（W_max = 0 的退化情形同样非法）。"""

    error_code = "invalid_wmax"


class InvalidCError(CubicServiceError):
    """立方系数 C <= 0。"""

    error_code = "invalid_c"


class InvalidTimeError(CubicServiceError):
    """时间取负（单点的 t 或轨迹中的某个采样时刻）。"""

    error_code = "invalid_time"


class InvalidRttError(CubicServiceError):
    """往返时延 RTT <= 0。"""

    error_code = "invalid_rtt"


class NonFiniteNumberError(CubicServiceError):
    """数值不是有限实数（NaN / +Inf / -Inf）。"""

    error_code = "non_finite_number"


class NonIncreasingTimesError(CubicServiceError):
    """采样时刻序列不是严格递增。"""

    error_code = "non_increasing_times"
    http_status = 422
