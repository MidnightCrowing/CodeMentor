"""
api/v1/endpoints/chat.py
========================
/api/v1/chat 和 /api/v1/questions 路由实现。

端点：
- POST /chat: 流式对话（SSE），编排前置分类与流式回答
- GET  /questions: 查询问答历史记录（支持分页）
"""

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.config import settings
from app.models.models import Question
from app.schemas.base import BaseResponse
from app.schemas.chat_schema import ChatRequest, QuestionOut
from app.services.chat_service import chat_stream_generator

router = APIRouter()


@router.get("/models")
async def get_models():
    """
    获取后台配置的可用模型列表。
    """
    return BaseResponse.ok(settings.available_models)


@router.post("/chat")
async def chat(
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    流式对话接口。

    响应类型: text/event-stream
    格式见 chat_service.py 的 SSE 规范说明。
    """
    if body.model_id:
        valid_model_ids = {m["id"] for m in settings.available_models}
        if body.model_id not in valid_model_ids:
            return BaseResponse.error(f"不支持的模型 ID: {body.model_id}")

    generator = chat_stream_generator(
        user_id=body.user_id,
        session_id=body.session_id,
        message=body.message,
        enable_thinking=body.enable_thinking,
        model_id=body.model_id,
        db=db,
    )
    return StreamingResponse(generator, media_type="text/event-stream")


@router.get("/questions", response_model=BaseResponse[list[QuestionOut]])
async def get_questions(
    user_id: str = Query(..., description="查询目标的用户 ID"),
    limit: int = Query(20, ge=1, le=100, description="每页返回条数"),
    offset: int = Query(0, ge=0, description="分页偏移量"),
    db: AsyncSession = Depends(get_db),
):
    """
    查询历史问答记录。

    支持分页（limit / offset）。
    返回该用户全部问答（包含非编程拒答记录）。
    """
    stmt = (
        select(Question)
        .where(Question.user_id == user_id)
        .order_by(Question.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    questions = result.scalars().all()
    data = [QuestionOut.model_validate(q) for q in questions]
    return BaseResponse.ok(data)
