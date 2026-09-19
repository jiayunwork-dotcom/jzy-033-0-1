"""内置标准情形（只读）与预置核对算例。

算例的检查点全部经过 :mod:`app.service` 同一套内核求值后回显，回显本身
不产生任何状态变更。预置算例 ``canonical_recovery_demo`` 的数值特意取整：

    W_max = 80 MSS, C = 0.375, RTT = 0.5 s, beta = 0.7

    K = cbrt(0.3 * 80 / 0.375) = cbrt(64) = 4 s
    W_cubic(0) = 0.375*(-4)^3 + 80 = 56 = beta*W_max （丢包缩减点）
    W_cubic(4) = 80 = W_max                           （精确回到峰值）
    W_cubic(8) = 0.375*(+4)^3 + 80 = 104 > W_max      （越过并加速）

看一眼检查点即可验证曲线方向（56 -> 77 -> 80 -> 83 -> 104）与峰值点对齐。
"""

from __future__ import annotations

from dataclasses import dataclass

from . import service


@dataclass(frozen=True, slots=True)
class Preset:
    preset_id: str
    title: str
    description: str
    parameters: dict[str, object]
    checkpoint_times_s: tuple[float, ...]


_PRESETS: tuple[Preset, ...] = (
    Preset(
        preset_id="canonical_recovery_demo",
        title="丢包后沿立方曲线爬回并越过峰值（整数核对算例）",
        description=(
            "W_max=80 MSS、C=0.375、RTT=0.5s，K 恰为 4s。"
            "t=0 窗口 56（=0.7*80 的乘性缩减点），t=4s 精确等于峰值 80，"
            "t=8s 为 104，严格越过峰值；上一次峰值 100 > 80，快速收敛处于激活态。"
        ),
        parameters={
            "peak_window_mss": 80,
            "rtt_s": 0.5,
            "cubic_coefficient": 0.375,
            "previous_peak_window_mss": 100,
        },
        checkpoint_times_s=(0.0, 2.0, 4.0, 6.0, 8.0),
    ),
    Preset(
        preset_id="low_bdp_tcp_friendly",
        title="低带宽时延积路径：退让到 TCP 友好支",
        description=(
            "W_max=10 MSS、RTT=10ms，线性对照窗口每秒增长约 161.5 MSS，"
            "远快于立方支，选支判据在回到峰值之前即令服务采用 tcp_friendly 分支。"
        ),
        parameters={
            "peak_window_mss": 10,
            "rtt_s": 0.01,
            "cubic_coefficient": 0.4,
        },
        checkpoint_times_s=(0.0, 0.5, 1.0),
    ),
    Preset(
        preset_id="high_bdp_cubic",
        title="高带宽时延积路径：立方支主导",
        description=(
            "W_max=10000 MSS、RTT=200ms，立方支在峰值附近高于线性对照，"
            "采用 cubic 分支，体现 CUBIC 在大 BDP 下的快速收敛。"
        ),
        parameters={
            "peak_window_mss": 10000,
            "rtt_s": 0.2,
            "cubic_coefficient": 0.4,
        },
        checkpoint_times_s=(0.0, 10.0, 19.57, 30.0),
    ),
    Preset(
        preset_id="rising_peak_fast_convergence_closed",
        title="峰值回升：快速收敛关闭",
        description=(
            "参数同 canonical_recovery_demo，但上一次峰值为 60 < 80，"
            "本次峰值相对记录值上升，fast_convergence.active 必须为 false、"
            "peak_trend 为 rising，与 canonical 算例的 falling/true 形成开合对照。"
        ),
        parameters={
            "peak_window_mss": 80,
            "rtt_s": 0.5,
            "cubic_coefficient": 0.375,
            "previous_peak_window_mss": 60,
        },
        checkpoint_times_s=(0.0, 4.0),
    ),
)

_PRESETS_BY_ID = {preset.preset_id: preset for preset in _PRESETS}


def _render(preset: Preset) -> dict[str, object]:
    points = [
        service.evaluate_at(**preset.parameters, elapsed_time_s=t).to_dict()  # type: ignore[arg-type]
        for t in preset.checkpoint_times_s
    ]
    return {
        "preset_id": preset.preset_id,
        "title": preset.title,
        "description": preset.description,
        "endpoint": "/evaluate",
        "parameters": dict(preset.parameters),
        "beta": 0.7,
        "k_s": points[0]["k_s"],
        "checkpoints": points,
    }


def list_presets() -> list[dict[str, object]]:
    """回显全部内置标准情形（只读）。"""

    return [_render(preset) for preset in _PRESETS]


def get_preset(preset_id: str) -> dict[str, object] | None:
    preset = _PRESETS_BY_ID.get(preset_id)
    return _render(preset) if preset is not None else None
