"""数学内核层面的行为不变量测试。

覆盖：峰值点精确等于峰值、峰值增大 K 变长、立方系数加倍 K 变短、
越过/未越过峰值的严格大小关系、TCP 友好分支在低 BDP 下被选中、
快速收敛随峰值升降开合、以及预置整数算例的核对。
"""

from __future__ import annotations

import math

import pytest

from app import cubic, presets, service
from app.errors import (
    InvalidCubicCoefficient,
    InvalidElapsedTime,
    InvalidPeakWindow,
    InvalidRtt,
)

CANON = dict(peak_window_mss=80.0, rtt_s=0.5, cubic_coefficient=0.375)


class TestKAndPeakPoint:
    def test_peak_point_exactly_equals_peak_kernel(self) -> None:
        # 多组参数下，t == K 时立方窗口必须精确（而不是近似）等于 W_max
        for w_max, coeff in [(80.0, 0.375), (100.0, 0.4), (123.456, 0.7), (1.0, 0.01)]:
            params = cubic.CubicParams(peak_window_mss=w_max, rtt_s=0.1, cubic_coefficient=coeff)
            k = cubic.k_seconds(params)
            assert cubic.cubic_window(k, k, w_max, coeff) == w_max

    def test_peak_point_exactly_equals_peak_via_service(self) -> None:
        sample = service.evaluate_at(elapsed_time_s=4.0, **CANON)
        assert sample.k_s == 4.0
        assert sample.cubic_window_mss == 80.0
        assert sample.adopted_window_mss == 80.0
        assert sample.at_peak is True
        assert sample.below_peak is False and sample.above_peak is False

    def test_slope_is_zero_at_k(self) -> None:
        # 数值验证 K 点斜率为零：K 两侧对称点的窗口关于峰值对称
        params = cubic.CubicParams(peak_window_mss=80.0, rtt_s=0.5, cubic_coefficient=0.375)
        k = cubic.k_seconds(params)
        eps = 1e-3
        lo = cubic.cubic_window(k - eps, k, 80.0, 0.375)
        hi = cubic.cubic_window(k + eps, k, 80.0, 0.375)
        assert lo == pytest.approx(hi)
        assert lo < 80.0 < hi

    def test_larger_peak_makes_k_longer(self) -> None:
        k1 = cubic.k_seconds(cubic.CubicParams(peak_window_mss=100.0, rtt_s=0.1))
        k2 = cubic.k_seconds(cubic.CubicParams(peak_window_mss=200.0, rtt_s=0.1))
        assert k2 > k1
        # 解析式核对：峰值翻倍，K 变为 2^(1/3) 倍
        assert k2 == pytest.approx(k1 * 2.0 ** (1.0 / 3.0))

    def test_recovery_later_when_peak_grows(self) -> None:
        # 「越过峰值后重新超越峰值的时刻」也随峰值推后：
        # 新 K 之后第一个达到旧峰值 100 的时刻，在 W_max=200 的曲线里更晚。
        def first_above(w_max: float, target: float) -> float:
            params = cubic.CubicParams(peak_window_mss=w_max, rtt_s=0.1, cubic_coefficient=0.4)
            k = cubic.k_seconds(params)
            t = k
            while True:
                t += 1e-4
                if cubic.cubic_window(t, k, w_max, 0.4) >= target:
                    return t

        t_small = first_above(100.0, 100.0 + 1e-9)
        t_big = first_above(200.0, 100.0 + 1e-9)
        assert t_big > t_small

    def test_doubling_coefficient_makes_k_shorter(self) -> None:
        base = cubic.CubicParams(peak_window_mss=100.0, rtt_s=0.1, cubic_coefficient=0.4)
        doubled = cubic.CubicParams(peak_window_mss=100.0, rtt_s=0.1, cubic_coefficient=0.8)
        k1, k2 = cubic.k_seconds(base), cubic.k_seconds(doubled)
        assert k2 < k1
        assert k2 == pytest.approx(k1 / 2.0 ** (1.0 / 3.0))

    @pytest.mark.parametrize("dt", [1e-4, 0.5, 1.0])
    def test_strict_below_and_above_peak(self, dt: float) -> None:
        # 注：dt 最小取 1e-4。W_max=80 附近 float64 的 ULP 约 1.4e-14 MSS，
        # 比它更小的立方差（如 dt=1e-9 时差约 4e-28 MSS）在浮点上不可表示，
        # 数学上的严格不等在可分辨尺度上检验。
        params = cubic.CubicParams(peak_window_mss=80.0, rtt_s=0.5, cubic_coefficient=0.375)
        k = cubic.k_seconds(params)
        w_before = cubic.cubic_window(k - dt, k, 80.0, 0.375)
        w_after = cubic.cubic_window(k + dt, k, 80.0, 0.375)
        assert w_before < 80.0
        assert w_after > 80.0

    def test_k_formula_matches_definition(self) -> None:
        params = cubic.CubicParams(peak_window_mss=80.0, rtt_s=0.5, cubic_coefficient=0.375)
        k = cubic.k_seconds(params)
        # C*K^3 必须恰好等于缩减量 (1-beta)*W_max
        assert 0.375 * k**3 == pytest.approx((1 - cubic.BETA) * 80.0)

    def test_origin_is_multiplicative_reduction(self) -> None:
        sample = service.evaluate_at(elapsed_time_s=0.0, **CANON)
        assert sample.cubic_window_mss == 80.0 * cubic.BETA == 56.0


