"""带类型的结构化领域错误。

所有非法输入都在开算前转换为 :class:`CubicServiceError` 的子类，
由 FastAPI 异常处理器统一渲染成 HTTP 400 JSON，绝不抛出未捕获异常，
也不返回空值。``error_type`` 对上游是稳定可区分的机器可读码。
"""

from __future__ import annotations


class CubicServiceError(ValueError):
    """本服务所有可预期错误的基类。"""

    error_type: str = "invalid_request"

    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.field = field

    def to_dict(self) -> dict[str, object]:
        body: dict[str, object] = {"error_type": self.error_type, "message": self.message}
        if self.field is not None:
            body["field"] = self.field
        return body


class InvalidPeakWindow(CubicServiceError):
    """峰值窗口（MSS 段数）非法，例如 <= 0、NaN/Inf；零窗口也在此挡下。"""

    error_type = "invalid_peak_window"

    def __init__(self, message: str = "peak_window_mss must be a finite number strictly greater than 0") -> None:
        super().__init__(message, field="peak_window_mss")


class InvalidCubicCoefficient(CubicServiceError):
    """立方系数 C 非法（<= 0 或 NaN/Inf）。"""

    error_type = "invalid_cubic_coefficient"

    def __init__(self, message: str = "cubic_coefficient must be a finite number strictly greater than 0") -> None:
        super().__init__(message, field="cubic_coefficient")


class InvalidElapsedTime(CubicServiceError):
    """求值时刻 t 非法（负数或 NaN/Inf）。"""

    error_type = "invalid_elapsed_time"

    def __init__(self, message: str = "elapsed_time_s must be finite and greater than or equal to 0") -> None:
        super().__init__(message, field="elapsed_time_s")


class InvalidRtt(CubicServiceError):
    """往返时延非法（<= 0 或 NaN/Inf）。"""

    error_type = "invalid_rtt"

    def __init__(self, message: str = "rtt_s must be a finite number strictly greater than 0") -> None:
        super().__init__(message, field="rtt_s")


class InvalidPreviousPeak(CubicServiceError):
    """上一次记录的峰值窗口非法（给了但 <= 0 或 NaN/Inf）。"""

    error_type = "invalid_previous_peak"

    def __init__(
        self, message: str = "previous_peak_window_mss must be a finite number strictly greater than 0 when provided"
    ) -> None:
        super().__init__(message, field="previous_peak_window_mss")


class InvalidSampleTimes(CubicServiceError):
    """轨迹采样时刻序列非法（为空或非严格递增）。"""

    error_type = "invalid_sample_times"

    def __init__(self, message: str = "sample_times_s must be a non-empty list of strictly increasing finite values") -> None:
        super().__init__(message, field="sample_times_s")
