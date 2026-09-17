from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import assert_site_access, get_current_user, visible_site_ids
from ..models import NumberAudit, Site, User
from ..schemas import NumberAuditItem
from .subjects import KIND_LABELS, NUMBER_STATUS_LABELS

router = APIRouter(prefix="/api/number-audits", tags=["numbers"])


@router.get("", response_model=list[NumberAuditItem])
def list_number_audits(
    site_id: int | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """号码台账：分配/作废全量留痕（含不挂受试者的作废号），按中心隔离。"""
    if site_id is not None:
        assert_site_access(current, site_id)

    q = select(NumberAudit)
    scope = visible_site_ids(current)
    if scope is not None:
        q = q.where(NumberAudit.site_id.in_(scope))
    if site_id is not None:
        q = q.where(NumberAudit.site_id == site_id)
    if status_filter in ("assigned", "voided"):
        q = q.where(NumberAudit.status == status_filter)

    rows = list(db.scalars(q.order_by(NumberAudit.site_id, NumberAudit.kind, NumberAudit.seq)))
    site_names = {
        s.id: s.name
        for s in db.scalars(select(Site).where(Site.id.in_({r.site_id for r in rows})))
    }
    return [
        NumberAuditItem(
            id=r.id,
            site_id=r.site_id,
            site_name=site_names.get(r.site_id),
            kind=r.kind,
            kind_label=KIND_LABELS.get(r.kind, r.kind),
            number=r.number,
            seq=r.seq,
            status=r.status,
            status_label=NUMBER_STATUS_LABELS.get(r.status, r.status),
            reason=r.reason,
            operator_name=r.operator_name,
            created_at=r.created_at,
        )
        for r in rows
    ]
