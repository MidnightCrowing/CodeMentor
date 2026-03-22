"""
services/analysis_service.py
=============================
离线分析业务层。

职责：
- run_daily_analysis(date_str): 对所有用户执行当天的学习分析
  - 从 questions 表提取当日编程问题
  - 每 20 条压缩一次（避免超 Token 限制）
  - 调用 llm_service.analyze() 生成结构化分析
  - 将结果写入 daily_analysis 表（UPSERT 去重）
- get_daily_analyses(user_id, start_date, end_date): 查询每日分析记录
- generate_report(user_id): 汇总最近 30 天分析生成完整报告

压缩策略：
- 每 20 条问答为一个 chunk（settings.compression_chunk_size）
- 多个 chunk 合并为一个摘要文本后再调用最终分析

测试入口：tests/test_analysis_service.py
"""

from datetime import date, timedelta, datetime
import json
import logging
from pathlib import Path

from sqlalchemy import and_, select, func, cast, Date
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.prompts import ANALYSIS_SYSTEM_PROMPT
from app.models.models import DailyAnalysis, Question, User, ModelUsageStat, AnalysisBatchJob
from app.services import batch_service, llm_service
from app.services.llm_service import LLMServiceError


logger = logging.getLogger(__name__)


# 私有：问答数据格式化
def _format_questions(questions: list[Question]) -> str:
    """
    将 Question 对象列表格式化为 LLM 可理解的文本段落。

    Args:
        questions: Question 对象列表

    Returns:
        格式化后的多行文本，每条格式为：
            Q: 学生问题
            A: AI 回答
    """
    lines: list[str] = []
    for i, q in enumerate(questions, start=1):
        lines.append(f"[{i}] Q: {q.question}\nA: {q.answer}")
    return "\n\n".join(lines)


# 私有：分块压缩
def _chunk_questions(questions: list[Question], chunk_size: int) -> list[list[Question]]:
    """
    将问答列表按 chunk_size 切分。

    Args:
        questions:  所有问答的列表
        chunk_size: 每块的最大条数（来自 settings.compression_chunk_size）

    Returns:
        列表的列表，每个子列表最多 chunk_size 条
    """
    return [questions[i:i + chunk_size] for i in range(0, len(questions), chunk_size)]


# 每日分析主函数（由定时器调用）
async def run_daily_analysis(db: AsyncSession, date_str: str) -> dict:
    """
    对所有用户执行指定日期的每日学习分析。
    通常由 APScheduler 在凌晨 3 点调用。

    流程：
    1. 按 user_id 分组提取该日期的 questions 记录
    2. 分块压缩（每 20 条一块）
    3. 合并各块摘要，调用 LLM 分析
    4. UPSERT 写入 daily_analysis 表

    Args:
        db:       数据库会话
        date_str: 目标日期字符串，格式 "YYYY-MM-DD"

    Returns:
        {"processed_users": int, "skipped": int} 执行摘要
    """
    # 提取该天的所有编程问题（过滤掉非编程拒答记录）
    target_date = _parse_date(date_str)
    stmt = (
        select(Question)
        .where(
            and_(
                func.date(Question.created_at) == target_date,
                Question.is_programming == True,  # noqa: E712
            )
        )
        .order_by(Question.user_id, Question.created_at)
    )
    result = await db.execute(stmt)
    all_questions: list[Question] = list(result.scalars().all())

    if not all_questions:
        return {"processed_users": 0, "skipped": 0}

    # 按 user_id 分组
    user_question_map: dict[str, list[Question]] = {}
    for q in all_questions:
        user_question_map.setdefault(q.user_id, []).append(q)

    processed = 0
    skipped = 0

    for user_id, questions in user_question_map.items():
        try:
            await _analyze_and_upsert(db, user_id, date_str, questions)
            processed += 1
        except LLMServiceError:
            # 单个用户失败不影响其他用户
            skipped += 1
            continue

    return {"processed_users": processed, "skipped": skipped}


