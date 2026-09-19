"""窗口数学层：内核、校验、轨迹推进。"""

from .kernel import (
    WindowResult,
    cbrt,
    cubic_window,
    evaluate,
    is_fast_convergence,
    kappa,
    reduced_window,
    tcp_window,
)
from .trajectory import run_trajectory
from .validation import validate_inputs, validate_sample_times

__all__ = [
    "WindowResult",
    "cbrt",
    "cubic_window",
    "evaluate",
    "is_fast_convergence",
    "kappa",
    "reduced_window",
    "tcp_window",
    "run_trajectory",
    "validate_inputs",
    "validate_sample_times",
]
