"""
services/chat_service.py
========================
聊天业务编排层。

职责：
- 编排 /api/v1/chat 接口的完整流程：
  1. 调用 llm_service.classify() 前置分类
  2. 若非编程 → 生成固定拒答 SSE 事件流
  3. 若编程 → 调用 llm_service.chat_stream() 生成流式回答
  4. 收集完整回答后，将问答异步写入 questions 表
- 将 SSE 事件格式化为标准 JSON SSE 字符串

SSE 消息格式（与前端约定）：
    data: {"type": "content", "data": "文字块"}
    data: {"type": "done"}
    data: {"type": "error", "message": "错误信息"}

测试入口：tests/test_chat_service.py
"""

import json
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Question
from app.services import llm_service
from app.services.llm_service import LLMServiceError


# 固定拒答提示
NON_PROGRAMMING_ANSWER = (
    "抱歉，我是专门解答编程和技术问题的助教，无法回答非编程类的问题。"
    "请提问与代码、算法或软件开发相关的内容 😊"
)


# SSE 格式化工具
def _sse(type_: str, **kwargs) -> str:
    """
    格式化单条 SSE 消息。

    Args:
        type_:  消息类型，"content" / "done" / "error"
        **kwargs: 附加字段（如 data=, message=）

    Returns:
        符合 SSE 协议的字符串，如：
            data: {"type": "content", "data": "xxx"}\n\n
    """
    payload = {"type": type_, **kwargs}
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


# 核心流式生成器
async def chat_stream_generator(
    user_id: str,
    session_id: str,
    message: str,
    enable_thinking: bool,
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

    # Step 1: 前置分类
    try:
        is_programming = await llm_service.classify(message)
    except LLMServiceError as e:
        yield _sse("error", message=str(e))
        return

    # Step 2: 非编程问题 → 直接返回固定拒答
    if not is_programming:
        yield _sse("content", data=NON_PROGRAMMING_ANSWER)
        yield _sse("done")
        # 仍然将记录写入数据库（is_programming=False）
        await _save_question(
            db=db,
            user_id=user_id,
            session_id=session_id,
            question=message,
            answer=NON_PROGRAMMING_ANSWER,
            is_programming=False,
            model=None,
            tokens=None,
        )
        return

    # Step 3: 编程问题 → 流式回答
    full_answer_parts: list[str] = []
    reasoning_parts: list[str] = []
    usage_info: dict | None = None

    try:
        async for chunk_type, chunk_data, usage in llm_service.chat_stream(message, enable_thinking=enable_thinking):
            if chunk_type == "content" and chunk_data:
                full_answer_parts.append(chunk_data)
                yield _sse("content", data=chunk_data)
            elif chunk_type == "reasoning" and chunk_data:
                reasoning_parts.append(chunk_data)
                yield _sse("reasoning", data=chunk_data)
            elif chunk_type == "done" and usage:
                # 最后一块，携带 usage 信息
                usage_info = usage

        yield _sse("done")

    except LLMServiceError as e:
        yield _sse("error", message=str(e))
        # 流中断，仍尝试保存已收到的部分（如有）
        if not full_answer_parts and not reasoning_parts:
            return

    # Step 4: 写入数据库
    answer_text = "".join(full_answer_parts)
    if reasoning_parts:
        reasoning_text = "".join(reasoning_parts)
        full_answer = f"<think>\n{reasoning_text}\n</think>\n\n{answer_text}"
    else:
        full_answer = answer_text

    await _save_question(
        db=db,
        user_id=user_id,
        session_id=session_id,
        question=message,
        answer=full_answer,
        is_programming=True,
        model=usage_info.get("model") if usage_info else None,
        tokens=usage_info.get("total_tokens") if usage_info else None,
    )


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
