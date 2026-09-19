"""CUBIC 窗口演进数学内核。

纯函数、无状态、不依赖任何 Web 框架；单点求值与轨迹推进都只调用
这里的函数，保证两个接口永远共用同一套算法。

三条基本关系（见 config.py 顶部说明）：

    W_cubic(t) = C * (t - K) ** 3 + W_max
    K          = cbrt(W_max * (1 - beta) / C)
    W_tcp(t)   = beta * W_max
                 + [3*beta/(2-beta)] * (t / RTT)

本模块对两个自洽性关键点做了锚定：

* t == 0 ：立方窗口精确等于 beta * W_max（丢包后的起点）；
* t == K ：立方窗口精确等于 W_max，且曲线在该点斜率为零。

锚定通过一个极小（相对量级 1e-12）的时间容差带实现，带内直接给出
精确值，既挡住浮点开三次方带来的尾数偏差，也不影响带外立方曲线的
严格单调性（t < K 严格小于峰值、t > K 严格大于峰值）。
"""

from __future__ import annotations

import math
from typing import TypedDict

from ..config import (
    BETA,
    BRANCH_CUBIC,
    BRANCH_TCP_FRIENDLY,
    DEFAULT_C,
    PEAK_EPS_REL,
    TCP_FRIENDLY_SLOPE,
)
from .validation import validate_inputs


class WindowResult(TypedDict):
    """单个时刻的求值结果（窗口单位均为 MSS 段数）。"""

    t: float
    w_cubic: float
    w_tcp: float
    w: float
    branch: str
    tcp_friendly: bool
    at_peak: bool
    w_reduced: float


def cbrt(x: float) -> float:
    """对非负实数求三次方根。

    先用幂运算取初值，再做两次牛顿迭代把舍入误差压到尾数级别，
    保证 K 被反复平方/立方时尽量精确。
    """
    if x < 0.0:
        raise ValueError("cbrt 仅支持非负输入")
    if x == 0.0:
        return 0.0
    root = float(x) ** (1.0 / 3.0)
    for _ in range(2):
        # 牛顿迭代：r <- (2r + x/r^2) / 3
        root = (2.0 * root + x / (root * root)) / 3.0
    return root


def kappa(w_max: float, c: float = DEFAULT_C) -> float:
    """回到峰值所需时间 K = cbrt(W_max * (1 - beta) / C)。

    W_max 越大 K 越长（单调递增）；C 加倍则 K 缩短为原来的
    2 ** (-1/3) 倍。
    """
    return cbrt(w_max * (1.0 - BETA) / c)


def reduced_window(w_max: float) -> float:
    """丢包瞬间的乘性缩减窗口 beta * W_max。"""
    return BETA * w_max


def cubic_window(t: float, w_max: float, k: float, c: float) -> float:
    """立方分支窗口 C*(t-K)^3 + W_max，带峰值点自洽锚定。"""
    dt = t - k
    tol = PEAK_EPS_REL * max(1.0, abs(t), abs(k))
    if abs(dt) <= tol:
        # t == K：曲线斜率为零的顶点，必须精确等于峰值。
        return w_max
    if t <= tol:
        # t == 0：精确锚定在 beta * W_max，避免 K 的尾数误差
        # 经 K**3 放大。
        return reduced_window(w_max)
    return c * dt * dt * dt + w_max


def tcp_window(t: float, w_max: float, rtt: float) -> float:
    """TCP 友好线性对照窗口（Reno 风格，自 beta*W_max 起线性增长）。"""
    return reduced_window(w_max) + TCP_FRIENDLY_SLOPE * (t / rtt)


def is_fast_convergence(w_max: float, w_last_max: float | None) -> bool:
    """快速收敛阶段开合判定（RFC 8312 第 4.6 节）。

    本次峰值相对上一次记录的峰值下降（当前 W_max < 上一次
    W_last_max）时判定仍处于快速收敛阶段；峰值持平或上升则退出。
    首个丢包事件（没有上一次峰值记录）也不属于快速收敛。
    """
    if w_last_max is None:
        return False
    return w_max < w_last_max


def evaluate(
    t: float,
    w_max: float,
    rtt: float,
    *,
    c: float = DEFAULT_C,
    w_last_max: float | None = None,
) -> WindowResult:
    """给定当前时刻 t，求出完整的窗口判定结果。

    参数
    ----
    t:
        距最近一次丢包时刻的时间（秒），不得为负。
    w_max:
        丢包前的峰值窗口（MSS 段数），必须大于 0。
    rtt:
        稳态往返时延（秒），必须大于 0。
    c:
        立方系数，必须大于 0，默认 0.4。
    w_last_max:
        上一次记录的峰值窗口，用于快速收敛判定；不传表示首个
        丢包事件。

    返回
    ----
    WindowResult，含立方值、线性对照值、最终采用值、分支标记、
    是否正好处于峰值点以及缩减窗口。
    """
    w_max = float(w_max)
    rtt = float(rtt)
    c = float(c)
    t = float(t)

    # 入参合法性在开算前挡下（路由层也会先校验一遍，内核被直接
    # 调用时同样安全）。
    validate_inputs(w_max=w_max, c=c, t=t, rtt=rtt, w_last_max=w_last_max)

    k = kappa(w_max, c)
    w_cubic = cubic_window(t, w_max, k, c)
    w_tcp = tcp_window(t, w_max, rtt)
    w_reduced = reduced_window(w_max)

    # 标准判据：低 BDP 下线性值超过立方值时退让给 TCP 友好分支。
    # 相等时归 CUBIC；而 t == K 时立方值被锚定为精确 W_max，
    # 该点采用立方分支则最终窗口精确等于峰值。
    tcp_friendly = w_tcp > w_cubic
    if tcp_friendly:
        w = w_tcp
        branch = BRANCH_TCP_FRIENDLY
    else:
        w = w_cubic
        branch = BRANCH_CUBIC

    tol = PEAK_EPS_REL * max(1.0, abs(t), abs(k))
    at_peak = abs(t - k) <= tol

    return WindowResult(
        t=t,
        w_cubic=w_cubic,
        w_tcp=w_tcp,
        w=w,
        branch=branch,
        tcp_friendly=tcp_friendly,
        at_peak=at_peak,
        w_reduced=w_reduced,
    )