async def _analyze_and_upsert(
    db: AsyncSession,
    user_id: str,
    date_str: str,
    questions: list[Question],
) -> None:
    """
    对单个用户执行分段压缩 + LLM 分析 + UPSERT 写入。

    私有函数，仅由 run_daily_analysis 调用。

    Args:
        db:        数据库会话
        user_id:   目标用户 ID
        date_str:  分析日期
        questions: 该用户当日的问答记录列表
    """
    chunk_size = settings.compression_chunk_size
    chunks = _chunk_questions(questions, chunk_size)

    # 多 chunk 时逐块分析，再合并摘要
    partial_texts: list[str] = []
    final_json: dict = {}

    for chunk in chunks:
        formatted = _format_questions(chunk)
        result = await llm_service.analyze(formatted)
        partial_texts.append(result.get("analysis_text", ""))
        # 最后一块的 analysis_json 作为最终结构（覆盖），通常 chunk 不超过 1-2 个
        if result.get("analysis_json"):
            final_json = result["analysis_json"]

    combined_text = "\n".join(filter(None, partial_texts))

    await _upsert_daily_analysis(
        db=db,
        user_id=user_id,
        date_str=date_str,
        analysis_text=combined_text,
        analysis_json=final_json or None,
    )


async def _upsert_daily_analysis(
    db: AsyncSession,
    user_id: str,
    date_str: str,
    analysis_text: str,
    analysis_json: dict | None,
) -> None:
    """
    UPSERT 写入 daily_analysis。
    """
    stmt = (
        pg_insert(DailyAnalysis)
        .values(
            user_id=user_id,
            date=date_str,
            analysis_text=analysis_text,
            analysis_json=analysis_json,
        )
        .on_conflict_do_update(
            constraint="uq_user_date",
            set_={
                "analysis_text": analysis_text,
                "analysis_json": analysis_json,
            },
        )
    )
    await db.execute(stmt)
    await db.flush()


