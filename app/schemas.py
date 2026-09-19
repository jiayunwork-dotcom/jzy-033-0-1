"""HTTP 请求/响应模型。

字段类型用 float/列表等基础类型；NaN/Inf、零值与负值的业务校验
统一在 app.window.validation 中完成，错误码可区分。
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field


class EvaluateRequest(BaseModel):
    """单点求值请求。"""

    w_max: Annotated[float, Field(description="丢包前峰值窗口（MSS 段数）")]
    rtt: Annotated[float, Field(description="稳态往返时延（秒）")]
    t: Annotated[float, Field(description="距最近一次丢包的时间（秒）")]
    c: Annotated[
        float, Field(default=0.4, description="CUBIC 立方系数 C")
    ] = 0.4
    w_last_max: Annotated[
        float | None,
        Field(default=None, description="上一次记录的峰值窗口，用于快速收敛判定"),
    ] = None


class TrajectoryRequest(BaseModel):
    """轨迹推进请求。"""

    w_max: Annotated[float, Field(description="丢包前峰值窗口（MSS 段数）")]
    rtt: Annotated[float, Field(description="稳态往返时延（秒）")]
    times: Annotated[
        list[float], Field(description="严格递增的采样时刻序列（秒）")
    ]
    c: Annotated[
        float, Field(default=0.4, description="CUBIC 立方系数 C")
    ] = 0.4
    w_last_max: Annotated[
        float | None,
        Field(default=None, description="上一次记录的峰值窗口"),
    ] = None


class WindowSample(BaseModel):
    t: float
    w_cubic: float
    w_tcp: float
    w: float
    branch: str
    tcp_friendly: bool
    at_peak: bool
    w_reduced: float


class TrajectoryResponse(BaseModel):
    w_max: float
    c: float
    rtt: float
    w_last_max: float | None
    k: float
    fast_convergence: bool
    samples: list[WindowSample]
