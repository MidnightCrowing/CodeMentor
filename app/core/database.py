"""
core/database.py
================
数据库连接与会话管理模块。

职责：
- 使用 SQLAlchemy AsyncEngine + asyncpg 创建异步数据库连接池
- 提供 AsyncSession 生成器 get_db，用于 FastAPI 依赖注入
- 提供 Base 基类供所有 ORM Model 继承

注意：
- 必须使用 `async with` 或 FastAPI `Depends(get_db)` 模式使用会话
- 会话在请求结束后自动 commit 或 rollback 并关闭
"""

from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


# 异步引擎
# pool_pre_ping 在每次使用前检活连接（避免连接超时断开导致错误）
engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    echo=False,  # 调试时可改为 True 打印 SQL
)

# 会话工厂
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,  # commit 后对象仍可读，避免 lazy load 报错
)


# ORM 基类
class Base(DeclarativeBase):
    """所有 SQLAlchemy ORM Model 必须继承此类。"""
    pass


# FastAPI 依赖注入生成器
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI 路由依赖。用法：
        async def endpoint(db: AsyncSession = Depends(get_db)):
            ...
    遇到异常自动回滚，正常结束自动提交，最终关闭连接。
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
