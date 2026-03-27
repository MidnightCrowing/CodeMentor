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
    session_id: str | None = Field(None, description="会话 ID，用于多轮上下文，为空则由后端新创建")
    dialog_id: uuid.UUID | None = Field(None, description="历史节点ID。若有值，其后的本会话旧记录将打上软删标记供重修此问")
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


class UsageRecordOut(BaseModel):
    """学生查看自己的模型使用记录。"""
    id: uuid.UUID
    session_id: str | None
    model_id: str | None
    tokens: int | None
    created_at: datetime


class UserIdentityOut(BaseModel):
    """用于返回当前用户身份信息。"""
    user_id: str
    role: str
    created_at: datetime


class SessionOut(BaseModel):
    """会话列表单条记录响应体。"""
    id: str
    title: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class SessionRenameRequest(BaseModel):
    """修改会话标题请求体。"""
    title: str = Field(..., min_length=1, max_length=100, description="新的会话标题, 长度限制1-100字符")


class TempRegisterRequest(BaseModel):
    """临时注册请求体。"""
    user_id: str = Field(..., min_length=1, max_length=100, description="自定义用户 ID")


class StudentRegisterRequest(BaseModel):
    """学生注册请求体。"""
    real_name: str = Field(..., min_length=1, max_length=100, description="真实姓名")
    student_no: str = Field(..., min_length=6, max_length=50, description="学号")
    password: str = Field(..., min_length=6, max_length=100, description="注册密码")
