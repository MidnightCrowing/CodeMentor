"""
api/v1/endpoints/analysis.py
=============================
/api/v1/analysis/* routes.
"""

from datetime import date, timedelta
import asyncio
import os

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, check_user_permission, get_current_user_id, require_user
from app.core.config import settings
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
    ExportSummaryReportRequest,
    ExportSummaryReportJobOut,
    ClassCodeOut,
)
from app.schemas.base import BaseResponse
from app.services import analysis_service
from app.services import report_export_service
from app.models.models import SummaryReportExportJob, User
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
    await require_user(target_user_id, db)
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
    force: bool = Query(False, description="Force regenerate report"),
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id),
):
    """
    Generate a full report (teacher).
    """
    await check_user_permission(current_user_id, db, "teacher")
    await require_user(body.target_user_id, db)
    try:
        end_date = date.today()
        start_date = end_date - timedelta(days=settings.max_report_days - 1)
        report = await analysis_service.get_or_generate_summary_report(
            db=db,
            user_id=body.target_user_id,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            force=force,
        )
        if report.report_json:
            return BaseResponse.ok(ReportOut.model_validate(report.report_json))
        return BaseResponse.ok(ReportOut(report_text=report.report_text))
    except ValueError:
        return BaseResponse.error("No analysis data in date range")
    except LLMServiceError:
        return BaseResponse.error("Model call failed")


@router.get("/analysis/classes", response_model=BaseResponse[list[ClassCodeOut]])
async def get_class_codes(
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id),
):
    """
    List distinct class codes derived from student_no.
    """
    await check_user_permission(current_user_id, db, "teacher")
    codes = await analysis_service.list_class_codes(db)
    data = [ClassCodeOut(class_code=c) for c in codes]
    return BaseResponse.ok(data)


@router.post("/analysis/report/export/jobs", response_model=BaseResponse[dict])
async def create_export_job(
    body: ExportSummaryReportRequest,
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id),
):
    """
    Create summary report export job.
    """
    await check_user_permission(current_user_id, db, "teacher")
    
    # Resolve teacher name and school name defaults
    teacher_name = body.teacher_name
    if not teacher_name:
        user = await db.get(User, current_user_id)
        teacher_name = user.real_name if user else None
    
    school_name = body.school_name or "河北农业大学"

    job = SummaryReportExportJob(
        user_id=current_user_id,
        class_code=body.class_code,
        include_text_evaluation=body.include_text_evaluation,
        course_name=body.course_name,
        teacher_name=teacher_name,
        school_name=school_name,
        status="pending",
    )
    db.add(job)
    await db.flush()

    from app.scheduler.daily_task import trigger_export_worker
    trigger_export_worker()

    return BaseResponse.ok({"job_id": str(job.id)})


@router.delete("/analysis/report/export/jobs/{job_id}", response_model=BaseResponse)
async def delete_export_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id),
):
    """
    Delete an export job and its result file on disk.
    Running jobs cannot be deleted.
    """
    await check_user_permission(current_user_id, db, "teacher")
    job = await db.get(SummaryReportExportJob, job_id)
    if not job:
        return BaseResponse.error("Job not found")
    if job.user_id != current_user_id:
        return BaseResponse.error("No permission")
    if job.status == "running":
        return BaseResponse.error("Cannot delete a job that is still running")

    # 删除磁盘文件（如有）
    if job.result_path and os.path.exists(job.result_path):
        try:
            os.remove(job.result_path)
        except OSError:
            pass  # 文件删除失败不影响数据库记录的删除

    from sqlalchemy import delete as sa_delete
    await db.execute(sa_delete(SummaryReportExportJob).where(SummaryReportExportJob.id == job.id))
    await db.commit()
    return BaseResponse.ok("Job deleted")


@router.get("/analysis/report/export/jobs", response_model=BaseResponse[list[ExportSummaryReportJobOut]])
async def list_export_jobs(
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id),
):
    """
    List export jobs for the current user.
    """
    await check_user_permission(current_user_id, db, "teacher")
    from sqlalchemy import select
    stmt = (
        select(SummaryReportExportJob)
        .where(SummaryReportExportJob.user_id == current_user_id)
        .order_by(SummaryReportExportJob.created_at.desc())
    )
    res = await db.execute(stmt)
    jobs = res.scalars().all()
    
    data = []
    for job in jobs:
        total = job.total_count or 0
        completed = job.completed_count or 0
        progress = (completed / total) if total > 0 else 0.0
        data.append(ExportSummaryReportJobOut(
            job_id=str(job.id),
            status=job.status,
            total_count=total,
            completed_count=completed,
            failed_count=job.failed_count or 0,
            progress=progress,
            created_at=job.created_at,
            updated_at=job.updated_at,
            result_ready=bool(job.result_path) and job.status in ("completed", "completed_with_errors"),
            class_code=job.class_code,
            school_name=job.school_name,
            course_name=job.course_name,
            teacher_name=job.teacher_name,
        ))
    return BaseResponse.ok(data)


