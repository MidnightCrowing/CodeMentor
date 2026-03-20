"""
schemas/base.py
===============
统一 API 响应信封（Envelope）。

所有接口必须使用 BaseResponse[T] 包装真实数据：
- 成功：BaseResponse(code=0, message="ok", data=T)
- 失败：BaseResponse(code=1, message="err msg", data=None)

用法示例：
    return BaseResponse(data=some_result)
    return BaseResponse.error("LLM timeout")
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
        """返回错误响应。"""
        return cls(code=1, message=message, data=None)
