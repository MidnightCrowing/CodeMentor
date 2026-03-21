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
    """提取 user_id 作为限流条件，如果没有则退化为 IP"""
    # 1. 尝试从 Query 获取
    user_id = request.query_params.get("user_id")
    if user_id:
        return user_id
        
    # 2. 尝试从已经被 FastAPI 解析并缓存的 JSON body 获取
    if hasattr(request, "_json"):
        try:
            body = request._json
            if isinstance(body, dict) and "user_id" in body:
                return body.get("user_id")
        except Exception:
            pass
            
    # 3. 兜底为 IP 限流
    return get_remote_address(request)

# 创建 Limiter 实例并以用户 ID（或 IP）作为哈希唯一标识来记录频次
limiter = Limiter(key_func=get_user_id_or_ip)