class TestBranchSelection:
    def test_tcp_friendly_selected_in_low_bdp(self) -> None:
        # 小峰值 + 短 RTT：线性对照支每秒涨 ~161.5 MSS，立方支退让
        sample = service.evaluate_at(peak_window_mss=10.0, elapsed_time_s=0.5, rtt_s=0.01)
        assert sample.branch == cubic.BRANCH_TCP_FRIENDLY
        assert sample.adopted_window_mss == sample.tcp_friendly_window_mss
        assert sample.adopted_window_mss > sample.cubic_window_mss

    def test_cubic_selected_in_high_bdp(self) -> None:
        sample = service.evaluate_at(
            peak_window_mss=10000.0, elapsed_time_s=30.0, rtt_s=0.2, cubic_coefficient=0.4
        )
        assert sample.branch == cubic.BRANCH_CUBIC
        assert sample.adopted_window_mss == sample.cubic_window_mss

    def test_tie_goes_to_cubic(self) -> None:
        # 选支判据：相等时不落入 tcp_friendly
        assert cubic.select_branch(70.0, 70.0) == cubic.BRANCH_CUBIC
        assert cubic.select_branch(69.999999, 70.0) == cubic.BRANCH_TCP_FRIENDLY
        # 整数算例 t=0 时两支起点同为 beta*W_max=56，平局取立方支
        sample = service.evaluate_at(elapsed_time_s=0.0, **CANON)
        assert sample.tcp_friendly_window_mss == sample.cubic_window_mss == 56.0
        assert sample.branch == cubic.BRANCH_CUBIC


class TestFastConvergence:
    def test_active_when_peak_falls(self) -> None:
        sample = service.evaluate_at(
            peak_window_mss=80.0, elapsed_time_s=4.0, rtt_s=0.5,
            cubic_coefficient=0.375, previous_peak_window_mss=100.0,
        )
        assert sample.fast_convergence is True
        assert sample.peak_trend == cubic.TREND_FALLING

    def test_inactive_when_peak_rises(self) -> None:
        sample = service.evaluate_at(
            peak_window_mss=80.0, elapsed_time_s=4.0, rtt_s=0.5,
            cubic_coefficient=0.375, previous_peak_window_mss=60.0,
        )
        assert sample.fast_convergence is False
        assert sample.peak_trend == cubic.TREND_RISING

    def test_inactive_when_equal_peak(self) -> None:
        sample = service.evaluate_at(
            peak_window_mss=80.0, elapsed_time_s=4.0, rtt_s=0.5,
            cubic_coefficient=0.375, previous_peak_window_mss=80.0,
        )
        assert sample.fast_convergence is False
        assert sample.peak_trend == cubic.TREND_RISING

    def test_unknown_without_history(self) -> None:
        sample = service.evaluate_at(elapsed_time_s=1.0, **CANON)
        assert sample.fast_convergence is False
        assert sample.peak_trend == cubic.TREND_UNKNOWN


