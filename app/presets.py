"""内置标准情形。

预置一个「丢包后窗口先低于峰值、沿立方曲线爬回、再越过峰值」的
可核对算例，由数学内核实时求值，/api/v3/standards 原样回显。
"""

from __future__ import annotations

from typing import Any

from .config import (
    BETA,
    DEFAULT_C,
    FAST_CONVERGENCE_BETA,
    TCP_FRIENDLY_SLOPE,
)
from .window import kappa
from .window.kernel import evaluate, is_fast_convergence
from .window.validation import validate_inputs

#: 可核对算例参数：取较大 RTT（高 BDP 场景），整条采样轨迹都由
#: CUBIC 立方分支主导，曲线方向与峰值点一目了然。
PRESET_W_MAX = 100.0
PRESET_C = DEFAULT_C
PRESET_RTT = 1.0
#: 本次峰值 100 < 上次峰值 140 → 快速收敛判定为开。
PRESET_W_LAST_MAX = 140.0

#: 采样时刻按 K 的倍数生成：0（丢包起点）、K/2（峰值下方）、
#: K（恰好回到峰值）、3K/2、2K（越过峰值后加速）。
PRESET_TIME_FRACTIONS = (0.0, 0.5, 1.0, 1.5, 2.0)


def build_standards() -> dict[str, Any]:
    """组装标准常量、公式与预置算例的完整只读回显内容。"""
    validate_inputs(
        w_max=PRESET_W_MAX,
        c=PRESET_C,
        rtt=PRESET_RTT,
        w_last_max=PRESET_W_LAST_MAX,
    )

    k = kappa(PRESET_W_MAX, PRESET_C)
    preset_times = [frac * k for frac in PRESET_TIME_FRACTIONS]
    samples = [
        evaluate(
            t,
            PRESET_W_MAX,
            PRESET_RTT,
            c=PRESET_C,
            w_last_max=PRESET_W_LAST_MAX,
        )
        for t in preset_times
    ]

    anchors = {
        "loss_origin": {
            "description": "丢包时刻 t=0，窗口经乘性缩减落到 beta*W_max",
            "t": 0.0,
            "expected_w_cubic": BETA * PRESET_W_MAX,
        },
        "return_to_peak": {
            "description": "t=K：曲线斜率为零，立方窗口精确等于峰值",
            "t": k,
            "expected_w_cubic": PRESET_W_MAX,
        },
        "beyond_peak": {
            "description": "t=2K：越过峰值后沿立方曲线继续加速增长",
            "t": 2.0 * k,
            "expected_w_cubic": PRESET_C * (k**3) + PRESET_W_MAX,
        },
    }

    preset = {
        "description": (
            "丢包后窗口先低于峰值（beta*W_max=70），沿立方曲线爬回，"
            "在 t=K 精确回到峰值 100，随后越过峰值加速增长的可核对算例"
        ),
        "inputs": {
            "w_max": PRESET_W_MAX,
            "c": PRESET_C,
            "rtt": PRESET_RTT,
            "w_last_max": PRESET_W_LAST_MAX,
        },
        "k": k,
        "fast_convergence": is_fast_convergence(
            PRESET_W_MAX, PRESET_W_LAST_MAX
        ),
        "time_fractions_of_k": list(PRESET_TIME_FRACTIONS),
        "samples": samples,
        "anchors": anchors,
    }

    return {
        "name": "TCP CUBIC 拥塞窗口核算标准",
        "constants": {
            "beta_multiplicative_decrease": BETA,
            "default_c": DEFAULT_C,
            "fast_convergence_beta": FAST_CONVERGENCE_BETA,
            "tcp_friendly_slope": TCP_FRIENDLY_SLOPE,
            "window_unit": "MSS 段数",
            "time_unit": "秒",
        },
        "equations": {
            "w_cubic": "W_cubic(t) = C * (t - K)**3 + W_max",
            "kappa": "K = cbrt(W_max * (1 - beta) / C)",
            "w_tcp": "W_tcp(t) = beta*W_max + (3*beta/(2-beta)) * (t/RTT)",
            "selection": (
                "W_tcp(t) > W_cubic(t) 时采用 tcp_friendly 分支，"
                "否则采用 cubic 分支"
            ),
            "fast_convergence": (
                "本次峰值 W_max < 上一次记录峰值 W_last_max 时"
                "快速收敛判定为开"
            ),
        },
        "branches": ["cubic", "tcp_friendly"],
        "error_codes": [
            "invalid_wmax",
            "invalid_c",
            "invalid_time",
            "invalid_rtt",
            "non_finite_number",
            "non_increasing_times",
        ],
        "preset_example": preset,
    }
