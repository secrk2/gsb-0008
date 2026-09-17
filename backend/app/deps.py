from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from .database import get_db
from .models import User
from .security import decode_access_token


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录或登录态已失效，请重新登录。",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = decode_access_token(token)
        user_id = int(payload["sub"])
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="登录令牌无效或已过期，请重新登录。",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="账号不存在或已停用，请联系管理员。")
    return user


def assert_site_access(user: User, site_id: int) -> None:
    """中心间数据严格隔离。

    仅申办方/CRO 级数据管理员（site_id 为空）可跨中心；
    其余账号只能访问自己所属中心，越权返回明确 403 错误态（而非空白页）。
    """
    if user.site_id is not None and user.site_id != site_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "SITE_FORBIDDEN",
                "message": (
                    f"越权访问拦截：您属于 {user.site.code if user.site else ''}，"
                    f"无权访问其他中心（站点ID {site_id}）的数据。"
                    "本次拒绝已按合规要求记录；如确需跨中心核查，请走跨中心授权申请。"
                ),
            },
        )


def visible_site_ids(user: User) -> list[int] | None:
    """None 表示不做中心过滤（跨中心 DM）。"""
    return None if user.site_id is None else [user.site_id]
