"""
FastAPI 依赖定义。

- `get_db`: 数据库会话依赖
- `get_current_user_id`: 从请求中提取当前用户 ID
- `check_user_permission`: 校验用户是否存在且具备目标角色
"""

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db  # noqa: F401
from app.models.models import User


def get_current_user_id(request: Request) -> str:
    """
    从 Authorization / X-User-Id / Cookie 中提取当前用户 ID。
    这里只做身份识别，权限校验交由 `check_user_permission` 完成。
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


async def check_user_permission(
    user_id: str | None,
    db: AsyncSession,
    required_role: str = "student",
) -> User:
    """校验用户存在且角色满足要求，不通过时抛出 HTTPException。"""
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="缺少用户标识")

    res = await db.execute(select(User).where(User.user_id == user_id))
    user = res.scalars().first()

    if not user:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="用户不存在")

    role_weights = {"student": 1, "teacher": 2, "admin": 3}
    if role_weights.get(user.role, 0) < role_weights.get(required_role, 1):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="权限不足")

    return user


async def require_user(user_id: str, db: AsyncSession) -> User:
    """确保用户存在，不存在时抛出 403。"""
    res = await db.execute(select(User).where(User.user_id == user_id))
    user = res.scalars().first()
    if not user:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="用户不存在")
    return user
