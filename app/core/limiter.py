"""
限流组件。

- 优先使用用户身份做限流键
- 未登录时退化为客户端 IP
"""

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


def get_user_id_or_ip(request: Request) -> str:
    """提取用户身份作为限流依据；未登录时回退到 IP。"""
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


limiter = Limiter(key_func=get_user_id_or_ip)
