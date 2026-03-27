"""
api/deps.py
===========
FastAPI 依赖注入基础定义。

目前提供：
- get_db: 数据库会话生成器（直接复用 database.py 中的实现）
- check_user_permission: 用户身份与角色权限校验函数
"""

from fastapi import HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db  # noqa: F401  直接再导出供路由使用
from app.models.models import User


def get_current_user_id(request: Request) -> str:
    """
    从 Authorization Header / X-User-Id Header / Cookie 中获取当前用户 ID。
    仅用于身份标识，具体权限由 check_user_permission 校验。
    """
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

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="缺少身份凭证")

async def check_user_permission(user_id: str | None, db: AsyncSession, required_role: str = "student") -> User:
    """手动调用鉴权，抛出 HTTPException（会被统一错误捕获转化为标准格式）"""
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="缺少 user_id")
        
    res = await db.execute(select(User).where(User.user_id == user_id))
    user = res.scalars().first()
    
    if not user:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="该用户不存在")
        
    role_weights = {"student": 1, "teacher": 2, "admin": 3}
    if role_weights.get(user.role, 0) < role_weights.get(required_role, 1):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="权限不足")
        
    return user


async def require_user(user_id: str, db: AsyncSession) -> User:
    """确保用户存在，不存在则抛出 403。"""
    res = await db.execute(select(User).where(User.user_id == user_id))
    user = res.scalars().first()
    if not user:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="该用户不存在")
    return user
