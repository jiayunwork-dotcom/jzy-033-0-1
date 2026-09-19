"""HTTP 路由层：只做请求解析、调用数学层、组装响应。

路由内不含任何窗口计算逻辑；单点与轨迹两个接口分别调用
window.evaluate 与 window.run_trajectory（后者内部也逐个调用
同一个 evaluate）。

* ``api_router``：版本化业务接口（/api/v3 前缀）；
* ``root_router``：健康检查与根路径（不带前缀）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from . import __version__
from .config import SERVICE_NAME
from .errors import CubicServiceError
from .monitor import monitor
from .presets import build_standards
from .schemas import EvaluateRequest, TrajectoryRequest
from .window import evaluate, is_fast_convergence, kappa, run_trajectory

api_router = APIRouter()
root_router = APIRouter()


def _single_response(payload: EvaluateRequest) -> dict[str, Any]:
    """单点求值的响应组装（轨迹接口走同一个 evaluate）。"""
    result = evaluate(
        payload.t,
        payload.w_max,
        payload.rtt,
        c=payload.c,
        w_last_max=payload.w_last_max,
    )
    result["k"] = kappa(payload.w_max, payload.c)
    result["fast_convergence"] = is_fast_convergence(
        payload.w_max, payload.w_last_max
    )
    result["w_max"] = float(payload.w_max)
    result["c"] = float(payload.c)
    result["rtt"] = float(payload.rtt)
    result["w_last_max"] = (
        None if payload.w_last_max is None else float(payload.w_last_max)
    )
    return result


@api_router.post("/evaluate", summary="单时刻 CUBIC 窗口求值")
def evaluate_window(request: EvaluateRequest) -> dict[str, Any]:
    return _single_response(request)


@api_router.post("/trajectory", summary="整段采样时刻的窗口演进轨迹")
def trajectory_window(request: TrajectoryRequest) -> dict[str, Any]:
    return run_trajectory(
        request.times,
        request.w_max,
        request.rtt,
        c=request.c,
        w_last_max=request.w_last_max,
    )


@api_router.get("/standards", summary="只读：内置标准常量、公式与预置算例")
def standards() -> dict[str, Any]:
    return build_standards()


@root_router.get("/healthz", summary="存活与运行状态（监控采集）")
def healthz() -> dict[str, Any]:
    return monitor.snapshot()


@root_router.get("/", include_in_schema=False)
def index() -> dict[str, Any]:
    return {
        "service": SERVICE_NAME,
        "version": __version__,
        "docs": "/docs",
        "endpoints": [
            "POST /api/v3/evaluate",
            "POST /api/v3/trajectory",
            "GET /api/v3/standards",
            "GET /healthz",
        ],
    }


def install_exception_handlers(app: FastAPI) -> None:
    """把业务错误和请求体校验错误统一成结构化 JSON。"""

    @app.exception_handler(CubicServiceError)
    async def _handle_service_error(
        _request: Request, exc: CubicServiceError
    ) -> JSONResponse:
        return JSONResponse(status_code=exc.http_status, content=exc.to_dict())

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = exc.errors()
        first = details[0] if details else {}
        loc = [
            str(part)
            for part in first.get("loc", [])
            if part not in ("body",)
        ]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "malformed_request",
                    "message": "请求体不符合接口模型，详见 details",
                    "field": ".".join(loc) if loc else None,
                    "details": details,
                }
            },
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(
        _request: Request, exc: Exception
    ) -> JSONResponse:
        # 兜底：任何未预期错误也以结构化形式返回 500，不泄露堆栈。
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": f"服务内部错误：{type(exc).__name__}",
                }
            },
        )


def install_monitor_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def _count(request: Request, call_next):  # type: ignore[no-untyped-def]
        try:
            response = await call_next(request)
        except Exception:
            monitor.record_request(is_error=True)
            raise
        monitor.record_request(is_error=response.status_code >= 400)
        return response
