import asyncio
import json
import uuid
from collections.abc import AsyncGenerator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.models import Question, Session
from app.models.models import Question, Session, ModelUsageStat
from sqlalchemy.dialects.postgresql import insert
import time
from datetime import datetime, timezone

from app.services import llm_service
from app.utils.sse_utils import format_sse as _sse
from app.utils.text_utils import remove_think_tags
from app.services.llm_service import LLMServiceError


# 固定拒答提示
NON_PROGRAMMING_ANSWER = (
    "抱歉，我是专门解答编程和技术问题的助教，无法回答非编程类的问题。"
    "请提问与代码、算法或软件开发相关的内容"
)


# 核心流式生成器
async def chat_stream_generator(
    user_id: str,
    session_id: str | None,
    dialog_id: uuid.UUID | None,
    message: str,
    enable_thinking: bool,
    model_id: str | None,
    db: AsyncSession,
) -> AsyncGenerator[str, None]:
    """
    聊天流式响应的完整编排生成器。

    供 FastAPI 路由 StreamingResponse 使用。
    生成器结束时，问答记录已写入数据库。

    Args:
        user_id:    用户 ID
        session_id: 会话 ID
        message:    学生的提问内容
        db:         AsyncSession（由路由层依赖注入传入）

    Yields:
        SSE 格式化字符串（标准 JSON SSE）

    Raises 不会向外传播异常，所有错误均以 SSE error 事件返回。
    """

    # Step 1: 会话和历史记录处理
    # ======================================================
    target_session_id = session_id
    history = []
    title_task = None

    from sqlalchemy import update
    if dialog_id and target_session_id:
        target_q = await db.scalar(select(Question).where(Question.id == dialog_id, Question.session_id == target_session_id))
        if target_q:
            stmt_del = (
                update(Question)
                .where(Question.session_id == target_session_id)
                .where(Question.created_at >= target_q.created_at)
                .values(is_deleted=True)
            )
            await db.execute(stmt_del)
            await db.flush()

    if not target_session_id:
        # 新建会话
        target_session_id = str(uuid.uuid4())
        new_session = Session(id=target_session_id, user_id=user_id)
        db.add(new_session)
        await db.flush()
        # 后台生成标题
        title_task = asyncio.create_task(llm_service.generate_session_title(message))
    else:
        # 校验会话
        stmt_session = select(Session).where(Session.id == target_session_id)
        result_sess = await db.execute(stmt_session)
        existing_session = result_sess.scalars().first()
        if not existing_session:
            yield _sse("error", message=f"会话不存在或已失效: {target_session_id}")
            return

        # 加载历史
        stmt_history = (
            select(Question)
            .where(Question.session_id == target_session_id)
            .where(Question.is_deleted == False)
            .order_by(Question.created_at.desc())
            .limit(settings.context_message_limit)
        )
        result_hist = await db.execute(stmt_history)
        questions = result_hist.scalars().all()
        # 按时间顺序（旧 -> 新）组装
        for q in reversed(questions):
            history.append({"role": "user", "content": q.question})
            history.append({"role": "assistant", "content": remove_think_tags(q.answer)})
    # ======================================================

    # Step 2: 前置分类
    try:
        is_programming = await llm_service.classify(message)
    except LLMServiceError as e:
        yield _sse("error", message=str(e))
        return

    # Step 3: 非编程问题 → 直接返回固定拒答
    if not is_programming:
        if title_task:
            session_title = await title_task
            db_sess = await db.scalar(select(Session).where(Session.id == target_session_id))
            if db_sess:
                db_sess.title = session_title
                await db.flush()
            yield _sse("session_meta", session_id=target_session_id, title=session_title)

        yield _sse("content", data=NON_PROGRAMMING_ANSWER)

        # 将记录写入数据库（is_programming=False），此时 target_session_id 必定有效
        saved_record = await _save_question(
            db=db,
            user_id=user_id,
            session_id=target_session_id,
            question=message,
            answer=NON_PROGRAMMING_ANSWER,
            is_programming=False,
            model=None,
            tokens=None,
        )
        yield _sse("done", dialog_id=str(saved_record.id))
        return
    # Step 3: 编程问题 → 流式回答
    full_answer_parts: list[str] = []
    reasoning_parts: list[str] = []
    usage_info: dict | None = None
    chat_start_time = time.perf_counter()

    try:
        session_title = None
        title_sent = False

        async for chunk_type, chunk_data, usage in llm_service.chat_stream(
            message,
            history=history,
            enable_thinking=enable_thinking,
            model_id=model_id,
        ):
            # 【新增逻辑】：一旦标题生成完成，立即在这发一条独立的 SSE，提前抛出
            if title_task and not title_sent and title_task.done():
                session_title = title_task.result()
                stmt_update = select(Session).where(Session.id == target_session_id)
                res_upd = await db.execute(stmt_update)
                db_sess = res_upd.scalars().first()
                if db_sess:
                    db_sess.title = session_title
                    await db.flush()
                yield _sse("session_meta", session_id=target_session_id, title=session_title)
                title_sent = True

            if chunk_type == "content" and chunk_data:
                full_answer_parts.append(chunk_data)
                yield _sse("content", data=chunk_data)
            elif chunk_type == "reasoning" and chunk_data:
                reasoning_parts.append(chunk_data)
                yield _sse("reasoning", data=chunk_data)
            elif chunk_type == "done" and usage:
                # 最后一块，携带 usage 信息
                usage_info = usage

        # 【兜底】：如果聊天非常简短，循环结束前标题任务仍未出结果，此处等它执行完并发出
        if title_task and not title_sent:
            session_title = await title_task
            stmt_update = select(Session).where(Session.id == target_session_id)
            res_upd = await db.execute(stmt_update)
            db_sess = res_upd.scalars().first()
            if db_sess:
                db_sess.title = session_title
                await db.flush()
            yield _sse("session_meta", session_id=target_session_id, title=session_title)
            title_sent = True

        # done 前落库
        answer_text = "".join(full_answer_parts)
        if reasoning_parts:
            reasoning_text = "".join(reasoning_parts)
            full_answer = f"<think>\n{reasoning_text}\n</think>\n\n{answer_text}"
        else:
            full_answer = answer_text

        saved_record = await _save_question(
            db=db,
            user_id=user_id,
            session_id=target_session_id,
            question=message,
            answer=full_answer,
            is_programming=True,
            model=usage_info.get("model") if usage_info else None,
            tokens=usage_info.get("total_tokens") if usage_info else None,
        )

        chat_latency_ms = int((time.perf_counter() - chat_start_time) * 1000)
        actual_model = usage_info.get("model") if usage_info else (model_id or settings.chat_model)
        await _upsert_model_usage(
            db=db,
            user_id=user_id,
            model_id=actual_model,
            prompt_tokens=usage_info.get("prompt_tokens", 0) if usage_info else 0,
            completion_tokens=usage_info.get("completion_tokens", 0) if usage_info else 0,
            total_tokens=usage_info.get("total_tokens", 0) if usage_info else 0,
            latency_ms=chat_latency_ms,
            is_error=False,
        )

        yield _sse("done", dialog_id=str(saved_record.id))

    except LLMServiceError as e:
        yield _sse("error", message=str(e))
        # 流中断，仍尝试保存已收到的部分（如有）
        if not full_answer_parts and not reasoning_parts:
            return
        
        answer_text = "".join(full_answer_parts)
        if reasoning_parts:
            reasoning_text = "".join(reasoning_parts)
            full_answer = f"<think>\n{reasoning_text}\n</think>\n\n{answer_text}"
        else:
            full_answer = answer_text
            
        await _save_question(
            db=db,
            user_id=user_id,
            session_id=target_session_id,
            question=message,
            answer=full_answer,
            is_programming=True,
            model=usage_info.get("model") if usage_info else None,
            tokens=usage_info.get("total_tokens") if usage_info else None,
        )
        
        # 记录失败指标
        chat_latency_ms = int((time.perf_counter() - chat_start_time) * 1000)
        actual_model = usage_info.get("model") if usage_info else (model_id or settings.chat_model)
        await _upsert_model_usage(
            db=db,
            user_id=user_id,
            model_id=actual_model,
            prompt_tokens=usage_info.get("prompt_tokens", 0) if usage_info else 0,
            completion_tokens=usage_info.get("completion_tokens", 0) if usage_info else 0,
            total_tokens=usage_info.get("total_tokens", 0) if usage_info else 0,
            latency_ms=chat_latency_ms,
            is_error=True,
        )

    except asyncio.CancelledError:
        # 客户端（前端）主动断开连接 / 点击了停止生成
        # 我们依然需要把已经生成的半截内容落库，并记录 Token 消耗
        answer_text = "".join(full_answer_parts)
        if reasoning_parts:
            reasoning_text = "".join(reasoning_parts)
            full_answer = f"<think>\n{reasoning_text}\n</think>\n\n{answer_text}"
        else:
            full_answer = answer_text
            
        await _save_question(
            db=db,
            user_id=user_id,
            session_id=target_session_id,
            question=message,
            answer=full_answer + "\n\n[回答被用户中断]",
            is_programming=True,
            model=usage_info.get("model") if usage_info else None,
            tokens=usage_info.get("total_tokens") if usage_info else None,
        )
        
        chat_latency_ms = int((time.perf_counter() - chat_start_time) * 1000)
        actual_model = usage_info.get("model") if usage_info else (model_id or settings.chat_model)
        await _upsert_model_usage(
            db=db,
            user_id=user_id,
            model_id=actual_model,
            prompt_tokens=usage_info.get("prompt_tokens", 0) if usage_info else 0,
            completion_tokens=usage_info.get("completion_tokens", 0) if usage_info else 0,
            total_tokens=usage_info.get("total_tokens", 0) if usage_info else 0,
            latency_ms=chat_latency_ms,
            is_error=False,
        )
        raise  # 必须重新抛出 CancelledError 遵守 asyncio 的底线规范



