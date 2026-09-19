"""CUBIC 拥塞窗口演进的数学内核。

本模块只做纯计算，不依赖 HTTP / Pydantic，单点求值与轨迹推进共用这里的
唯一一套函数。时间原点 ``t = 0`` 为最近一次丢包时刻，窗口单位为 MSS 段数。

三条必须同时成立的关系（RFC 8312 / Ha 等人的 CUBIC 模型）::

    W_cubic(t) = C * (t - K)^3 + W_max          # 立方曲线
    dW/dt(t=K) = 3*C*(t-K)^2 = 0                 # 回到峰值处斜率为零
    C * K^3    = (1 - beta) * W_max              # t=0 起点即乘性缩减后的窗口

因此::

    K = cbrt( (1-beta) * W_max / C )

其中乘性缩减因子固定 ``beta = 0.7``（丢包后窗口从 ``W_max`` 降到
``beta * W_max``），``C`` 为立方系数。``t < K`` 时立方窗口严格低于峰值、
缓慢逼近；``t = K`` 时精确等于峰值；``t > K`` 时严格高于峰值并加速增长。

TCP 友好对照窗口取线性增长::

    W_tcp(t) = beta*W_max + [3*beta/(2-beta)] * (t/RTT)

选支判据（标准判据）：``W_cubic(t) < W_tcp(t)`` 时退让到 TCP 友好区、
采用线性对照值；否则采用立方值。等价于取两者较大者。短 RTT / 小峰值
（低带宽时延积）路径上线性支每物理秒增长更快，正是在这类场景下被选中。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

#: 乘性缩减因子（固定，不对外暴露为入参）
BETA: float = 0.7

#: 立方系数缺省值（RFC 8312 取 0.4）
DEFAULT_CUBIC_COEFFICIENT: float = 0.4

#: TCP 友好支每个 RTT 的线性增量 3*beta/(2-beta)，beta=0.7 时约 1.615 MSS/RTT
TCP_FRIENDLY_SLOPE_PER_RTT: float = 3.0 * BETA / (2.0 - BETA)

BRANCH_CUBIC = "cubic"
BRANCH_TCP_FRIENDLY = "tcp_friendly"

TREND_FALLING = "falling"
TREND_RISING = "rising"
TREND_UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class CubicParams:
    """一次丢包事件之后、决定整条演进曲线的固定参数。

    峰值窗口以 MSS 段数计；``previous_peak_window_mss`` 为可选的上一次
    记录峰值，仅用于快速收敛判定，不参与窗口曲线计算。
    """

    peak_window_mss: float
    rtt_s: float
    cubic_coefficient: float = DEFAULT_CUBIC_COEFFICIENT
    previous_peak_window_mss: float | None = None

    @property
    def beta(self) -> float:
        return BETA


def k_seconds(params: CubicParams) -> float:
    """回到峰值所需时间 ``K = cbrt((1-beta)*W_max/C)``（秒）。

    关于 ``W_max`` 与 ``C`` 严格单调：峰值增大则 K 变长；立方系数加倍
    则 K 缩短为原来的 ``cbrt(1/2)``。
    """

    return math.cbrt((1.0 - BETA) * params.peak_window_mss / params.cubic_coefficient)


def cubic_window(elapsed_time_s: float, k_s: float, peak_window_mss: float, cubic_coefficient: float) -> float:
    """立方支窗口 ``C*(t-K)^3 + W_max``。

    峰值点守卫：``t == K`` 时直接返回 ``W_max``，不经过任何浮点减法/乘方，
    从代码路径上保证「恰好回到峰值时刻窗口精确等于峰值」，不依赖 libm
    在 ``0.0**3`` 上的具体舍入行为。``t`` 略低于/高于 K 时仍严格走立方式，
    保持严格小于/大于峰值的关系。
    """

    if elapsed_time_s == k_s:
        return float(peak_window_mss)
    return cubic_coefficient * (elapsed_time_s - k_s) ** 3 + peak_window_mss


def tcp_friendly_window(elapsed_time_s: float, peak_window_mss: float, rtt_s: float) -> float:
    """TCP 友好线性对照窗口 ``beta*W_max + (3beta/(2-beta)) * t/RTT``。"""

    return BETA * peak_window_mss + TCP_FRIENDLY_SLOPE_PER_RTT * (elapsed_time_s / rtt_s)


def select_branch(w_cubic_mss: float, w_tcp_mss: float) -> str:
    """标准选支判据：立方值低于 TCP 对照值时退让到 TCP 友好区，平局取立方。"""

    if w_cubic_mss < w_tcp_mss:
        return BRANCH_TCP_FRIENDLY
    return BRANCH_CUBIC


def fast_convergence_state(
    peak_window_mss: float, previous_peak_window_mss: float | None
) -> tuple[bool, str]:
    """快速收敛阶段判定。

    标准 CUBIC 规则：本次丢包峰值低于上一次记录峰值时，下一轮把收敛目标
    进一步折减为 ``W_max*(1+beta)/2``，即进入快速收敛；峰值持平或上升时
    不进入。未提供历史峰值时无法比较，返回非快速收敛 + ``unknown`` 趋势，
    判定结果会随峰值的升降真实开合，不会恒定。

    返回 ``(是否快速收敛, 峰值趋势)``。
    """

    if previous_peak_window_mss is None:
        return False, TREND_UNKNOWN
    if peak_window_mss < previous_peak_window_mss:
        return True, TREND_FALLING
    return False, TREND_RISING
