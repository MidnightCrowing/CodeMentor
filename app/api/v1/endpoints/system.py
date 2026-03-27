"""
api/v1/endpoints/system.py
==========================
系统相关接口：健康检查、状态查询等。
"""

from fastapi import APIRouter
from app.schemas.base import BaseResponse

router = APIRouter()

@router.get("/health", tags=["系统"])
async def health_check():
    """服务心跳检测接口。现在路径应为 /api/v1/health"""
    return BaseResponse.ok({"status": "ok"})
