from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import Site, User
from ..schemas import LoginIn, LoginOut, SiteOut, UserOut
from ..security import create_access_token, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])

ROLE_LABELS = {
    "investigator": "研究者",
    "dm": "数据管理员",
    "monitor": "监查员",
}


def serialize_user(user: User) -> UserOut:
    site = None
    if user.site:
        site = SiteOut(
            id=user.site.id,
            code=user.site.code,
            name=user.site.name,
            prefix=user.site.prefix,
            city=user.site.city,
            pi_name=user.site.pi_name,
            target_enrollment=user.site.target_enrollment,
        )
    return UserOut(
        id=user.id,
        username=user.username,
        full_name=user.full_name,
        role=user.role,
        role_label=ROLE_LABELS.get(user.role, user.role),
        site_id=user.site_id,
        site=site,
    )


@router.post("/login", response_model=LoginOut)
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == body.username))
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误，请重试。")
    token = create_access_token(user.id, user.username)
    return LoginOut(access_token=token, user=serialize_user(user))


@router.get("/me", response_model=UserOut)
def me(current: User = Depends(get_current_user)):
    return serialize_user(current)
