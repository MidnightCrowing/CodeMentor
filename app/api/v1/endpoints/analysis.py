"""
api/v1/endpoints/analysis.py
=============================
/api/v1/analysis/* routes.
"""

from datetime import timedelta
import asyncio
import json
import os
import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, check_user_permission, get_current_user_id, require_user
from app.core.config import settings
from app.core.time_utils import today_biz, yesterday_biz_iso_date
from app.models.models import AdminBatchAnalysisJob
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
    AdminBatchAnalysisRequest,
    AdminBatchAnalysisJobOut,
)
from app.schemas.base import BaseResponse
from app.services import analysis_service
from app.services import report_export_service
from app.models.models import SummaryReportExportJob, User
from app.services.llm_service import LLMServiceError

router = APIRouter()


async def _get_owned_export_job(
    db: AsyncSession,
    current_user_id: str,
    job_id: str,
) -> SummaryReportExportJob | None:
    job = await db.get(SummaryReportExportJob, job_id)
    if not job or job.user_id != current_user_id:
        return None
    return job


@router.get("/analysis/daily", response_model=BaseResponse[list[DailyAnalysisSummaryOut]])
async def get_daily_analysis(
    target_user_id: str = Query(..., description="Target student user id"),
    start_date: str = Query(
        default_factory=lambda: today_biz().isoformat(),
        description="Start date, format YYYY-MM-DD",
    ),
    end_date: str = Query(
        default_factory=lambda: today_biz().isoformat(),
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
        end_date = today_biz()
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
        return BaseResponse.error("指定时间范围内暂无分析数据")
    except LLMServiceError as exc:
        return BaseResponse.error(str(exc))


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
    job = await _get_owned_export_job(db, current_user_id, job_id)
    if not job:
        return BaseResponse.error("任务不存在")
    if job.status == "running":
        return BaseResponse.error("任务执行中，暂时无法删除")

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
    job = await _get_owned_export_job(db, current_user_id, job_id)
    if not job:
        return BaseResponse.error("任务不存在")

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
    job = await _get_owned_export_job(db, current_user_id, job_id)
    if not job or not job.result_path:
        return BaseResponse.error("结果尚未生成")
    if not os.path.exists(job.result_path):
        return BaseResponse.error("结果文件不存在")
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
        RecentModelUsageOut(**r)
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
    target_date = body.date or today_biz().isoformat()

    result = await analysis_service.run_daily_analysis_for_user(
        db=db,
        user_id=body.target_user_id,
        date_str=target_date,
    )
    if not result.get("processed"):
        return BaseResponse.ok(
            {
                **result,
                "date": target_date,
                "analysis_text": None,
                "analysis_json": None,
                "created_at": None,
            }
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


@router.post("/analysis/daily/batch")
async def run_daily_batch_analysis(
    body: AdminBatchAnalysisRequest,
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id),
):
    """
    Admin: batch analysis with streaming logs (SSE).

    Supports two modes:
    - batch: submit to OpenAI Batch API
    - concurrent: run concurrent chat calls with retry
    """
    await check_user_permission(current_user_id, db, "admin")

    target_date = body.date or yesterday_biz_iso_date()

    async def _sse(event: str, data: str) -> str:
        return f"event: {event}\ndata: {data}\n\n"

    async def _stream_logs():
        try:
            # 重试模式
            if body.retry:
                if not body.job_id:
                    yield await _sse("error", json.dumps({"message": "重试模式需要提供 job_id"}))
                    return

                # 查询任务
                stmt = select(AdminBatchAnalysisJob).where(AdminBatchAnalysisJob.id == uuid.UUID(body.job_id))
                result = await db.execute(stmt)
                job = result.scalar_one_or_none()

                if not job:
                    yield await _sse("error", json.dumps({"message": "任务不存在"}))
                    return

                if job.status == "running":
                    yield await _sse("log", json.dumps({"message": "任务正在进行中，请稍后查询状态"}))
                    yield await _sse("done", json.dumps({"job_id": str(job.id)}))
                    return

                # 提取失败用户
                retry_user_ids = job.failed_user_ids or []
                if not retry_user_ids:
                    yield await _sse("log", json.dumps({"message": "没有失败的用户需要重试"}))
                    yield await _sse("done", json.dumps({"job_id": str(job.id)}))
                    return

                yield await _sse("log", json.dumps({"message": f"开始重试 {len(retry_user_ids)} 个失败的学生"}))

                # 更新任务状态
                job.status = "running"
                job.failed_count = 0
                job.completed_count = 0
                job.failed_user_ids = []
                await db.commit()

                # 执行重试
                result = await analysis_service.run_daily_analysis_concurrent(
                    db=db,
                    date_str=target_date,
                    concurrency=body.concurrency or 10,
                    max_retries=5,
                    retry_user_ids=retry_user_ids,
                )

                # 更新任务
                job.completed_count = result["completed"]
                job.failed_count = result["failed"]
                job.failed_user_ids = result["failed_user_ids"]
                job.status = "completed" if result["failed"] == 0 else "failed"
                await db.commit()

                yield await _sse("log", json.dumps({
                    "message": f"重试完成：成功 {result['completed']}，失败 {result['failed']}"
                }))
                yield await _sse("done", json.dumps({
                    "job_id": str(job.id),
                    "completed": result["completed"],
                    "failed": result["failed"],
                }))
                return

            # Batch 模式
            if body.mode == "batch":
                yield await _sse("log", json.dumps({"message": "正在提交 Batch 任务..."}))

                batch_result = await analysis_service.submit_daily_analysis_batch(
                    db=db,
                    date_str=target_date,
                )

                # 创建任务记录
                job = AdminBatchAnalysisJob(
                    id=uuid.uuid4(),
                    user_id=current_user_id,
                    date=target_date,
                    mode="batch",
                    status="pending",
                    total_count=batch_result.get("total_users", 0),
                )
                db.add(job)
                await db.commit()

                yield await _sse("log", json.dumps({
                    "message": f"Batch 任务已提交，batch_id: {batch_result.get('batch_id')}"
                }))
                yield await _sse("done", json.dumps({
                    "job_id": str(job.id),
                    "batch_id": batch_result.get("batch_id"),
                }))
                return

            # 并发 Chat 模式
            yield await _sse("log", json.dumps({"message": f"开始并发分析，日期: {target_date}"}))

            # 创建任务记录
            job = AdminBatchAnalysisJob(
                id=uuid.uuid4(),
                user_id=current_user_id,
                date=target_date,
                mode="concurrent",
                concurrency=body.concurrency or 10,
                status="running",
            )
            db.add(job)
            await db.commit()

            yield await _sse("log", json.dumps({"message": f"任务 ID: {job.id}"}))

            # 执行并发分析
            result = await analysis_service.run_daily_analysis_concurrent(
                db=db,
                date_str=target_date,
                concurrency=body.concurrency or 10,
                max_retries=5,
            )

            # 更新任务
            job.total_count = result["total"]
            job.completed_count = result["completed"]
            job.failed_count = result["failed"]
            job.failed_user_ids = result["failed_user_ids"]
            job.status = "completed" if result["failed"] == 0 else "failed"
            await db.commit()

            yield await _sse("log", json.dumps({
                "message": f"分析完成：总计 {result['total']}，成功 {result['completed']}，失败 {result['failed']}"
            }))

            if result["failed"] > 0:
                yield await _sse("log", json.dumps({
                    "message": f"失败的学生: {', '.join(result['failed_user_ids'][:10])}" +
                               (f" 等 {result['failed']} 个" if result['failed'] > 10 else "")
                }))

            yield await _sse("done", json.dumps({
                "job_id": str(job.id),
                "total": result["total"],
                "completed": result["completed"],
                "failed": result["failed"],
            }))

        except Exception as exc:
            import logging
            logging.exception("批量分析流式接口异常")
            yield await _sse("error", json.dumps({"message": str(exc)}))

    return StreamingResponse(_stream_logs(), media_type="text/event-stream")


@router.get("/analysis/daily/batch/jobs/{job_id}")
async def get_batch_analysis_job_status(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id),
):
    """
    Query batch analysis job status.
    """
    await check_user_permission(current_user_id, db, "admin")

    stmt = select(AdminBatchAnalysisJob).where(AdminBatchAnalysisJob.id == uuid.UUID(job_id))
    result = await db.execute(stmt)
    job = result.scalar_one_or_none()

    if not job:
        return BaseResponse.error("任务不存在", code=404)

    progress = (job.completed_count / job.total_count * 100) if job.total_count > 0 else 0.0

    data = AdminBatchAnalysisJobOut(
        job_id=str(job.id),
        status=job.status,
        mode=job.mode,
        date=job.date,
        total_count=job.total_count,
        completed_count=job.completed_count,
        failed_count=job.failed_count,
        failed_user_ids=job.failed_user_ids,
        progress=progress,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )

    return BaseResponse.ok(data)
