"""
api/v1/endpoints/analysis.py
=============================
/api/v1/analysis/* 路由实现。

端点：
- GET  /analysis/daily:  查询每日分析记录（带日期范围参数）
- POST /analysis/report: 触发生成综合学习报告（最多取 30 天数据）
"""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, check_user_permission
from app.schemas.analysis_schema import DailyAnalysisOut, ReportOut, ReportRequest
from app.schemas.base import BaseResponse
from app.services import analysis_service
from app.services.llm_service import LLMServiceError

router = APIRouter()


@router.get("/analysis/daily", response_model=BaseResponse[list[DailyAnalysisOut]])
async def get_daily_analysis(
    user_id: str = Query(..., description="目标用户 ID"),
    start_date: str = Query(
        default_factory=lambda: date.today().isoformat(),
        description="起始日期，格式 YYYY-MM-DD",
    ),
    end_date: str = Query(
        default_factory=lambda: date.today().isoformat(),
        description="结束日期，格式 YYYY-MM-DD",
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    查询每日学习分析记录。

    必须传入 start_date 和 end_date，防止全表扫描。
    """
    await check_user_permission(user_id, db, "teacher")
    rows = await analysis_service.get_daily_analyses(
        db=db,
        user_id=user_id,
        start_date=start_date,
        end_date=end_date,
    )
    data = [DailyAnalysisOut.model_validate(r) for r in rows]
    return BaseResponse.ok(data)


@router.post("/analysis/report", response_model=BaseResponse[ReportOut])
async def generate_report(
    body: ReportRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    生成完整学习报告（教师端使用）。

    从该用户最近 30 天的每日分析中汇总，调用 LLM 生成多维度评估报告。
    """
    await check_user_permission(body.user_id, db, "teacher")
    try:
        report_text = await analysis_service.generate_report(db=db, user_id=body.user_id)
        return BaseResponse.ok(ReportOut(report=report_text))
    except ValueError as e:
        return BaseResponse.error(str(e))
    except LLMServiceError as e:
        return BaseResponse.error(str(e))
