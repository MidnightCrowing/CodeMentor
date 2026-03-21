"""
main.py
=======
FastAPI 应用入口。

职责：
- 创建 FastAPI 应用实例
- 通过 lifespan 管理启动/关闭时的资源（APScheduler、数据库）
- 挂载 v1 路由
- 注册全局 HTTP 异常处理（统一返回信封格式）
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.schemas.base import BaseResponse

from app.api.v1.router import router as v1_router
from app.scheduler.daily_task import start_scheduler, stop_scheduler
from app.core.logger import setup_logging

setup_logging()
logger = logging.getLogger(__name__)


# 生命周期管理
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    管理 FastAPI 启动和关闭流程。
    在 startup 中启动 APScheduler，在 shutdown 时安全关闭。
    """
    logger.info("应用启动中...")
    start_scheduler()
    yield
    logger.info("应用关闭中...")
    stop_scheduler()


# FastAPI 实例
app = FastAPI(
    title="CodeMentor - AI 学习行为分析系统",
    description="与学生进行代码问答，并持续收集和分析学习行为数据。",
    version="1.0.0",
    lifespan=lifespan,
)


# 全局 HTTP 异常处理（返回统一信封格式）
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """拦截 FastAPI 默认的 422 校验错误，转换为统一格式。"""
    err_msg = "参数校验错误"
    if exc.errors():
        err = exc.errors()[0]
        # 去掉默认的 query/body 等前缀，只保留字段名
        field = ".".join(str(x) for x in err.get("loc", []) if x not in ("query", "body", "path"))
        msg = err.get("msg", "")
        err_msg = f"参数错误: {msg}" if field else f"参数错误: {msg}"
        
    logger.warning(f"参数校验失败: {exc.errors()}")
    return JSONResponse(
        status_code=400,  # 也可以保持 422，但对前端来说 400 更通用
        content={"code": 1, "message": err_msg, "data": None},
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """捕获所有未处理的异常，返回统一的错误信封格式。"""
    logger.error(f"未捕获异常：{exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"code": 1, "message": "服务内部错误，请稍后重试", "data": None},
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """拦截 FastAPI 中抛出的 HTTPException，转换为统一错误格式。"""
    logger.warning(f"HTTP 异常: {exc.detail}")
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": 1, "message": str(exc.detail), "data": None},
    )


# 挂载路由
app.include_router(v1_router)


# 健康检查
@app.get("/health", tags=["系统"])
async def health_check():
    """服务心跳检测接口。"""
    return BaseResponse.ok({"status": "ok"})
