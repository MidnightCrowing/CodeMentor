import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from sqlalchemy import select
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.router import router as v1_router
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.limiter import limiter
from app.core.logger import setup_logging
from app.core.request_context import set_user_role
from app.core.startup import sync_models_to_db
from app.models.models import User
from app.scheduler.daily_task import acquire_master_lock, start_scheduler, stop_scheduler

setup_logging()
logger = logging.getLogger(__name__)


def _extract_user_id(request: Request) -> str | None:
    auth = request.headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        token = auth.split(" ", 1)[1].strip()
        if token:
            return token

    x_user_id = request.headers.get("X-User-Id")
    if x_user_id:
        return x_user_id

    cookie_user_id = request.cookies.get("user_id")
    if cookie_user_id:
        return cookie_user_id

    return None


def _extract_model_from_request(request: Request) -> str | None:
    state_model = getattr(request.state, "model_id", None)
    if state_model:
        return str(state_model)

    query_model = request.query_params.get("model_id")
    if query_model:
        return query_model

    raw_body = getattr(request.state, "raw_body", b"")
    if not raw_body:
        return None

    try:
        body = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None

    model_id = body.get("model_id")
    if model_id is None:
        return None
    return str(model_id)


def _request_log_context(request: Request) -> dict[str, str]:
    user_id = getattr(request.state, "request_user_id", None) or _extract_user_id(request)
    client_ip = request.client.host if request.client else "unknown"
    return {
        "method": request.method,
        "path": request.url.path,
        "user_id": user_id or "匿名",
        "model": _extract_model_from_request(request) or "未提供",
        "client_ip": client_ip,
    }


def _format_request_context(request: Request) -> str:
    ctx = _request_log_context(request)
    return (
        f"方法={ctx['method']} 路径={ctx['path']} 用户ID={ctx['user_id']} "
        f"模型={ctx['model']} 客户端IP={ctx['client_ip']}"
    )


async def attach_user_role(request: Request, call_next):
    try:
        request.state.request_user_id = _extract_user_id(request)
        if request.url.path.startswith("/api/v1/chat"):
            user_id = request.state.request_user_id
            if user_id:
                try:
                    async with AsyncSessionLocal() as db:
                        res = await db.execute(select(User).where(User.user_id == user_id))
                        user = res.scalars().first()
                        if user:
                            request.state.user_role = user.role
                            set_user_role(user.role)
                except Exception:
                    logger.warning("挂载用户角色失败: %s", _format_request_context(request), exc_info=True)
        response = await call_next(request)
        return response
    finally:
        set_user_role(None)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("应用启动中")
    
    is_master = acquire_master_lock()
    
    if is_master:
        await sync_models_to_db()
        from app.services import report_export_service

        await report_export_service.reset_stale_jobs()
        start_scheduler()
    else:
        logger.info("[多进程] 其它 Worker 已取得全局锁，本进程继续作为纯 API 节点运行")
        
    yield
    logger.info("应用关闭中")
    if is_master:
        await stop_scheduler()


app = FastAPI(
    title="CodeMentor - AI Learning Behavior Analysis System",
    description="CodeMentor backend API for chat, analytics, and report export.",
    version="1.0.0",
    lifespan=lifespan,
)

app.middleware("http")(attach_user_role)
app.state.limiter = limiter

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    logger.warning("触发限流: %s", _format_request_context(request))
    return JSONResponse(
        status_code=429,
        content={"code": 1, "message": "请求过于频繁，请稍后再试", "data": None},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    err_msg = "请求参数错误"
    if exc.errors():
        err = exc.errors()[0]
        field = ".".join(
            str(x) for x in err.get("loc", []) if x not in ("query", "body", "path")
        )
        err_msg = f"参数错误: {field}" if field else "请求参数错误"

    logger.warning(
        "请求参数校验失败: %s 错误详情=%s",
        _format_request_context(request),
        exc.errors(),
    )
    return JSONResponse(
        status_code=400,
        content={"code": 1, "message": err_msg, "data": None},
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("未处理异常: %s 异常=%s", _format_request_context(request), exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"code": 1, "message": "请求处理失败，请稍后重试", "data": None},
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    level = logging.INFO if exc.status_code in {401, 403, 404} else logging.WARNING
    logger.log(
        level,
        "HTTP异常: %s 状态码=%s 详情=%s",
        _format_request_context(request),
        exc.status_code,
        exc.detail,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": 1, "message": str(exc.detail), "data": None},
    )


app.include_router(v1_router)
