"""请求/内核入参校验。

校验顺序固定且短路返回，保证每类非法输入拿到唯一可区分的错误码：

1. 峰值窗口 W_max 必须是有限实数且 > 0（= 0 的退化情形同样拒绝）；
2. 立方系数 C 必须是有限实数且 > 0；
3. 时间 t 必须是有限实数且 >= 0；
4. 往返时延 RTT 必须是有限实数且 > 0；
5. 上一次峰值 W_last_max 若提供，必须是有限实数且 > 0；
6. 轨迹采样时刻必须是有限、非负、严格递增的序列。
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from ..errors import (
    InvalidCError,
    InvalidRttError,
    InvalidTimeError,
    InvalidWmaxError,
    NonFiniteNumberError,
    NonIncreasingTimesError,
)


def _finite(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise NonFiniteNumberError(
            f"{name} 必须是实数，收到 {value!r}", field=name
        )
    number = float(value)
    if not math.isfinite(number):
        raise NonFiniteNumberError(
            f"{name} 必须是有限实数，收到 {value!r}", field=name
        )
    return number


def validate_inputs(
    *,
    w_max: float,
    c: float,
    t: float | None = None,
    rtt: float,
    w_last_max: float | None = None,
) -> None:
    """校验单次求值所需的全部标量输入。"""
    w_max_f = _finite("w_max", w_max)
    if w_max_f <= 0.0:
        raise InvalidWmaxError(
            f"峰值窗口 w_max 必须大于 0，收到 {w_max!r}（w_max=0 的"
            "退化情形同样非法）",
            field="w_max",
        )

    c_f = _finite("c", c)
    if c_f <= 0.0:
        raise InvalidCError(
            f"立方系数 c 必须大于 0，收到 {c!r}", field="c"
        )

    if t is not None:
        t_f = _finite("t", t)
        if t_f < 0.0:
            raise InvalidTimeError(
                f"时间 t 不能取负值，收到 {t!r}", field="t"
            )

    rtt_f = _finite("rtt", rtt)
    if rtt_f <= 0.0:
        raise InvalidRttError(
            f"往返时延 rtt 必须大于 0，收到 {rtt!r}", field="rtt"
        )

    if w_last_max is not None:
        w_last_f = _finite("w_last_max", w_last_max)
        if w_last_f <= 0.0:
            raise InvalidWmaxError(
                "上一次峰值窗口 w_last_max 若提供必须大于 0，"
                f"收到 {w_last_max!r}",
                field="w_last_max",
            )


def validate_sample_times(times: Sequence[float]) -> None:
    """校验轨迹采样时刻：逐个有限非负，且严格递增。"""
    previous: float | None = None
    for index, raw in enumerate(times):
        t_f = _finite(f"times[{index}]", raw)
        if t_f < 0.0:
            raise InvalidTimeError(
                f"采样时刻 times[{index}] 不能取负值，收到 {raw!r}",
                field=f"times[{index}]",
            )
        if previous is not None and t_f <= previous:
            raise NonIncreasingTimesError(
                "采样时刻必须严格递增："
                f"times[{index - 1}]={previous} 后面出现 "
                f"times[{index}]={t_f}",
                field=f"times[{index}]",
            )
        previous = t_f
