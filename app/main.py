"""FastAPI 应用与 HTTP 路由（薄层）。

路由只负责取请求模型、调 ``service`` 编排层、把领域结果序列化；
所有数学在 ``cubic``、所有非法输入拦截在 ``validation``。
"""

from __future__ import annotations

import time

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from . import __version__, presets, service
from .errors import CubicServiceError
from .monitoring import Metrics
from .validation import EvaluateRequest, TrajectoryRequest

app = FastAPI(
    title="TCP CUBIC 拥塞窗口核算服务",
    version=__version__,
    description=(
        "以最近一次丢包为时间原点，核算任意时刻的 CUBIC 立方窗口、TCP 友好"
        "线性对照窗口、实际采用分支与快速收敛状态。无状态，仅经 HTTP 提供。"
    ),
)

metrics = Metrics()


@app.middleware("http")
async def _count_requests(request: Request, call_next):
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:  # noqa: BLE001 - 兜底，保证监控不吞掉异常
        metrics.record_request(time.perf_counter() - start, is_error=True)
        raise
    metrics.record_request(time.perf_counter() - start, is_error=response.status_code >= 400)
    return response


@app.exception_handler(CubicServiceError)
async def _handle_domain_error(_: Request, exc: CubicServiceError) -> JSONResponse:
    # 领域错误：带可区分 error_type 的结构化 JSON，HTTP 400
    return JSONResponse(status_code=400, content=exc.to_dict())


@app.exception_handler(RequestValidationError)
async def _handle_request_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    # 请求结构/类型错误也归一成结构化错误，不抛 500
    return JSONResponse(
        status_code=400,
        content={
            "error_type": "invalid_request_schema",
            "message": "request payload failed schema validation",
            "details": exc.errors(),
        },
    )


@app.get("/health", tags=["ops"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics", tags=["ops"])
async def get_metrics() -> dict[str, object]:
    return metrics.snapshot()


@app.post("/evaluate", tags=["cubic"])
async def evaluate(request: EvaluateRequest) -> dict[str, object]:
    """单点求值：给出一个时刻的立方值、线性对照值、采用值与分支。"""

    result = service.evaluate_at(
        peak_window_mss=request.peak_window_mss,
        elapsed_time_s=request.elapsed_time_s,
        rtt_s=request.rtt_s,
        cubic_coefficient=request.cubic_coefficient,
        previous_peak_window_mss=request.previous_peak_window_mss,
    )
    return {
        "beta": service.cubic.BETA,
        **result.to_dict(),
    }


@app.post("/trajectory", tags=["cubic"])
async def trajectory(request: TrajectoryRequest) -> dict[str, object]:
    """轨迹推进：一串严格递增时刻逐点求值，与 /evaluate 共用同一内核。"""

    result = service.evaluate_trajectory(
        peak_window_mss=request.peak_window_mss,
        rtt_s=request.rtt_s,
        sample_times_s=request.sample_times_s,
        cubic_coefficient=request.cubic_coefficient,
        previous_peak_window_mss=request.previous_peak_window_mss,
    )
    return result.to_dict()


@app.get("/presets", tags=["reference"])
async def list_presets() -> dict[str, object]:
    """只读回显所有内置标准情形及其经同一内核算出的检查点。"""

    return {"count": len(presets.list_presets()), "presets": presets.list_presets()}


@app.get("/presets/{preset_id}", tags=["reference"], response_model=None)
async def get_preset(preset_id: str):
    rendered = presets.get_preset(preset_id)
    if rendered is None:
        return JSONResponse(
            status_code=404,
            content={"error_type": "preset_not_found", "message": f"unknown preset: {preset_id}"},
        )
    return rendered
