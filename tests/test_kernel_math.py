"""数学内核行为不变量测试。

覆盖：
* t=K 处立方窗口精确等于峰值、t=0 精确落在 beta*W_max；
* 增大峰值 → K 变长，越过峰值（重新超越峰值）的时刻随之推后；
* 立方系数加倍 → K 缩短为 2^(-1/3)；
* t 取在 K 正上方严格大于峰值、取在下方严格小于峰值；
* 快速收敛判定随本次峰值相对上次峰值的升降正确开合。
"""

from __future__ import annotations

import math

import pytest

from app.config import BETA, DEFAULT_C
from app.window import cbrt, evaluate, is_fast_convergence, kappa
from app.window.validation import (
    InvalidCError,
    InvalidRttError,
    InvalidTimeError,
    InvalidWmaxError,
)


def test_cbrt_basic() -> None:
    assert cbrt(0.0) == 0.0
    assert cbrt(1.0) == pytest.approx(1.0)
    assert cbrt(27.0) == pytest.approx(3.0)
    assert cbrt(123456.789**3) == pytest.approx(123456.789, rel=1e-12)


def test_kappa_returns_time_in_seconds() -> None:
    k = kappa(100.0, DEFAULT_C)
    # 由 K 定义直接反推：C*K^3 == (1-beta)*W_max
    assert DEFAULT_C * k**3 == pytest.approx((1.0 - BETA) * 100.0, rel=1e-12)


def test_at_peak_time_cubic_window_is_exactly_wmax() -> None:
    """核心自洽性：t == K 时立方窗口必须精确（bit 级）等于峰值。

    高 BDP（rtt=1s）下立方分支主导，最终采用值同样精确等于峰值；
    低 BDP 下 TCP 友好线性值可以更大，该分支在另一用例单独验证。
    """
    # 每个峰值取足够大的 RTT，保证峰值点处于 CUBIC 主导区：
    # 需要 w_tcp(K) <= w_max，即 RTT >= alpha*K/(0.3*W)
    alpha = (3 * BETA) / (2 - BETA)
    for w_max in (1.0, 7.0, 100.0, 4096.0, 65535.5):
        k = kappa(w_max, DEFAULT_C)
        rtt = 10.0 * alpha * k / (0.3 * w_max)
        result = evaluate(k, w_max, rtt=rtt)
        assert result["w_cubic"] == w_max  # 精确相等，不使用 approx
        assert result["w"] == w_max
        assert result["branch"] == "cubic"
        assert result["at_peak"] is True

    # 即便低 BDP 导致线性分支接管，立方分支自身在 t=K 仍精确等于峰值
    low_bdp = evaluate(kappa(10.0), 10.0, rtt=0.01)
    assert low_bdp["w_cubic"] == 10.0
    assert low_bdp["w_tcp"] > 10.0
    assert low_bdp["branch"] == "tcp_friendly"
    assert low_bdp["w"] == low_bdp["w_tcp"]


def test_at_loss_origin_window_is_exactly_reduced_window() -> None:
    """t=0 时立方窗口精确等于 beta*W_max。"""
    result = evaluate(0.0, 100.0, rtt=1.0)
    assert result["w_cubic"] == BETA * 100.0
    assert result["w"] == BETA * 100.0
    assert result["at_peak"] is False


def test_larger_wmax_makes_kappa_longer_and_crossover_later() -> None:
    """增大峰值：K 单调变长；重新超越峰值的时刻就是 K，故一并推后。

    「越过峰值后重新超越峰值的时刻」对 CUBIC 而言即 t=K：
    t>K 时窗口才严格大于 W_max。
    """
    k_small = kappa(100.0)
    k_large = kappa(200.0)
    k_xlarge = kappa(400.0)
    assert k_small < k_large < k_xlarge

    # 越过峰值的时刻推后：在小峰值的 K 时刻，大峰值仍在峰值下方
    t = k_small
    assert evaluate(t, 100.0, rtt=1.0)["w_cubic"] == pytest.approx(100.0)
    assert evaluate(t, 200.0, rtt=1.0)["w_cubic"] < 200.0