async def _upsert_model_usage(
    db: AsyncSession,
    user_id: str,
    model_id: str,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    latency_ms: int,
    is_error: bool,
):
    """通过 PostgreSQL 无冲突高并发更新"""
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    stmt = insert(ModelUsageStat).values(
        date=date_str,
        user_id=user_id,
        model_id=model_id,
        request_count=1,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        total_latency_ms=latency_ms,
        error_count=1 if is_error else 0,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_usage_stat_dim",
        set_={
            "request_count": ModelUsageStat.request_count + 1,
            "prompt_tokens": ModelUsageStat.prompt_tokens + prompt_tokens,
            "completion_tokens": ModelUsageStat.completion_tokens + completion_tokens,
            "total_tokens": ModelUsageStat.total_tokens + total_tokens,
            "total_latency_ms": ModelUsageStat.total_latency_ms + latency_ms,
            "error_count": ModelUsageStat.error_count + (1 if is_error else 0),
        }
    )
    await db.execute(stmt)
    await db.flush()

# 数据库写入（私有）
async def _save_question(
    db: AsyncSession,
    user_id: str,
    session_id: str,
    question: str,
    answer: str,
    is_programming: bool,
    model: str | None,
    tokens: int | None,
) -> Question:
    """
    将一条问答记录持久化到 questions 表。

    Args:
        db:             数据库会话
        user_id:        学生 ID
        session_id:     会话 ID
        question:       学生提问
        answer:         AI 回答（或固定拒答文本）
        is_programming: 分类结果
        model:          使用的模型 ID（可能为 None）
        tokens:         消耗的 token 数（可能为 None）

    Returns:
        已落库的 Question 对象
    """
    record = Question(
        user_id=user_id,
        session_id=session_id,
        question=question,
        answer=answer,
        is_programming=is_programming,
        model=model,
        tokens=tokens,
    )
    db.add(record)
    await db.flush()  # 让 ORM 分配 id，commit 由依赖注入的会话生命周期统一处理
    return record
