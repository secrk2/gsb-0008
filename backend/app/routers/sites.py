from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user, visible_site_ids
from ..domain import ACTION_LABELS, STATUS_LABELS, Action, SubjectStatus
from ..models import Site, User
from ..schemas import SiteOut
from .dashboard import serialize_site

router = APIRouter(prefix="/api", tags=["meta"])


@router.get("/sites", response_model=list[SiteOut])
def list_sites(
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    scope = visible_site_ids(current)
    q = select(Site)
    if scope is not None:
        q = q.where(Site.id.in_(scope))
    return [serialize_site(s) for s in db.scalars(q.order_by(Site.id))]


@router.get("/meta/statuses")
def status_meta(current: User = Depends(get_current_user)):
    return {
        "statuses": [
            {"value": st.value, "label": STATUS_LABELS[st], "terminal": st in (
                SubjectStatus.COMPLETED,
                SubjectStatus.DROPPED,
                SubjectStatus.TERMINATED,
                SubjectStatus.SCREEN_FAILED,
                SubjectStatus.REMOVED,
            )}
            for st in SubjectStatus
        ],
        "actions": [
            {"value": a.value, "label": ACTION_LABELS[a]}
            for a in Action
        ],
    }
