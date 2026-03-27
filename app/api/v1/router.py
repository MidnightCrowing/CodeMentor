"""
api/v1/router.py
================
v1 版本路由总线。

将各子模块的 router 挂载到 /api/v1 前缀下。
"""

from fastapi import APIRouter

from app.api.v1.endpoints.chat import router as chat_router
from app.api.v1.endpoints.analysis import router as analysis_router
from app.api.v1.endpoints.system import router as system_router

router = APIRouter(prefix="/api/v1")

router.include_router(chat_router, tags=["对话"])
router.include_router(analysis_router, tags=["分析"])
router.include_router(system_router, tags=["系统"])