def test_doubling_c_shortens_kappa() -> None:
    """立方系数加倍，K 缩短为原来的 2^(-1/3)。"""
    k = kappa(100.0, c=0.4)
    k_double = kappa(100.0, c=0.8)
    assert k_double < k
    assert k_double / k == pytest.approx(2.0 ** (-1.0 / 3.0), rel=1e-12)


@pytest.mark.parametrize("w_max", [10.0, 100.0, 1000.0])
def test_window_strictly_below_and_above_peak(w_max: float) -> None:
    """t 取在 K 正上方严格大于峰值；正下方严格小于峰值。

    采样点取 K 的 ±1%，远离峰值锚定容差带（1e-12 相对量级）。
    """
    k = kappa(w_max)
    below = evaluate(0.99 * k, w_max, rtt=1.0)
    above = evaluate(1.01 * k, w_max, rtt=1.0)

    assert below["w_cubic"] < w_max
    assert below["at_peak"] is False
    assert above["w_cubic"] > w_max
    assert above["at_peak"] is False

    # 对照立方公式直接验证方向与幅度
    delta = 0.01 * k
    assert below["w_cubic"] == pytest.approx(
        w_max - DEFAULT_C * delta**3, rel=1e-9
    )
    assert above["w_cubic"] == pytest.approx(
        w_max + DEFAULT_C * delta**3, rel=1e-9
    )


def test_cubic_curve_monotone_growth_until_and_after_peak() -> None:
    """整条曲线除峰值顶点外严格增长（顶点斜率为零）。"""
    w_max = 100.0
    k = kappa(w_max)
    times = [0.0, 0.25 * k, 0.5 * k, 0.75 * k, k, 1.25 * k, 1.5 * k, 2 * k]
    windows = [evaluate(t, w_max, rtt=1.0)["w_cubic"] for t in times]
    for earlier, later in zip(windows, windows[1:]):
        assert later > earlier


def test_fast_convergence_opens_and_closes_with_peak_trend() -> None:
    """快速收敛不能永远返回同一个状态：随峰值升降开合。"""
    # 首次丢包（无上次峰值）→ 关
    assert is_fast_convergence(100.0, None) is False
    # 峰值下降（本次 100 < 上次 140）→ 开
    assert is_fast_convergence(100.0, 140.0) is True
    # 峰值持平 → 关
    assert is_fast_convergence(100.0, 100.0) is False
    # 峰值上升 → 关
    assert is_fast_convergence(140.0, 100.0) is False
    # 再次下降 → 重新打开
    assert is_fast_convergence(120.0, 140.0) is True


def test_fast_convergence_reflected_in_evaluate() -> None:
    down = evaluate(1.0, 100.0, rtt=1.0, w_last_max=140.0)
    up = evaluate(1.0, 100.0, rtt=1.0, w_last_max=80.0)
    none = evaluate(1.0, 100.0, rtt=1.0)
    assert down["w_cubic"] == up["w_cubic"] == none["w_cubic"]  # 曲线不受影响


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"t": 0.0, "w_max": 0.0, "rtt": 1.0}, InvalidWmaxError),
        ({"t": 0.0, "w_max": -1.0, "rtt": 1.0}, InvalidWmaxError),
        ({"t": 0.0, "w_max": 10.0, "rtt": 1.0, "c": 0.0}, InvalidCError),
        ({"t": 0.0, "w_max": 10.0, "rtt": 1.0, "c": -2.0}, InvalidCError),
        ({"t": -0.001, "w_max": 10.0, "rtt": 1.0}, InvalidTimeError),
        ({"t": 0.0, "w_max": 10.0, "rtt": 0.0}, InvalidRttError),
        ({"t": 0.0, "w_max": 10.0, "rtt": -1.0}, InvalidRttError),
    ],
)
def test_kernel_rejects_invalid_inputs(kwargs, expected) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(expected):
        evaluate(**kwargs)


def test_kernel_invalid_inputs_are_distinct_types() -> None:
    """四类非法输入必须是可区分的不同错误类型。"""
    assert len({InvalidWmaxError, InvalidCError, InvalidTimeError, InvalidRttError}) == 4


def test_math_constants() -> None:
    assert BETA == 0.7
    assert math.isclose((3 * BETA) / (2 - BETA), 21.0 / 13.0)
