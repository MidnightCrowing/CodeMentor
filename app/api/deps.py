"""
api/deps.py
===========
FastAPI 依赖注入基础定义。

目前提供：
- get_db: 数据库会话生成器（直接复用 database.py 中的实现）

后续可在此添加：
- get_current_user: 身份验证
- rate_limiter: 频率限制
"""

from app.core.database import get_db  # noqa: F401  直接再导出供路由使用
