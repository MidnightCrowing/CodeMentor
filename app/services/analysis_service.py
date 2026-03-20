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

from datetime import date, timedelta

from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.models import DailyAnalysis, Question
from app.services import llm_service
from app.services.llm_service import LLMServiceError


# ── 私有：问答数据格式化 ──────────────────────────────────────
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


# ── 私有：分块压缩 ────────────────────────────────────────────
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


# ── 每日分析主函数（由定时器调用）────────────────────────────
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
    stmt = (
        select(Question)
        .where(
            and_(
                Question.created_at.cast(type_=None).cast("date")  # 转成 DATE 比对
                == date_str,
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

    # UPSERT：同一用户同一天只保留一条，冲突时覆盖
    stmt = (
        pg_insert(DailyAnalysis)
        .values(
            user_id=user_id,
            date=date_str,
            analysis_text=combined_text,
            analysis_json=final_json or None,
        )
        .on_conflict_do_update(
            constraint="uq_user_date",
            set_={
                "analysis_text": combined_text,
                "analysis_json": final_json or None,
            },
        )
    )
    await db.execute(stmt)
    await db.flush()


# ── 教师端：查询每日分析列表 ─────────────────────────────────
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


# ── 教师端：生成完整报告 ──────────────────────────────────────
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
