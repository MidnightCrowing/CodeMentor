"""
schemas/chat_schema.py
======================
聊天接口相关的 Pydantic 数据模型。

ChatRequest:  POST /api/v1/chat 的请求体
QuestionOut:  GET /api/v1/questions 的单条问答记录响应
"""

import uuid
from datetime import datetime
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """流式对话接口请求体。"""
    user_id: str = Field(..., description="用户唯一标识")
    session_id: str = Field(..., description="会话 ID，用于多轮上下文")
    message: str = Field(..., min_length=1, max_length=8000, description="学生的提问内容")
    model_id: str | None = Field(None, description="指定对话模型 ID，不传则使用默认")
    enable_thinking: bool = Field(True, description="是否开启深度思考")


class QuestionOut(BaseModel):
    """问答记录响应体。"""
    id: uuid.UUID
    question: str
    answer: str
    is_programming: bool | None
    model: str | None
    tokens: int | None
    created_at: datetime

    model_config = {"from_attributes": True}
