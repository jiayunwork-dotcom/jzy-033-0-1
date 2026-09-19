"""单点求值与轨迹推进的编排层。

两个入口都只做「校验 -> 调 ``cubic`` 数学内核 -> 组装结果」，并且轨迹只是
对单点求值器的逐点复用，因此两个 HTTP 接口在同一时刻不可能算出两套结果。
本层返回纯领域 dataclass，不感知 HTTP。
"""

from __future__ import annotations

from dataclasses import dataclass

from . import cubic
from .errors import InvalidElapsedTime
from .validation import require_non_negative_finite, validate_common, validate_sample_times


@dataclass(frozen=True, slots=True)
class WindowSample:
    """单个时刻的完整核算结果。"""

    elapsed_time_s: float
    k_s: float
    peak_window_mss: float
    cubic_window_mss: float
    tcp_friendly_window_mss: float
    adopted_window_mss: float
    branch: str
    below_peak: bool
    at_peak: bool
    above_peak: bool
    fast_convergence: bool
    peak_trend: str

    def to_dict(self) -> dict[str, object]:
        return {
            "elapsed_time_s": self.elapsed_time_s,
            "k_s": self.k_s,
            "peak_window_mss": self.peak_window_mss,
            "cubic_window_mss": self.cubic_window_mss,
            "tcp_friendly_window_mss": self.tcp_friendly_window_mss,
            "adopted_window_mss": self.adopted_window_mss,
            "branch": self.branch,
            "position": {
                "below_peak": self.below_peak,
                "at_peak": self.at_peak,
                "above_peak": self.above_peak,
            },
            "fast_convergence": {
                "active": self.fast_convergence,
                "peak_trend": self.peak_trend,
            },
        }


@dataclass(frozen=True, slots=True)
class TrajectoryResult:
    peak_window_mss: float
    k_s: float
    beta: float
    cubic_coefficient: float
    rtt_s: float
    points: tuple[WindowSample, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "peak_window_mss": self.peak_window_mss,
            "k_s": self.k_s,
            "beta": self.beta,
            "cubic_coefficient": self.cubic_coefficient,
            "rtt_s": self.rtt_s,
            "points": [point.to_dict() for point in self.points],
        }


def evaluate_at(
    *,
    peak_window_mss: float,
    elapsed_time_s: float,
    rtt_s: float,
    cubic_coefficient: float = cubic.DEFAULT_CUBIC_COEFFICIENT,
    previous_peak_window_mss: float | None = None,
) -> WindowSample:
    """核算单个时刻的 CUBIC 窗口演进状态。"""

    params = validate_common(
        peak_window_mss, rtt_s, cubic_coefficient, previous_peak_window_mss
    )
    t = require_non_negative_finite(elapsed_time_s, InvalidElapsedTime)

    k = cubic.k_seconds(params)
    w_cubic = cubic.cubic_window(t, k, params.peak_window_mss, params.cubic_coefficient)
    w_tcp = cubic.tcp_friendly_window(t, params.peak_window_mss, params.rtt_s)
    branch = cubic.select_branch(w_cubic, w_tcp)
    adopted = w_tcp if branch == cubic.BRANCH_TCP_FRIENDLY else w_cubic

    fast_convergence, trend = cubic.fast_convergence_state(
        params.peak_window_mss, params.previous_peak_window_mss
    )

    # 位置判定与峰值点守卫共用同一个精确等式：立方支在 t==K 时精确等于峰值
    at_peak = t == k
    below_peak = w_cubic < params.peak_window_mss
    above_peak = w_cubic > params.peak_window_mss

    return WindowSample(
        elapsed_time_s=t,
        k_s=k,
        peak_window_mss=params.peak_window_mss,
        cubic_window_mss=w_cubic,
        tcp_friendly_window_mss=w_tcp,
        adopted_window_mss=adopted,
        branch=branch,
        below_peak=below_peak,
        at_peak=at_peak,
        above_peak=above_peak,
        fast_convergence=fast_convergence,
        peak_trend=trend,
    )


def evaluate_trajectory(
    *,
    peak_window_mss: float,
    rtt_s: float,
    sample_times_s: list[float],
    cubic_coefficient: float = cubic.DEFAULT_CUBIC_COEFFICIENT,
    previous_peak_window_mss: float | None = None,
) -> TrajectoryResult:
    """沿一串严格递增的采样时刻推进整条轨迹。

    参数先统一校验，随后逐点调用 :func:`evaluate_at` 本身——轨迹接口与
    单点接口共用同一个求值函数，不存在第二套算法。
    """

    params = validate_common(
        peak_window_mss, rtt_s, cubic_coefficient, previous_peak_window_mss
    )
    times = validate_sample_times(sample_times_s)

    points = tuple(
        evaluate_at(
            peak_window_mss=params.peak_window_mss,
            elapsed_time_s=t,
            rtt_s=params.rtt_s,
            cubic_coefficient=params.cubic_coefficient,
            previous_peak_window_mss=params.previous_peak_window_mss,
        )
        for t in times
    )
    return TrajectoryResult(
        peak_window_mss=params.peak_window_mss,
        k_s=points[0].k_s,
        beta=cubic.BETA,
        cubic_coefficient=params.cubic_coefficient,
        rtt_s=params.rtt_s,
        points=points,
    )