class TestInvalidInputs:
    @pytest.mark.parametrize(
        "kwargs,exc",
        [
            (dict(peak_window_mss=0.0, elapsed_time_s=1.0, rtt_s=0.1), InvalidPeakWindow),
            (dict(peak_window_mss=-5.0, elapsed_time_s=1.0, rtt_s=0.1), InvalidPeakWindow),
            (dict(peak_window_mss=100.0, elapsed_time_s=1.0, rtt_s=0.1,
                  cubic_coefficient=0.0), InvalidCubicCoefficient),
            (dict(peak_window_mss=100.0, elapsed_time_s=1.0, rtt_s=0.1,
                  cubic_coefficient=-0.4), InvalidCubicCoefficient),
            (dict(peak_window_mss=100.0, elapsed_time_s=-0.1, rtt_s=0.1), InvalidElapsedTime),
            (dict(peak_window_mss=100.0, elapsed_time_s=1.0, rtt_s=0.0), InvalidRtt),
            (dict(peak_window_mss=100.0, elapsed_time_s=1.0, rtt_s=-1.0), InvalidRtt),
        ],
    )
    def test_four_invalid_categories_raised(self, kwargs, exc) -> None:
        with pytest.raises(exc):
            service.evaluate_at(**kwargs)

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
    def test_non_finite_values_rejected(self, bad: float) -> None:
        with pytest.raises(InvalidPeakWindow):
            service.evaluate_at(peak_window_mss=bad, elapsed_time_s=1.0, rtt_s=0.1)

    def test_error_types_are_distinguishable(self) -> None:
        types_seen = set()
        for kwargs, exc in [
            (dict(peak_window_mss=0.0, elapsed_time_s=1.0, rtt_s=0.1), InvalidPeakWindow),
            (dict(peak_window_mss=1.0, elapsed_time_s=1.0, rtt_s=0.1,
                  cubic_coefficient=0.0), InvalidCubicCoefficient),
            (dict(peak_window_mss=1.0, elapsed_time_s=-1.0, rtt_s=0.1), InvalidElapsedTime),
            (dict(peak_window_mss=1.0, elapsed_time_s=1.0, rtt_s=0.0), InvalidRtt),
        ]:
            with pytest.raises(Exception) as caught:
                service.evaluate_at(**kwargs)
            assert isinstance(caught.value, exc)
            types_seen.add(caught.value.error_type)
        assert types_seen == {
            "invalid_peak_window",
            "invalid_cubic_coefficient",
            "invalid_elapsed_time",
            "invalid_rtt",
        }


class TestCanonicalPreset:
    def test_checkpoint_direction_and_peak(self) -> None:
        rendered = presets.get_preset("canonical_recovery_demo")
        assert rendered is not None and rendered["k_s"] == 4.0
        by_t = {c["elapsed_time_s"]: c for c in rendered["checkpoints"]}
        assert by_t[0.0]["cubic_window_mss"] == 56.0
        assert by_t[2.0]["cubic_window_mss"] == 77.0
        assert by_t[4.0]["cubic_window_mss"] == 80.0
        assert by_t[4.0]["position"]["at_peak"] is True
        assert by_t[6.0]["cubic_window_mss"] == 83.0
        assert by_t[8.0]["cubic_window_mss"] == 104.0
        # 方向单调向上
        values = [c["cubic_window_mss"] for c in rendered["checkpoints"]]
        assert values == sorted(values)

    def test_canonical_fast_convergence_open(self) -> None:
        rendered = presets.get_preset("canonical_recovery_demo")
        cp = rendered["checkpoints"][0]
        assert cp["fast_convergence"]["active"] is True
        assert cp["fast_convergence"]["peak_trend"] == "falling"

    def test_k_is_finite_for_all_presets(self) -> None:
        for rendered in presets.list_presets():
            assert math.isfinite(rendered["k_s"]) and rendered["k_s"] > 0
