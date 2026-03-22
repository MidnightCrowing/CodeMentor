"""
api/v1/endpoints/analysis.py
=============================
/api/v1/analysis/* routes.

Endpoints:
- GET  /analysis/daily: daily analysis list (date range, with model usage)
- POST /analysis/report: generate report (last 30 days)
- GET  /analysis/students: list students (teacher)
- GET  /analysis/recent-usage: recent student model usage
- GET  /analysis/usage/chart: model usage time series
- GET  /analysis/usage/rank: model usage ranking (with delta)
- GET  /analysis/usage/active: active students (day/week/month)
- GET  /analysis/usage/error-trend: model error rate trend
- GET  /analysis/usage/latency-trend: model latency trend
- POST /analysis/daily/run: admin runs daily analysis for a user
"""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, check_user_permission, get_current_user_id
from app.schemas.analysis_schema import (
    DailyAnalysisSummaryOut,
    ModelUsageChartPoint,
    ModelUsageRankItem,
    ActiveUserPoint,
    ModelErrorTrendPoint,
    ModelLatencyTrendPoint,
    RecentModelUsageOut,
    ReportOut,
    ReportRequest,
    ManualDailyAnalysisRequest,
    StudentOut,
)
from app.schemas.base import BaseResponse
from app.services import analysis_service
from app.services.llm_service import LLMServiceError

router = APIRouter()


@router.get("/analysis/daily", response_model=BaseResponse[list[DailyAnalysisSummaryOut]])
async def get_daily_analysis(
    target_user_id: str = Query(..., description="Target student user id"),
    start_date: str = Query(
        default_factory=lambda: date.today().isoformat(),
        description="Start date, format YYYY-MM-DD",
    ),
    end_date: str = Query(
        default_factory=lambda: date.today().isoformat(),
        description="End date, format YYYY-MM-DD",
    ),
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id),
):
    """
    Query daily analysis records (with model usage).
    """
    await check_user_permission(current_user_id, db, "teacher")
    rows = await analysis_service.get_daily_analysis_with_usage(
        db=db,
        user_id=target_user_id,
        start_date=start_date,
        end_date=end_date,
    )
    data = [DailyAnalysisSummaryOut.model_validate(r) for r in rows]
    return BaseResponse.ok(data)


@router.post("/analysis/report", response_model=BaseResponse[ReportOut])
async def generate_report(
    body: ReportRequest,
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id),
):
    """
    Generate a full report (teacher).
    """
    await check_user_permission(current_user_id, db, "teacher")
    try:
        report_text = await analysis_service.generate_report(db=db, user_id=body.target_user_id)
        return BaseResponse.ok(ReportOut(report=report_text))
    except ValueError as e:
        return BaseResponse.error(str(e))
    except LLMServiceError as e:
        return BaseResponse.error(str(e))


@router.get("/analysis/students", response_model=BaseResponse[list[StudentOut]])
async def get_students(
    limit: int = Query(100, ge=1, le=500, description="Page size"),
    offset: int = Query(0, ge=0, description="Page offset"),
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id),
):
    """
    List students (teacher).
    """
    await check_user_permission(current_user_id, db, "teacher")
    rows = await analysis_service.list_students(db=db, limit=limit, offset=offset)
    data = [StudentOut.model_validate(r) for r in rows]
    return BaseResponse.ok(data)


@router.get("/analysis/recent-usage", response_model=BaseResponse[list[RecentModelUsageOut]])
async def get_recent_usage(
    limit: int = Query(10, ge=1, le=100, description="Records to return"),
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id),
):
    """
    Recent student model usage (teacher).
    """
    await check_user_permission(current_user_id, db, "teacher")
    rows = await analysis_service.get_recent_student_model_usage(db=db, limit=limit)
    data = [
        RecentModelUsageOut(
            user_id=r.user_id,
            date=r.date,
            model_id=r.model_id,
            request_count=r.request_count,
            prompt_tokens=r.prompt_tokens,
            completion_tokens=r.completion_tokens,
            total_tokens=r.total_tokens,
            total_latency_ms=r.total_latency_ms,
            error_count=r.error_count,
        )
        for r in rows
    ]
    return BaseResponse.ok(data)


