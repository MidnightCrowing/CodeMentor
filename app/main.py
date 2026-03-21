import logging
from contextlib import asynccontextmanager

from slowapi.errors import RateLimitExceeded
from app.core.limiter import limiter

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.schemas.base import BaseResponse

from app.api.v1.router import router as v1_router
from app.scheduler.daily_task import start_scheduler, stop_scheduler
from app.core.logger import setup_logging
from app.core.startup import sync_models_to_db

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
    await sync_models_to_db()
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

# 全局挂载 limiter
app.state.limiter = limiter

# 配置 CORS 跨域请求（支持前后端分离集成）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 默认允许全部，建议在生产中通过环境变量限制
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



# 全局 HTTP 异常处理（返回统一信封格式）
@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    """防刷限流器拦截。"""
    client_ip = request.client.host if request.client else "Unknown"
    logger.warning(f"触发反爬阈值: {client_ip} 遭到拦截")
    return JSONResponse(
        status_code=429,
        content={"code": 1, "message": "请求过于频繁，请稍后再试", "data": None},
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """拦截 FastAPI 默认的 422 校验错误，转换为统一格式。"""
    err_msg = "参数校验错误"
    if exc.errors():
        err = exc.errors()[0]
        # 去掉默认的 query/body 等前缀，只保留字段名
        field = ".".join(str(x) for x in err.get("loc", []) if x not in ("query", "body", "path"))
        msg = err.get("msg", "")
        # FIX: 将前面的判断漏掉 field 的问题补齐
        err_msg = f"参数错误: {field} {msg}" if field else f"参数错误: {msg}"
        
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
