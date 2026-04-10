"""
统一 API 响应包装。

- 成功：`BaseResponse(code=0, message="ok", data=...)`
- 失败：`BaseResponse(code=1, message="错误信息", data=None)`
"""

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class BaseResponse(BaseModel, Generic[T]):
    """统一 API 响应格式。"""

    code: int = 0
    message: str = "ok"
    data: T | None = None

    @classmethod
    def ok(cls, data: T | None = None) -> "BaseResponse[T]":
        """返回成功响应。"""
        return cls(code=0, message="ok", data=data)

    @classmethod
    def error(cls, message: str) -> "BaseResponse[None]":
        """返回失败响应。"""
        return cls(code=1, message=message, data=None)