# 教师端：查询每日分析列表
async def get_daily_analyses(
    db: AsyncSession,
    user_id: str,
    start_date: str,
    end_date: str,
) -> list[DailyAnalysis]:
    """
    查询指定用户在 [start_date, end_date] 区间内的每日分析记录。

    Args:
        db:         数据库会话
        user_id:    目标用户 ID
        start_date: 起始日期，格式 "YYYY-MM-DD"
        end_date:   结束日期，格式 "YYYY-MM-DD"

    Returns:
        DailyAnalysis 对象列表（按日期升序）
    """
    stmt = (
        select(DailyAnalysis)
        .where(
            and_(
                DailyAnalysis.user_id == user_id,
                DailyAnalysis.date >= start_date,
                DailyAnalysis.date <= end_date,
            )
        )
        .order_by(DailyAnalysis.date)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


# 教师端：生成完整报告
async def generate_report(db: AsyncSession, user_id: str) -> str:
    """
    汇总最近 max_report_days（默认30天）的每日分析，生成完整学习报告。

    Args:
        db:      数据库会话
        user_id: 目标用户 ID

    Returns:
        LLM 生成的汇总报告文本

    Raises:
        LLMServiceError: LLM 调用失败
        ValueError: 该用户无任何分析数据
    """
    # 计算时间窗口（最近 max_report_days 天）
    end_date = date.today()
    start_date = end_date - timedelta(days=settings.max_report_days - 1)

    rows = await get_daily_analyses(
        db,
        user_id=user_id,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
    )

    if not rows:
        raise ValueError(f"用户 {user_id} 在最近 {settings.max_report_days} 天内无分析数据")

    # 拼接所有分析文本
    summaries = "\n\n".join(
        f"【{row.date}】{row.analysis_text}" for row in rows
    )

    return await llm_service.summarize_report(summaries)


async def list_students(
    db: AsyncSession,
    limit: int,
    offset: int,
) -> list[User]:
    """
    获取学生列表（教师端使用）。

    Args:
        db:     数据库会话
        limit:  分页条数
        offset: 分页偏移

    Returns:
        User 对象列表（仅包含 role=student）
    """
    stmt = (
        select(User)
        .where(User.role == "student")
        .order_by(User.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_daily_analysis_with_usage(
    db: AsyncSession,
    user_id: str,
    start_date: str,
    end_date: str,
) -> list[dict]:
    """
    获取指定用户每日分析 + 当日各模型调用次数。

    Returns:
        列表元素结构：
        {
            "user_id": str,
            "date": str,
            "analysis_text": str,
            "analysis_json": dict | None,
            "model_usage": [{"model_id": str, "request_count": int}, ...]
        }
    """
    rows = await get_daily_analyses(
        db=db,
        user_id=user_id,
        start_date=start_date,
        end_date=end_date,
    )

    usage_stmt = (
        select(
            ModelUsageStat.date,
            ModelUsageStat.model_id,
            ModelUsageStat.request_count,
        )
        .where(
            and_(
                ModelUsageStat.user_id == user_id,
                ModelUsageStat.date >= start_date,
                ModelUsageStat.date <= end_date,
            )
        )
        .order_by(ModelUsageStat.date, ModelUsageStat.model_id)
    )
    usage_res = await db.execute(usage_stmt)
    usage_rows = usage_res.all()

    usage_map: dict[str, dict[str, int]] = {}
    for date_val, model_id, request_count in usage_rows:
        per_date = usage_map.setdefault(date_val, {})
        per_date[model_id] = per_date.get(model_id, 0) + int(request_count or 0)

    analysis_map = {r.date: r for r in rows}
    all_dates = sorted(set(usage_map.keys()) | set(analysis_map.keys()))

    result: list[dict] = []
    for date_key in all_dates:
        r = analysis_map.get(date_key)
        model_usage = [
            {"model_id": model_id, "request_count": count}
            for model_id, count in (usage_map.get(date_key) or {}).items()
        ]
        result.append(
            {
                "user_id": user_id,
                "date": date_key,
                "analysis_text": r.analysis_text if r else "",
                "analysis_json": r.analysis_json if r else None,
                "model_usage": model_usage,
            }
        )
    return result


async def _fetch_daily_questions(
    db: AsyncSession,
    date_str: str,
) -> dict[str, list[Question]]:
    """
    提取指定日期的编程问题，按 user_id 分组。
    """
    target_date = _parse_date(date_str)
    stmt = (
        select(Question)
        .where(
            and_(
                func.date(Question.created_at) == target_date,
                Question.is_programming == True,  # noqa: E712
            )
        )
        .order_by(Question.user_id, Question.created_at)
    )
    result = await db.execute(stmt)
    all_questions: list[Question] = list(result.scalars().all())

    user_question_map: dict[str, list[Question]] = {}
    for q in all_questions:
        user_question_map.setdefault(q.user_id, []).append(q)
    return user_question_map


async def run_daily_analysis_for_user(
    db: AsyncSession,
    user_id: str,
    date_str: str,
) -> dict:
    """
    为指定用户立即生成指定日期的每日分析。
    """
    target_date = _parse_date(date_str)
    stmt = (
        select(Question)
        .where(
            and_(
                Question.user_id == user_id,
                func.date(Question.created_at) == target_date,
                Question.is_programming == True,  # noqa: E712
            )
        )
        .order_by(Question.created_at)
    )
    result = await db.execute(stmt)
    questions: list[Question] = list(result.scalars().all())

    if not questions:
        return {"processed": False, "reason": "no_questions"}

    await _analyze_and_upsert(db, user_id, date_str, questions)
    return {"processed": True, "user_id": user_id, "date": date_str}


async def get_daily_analysis_by_date(
    db: AsyncSession,
    user_id: str,
    date_str: str,
) -> DailyAnalysis | None:
    """
    获取指定用户指定日期的日报结果。
    """
    stmt = (
        select(DailyAnalysis)
        .where(
            and_(
                DailyAnalysis.user_id == user_id,
                DailyAnalysis.date == date_str,
            )
        )
        .limit(1)
    )
    res = await db.execute(stmt)
    return res.scalars().first()


def _build_batch_messages(question_text: str) -> list[dict]:
    return [
        {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
        {"role": "user", "content": question_text},
    ]


async def submit_daily_analysis_batch(
    db: AsyncSession,
    date_str: str,
) -> dict:
    """
    构建 batch 输入并提交任务，写入批处理任务记录。
    """
    if not settings.batch_api_key:
        raise ValueError("BATCH_API_KEY 未配置，无法提交 batch 任务")

    user_question_map = await _fetch_daily_questions(db=db, date_str=date_str)
    if not user_question_map:
        return {"submitted": 0, "skipped": 0}

    lines: list[str] = []
    for user_id, questions in user_question_map.items():
        chunks = _chunk_questions(questions, settings.compression_chunk_size)
        for idx, chunk in enumerate(chunks):
            formatted = _format_questions(chunk)
            payload = {
                "custom_id": f"{user_id}|{idx}",
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": {
                    "model": settings.analysis_model,
                    "messages": _build_batch_messages(formatted),
                    "response_format": {"type": "json_object"},
                    "temperature": 0.3,
                    "stream": False,
                },
            }
            lines.append(json.dumps(payload, ensure_ascii=False))

    if not lines:
        return {"submitted": 0, "skipped": 0}

    batch_dir = Path(settings.log_dir) / "batch_inputs"
    batch_dir.mkdir(parents=True, exist_ok=True)
    file_path = batch_dir / f"daily_analysis_{date_str}.jsonl"
    file_path.write_text("\n".join(lines), encoding="utf-8")

    input_file_id = await batch_service.upload_batch_input(file_path)
    batch_obj = await batch_service.create_batch(
        input_file_id=input_file_id,
        model=settings.analysis_model,
        completion_window=settings.batch_completion_window,
        metadata={"date": date_str, "job": "daily_analysis"},
    )

    batch_id = batch_obj.get("id")
    status = batch_obj.get("status", "created")
    job = AnalysisBatchJob(
        date=date_str,
        status=status,
        batch_id=batch_id,
        input_file_id=input_file_id,
        output_file_id=batch_obj.get("output_file_id"),
        error_file_id=batch_obj.get("error_file_id"),
    )
    db.add(job)
    await db.flush()

    return {"submitted": len(lines), "skipped": 0, "batch_id": batch_id}


async def list_pending_batch_jobs(db: AsyncSession) -> list[AnalysisBatchJob]:
    """
    获取未完成的 batch 任务。
    """
    stmt = (
        select(AnalysisBatchJob)
        .where(AnalysisBatchJob.status.in_(
            ["validating", "in_queue", "in_progress", "finalizing", "created"]
        ))
        .order_by(AnalysisBatchJob.created_at.asc())
    )
    res = await db.execute(stmt)
    return list(res.scalars().all())


async def process_batch_job(
    db: AsyncSession,
    job: AnalysisBatchJob,
) -> None:
    """
    拉取 batch 状态并在完成时回写日报。
    """
    if not job.batch_id:
        job.status = "failed"
        await db.flush()
        return

    batch_info = await batch_service.retrieve_batch(job.batch_id)
    job.status = batch_info.get("status", job.status)
    job.output_file_id = batch_info.get("output_file_id") or job.output_file_id
    job.error_file_id = batch_info.get("error_file_id") or job.error_file_id
    await db.flush()

    if job.status != "completed" or not job.output_file_id:
        return

    content_bytes = await batch_service.download_file_content(job.output_file_id)
    try:
        content_text = content_bytes.decode("utf-8")
    except Exception:
        content_text = content_bytes.decode("utf-8", errors="ignore")

    # 聚合每个用户的分块结果
    user_parts: dict[str, list[tuple[int, str]]] = {}
    user_json: dict[str, dict] = {}

    for line in content_text.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("[batch] 输出解析失败: 非法 JSON 行")
            continue

        custom_id = row.get("custom_id", "")
        if not custom_id or "|" not in custom_id:
            continue
        user_id, chunk_idx_str = custom_id.split("|", 1)
        try:
            chunk_idx = int(chunk_idx_str)
        except ValueError:
            chunk_idx = 0

        if row.get("error"):
            logger.warning(f"[batch] 请求失败 custom_id={custom_id}: {row.get('error')}")
            continue

        resp = row.get("response", {})
        body = resp.get("body", {}) if isinstance(resp, dict) else {}
        choices = body.get("choices", [])
        if not choices:
            continue
        content = choices[0].get("message", {}).get("content", "") or "{}"

        try:
            result = json.loads(content)
        except json.JSONDecodeError:
            logger.warning(f"[batch] 解析 content 失败 custom_id={custom_id}")
            continue

        analysis_text = result.get("analysis_text", "")
        analysis_json = result.get("analysis_json") or None

        user_parts.setdefault(user_id, []).append((chunk_idx, analysis_text))
        if analysis_json:
            user_json[user_id] = analysis_json

    for user_id, parts in user_parts.items():
        combined_text = "\n".join(text for _, text in sorted(parts, key=lambda x: x[0]) if text)
        if not combined_text and user_id not in user_json:
            continue
        await _upsert_daily_analysis(
            db=db,
            user_id=user_id,
            date_str=job.date,
            analysis_text=combined_text,
            analysis_json=user_json.get(user_id),
        )


async def get_recent_student_model_usage(
    db: AsyncSession,
    limit: int = 10,
) -> list[ModelUsageStat]:
    """
    获取最近 10 名学生的模型使用记录（按日期倒序）。
    """
    latest_subq = (
        select(
            ModelUsageStat.user_id.label("user_id"),
            func.max(ModelUsageStat.date).label("max_date"),
        )
        .join(User, User.user_id == ModelUsageStat.user_id)
        .where(User.role == "student")
        .group_by(ModelUsageStat.user_id)
        .order_by(func.max(ModelUsageStat.date).desc())
        .limit(limit)
        .subquery()
    )

    stmt = (
        select(ModelUsageStat)
        .join(
            latest_subq,
            and_(
                ModelUsageStat.user_id == latest_subq.c.user_id,
                ModelUsageStat.date == latest_subq.c.max_date,
            ),
        )
        .order_by(ModelUsageStat.date.desc(), ModelUsageStat.user_id)
    )
    res = await db.execute(stmt)
    return list(res.scalars().all())


def _parse_date(date_str: str) -> date:
    return datetime.strptime(date_str, "%Y-%m-%d").date()


async def get_model_usage_timeseries(
    db: AsyncSession,
    start_date: str,
    end_date: str,
) -> list[dict]:
    """
    获取模型使用量时间序列（按日）。
    """
    stmt = (
        select(
            ModelUsageStat.date,
            ModelUsageStat.model_id,
            func.sum(ModelUsageStat.request_count).label("request_count"),
            func.sum(ModelUsageStat.total_tokens).label("total_tokens"),
        )
        .join(User, User.user_id == ModelUsageStat.user_id)
        .where(
            and_(
                User.role == "student",
                ModelUsageStat.date >= start_date,
                ModelUsageStat.date <= end_date,
            )
        )
        .group_by(ModelUsageStat.date, ModelUsageStat.model_id)
        .order_by(ModelUsageStat.date, ModelUsageStat.model_id)
    )
    res = await db.execute(stmt)
    rows = res.all()
    return [
        {
            "date": r.date,
            "model_id": r.model_id,
            "request_count": int(r.request_count or 0),
            "total_tokens": int(r.total_tokens or 0),
        }
        for r in rows
    ]


def _period_range(anchor: date, period: str) -> tuple[date, date]:
    if period == "day":
        return anchor, anchor
    if period == "week":
        start = anchor - timedelta(days=anchor.weekday())
        end = start + timedelta(days=6)
        return start, end
    if period == "month":
        start = anchor.replace(day=1)
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1) - timedelta(days=1)
        else:
            end = start.replace(month=start.month + 1) - timedelta(days=1)
        return start, end
    raise ValueError("invalid period")


async def get_model_usage_rank(
    db: AsyncSession,
    period: str,
    anchor_date: str,
    limit: int = 20,
) -> list[dict]:
    """
    获取模型使用排名（含上一周期变化量）。
    """
    anchor = _parse_date(anchor_date)
    cur_start, cur_end = _period_range(anchor, period)
    prev_end = cur_start - timedelta(days=1)
    prev_start, prev_end = _period_range(prev_end, period)

    stmt = (
        select(
            ModelUsageStat.date,
            ModelUsageStat.model_id,
            func.sum(ModelUsageStat.request_count).label("request_count"),
            func.sum(ModelUsageStat.total_tokens).label("total_tokens"),
        )
        .join(User, User.user_id == ModelUsageStat.user_id)
        .where(
            and_(
                User.role == "student",
                ModelUsageStat.date >= prev_start.isoformat(),
                ModelUsageStat.date <= cur_end.isoformat(),
            )
        )
        .group_by(ModelUsageStat.date, ModelUsageStat.model_id)
    )
    res = await db.execute(stmt)
    rows = res.all()

    cur_map: dict[str, dict[str, int]] = {}
    prev_map: dict[str, dict[str, int]] = {}

    for r in rows:
        date_val = _parse_date(r.date)
        target = cur_map if cur_start <= date_val <= cur_end else prev_map
        model = r.model_id
        bucket = target.setdefault(model, {"request_count": 0, "total_tokens": 0})
        bucket["request_count"] += int(r.request_count or 0)
        bucket["total_tokens"] += int(r.total_tokens or 0)

    items: list[dict] = []
    for model_id, cur in cur_map.items():
        prev = prev_map.get(model_id, {"request_count": 0, "total_tokens": 0})
        items.append(
            {
                "model_id": model_id,
                "request_count": cur["request_count"],
                "total_tokens": cur["total_tokens"],
                "delta_request_count": cur["request_count"] - prev["request_count"],
                "delta_total_tokens": cur["total_tokens"] - prev["total_tokens"],
            }
        )

    items.sort(key=lambda x: x["total_tokens"], reverse=True)
    return items[:limit]


def _period_key(d: date, period: str) -> str:
    if period == "day":
        return d.isoformat()
    if period == "week":
        start = d - timedelta(days=d.weekday())
        return start.isoformat()
    if period == "month":
        return d.replace(day=1).isoformat()
    raise ValueError("invalid period")


async def get_active_users(
    db: AsyncSession,
    start_date: str,
    end_date: str,
    period: str,
) -> list[dict]:
    """
    获取活跃学生数（日/周/月）。
    """
    stmt = (
        select(ModelUsageStat.date, ModelUsageStat.user_id)
        .join(User, User.user_id == ModelUsageStat.user_id)
        .where(
            and_(
                User.role == "student",
                ModelUsageStat.date >= start_date,
                ModelUsageStat.date <= end_date,
            )
        )
        .group_by(ModelUsageStat.date, ModelUsageStat.user_id)
        .order_by(ModelUsageStat.date)
    )
    res = await db.execute(stmt)
    rows = res.all()

    buckets: dict[str, set[str]] = {}
    for date_str, user_id in rows:
        key = _period_key(_parse_date(date_str), period)
        buckets.setdefault(key, set()).add(user_id)

    return [
        {"period": key, "active_users": len(users)}
        for key, users in sorted(buckets.items())
    ]


async def get_model_error_trend(
    db: AsyncSession,
    start_date: str,
    end_date: str,
) -> list[dict]:
    """
    获取每模型错误率趋势（按日）。
    """
    stmt = (
        select(
            ModelUsageStat.date,
            ModelUsageStat.model_id,
            func.sum(ModelUsageStat.error_count).label("error_count"),
            func.sum(ModelUsageStat.request_count).label("request_count"),
        )
        .join(User, User.user_id == ModelUsageStat.user_id)
        .where(
            and_(
                User.role == "student",
                ModelUsageStat.date >= start_date,
                ModelUsageStat.date <= end_date,
            )
        )
        .group_by(ModelUsageStat.date, ModelUsageStat.model_id)
        .order_by(ModelUsageStat.date, ModelUsageStat.model_id)
    )
    res = await db.execute(stmt)
    rows = res.all()
    data: list[dict] = []
    for r in rows:
        req = int(r.request_count or 0)
        err = int(r.error_count or 0)
        rate = (err / req) if req > 0 else 0.0
        data.append(
            {
                "date": r.date,
                "model_id": r.model_id,
                "error_count": err,
                "request_count": req,
                "error_rate": rate,
            }
        )
    return data


async def get_model_latency_trend(
    db: AsyncSession,
    start_date: str,
    end_date: str,
) -> list[dict]:
    """
    获取每模型平均响应时延趋势（按日）。
    """
    stmt = (
        select(
            ModelUsageStat.date,
            ModelUsageStat.model_id,
            func.sum(ModelUsageStat.total_latency_ms).label("total_latency_ms"),
            func.sum(ModelUsageStat.request_count).label("request_count"),
        )
        .join(User, User.user_id == ModelUsageStat.user_id)
        .where(
            and_(
                User.role == "student",
                ModelUsageStat.date >= start_date,
                ModelUsageStat.date <= end_date,
            )
        )
        .group_by(ModelUsageStat.date, ModelUsageStat.model_id)
        .order_by(ModelUsageStat.date, ModelUsageStat.model_id)
    )
    res = await db.execute(stmt)
    rows = res.all()
    data: list[dict] = []
    for r in rows:
        req = int(r.request_count or 0)
        total = int(r.total_latency_ms or 0)
        avg = (total / req) if req > 0 else 0.0
        data.append(
            {
                "date": r.date,
                "model_id": r.model_id,
                "total_latency_ms": total,
                "request_count": req,
                "avg_latency_ms": avg,
            }
        )
    return data
