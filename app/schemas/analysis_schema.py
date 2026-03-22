"""
schemas/analysis_schema.py
===========================
分析相关的 Pydantic 数据模型。

AnalysisJson:      analysis_json 字段的固化结构（必须严格固化，禁止随意扩展）
DailyAnalysisOut:  GET /api/v1/analysis/daily 的单条返回结构（旧）
DailyAnalysisSummaryOut: GET /api/v1/analysis/daily 的汇总返回结构（含模型调用次数）
ReportRequest:     POST /api/v1/analysis/report 的请求体
ReportOut:         /analysis/report 的响应体
RecentModelUsageOut: /analysis/recent-usage 的响应体
ModelUsageChartPoint: /analysis/usage/chart 响应体单条
ModelUsageRankItem: /analysis/usage/rank 响应体单条
ActiveUserPoint: /analysis/usage/active 响应体单条
ModelErrorTrendPoint: /analysis/usage/error-trend 响应体单条
ModelLatencyTrendPoint: /analysis/usage/latency-trend 响应体单条
ManualDailyAnalysisRequest: /analysis/daily/run 请求体
"""

import uuid
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field


# 固化的分析 JSON 结构
# ⚠️ 不允许随意修改此结构！修改后需同步 LLM Prompt 中的要求。
class AnalysisJson(BaseModel):
    """
    每日分析中 analysis_json 字段的严格固化结构。
    LLM 在生成分析结果时必须输出可与此 Schema 匹配的 JSON。

    字段含义：
    - initiative: 学习主动性（high / medium / low）
    - depth:      提问深度，即追问/延伸程度（high / medium / low）
    - topic:      今日主要讨论的编程主题，自由文字
    """
    initiative: Literal["high", "medium", "low"] = Field(description="学习主动性")
    depth: Literal["high", "medium", "low"] = Field(description="提问深度")
    topic: str = Field(default="unknown", description="今日主要编程主题")


# 每日分析查询响应体
class DailyAnalysisOut(BaseModel):
    """GET /api/v1/analysis/daily 的单条响应结构。"""
    id: uuid.UUID
    user_id: str
    date: str
    analysis_text: str
    analysis_json: AnalysisJson | None
    created_at: datetime

    model_config = {"from_attributes": True}


# 完整报告触发请求体
class ReportRequest(BaseModel):
    """POST /api/v1/analysis/report 请求体。"""
    target_user_id: str = Field(..., description="目标学生用户 ID")


# 完整报告响应体
class ReportOut(BaseModel):
    """POST /api/v1/analysis/report 响应结构。"""
    report: str = Field(description="完整学习报告文本（LLM 汇总生成）")


class StudentOut(BaseModel):
    """GET /api/v1/analysis/students 的单条学生信息。"""
    user_id: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ModelUsageCount(BaseModel):
    """每日模型调用次数。"""
    model_id: str
    request_count: int


class DailyAnalysisSummaryOut(BaseModel):
    """GET /api/v1/analysis/daily 的汇总响应结构（含模型调用次数）。"""
    user_id: str
    date: str
    analysis_text: str
    analysis_json: AnalysisJson | None
    model_usage: list[ModelUsageCount]


class RecentModelUsageOut(BaseModel):
    """GET /api/v1/analysis/recent-usage 响应结构。"""
    user_id: str
    date: str
    model_id: str
    request_count: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    total_latency_ms: int
    error_count: int


class ModelUsageChartPoint(BaseModel):
    """GET /api/v1/analysis/usage/chart 响应单条。"""
    date: str
    model_id: str
    request_count: int
    total_tokens: int


class ModelUsageRankItem(BaseModel):
    """GET /api/v1/analysis/usage/rank 响应单条。"""
    model_id: str
    request_count: int
    total_tokens: int
    delta_request_count: int
    delta_total_tokens: int


class ActiveUserPoint(BaseModel):
    """GET /api/v1/analysis/usage/active 响应单条。"""
    period: str
    active_users: int


class ModelErrorTrendPoint(BaseModel):
    """GET /api/v1/analysis/usage/error-trend 响应单条。"""
    date: str
    model_id: str
    error_count: int
    request_count: int
    error_rate: float


class ModelLatencyTrendPoint(BaseModel):
    """GET /api/v1/analysis/usage/latency-trend 响应单条。"""
    date: str
    model_id: str
    total_latency_ms: int
    request_count: int
    avg_latency_ms: float


class ManualDailyAnalysisRequest(BaseModel):
    """POST /api/v1/analysis/daily/run 请求体。"""
    target_user_id: str = Field(..., description="目标学生用户 ID")
    date: str | None = Field(None, description="分析日期，格式 YYYY-MM-DD，默认当天")
