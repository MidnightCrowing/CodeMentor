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

from app.api.v1.router import router as v1_router
from app.scheduler.daily_task import start_scheduler, stop_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)


# ── 生命周期管理 ─────────────────────────────────────────────
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


# ── FastAPI 实例 ──────────────────────────────────────────────
app = FastAPI(
    title="CodeMentor - AI 学习行为分析系统",
    description="与学生进行代码问答，并持续收集和分析学习行为数据。",
    version="1.0.0",
    lifespan=lifespan,
)


# ── 全局 HTTP 异常处理（返回统一信封格式）──────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """捕获所有未处理的异常，返回统一的错误信封格式。"""
    logger.error(f"未捕获异常：{exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"code": 1, "message": "服务内部错误，请稍后重试", "data": None},
    )


# ── 挂载路由 ─────────────────────────────────────────────────
app.include_router(v1_router)


# ── 健康检查 ──────────────────────────────────────────────────
@app.get("/health", tags=["系统"])
async def health_check():
    """服务心跳检测接口。"""
    return {"status": "ok"}