@router.get("/analysis/usage/chart", response_model=BaseResponse[list[ModelUsageChartPoint]])
async def get_usage_chart(
    start_date: str = Query(..., description="Start date, format YYYY-MM-DD"),
    end_date: str = Query(..., description="End date, format YYYY-MM-DD"),
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id),
):
    """
    Model usage time series (teacher).
    """
    await check_user_permission(current_user_id, db, "teacher")
    rows = await analysis_service.get_model_usage_timeseries(
        db=db,
        start_date=start_date,
        end_date=end_date,
    )
    data = [ModelUsageChartPoint.model_validate(r) for r in rows]
    return BaseResponse.ok(data)


@router.get("/analysis/usage/rank", response_model=BaseResponse[list[ModelUsageRankItem]])
async def get_usage_rank(
    period: str = Query("day", pattern="^(day|week|month)$", description="Period"),
    anchor_date: str = Query(default_factory=lambda: date.today().isoformat(), description="Anchor date"),
    limit: int = Query(20, ge=1, le=100, description="Records to return"),
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id),
):
    """
    Model usage ranking (teacher, with delta).
    """
    await check_user_permission(current_user_id, db, "teacher")
    rows = await analysis_service.get_model_usage_rank(
        db=db,
        period=period,
        anchor_date=anchor_date,
        limit=limit,
    )
    data = [ModelUsageRankItem.model_validate(r) for r in rows]
    return BaseResponse.ok(data)


@router.get("/analysis/usage/active", response_model=BaseResponse[list[ActiveUserPoint]])
async def get_active_users(
    start_date: str = Query(..., description="Start date, format YYYY-MM-DD"),
    end_date: str = Query(..., description="End date, format YYYY-MM-DD"),
    period: str = Query("day", pattern="^(day|week|month)$", description="Period"),
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id),
):
    """
    Active students (teacher).
    """
    await check_user_permission(current_user_id, db, "teacher")
    rows = await analysis_service.get_active_users(
        db=db,
        start_date=start_date,
        end_date=end_date,
        period=period,
    )
    data = [ActiveUserPoint.model_validate(r) for r in rows]
    return BaseResponse.ok(data)


@router.get("/analysis/usage/error-trend", response_model=BaseResponse[list[ModelErrorTrendPoint]])
async def get_error_trend(
    start_date: str = Query(..., description="Start date, format YYYY-MM-DD"),
    end_date: str = Query(..., description="End date, format YYYY-MM-DD"),
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id),
):
    """
    Model error rate trend (teacher).
    """
    await check_user_permission(current_user_id, db, "teacher")
    rows = await analysis_service.get_model_error_trend(
        db=db,
        start_date=start_date,
        end_date=end_date,
    )
    data = [ModelErrorTrendPoint.model_validate(r) for r in rows]
    return BaseResponse.ok(data)


@router.get("/analysis/usage/latency-trend", response_model=BaseResponse[list[ModelLatencyTrendPoint]])
async def get_latency_trend(
    start_date: str = Query(..., description="Start date, format YYYY-MM-DD"),
    end_date: str = Query(..., description="End date, format YYYY-MM-DD"),
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id),
):
    """
    Model latency trend (teacher).
    """
    await check_user_permission(current_user_id, db, "teacher")
    rows = await analysis_service.get_model_latency_trend(
        db=db,
        start_date=start_date,
        end_date=end_date,
    )
    data = [ModelLatencyTrendPoint.model_validate(r) for r in rows]
    return BaseResponse.ok(data)


@router.post("/analysis/daily/run", response_model=BaseResponse[dict])
async def run_daily_for_user(
    body: ManualDailyAnalysisRequest,
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id),
):
    """
    Admin: run daily analysis for a user immediately.
    """
    await check_user_permission(current_user_id, db, "admin")
    date_str = body.date or date.today().isoformat()
    result = await analysis_service.run_daily_analysis_for_user(
        db=db,
        user_id=body.target_user_id,
        date_str=date_str,
    )
    if not result.get("processed"):
        return BaseResponse.ok(result)

    row = await analysis_service.get_daily_analysis_by_date(
        db=db,
        user_id=body.target_user_id,
        date_str=date_str,
    )
    if row:
        result["analysis"] = {
            "analysis_text": row.analysis_text,
            "analysis_json": row.analysis_json,
            "created_at": row.created_at,
        }
    return BaseResponse.ok(result)
