"""
Alembic 入口脚本（env.py）
===========================
在此文件中配置数据库迁移的目标元数据和异步连接方式。
使用 asyncpg 驱动时，必须用异步运行方式（run_async_migrations）。
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.core.database import Base

# 导入所有模型，确保 metadata 中有表信息
import app.models.models  # noqa: F401

# Alembic Config 对象
config = context.config

# 配置日志
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 目标元数据
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """离线模式（不连接数据库，只生成 SQL 脚本）"""
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """在线异步模式（连接数据库执行迁移）"""
    connectable = create_async_engine(settings.database_url)
    async with connectable.connect() as connection:
        await connection.run_sync(
            lambda sync_conn: context.configure(
                connection=sync_conn,
                target_metadata=target_metadata,
            )
        )
        async with connection.begin():
            await connection.run_sync(
                lambda _: context.run_migrations()
            )
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
