"""
聊天与会话相关接口。

- POST `/chat`: 流式对话
- GET `/questions`: 问题历史
"""

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import check_user_permission, get_current_user_id, get_db
from app.core.config import settings
from app.core.limiter import limiter
from app.core.request_context import get_user_role
from app.core.security import hash_password
from app.models.models import Question, Session, User
from app.schemas.base import BaseResponse
from app.schemas.chat_schema import (
    ChatRequest,
    QuestionOut,
    SessionOut,
    SessionRenameRequest,
    StudentRegisterRequest,
    TempRegisterRequest,
    UsageRecordOut,
    UserIdentityOut,
)
from app.services.chat_service import chat_stream_generator

router = APIRouter()


def _exempt_teacher_admin() -> bool:
    role = get_user_role()
    return role in ("teacher", "admin")


@router.post("/register/temp", response_model=BaseResponse[dict])
async def temp_register(
    body: TempRegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    """学生临时注册。"""
    res = await db.execute(select(User).where(User.user_id == body.user_id))
    if res.scalars().first():
        return BaseResponse.error("账号已存在")

    user = User(user_id=body.user_id, role="student")
    db.add(user)
    await db.flush()
    return BaseResponse.ok({"user_id": body.user_id})


@router.post("/register", response_model=BaseResponse[dict])
async def register_student(
    body: StudentRegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    """学生正式注册。"""
    res = await db.execute(
        select(User).where(
            (User.user_id == body.student_no) | (User.student_no == body.student_no)
        )
    )
    if res.scalars().first():
        return BaseResponse.error("账号已存在")

    user = User(
        user_id=body.student_no,
        role="student",
        real_name=body.real_name,
        student_no=body.student_no,
        password_hash=hash_password(body.password),
    )
    db.add(user)
    await db.flush()
    return BaseResponse.ok({"user_id": user.user_id})


@router.get("/models")
async def get_models():
    """获取可用模型列表。"""
    return BaseResponse.ok(
        {
            "default_model": settings.chat_model,
            "models": settings.available_models,
        }
    )


@router.get("/sessions", response_model=BaseResponse[list[SessionOut]])
async def get_sessions(
    limit: int = Query(20, ge=1, le=100, description="默认 20 条"),
    offset: int = Query(0, ge=0, description="分页偏移"),
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id),
):
    """获取当前用户会话列表。"""
    await check_user_permission(current_user_id, db, "student")
    stmt = (
        select(Session)
        .where(Session.user_id == current_user_id)
        .order_by(Session.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    res = await db.execute(stmt)
    data = [SessionOut.model_validate(s) for s in res.scalars().all()]
    return BaseResponse.ok(data)


@router.delete("/sessions/batch", response_model=BaseResponse)
async def delete_sessions_batch(
    days: int = Query(..., ge=0, description="删除 N 天前的会话"),
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id),
):
    """批量删除历史会话。"""
    await check_user_permission(current_user_id, db, "student")

    from datetime import datetime, timedelta, timezone

    cutoff_time = datetime.now(timezone.utc) - timedelta(days=days)

    stmt_sess = select(Session.id).where(
        Session.user_id == current_user_id,
        Session.created_at <= cutoff_time,
    )
    res_sess = await db.execute(stmt_sess)
    session_ids = res_sess.scalars().all()

    if not session_ids:
        return BaseResponse.ok("没有可删除的会话")

    from sqlalchemy import delete, update

    await db.execute(delete(Session).where(Session.id.in_(session_ids)))
    await db.execute(
        update(Question)
        .where(Question.session_id.in_(session_ids))
        .values(is_deleted=True)
    )

    await db.commit()
    return BaseResponse.ok(f"已删除 {len(session_ids)} 个会话")


@router.delete("/sessions/{session_id}", response_model=BaseResponse)
async def delete_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id),
):
    """删除单个会话。"""
    await check_user_permission(current_user_id, db, "student")
    stmt_sess = select(Session).where(Session.id == session_id, Session.user_id == current_user_id)
    res_sess = await db.execute(stmt_sess)
    sess_obj = res_sess.scalars().first()
    if not sess_obj:
        return BaseResponse.error("会话不存在或无权访问")

    from sqlalchemy import delete, update

    await db.execute(delete(Session).where(Session.id == session_id))
    await db.execute(
        update(Question)
        .where(Question.session_id == session_id)
        .values(is_deleted=True)
    )

    await db.commit()
    return BaseResponse.ok("会话已删除")


@router.patch("/sessions/{session_id}/title", response_model=BaseResponse)
async def rename_session(
    session_id: str,
    body: SessionRenameRequest,
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id),
):
    """重命名会话标题。"""
    await check_user_permission(current_user_id, db, "student")

    from sqlalchemy import update

    stmt = (
        update(Session)
        .where(Session.id == session_id, Session.user_id == current_user_id)
        .values(title=body.title)
    )
    result = await db.execute(stmt)
    if result.rowcount == 0:
        return BaseResponse.error("会话不存在或无权访问")

    await db.commit()
    return BaseResponse.ok("会话标题已更新")


@router.post("/chat")
@limiter.limit(settings.rate_limit_chat, exempt_when=_exempt_teacher_admin)
async def chat(
    request: Request,
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id),
):
    """流式聊天接口。"""
    await check_user_permission(current_user_id, db, "student")
    model_id_val = body.model_id.strip() if body.model_id else None
    if model_id_val:
        valid_model_ids = {m["id"] for m in settings.available_models}
        if model_id_val not in valid_model_ids:
            return BaseResponse.error("模型不可用")

    request.state.model_id = model_id_val or settings.chat_model

    generator = chat_stream_generator(
        user_id=current_user_id,
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
    session_id: str = Query(..., description="目标会话 ID"),
    limit: int = Query(50, ge=1, le=200, description="分页大小"),
    offset: int = Query(0, ge=0, description="分页偏移"),
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id),
):
    """获取会话问题历史。"""
    await check_user_permission(current_user_id, db, "student")
    stmt_sess = select(Session).where(Session.id == session_id, Session.user_id == current_user_id)
    res_sess = await db.execute(stmt_sess)
    if not res_sess.scalars().first():
        return BaseResponse.error("会话不存在或无权访问")

    stmt = (
        select(Question)
        .where(Question.user_id == current_user_id)
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


@router.get("/usage", response_model=BaseResponse[list[UsageRecordOut]])
async def get_usage_records(
    limit: int = Query(50, ge=1, le=200, description="分页大小"),
    offset: int = Query(0, ge=0, description="分页偏移"),
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id),
):
    """学生查看自己的模型使用记录。"""
    await check_user_permission(current_user_id, db, "student")
    stmt = (
        select(Question)
        .where(Question.user_id == current_user_id)
        .where(Question.is_deleted == False)
        .order_by(Question.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    res = await db.execute(stmt)
    rows = res.scalars().all()
    data = [
        UsageRecordOut(
            id=r.id,
            session_id=r.session_id,
            model_id=r.model,
            tokens=r.tokens,
            created_at=r.created_at,
        )
        for r in rows
    ]
    return BaseResponse.ok(data)


@router.get("/whoami", response_model=BaseResponse[UserIdentityOut])
async def whoami(
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id),
):
    """返回当前登录用户信息。"""
    user = await check_user_permission(current_user_id, db, "student")
    data = UserIdentityOut(
        user_id=user.user_id,
        role=user.role,
        created_at=user.created_at,
    )
    return BaseResponse.ok(data)
