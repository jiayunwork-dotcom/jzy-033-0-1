"""轨迹推进：给定一串严格递增的采样时刻，推出整条窗口演进轨迹。

逐点调用 kernel.evaluate，与单点求值接口共用同一套窗口函数，
因此同一时刻在两个接口上的结果必然一致。
"""

from __future__ import annotations

from typing import Any

from .kernel import evaluate, is_fast_convergence, kappa
from .validation import validate_inputs, validate_sample_times


def run_trajectory(
    times: list[float],
    w_max: float,
    rtt: float,
    *,
    c: float = 0.4,
    w_last_max: float | None = None,
) -> dict[str, Any]:
    """计算整条轨迹。

    标量输入先做一遍与单点接口完全相同的校验，再校验采样序列，
    然后对每个采样时刻调用同一份 evaluate。
    """
    validate_inputs(w_max=w_max, c=c, rtt=rtt, w_last_max=w_last_max)
    validate_sample_times(times)

    k = kappa(float(w_max), float(c))
    samples = [
        evaluate(t, w_max, rtt, c=c, w_last_max=w_last_max) for t in times
    ]

    return {
        "w_max": float(w_max),
        "c": float(c),
        "rtt": float(rtt),
        "w_last_max": (None if w_last_max is None else float(w_last_max)),
        "k": k,
        "fast_convergence": is_fast_convergence(
            float(w_max),
            None if w_last_max is None else float(w_last_max),
        ),
        "samples": samples,
    }
