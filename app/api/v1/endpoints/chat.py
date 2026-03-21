"""
api/v1/endpoints/chat.py
========================
/api/v1/chat 和 /api/v1/questions 路由实现。

端点：
- POST /chat: 流式对话（SSE），编排前置分类与流式回答
- GET  /questions: 查询问答历史记录（支持分页）
"""

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, check_user_permission
from app.core.config import settings
from app.core.limiter import limiter
from app.models.models import Question, Session
from app.schemas.base import BaseResponse
from app.schemas.chat_schema import ChatRequest, QuestionOut, SessionOut, SessionRenameRequest
from app.services.chat_service import chat_stream_generator

router = APIRouter()


@router.get("/models")
async def get_models():
    """
    获取后台配置的可用模型列表。
    """
    return BaseResponse.ok(settings.available_models)


@router.get("/sessions", response_model=BaseResponse[list[SessionOut]])
async def get_sessions(
    user_id: str = Query(..., description="查询目标的用户 ID"),
    limit: int = Query(20, ge=1, le=100, description="默认20条"),
    offset: int = Query(0, ge=0, description="分页参数"),
    db: AsyncSession = Depends(get_db),
):
    """
    查询历史会话列表。
    """
    await check_user_permission(user_id, db, "student")
    stmt = (
        select(Session)
        .where(Session.user_id == user_id)
        .order_by(Session.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    res = await db.execute(stmt)
    data = [SessionOut.model_validate(s) for s in res.scalars().all()]
    return BaseResponse.ok(data)


@router.delete("/sessions/batch", response_model=BaseResponse)
async def delete_sessions_batch(
    days: int = Query(..., ge=0, description="删除多少天前的会话"),
    user_id: str = Query(..., description="操作所属用户 ID，防止越权"),
    db: AsyncSession = Depends(get_db),
):
    """
    批量删除指定天数之前的历史会话。
    （注：会话头将物理删除，而详细问答会被标记为离线归档不会被前端查询到）
    """
    await check_user_permission(user_id, db, "student")
    
    from datetime import datetime, timezone, timedelta
    cutoff_time = datetime.now(timezone.utc) - timedelta(days=days)

    stmt_sess = select(Session.id).where(Session.user_id == user_id, Session.created_at <= cutoff_time)
    res_sess = await db.execute(stmt_sess)
    session_ids = res_sess.scalars().all()
    
    if not session_ids:
        return BaseResponse.ok("没有满足条件的会话可删除")

    from sqlalchemy import delete, update
    # 物理删除满足条件的会话
    await db.execute(delete(Session).where(Session.id.in_(session_ids)))

    # 逻辑删除名下所有问题记录
    await db.execute(
        update(Question)
        .where(Question.session_id.in_(session_ids))
        .values(is_deleted=True)
    )

    await db.commit()
    return BaseResponse.ok(f"成功删除 {len(session_ids)} 个历史会话")


@router.delete("/sessions/{session_id}", response_model=BaseResponse)
async def delete_session(
    session_id: str,
    user_id: str = Query(..., description="操作所属用户 ID，防止越权"),
    db: AsyncSession = Depends(get_db),
):
    """
    删除指定的会话以及其中的聊天详情。
    （注：为了历史学习分析的完整性，详细问答会被标记为离线归档，而会话头将物理删除）
    """
    # 1. 查询会话校验权限
    await check_user_permission(user_id, db, "student")
    stmt_sess = select(Session).where(Session.id == session_id, Session.user_id == user_id)
    res_sess = await db.execute(stmt_sess)
    sess_obj = res_sess.scalars().first()
    if not sess_obj:
        return BaseResponse.error("该会话不存在或无权删除")

    # 2. 从 Session 列表移除
    from sqlalchemy import delete, update
    await db.execute(delete(Session).where(Session.id == session_id))

    # 3. 将其下挂载的全部 Question 置为已回收状态（保证下一次离线报表读取统计但界面前端不可见）
    await db.execute(
        update(Question)
        .where(Question.session_id == session_id)
        .values(is_deleted=True)
    )

    await db.commit()
    return BaseResponse.ok("会话删除成功")


@router.patch("/sessions/{session_id}/title", response_model=BaseResponse)
async def rename_session(
    session_id: str,
    body: SessionRenameRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    修改指定历史会话的标题，带长度限制。
    """
    await check_user_permission(body.user_id, db, "student")
    
    from sqlalchemy import update
    stmt = (
        update(Session)
        .where(Session.id == session_id, Session.user_id == body.user_id)
        .values(title=body.title)
    )
    result = await db.execute(stmt)
    if result.rowcount == 0:
        return BaseResponse.error("该会话不存在或无权修改")
        
    await db.commit()
    return BaseResponse.ok("会话标题更新成功")


@router.post("/chat")
@limiter.limit(settings.rate_limit_chat)
async def chat(
    request: Request,
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    流式对话接口。

    响应类型: text/event-stream
    格式见 chat_service.py 的 SSE 规范说明。
    """
    await check_user_permission(body.user_id, db, "student")
    model_id_val = body.model_id.strip() if body.model_id else None
    if model_id_val:
        valid_model_ids = {m["id"] for m in settings.available_models}
        if model_id_val not in valid_model_ids:
            return BaseResponse.error(f"不支持的模型 ID: {model_id_val}")

    generator = chat_stream_generator(
        user_id=body.user_id,
        session_id=body.session_id,
        dialog_id=body.dialog_id,
        message=body.message,
        enable_thinking=body.enable_thinking,
        model_id=model_id_val,
        db=db,
    )
    return StreamingResponse(generator, media_type="text/event-stream")


@router.get("/questions", response_model=BaseResponse[list[QuestionOut]])
async def get_questions(
    user_id: str = Query(..., description="查询目标的用户 ID"),
    session_id: str = Query(..., description="查询目标的会话 ID"),
    limit: int = Query(50, ge=1, le=200, description="每页返回条数"),
    offset: int = Query(0, ge=0, description="分页偏移量"),
    db: AsyncSession = Depends(get_db),
):
    """
    查询指定历史会话内的所有问答记录。

    返回该用户该会话中未被撤回或覆盖的问答记录（正序）。
    """
    await check_user_permission(user_id, db, "student")
    stmt_sess = select(Session).where(Session.id == session_id, Session.user_id == user_id)
    res_sess = await db.execute(stmt_sess)
    if not res_sess.scalars().first():
        return BaseResponse.error("指定的会话不存在或无权访问")

    stmt = (
        select(Question)
        .where(Question.user_id == user_id)
        .where(Question.session_id == session_id)
        .where(Question.is_deleted == False)
        .order_by(Question.created_at.asc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    questions = result.scalars().all()
    data = [QuestionOut.model_validate(q) for q in questions]
    return BaseResponse.ok(data)
