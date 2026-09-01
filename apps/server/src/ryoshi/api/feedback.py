"""站点反馈路由:POST /api/feedback。

设计意图:
    对应原项目 lib/actions/site-feedback.ts。用户通过反馈弹窗提交
    满意度(positive/neutral/negative)+ 留言,匿名也可提交。
"""

import uuid

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ryoshi.auth import AuthError, AuthUser, resolve_user
from ryoshi.db.engine import get_session
from ryoshi.db.models import Feedback

router = APIRouter(prefix="/api", tags=["feedback"])


class FeedbackRequest(BaseModel):
    sentiment: str  # positive / neutral / negative
    message: str
    pageUrl: str


def _optional_user(authorization: str | None = Header(None)) -> AuthUser | None:
    """反馈允许匿名提交,认证失败不报错,只是 user_id 为空。"""
    try:
        return resolve_user(authorization, allow_anonymous_fallback=True)
    except AuthError:
        return None


@router.post("/feedback", status_code=201)
async def submit_feedback(
    req: FeedbackRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: AuthUser | None = Depends(_optional_user),
):
    """保存一条站点反馈。对应原项目 submitFeedback。"""
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
