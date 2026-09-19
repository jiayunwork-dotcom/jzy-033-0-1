"""FastAPI 应用装配入口：python -m uvicorn app.main:app。"""

from __future__ import annotations

from fastapi import FastAPI

from . import __version__
from .config import SERVICE_NAME
from .routes import (
    api_router,
    install_exception_handlers,
    install_monitor_middleware,
    root_router,
)


def create_app() -> FastAPI:
    app = FastAPI(
        title=SERVICE_NAME,
        version=__version__,
        description=(
            "TCP CUBIC 拥塞窗口演进核算：给定丢包后的关键量，计算任意"
            "时刻的立方窗口、TCP 友好线性对照窗口、采用分支与快速收敛"
            "状态。范围仅限 CUBIC 窗口演进，无状态、可独立运行。"
        ),
    )
    install_exception_handlers(app)
    install_monitor_middleware(app)
    app.include_router(api_router, prefix="/api/v3", tags=["cubic"])
    app.include_router(root_router, tags=["monitor"])
    return app


app = create_app()
