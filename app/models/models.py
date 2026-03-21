"""
models/models.py
================
所有数据库 ORM 模型定义。

表结构：
- Session: 会话管理（可选，用于多轮对话扩展）
- Question: 每对问答一条记录，含 model 和 tokens 字段
- DailyAnalysis: 每用户每天一条的离线分析结果

注意：
- UUID 主键使用 Python 端生成（uuid4），不依赖数据库序列
- 时间戳字段统一使用 TIMESTAMP WITH TIME ZONE，存 UTC
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _now_utc() -> datetime:
    """返回当前 UTC 时间（带时区）。"""
    return datetime.now(timezone.utc)


# Session 表
class Session(Base):
    """
    会话管理表（可选）。
    一个 session_id 对应某个用户的一段对话上下文。
    """
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String(200), nullable=True, default="新会话")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now_utc
    )


# Question 表
class Question(Base):
    """
    问答记录表。
    每次学生与 AI 的一轮对话（一问一答）写一条记录。

    字段说明：
    - question: 学生原始提问
    - answer:   模型最终回答（流结束后拼接）
    - is_programming: 前置分类结果，False 时 answer 为固定提示
    - model:    本次调用的模型 ID（便于后期成本分析和切换追踪）
    - tokens:   本次消耗的 token 总数（prompt + completion）
    """
    __tablename__ = "questions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    is_programming: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now_utc
    )

    __table_args__ = (
        Index("idx_user_id", "user_id"),
        Index("idx_created_at", "created_at"),
    )


# DailyAnalysis 表
class DailyAnalysis(Base):
    """
    每日学习分析结果表。
    离线定时任务凌晨 3 点写入，每用户每天最多一条记录。

    字段说明：
    - analysis_text: 给前端展示的自然语言分析
    - analysis_json: 固化的结构化指标，格式如：
        {"initiative": "high", "depth": "medium"}
    """
    __tablename__ = "daily_analysis"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    date: Mapped[str] = mapped_column(String(10), nullable=False)  # "YYYY-MM-DD"
    analysis_text: Mapped[str] = mapped_column(Text, nullable=False)
    analysis_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now_utc
    )

    __table_args__ = (
        UniqueConstraint("user_id", "date", name="uq_user_date"),
        Index("idx_user_date", "user_id", "date"),
    )
