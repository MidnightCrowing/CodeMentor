from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.models import ModelUsageStat, Question, Session
from app.services import llm_service
from app.services.llm_service import LLMServiceError
from app.utils.sse_utils import format_sse as _sse
from app.utils.text_utils import remove_think_tags

logger = logging.getLogger(__name__)


NON_PROGRAMMING_ANSWER = (
    "抱歉，我是专门解答编程和技术问题的助教，暂时无法回答非编程类问题。"
    "请尽量提问与代码、算法、软件开发或调试相关的内容。"
)


def _chat_log_context(
    *,
    user_id: str,
    session_id: str | None,
    dialog_id: uuid.UUID | None,
    model_id: str | None,
    message: str,
) -> str:
    return (
        f"用户ID={user_id} 会话ID={session_id or '新会话'} 对话ID={dialog_id or '无'} "
        f"模型={model_id or settings.chat_model} 提问长度={len(message)}"
    )


async def chat_stream_generator(
    user_id: str,
    session_id: str | None,
    dialog_id: uuid.UUID | None,
    message: str,
    enable_thinking: bool,
    model_id: str | None,
    db: AsyncSession,
) -> AsyncGenerator[str, None]:
    target_session_id = session_id
    history: list[dict] = []
    title_task = None

    async def _get_owned_session() -> Session | None:
        if not target_session_id:
            return None
        stmt_session = select(Session).where(
            Session.id == target_session_id,
            Session.user_id == user_id,
        )
        result_sess = await db.execute(stmt_session)
        return result_sess.scalars().first()

    from sqlalchemy import update

    if dialog_id and target_session_id:
        existing_session = await _get_owned_session()
        if not existing_session:
            yield _sse("error", message="会话不存在或无权访问")
            return

        target_q = await db.scalar(
            select(Question).where(
                Question.id == dialog_id,
                Question.session_id == target_session_id,
                Question.user_id == user_id,
            )
        )
        if target_q:
            stmt_del = (
                update(Question)
                .where(Question.session_id == target_session_id)
                .where(Question.user_id == user_id)
                .where(Question.created_at >= target_q.created_at)
                .values(is_deleted=True)
            )
            await db.execute(stmt_del)
            await db.flush()

    if not target_session_id:
        target_session_id = str(uuid.uuid4())
        new_session = Session(id=target_session_id, user_id=user_id)
        db.add(new_session)
        await db.flush()
        title_task = asyncio.create_task(llm_service.generate_session_title(message))
    else:
        existing_session = await _get_owned_session()
        if not existing_session:
            yield _sse("error", message="会话不存在或无权访问")
            return

        stmt_history = (
            select(Question)
            .where(Question.session_id == target_session_id)
            .where(Question.user_id == user_id)
            .where(Question.is_deleted == False)
            .order_by(Question.created_at.desc())
            .limit(settings.context_message_limit)
        )
        result_hist = await db.execute(stmt_history)
        questions = result_hist.scalars().all()
        for q in reversed(questions):
            history.append({"role": "user", "content": q.question})
            history.append({"role": "assistant", "content": remove_think_tags(q.answer)})

    try:
        is_programming = await llm_service.classify(message)
    except LLMServiceError as exc:
        logger.warning(
            "问题分类失败: %s 错误=%s",
            _chat_log_context(
                user_id=user_id,
                session_id=target_session_id,
                dialog_id=dialog_id,
                model_id=model_id,
                message=message,
            ),
            exc,
        )
        yield _sse("error", message=str(exc))
        return

    if not is_programming:
        if title_task:
            session_title = await title_task
            db_sess = await db.scalar(
                select(Session).where(
                    Session.id == target_session_id,
                    Session.user_id == user_id,
                )
            )
            if db_sess:
                db_sess.title = session_title
                await db.flush()
            yield _sse("session_meta", session_id=target_session_id, title=session_title)

        yield _sse("content", data=NON_PROGRAMMING_ANSWER)
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

    full_answer_parts: list[str] = []
    reasoning_parts: list[str] = []
    usage_info: dict | None = None
    chat_start_time = time.perf_counter()

    try:
        title_sent = False

        async for chunk_type, chunk_data, usage in llm_service.chat_stream(
            message,
            history=history,
            enable_thinking=enable_thinking,
            model_id=model_id,
        ):
            if title_task and not title_sent and title_task.done():
                session_title = title_task.result()
                stmt_update = select(Session).where(
                    Session.id == target_session_id,
                    Session.user_id == user_id,
                )
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
                usage_info = usage

        if title_task and not title_sent:
            session_title = await title_task
            stmt_update = select(Session).where(
                Session.id == target_session_id,
                Session.user_id == user_id,
            )
            res_upd = await db.execute(stmt_update)
            db_sess = res_upd.scalars().first()
            if db_sess:
                db_sess.title = session_title
                await db.flush()
            yield _sse("session_meta", session_id=target_session_id, title=session_title)

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

    except LLMServiceError as exc:
        chat_latency_ms = int((time.perf_counter() - chat_start_time) * 1000)
        actual_model = usage_info.get("model") if usage_info else (model_id or settings.chat_model)
        logger.warning(
            "聊天流式调用失败: %s 实际模型=%s 延迟毫秒=%s 错误=%s",
            _chat_log_context(
                user_id=user_id,
                session_id=target_session_id,
                dialog_id=dialog_id,
                model_id=model_id,
                message=message,
            ),
            actual_model,
            chat_latency_ms,
            exc,
        )
        yield _sse("error", message=str(exc))
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

    except asyncio.CancelledError:
        actual_model = usage_info.get("model") if usage_info else (model_id or settings.chat_model)
        logger.info(
            "聊天请求被取消: %s 实际模型=%s",
            _chat_log_context(
                user_id=user_id,
                session_id=target_session_id,
                dialog_id=dialog_id,
                model_id=model_id,
                message=message,
            ),
            actual_model,
        )
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
            answer=full_answer + "\n\n[回答已被用户中断]",
            is_programming=True,
            model=usage_info.get("model") if usage_info else None,
            tokens=usage_info.get("total_tokens") if usage_info else None,
        )

        chat_latency_ms = int((time.perf_counter() - chat_start_time) * 1000)
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
        raise


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
        },
    )
    await db.execute(stmt)
    await db.flush()


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
    await db.flush()
    return record
