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
- 时间戳字段统一使用 TIMESTAMP WITH TIME ZONE，应用层写入 UTC+8 aware datetime
"""

import uuid
from datetime import datetime

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
from app.core.time_utils import now_biz_dt_for_db


def _now_biz() -> datetime:
    return now_biz_dt_for_db()


# User 表
class User(Base):
    """
    用户鉴权管理表。
    """
    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="student", server_default="student")
    real_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    student_no: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now_biz
    )

    __table_args__ = (
        Index("idx_users_student_no", "student_no", unique=True),
    )


# 大模型同步底表
class LlmModel(Base):
    """
    保存 config 配置文件中所有可选模型的信息。
    主程序启动时将比对自动更新以保证数据的唯一入口同步。
    """
    __tablename__ = "llm_models"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    support_thinking: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


# 模型每日用量统计表
class ModelUsageStat(Base):
    """
    按日（date）、用户（user_id）、模型（model_id）维度的大模型使用用量统计表。
    包含调用次数、Token总和、接口总耗时与中断/报错总和。
    """
    __tablename__ = "model_usage_stats"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    date: Mapped[str] = mapped_column(String(10), nullable=False)  # "YYYY-MM-DD"
    user_id: Mapped[str] = mapped_column(String(100), nullable=False)
    model_id: Mapped[str] = mapped_column(String(100), nullable=False)

    request_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    __table_args__ = (
        UniqueConstraint("date", "user_id", "model_id", name="uq_usage_stat_dim"),
        Index("idx_usage_stat", "user_id", "date"),
    )


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
        DateTime(timezone=True), default=_now_biz
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
    session_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    is_programming: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now_biz
    )

    __table_args__ = (
        Index("idx_user_id", "user_id"),
        Index("idx_session_id", "session_id"),
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
        DateTime(timezone=True), default=_now_biz
    )

    __table_args__ = (
        UniqueConstraint("user_id", "date", name="uq_user_date"),
        Index("idx_user_date", "user_id", "date"),
    )


# 总报告缓存表
class SummaryReport(Base):
    """
    教师端总报告（多日汇总）缓存表。
    用于避免重复生成，提高响应速度。
    """
    __tablename__ = "summary_reports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[str] = mapped_column(String(100), nullable=False)
    start_date: Mapped[str] = mapped_column(String(10), nullable=False)  # "YYYY-MM-DD"
    end_date: Mapped[str] = mapped_column(String(10), nullable=False)  # "YYYY-MM-DD"
    report_text: Mapped[str] = mapped_column(Text, nullable=False)
    report_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    total_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now_biz
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now_biz, onupdate=_now_biz
    )

    __table_args__ = (
        UniqueConstraint("user_id", "start_date", "end_date", name="uq_summary_report_dim"),
        Index("idx_summary_report_user", "user_id"),
        Index("idx_summary_report_range", "start_date", "end_date"),
    )


# 总报告导出任务表
class SummaryReportExportJob(Base):
    """
    教师端批量导出汇总报告的异步任务表。
    """
    __tablename__ = "summary_report_export_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    class_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    course_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    teacher_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    school_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    include_text_evaluation: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    total_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    result_path: Mapped[str | None] = mapped_column(String(300), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now_biz
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now_biz, onupdate=_now_biz
    )

    __table_args__ = (
        Index("idx_summary_export_user", "user_id"),
        Index("idx_summary_export_status", "status"),
        Index("idx_summary_export_created_at", "created_at"),
    )


# Batch 分析任务表
class AnalysisBatchJob(Base):
    """
    记录批量推理任务状态，用于离线分析结果回写。
    """
    __tablename__ = "analysis_batch_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    date: Mapped[str] = mapped_column(String(10), nullable=False)  # "YYYY-MM-DD"
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="created")

    batch_id: Mapped[str] = mapped_column(String(100), nullable=True)
    input_file_id: Mapped[str] = mapped_column(String(100), nullable=True)
    output_file_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_file_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now_biz
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now_biz, onupdate=_now_biz
    )

    __table_args__ = (
        Index("idx_batch_date", "date"),
        Index("idx_batch_status", "status"),
    )


# 管理员批量分析任务表
class AdminBatchAnalysisJob(Base):
    """
    管理员手动触发的批量分析任务，支持 batch/concurrent 模式。
    """
    __tablename__ = "admin_batch_analysis_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    date: Mapped[str] = mapped_column(String(10), nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    concurrency: Mapped[int | None] = mapped_column(Integer, nullable=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    total_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    failed_user_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now_biz
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now_biz, onupdate=_now_biz
    )

    __table_args__ = (
        Index("idx_admin_batch_user", "user_id"),
        Index("idx_admin_batch_status", "status"),
        Index("idx_admin_batch_created_at", "created_at"),
    )
