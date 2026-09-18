from datetime import date, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import scheduling as sch
from ..database import get_db
from ..deps import get_current_user, visible_site_ids
from ..domain import (
    SubjectStatus,
    VisitState,
    mask_name,
    visit_state,
)
from ..models import Site, Subject, User, Visit
from ..schemas import (
    DashboardOut,
    FunnelStage,
    SiteFunnel,
    SiteOut,
    VisitItem,
)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

VISIT_STATE_LABELS = {
    VisitState.UPCOMING: "未到窗",
    VisitState.IN_WINDOW: "窗内可随访",
    VisitState.DUE_TODAY: "今日应随访",
    VisitState.OVERDUE: "逾期",
    VisitState.OUT_OF_WINDOW: "超窗",
    VisitState.DONE: "已完成",
    VisitState.SKIPPED: "已跳过",
    VisitState.MISSED: "已失访",
}


def serialize_site(site: Site) -> SiteOut:
    return SiteOut(
        id=site.id,
        code=site.code,
        name=site.name,
        prefix=site.prefix,
        city=site.city,
        pi_name=site.pi_name,
        target_enrollment=site.target_enrollment,
    )


def _visit_item(v: Visit, subject: Subject, site: Site, today: date) -> VisitItem:
    tz = site.timezone
    local_planned = sch.utc_date_to_local(v.planned_date, tz)
    state = visit_state(
        local_planned, today, v.window_before, v.window_after, v.status
    )
    return VisitItem(
        id=v.id,
        subject_id=subject.id,
        subject_code=subject.subject_code,
        screening_no=subject.screening_no,
        masked_name=mask_name(subject.full_name, subject.subject_code),
        site_id=site.id,
        site_name=site.name,
        visit_no=v.visit_no,
        name=v.name,
        planned_date=local_planned,
        window_before=v.window_before,
        window_after=v.window_after,
        visit_state=state.value,
        visit_state_label=VISIT_STATE_LABELS[state],
        days_offset=(today - local_planned).days,
        status=v.status,
    )


@router.get("", response_model=DashboardOut)
def dashboard(
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    site_ids = visible_site_ids(current)

    site_q = select(Site)
    if site_ids is not None:
        site_q = site_q.where(Site.id.in_(site_ids))
    sites = list(db.scalars(site_q.order_by(Site.id)))

    subj_q = select(Subject).options(selectinload(Subject.visits))
    if site_ids is not None:
        subj_q = subj_q.where(Subject.site_id.in_(site_ids))
    subjects = list(db.scalars(subj_q))

    subs_by_site: dict[int, list[Subject]] = {s.id: [] for s in sites}
    for subj in subjects:
        subs_by_site.setdefault(subj.site_id, []).append(subj)

    site_funnels: list[SiteFunnel] = []
    totals = {st: 0 for st in SubjectStatus}

    all_today: list[VisitItem] = []
    all_overdue: list[VisitItem] = []
    all_oow: list[VisitItem] = []

    for site in sites:
        site_today = sch.site_local_today(site.timezone)
        site_subjects = subs_by_site.get(site.id, [])
        counts = {st: 0 for st in SubjectStatus}
        for subj in site_subjects:
            try:
                st = SubjectStatus(subj.status)
            except ValueError:
                continue
            counts[st] += 1
            totals[st] += 1

        screened = len(site_subjects)
        enrolled = counts[SubjectStatus.ENROLLED] + counts[SubjectStatus.COMPLETED]
        active = counts[SubjectStatus.ENROLLED]
        enroll_rate = round(enrolled / screened * 100, 1) if screened else 0.0
        complete_rate = (
            round(counts[SubjectStatus.COMPLETED] / enrolled * 100, 1) if enrolled else 0.0
        )

        site_funnels.append(
            SiteFunnel(
                site=serialize_site(site),
                target=site.target_enrollment,
                screened=screened,
                enrolled=enrolled,
                completed=counts[SubjectStatus.COMPLETED],
                dropped=counts[SubjectStatus.DROPPED],
                terminated=counts[SubjectStatus.TERMINATED],
                screen_failed=counts[SubjectStatus.SCREEN_FAILED],
                removed=counts[SubjectStatus.REMOVED],
                active=active,
                enrollment_rate=enroll_rate,
                completion_rate=complete_rate,
            )
        )

        for subj in site_subjects:
            for v in subj.visits:
                item = _visit_item(v, subj, site, site_today)
                if item.visit_state == VisitState.DUE_TODAY.value:
                    all_today.append(item)
                elif item.visit_state == VisitState.OVERDUE.value:
                    all_overdue.append(item)
                elif item.visit_state == VisitState.OUT_OF_WINDOW.value:
                    all_oow.append(item)

    all_today.sort(key=lambda x: (x.site_name, x.planned_date))
    all_overdue.sort(key=lambda x: x.days_offset, reverse=True)
    all_oow.sort(key=lambda x: x.days_offset, reverse=True)

    funnel_total = [
        FunnelStage(key="screened", label="筛选登记", count=len(subjects)),
        FunnelStage(
            key="enrolled",
            label="成功入组",
            count=totals[SubjectStatus.ENROLLED] + totals[SubjectStatus.COMPLETED],
        ),
        FunnelStage(key="active", label="在研", count=totals[SubjectStatus.ENROLLED]),
        FunnelStage(key="completed", label="完成研究", count=totals[SubjectStatus.COMPLETED]),
    ]

    return DashboardOut(
        generated_at=datetime.now(),
        sites=site_funnels,
        funnel_total=funnel_total,
        today_visits=all_today,
        overdue_visits=all_overdue,
        out_of_window_visits=all_oow,
        alerts={
            "today": len(all_today),
            "overdue": len(all_overdue),
            "out_of_window": len(all_oow),
        },
        subject_status_counts={st.value: totals[st] for st in SubjectStatus},
    )
