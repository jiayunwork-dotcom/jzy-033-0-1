"""请求模型与开算前的参数校验。

非法输入一律在触碰任何窗口函数之前挡下，并抛出 ``errors`` 里带类型的
领域错误（由路由层统一渲染成结构化 JSON）。NaN / Inf 也按非法处理，
峰值窗口取零属于非法而不是退化出一个零窗口。
"""

from __future__ import annotations

import math
from pydantic import BaseModel, ConfigDict, Field

from . import cubic
from .errors import (
    InvalidCubicCoefficient,
    InvalidPeakWindow,
    InvalidPreviousPeak,
    InvalidRtt,
    InvalidSampleTimes,
)


def _is_finite_number(value: object) -> bool:
    return isinstance(value, bool) is False and isinstance(value, (int, float)) and math.isfinite(value)


def require_positive_finite(value: object, exc: type[Exception]) -> float:
    if not _is_finite_number(value) or value <= 0:
        raise exc
    return float(value)


def require_non_negative_finite(value: object, exc: type[Exception]) -> float:
    if not _is_finite_number(value) or value < 0:
        raise exc
    return float(value)


def validate_common(
    peak_window_mss: object,
    rtt_s: object,
    cubic_coefficient: object,
    previous_peak_window_mss: object = None,
) -> cubic.CubicParams:
    """校验四类基础量（顺序固定，便于错误类型稳定）。"""

    w_max = require_positive_finite(peak_window_mss, InvalidPeakWindow)
    c = require_positive_finite(cubic_coefficient, InvalidCubicCoefficient)
    rtt = require_positive_finite(rtt_s, InvalidRtt)
    prev = None
    if previous_peak_window_mss is not None:
        prev = require_positive_finite(previous_peak_window_mss, InvalidPreviousPeak)
    return cubic.CubicParams(
        peak_window_mss=w_max,
        rtt_s=rtt,
        cubic_coefficient=c,
        previous_peak_window_mss=prev,
    )


def validate_sample_times(sample_times_s: object) -> list[float]:
    """采样时刻必须是非空、有限、非负且严格递增的序列。"""

    if not isinstance(sample_times_s, list) or len(sample_times_s) == 0:
        raise InvalidSampleTimes()
    checked: list[float] = []
    for sample in sample_times_s:
        checked.append(require_non_negative_finite(sample, InvalidSampleTimes))
    for earlier, later in zip(checked, checked[1:]):
        if later <= earlier:
            raise InvalidSampleTimes(
                f"sample_times_s must be strictly increasing; got {later!r} not greater than {earlier!r}"
            )
    return checked


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvaluateRequest(_StrictModel):
    """/evaluate 单点求值请求。"""

    peak_window_mss: float = Field(..., description="丢包前峰值窗口 W_max（MSS 段数），必须 > 0")
    elapsed_time_s: float = Field(..., description="距最近一次丢包的时间 t（秒），必须 >= 0")
    rtt_s: float = Field(..., description="往返时延（秒），必须 > 0")
    cubic_coefficient: float = Field(
        default=cubic.DEFAULT_CUBIC_COEFFICIENT, description="立方系数 C，必须 > 0"
    )
    previous_peak_window_mss: float | None = Field(
        default=None, description="上一次记录的峰值窗口（MSS 段数），用于快速收敛判定"
    )


class TrajectoryRequest(_StrictModel):
    """/trajectory 轨迹请求。"""

    peak_window_mss: float
    rtt_s: float
    sample_times_s: list[float] = Field(..., description="严格递增的采样时刻序列（秒）")
    cubic_coefficient: float = cubic.DEFAULT_CUBIC_COEFFICIENT
    previous_peak_window_mss: float | None = None