@router.get("/analysis/report/export/jobs/{job_id}", response_model=BaseResponse[ExportSummaryReportJobOut])
async def get_export_job_status(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id),
):
    """
    Get export job status.
    """
    await check_user_permission(current_user_id, db, "teacher")
    job = await db.get(SummaryReportExportJob, job_id)
    if not job:
        return BaseResponse.error("Job not found")

    total = job.total_count or 0
    completed = job.completed_count or 0
    progress = (completed / total) if total > 0 else 0.0
    data = ExportSummaryReportJobOut(
        job_id=str(job.id),
        status=job.status,
        total_count=total,
        completed_count=completed,
        failed_count=job.failed_count or 0,
        progress=progress,
        created_at=job.created_at,
        updated_at=job.updated_at,
        result_ready=bool(job.result_path) and job.status in ("completed", "completed_with_errors"),
        class_code=job.class_code,
        school_name=job.school_name,
        course_name=job.course_name,
        teacher_name=job.teacher_name,
    )
    return BaseResponse.ok(data)


@router.get("/analysis/report/export/jobs/{job_id}/result")
async def download_export_result(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id),
):
    """
    Download export result file.
    """
    await check_user_permission(current_user_id, db, "teacher")
    job = await db.get(SummaryReportExportJob, job_id)
    if not job or not job.result_path:
        return BaseResponse.error("Result not ready")
    if not os.path.exists(job.result_path):
        return BaseResponse.error("Result file missing")
    return FileResponse(
        path=job.result_path,
        filename=os.path.basename(job.result_path),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.get("/analysis/students", response_model=BaseResponse[list[StudentOut]])
async def list_students(
    limit: int = Query(20, ge=1, le=100, description="Page size"),
    offset: int = Query(0, ge=0, description="Page offset"),
    class_code: str | None = Query(None, description="Class code filter"),
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id),
):
    """
    List students (teacher).
    """
    await check_user_permission(current_user_id, db, "teacher")
    rows = await analysis_service.list_students(
        db=db, limit=limit, offset=offset, class_code=class_code
    )
    data = [StudentOut.model_validate(r) for r in rows]
    return BaseResponse.ok(data)


@router.get("/analysis/recent-usage", response_model=BaseResponse[list[RecentModelUsageOut]])
async def get_recent_usage(
    limit: int = Query(10, ge=1, le=50, description="Top N students"),
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id),
):
    """
    Get recent model usage for latest students.
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
    start_date: str = Query(..., description="Start date YYYY-MM-DD"),
    end_date: str = Query(..., description="End date YYYY-MM-DD"),
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id),
):
    """
    Model usage time series.
    """
    await check_user_permission(current_user_id, db, "teacher")
    rows = await analysis_service.get_model_usage_timeseries(db=db, start_date=start_date, end_date=end_date)
    data = [ModelUsageChartPoint.model_validate(r) for r in rows]
    return BaseResponse.ok(data)


@router.get("/analysis/usage/rank", response_model=BaseResponse[list[ModelUsageRankItem]])
async def get_usage_rank(
    start_date: str = Query(..., description="Start date YYYY-MM-DD"),
    end_date: str = Query(..., description="End date YYYY-MM-DD"),
    period: str = Query("day", description="day|week|month"),
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id),
):
    """
    Model usage ranking with delta.
    """
    await check_user_permission(current_user_id, db, "teacher")
    rows = await analysis_service.get_model_usage_rank(
        db=db,
        period=period,
        anchor_date=end_date,
    )
    data = [ModelUsageRankItem.model_validate(r) for r in rows]
    return BaseResponse.ok(data)


@router.get("/analysis/usage/active", response_model=BaseResponse[list[ActiveUserPoint]])
async def get_active_users(
    start_date: str = Query(..., description="Start date YYYY-MM-DD"),
    end_date: str = Query(..., description="End date YYYY-MM-DD"),
    period: str = Query("day", description="day|week|month"),
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id),
):
    """
    Active students (day/week/month buckets).
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
    start_date: str = Query(..., description="Start date YYYY-MM-DD"),
    end_date: str = Query(..., description="End date YYYY-MM-DD"),
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id),
):
    """
    Error rate trend by model.
    """
    await check_user_permission(current_user_id, db, "teacher")
    rows = await analysis_service.get_model_error_trend(db=db, start_date=start_date, end_date=end_date)
    data = [ModelErrorTrendPoint.model_validate(r) for r in rows]
    return BaseResponse.ok(data)


@router.get("/analysis/usage/latency-trend", response_model=BaseResponse[list[ModelLatencyTrendPoint]])
async def get_latency_trend(
    start_date: str = Query(..., description="Start date YYYY-MM-DD"),
    end_date: str = Query(..., description="End date YYYY-MM-DD"),
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id),
):
    """
    Average latency trend by model.
    """
    await check_user_permission(current_user_id, db, "teacher")
    rows = await analysis_service.get_model_latency_trend(db=db, start_date=start_date, end_date=end_date)
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
    await require_user(body.target_user_id, db)

    result = await analysis_service.run_daily_analysis_for_user(
        db=db,
        user_id=body.target_user_id,
        date_str=body.date,
    )
    analysis = await analysis_service.get_daily_analysis_by_date(
        db=db,
        user_id=body.target_user_id,
        date_str=result["date"],
    )
    data = {
        **result,
        "analysis_text": analysis.analysis_text if analysis else None,
        "analysis_json": analysis.analysis_json if analysis else None,
        "created_at": analysis.created_at if analysis else None,
    }
    return BaseResponse.ok(data)
