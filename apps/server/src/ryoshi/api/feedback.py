"""反馈路由:POST /api/feedback。

设计意图:
    对应原项目两个入口:
      1. 站点反馈(lib/actions/site-feedback.ts): 反馈弹窗提交
         sentiment + message + pageUrl
      2. 消息级反馈(app/api/feedback/route.ts): 消息下方的 thumbs up/down,
         提交 traceId + score(1/-1) + messageId

    两种形状共用一个端点,按请求体字段自动区分。
    匿名也可提交;消息级反馈需要 traceId(关联 Langfuse trace)。
"""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ryoshi.auth import AuthError, AuthUser, resolve_user
from ryoshi.db.engine import get_session
from ryoshi.db.models import Feedback

router = APIRouter(prefix="/api", tags=["feedback"])


class SiteFeedbackRequest(BaseModel):
    """站点反馈(反馈弹窗)。"""

    sentiment: str  # positive / neutral / negative
    message: str
    pageUrl: str


class MessageFeedbackRequest(BaseModel):
    """消息级反馈(thumbs up/down)。"""

    traceId: str
    score: Literal[1, -1]
    messageId: str | None = None


async def _optional_user(authorization: str | None = Header(None)) -> AuthUser | None:
    """反馈允许匿名提交,认证失败不报错,只是 user_id 为空。"""
    try:
        return await resolve_user(authorization, allow_anonymous_fallback=True)
    except AuthError:
        return None


@router.post("/feedback", status_code=201)
async def submit_feedback(
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: AuthUser | None = Depends(_optional_user),
):
    """保存反馈。自动识别站点反馈 vs 消息级反馈。

    - 站点反馈: {sentiment, message, pageUrl} → 写 feedback 表
    - 消息级反馈: {traceId, score, messageId} → 写 feedback 表
      (sentiment 由 score 映射: 1→positive, -1→negative)
    """
    body = await request.json()

    # 消息级反馈:有 traceId + score
    if "traceId" in body and "score" in body:
        req = MessageFeedbackRequest(**body)
        feedback = Feedback(
            id=uuid.uuid4().hex[:24],
            user_id=user.id if user and not user.is_anonymous else None,
            sentiment="positive" if req.score == 1 else "negative",
            message=f"[trace:{req.traceId}]" + (f" [msg:{req.messageId}]" if req.messageId else ""),
            page_url=f"trace://{req.traceId}",
            user_agent=request.headers.get("user-agent"),
        )
        session.add(feedback)
        await session.commit()
        return {"success": True, "id": feedback.id}

    # 站点反馈:有 sentiment + message
    if "sentiment" in body and "message" in body:
        req = SiteFeedbackRequest(**body)
        feedback = Feedback(
            id=uuid.uuid4().hex[:24],
            user_id=user.id if user and not user.is_anonymous else None,
            sentiment=req.sentiment,
            message=req.message.strip(),
            page_url=req.pageUrl,
            user_agent=request.headers.get("user-agent"),
        )
        session.add(feedback)
        await session.commit()
        return {"success": True, "id": feedback.id}

    raise HTTPException(status_code=400, detail="Invalid feedback format")
