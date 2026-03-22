"""
core/limiter.py
===============
限流功能核心组件加载层。

职责：
- 构建项目全局的防刷频率控制器（基于 slowapi）。
- 提取用户访问 IP 用于独立封锁识别。
"""

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address
import typing

def get_user_id_or_ip(request: Request) -> str:
    """提取用户身份作为限流条件，如果没有则退化为 IP"""
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

    return get_remote_address(request)

# 创建 Limiter 实例并以用户 ID（或 IP）作为哈希唯一标识来记录频次
limiter = Limiter(key_func=get_user_id_or_ip)
