"""访视计划路由：甘特总览（月/周）、访视详情、改期/跳过/恢复/计划外、
方案修订发布、锁库、CSV 导出。

完成度与访视序列化统一走 schedule_service，保证总览/详情/导出三处一致。
"""
from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import schedule_service as svc
from .. import scheduling as sch
from ..database import get_db
from ..deps import assert_site_access, get_current_user, visible_site_ids
from ..models import (
    ProtocolVersion,
    Site,
    Subject,
    User,
    Visit,
    VisitScheduleAudit,
)
from ..scheduling import VisitStatus, site_local_today
from ..schemas import (
    CalendarDay,
    LockIn,
    ProtocolVersionOut,
    RescheduleIn,
    RevisionPublishIn,
    RevisionResultOut,
    SkipIn,
    UnscheduledIn,
    VisitDetailOut,
    VisitPlanOut,
)

router = APIRouter(prefix="/api", tags=["visit-plan"])


# ---------------------------------------------------------------------------
# 加载与范围
# ---------------------------------------------------------------------------
def _load_subjects(db: Session, user: User, site_id: int | None,
                   subject_id: int | None = None) -> list[Subject]:
    q = (
        select(Subject)
        .options(
            selectinload(Subject.site),
            selectinload(Subject.visits).selectinload(Visit.forms),
        )
    )
    scope = visible_site_ids(user)
    if scope is not None:
        q = q.where(Subject.site_id.in_(scope))
    if site_id is not None:
        q = q.where(Subject.site_id == site_id)
    if subject_id is not None:
        q = q.where(Subject.id == subject_id)
    return list(db.scalars(q.order_by(Subject.site_id, Subject.id.desc())))


def _get_visit_subject(db: Session, visit_id: int, user: User) -> tuple[Visit, Subject]:
    visit = db.scalar(
        select(Visit)
        .options(selectinload(Visit.forms))
        .where(Visit.id == visit_id)
    )
    if not visit:
        raise HTTPException(status_code=404, detail="访视不存在或已被移除。")
    subject = db.scalar(
        select(Subject)
        .options(selectinload(Subject.site), selectinload(Subject.visits).selectinload(Visit.forms))
        .where(Subject.id == visit.subject_id)
    )
    assert_site_access(user, subject.site_id)
    return visit, subject


def _grid_days(view: str, anchor: date) -> list[date]:
    if view == "week":
        start = anchor - timedelta(days=anchor.weekday())  # 周一
        return [start + timedelta(days=i) for i in range(7)]
    # month：含首尾补齐到整周
    first = anchor.replace(day=1)
    start = first - timedelta(days=first.weekday())
    _, last_day_num = calendar.monthrange(anchor.year, anchor.month)
    last = anchor.replace(day=last_day_num)
    end = last + timedelta(days=(6 - last.weekday()))
    days = []
    cur = start
    while cur <= end:
        days.append(cur)
        cur += timedelta(days=1)
    return days


def _versions(db: Session) -> list[ProtocolVersionOut]:
    rows = db.scalars(select(ProtocolVersion).order_by(ProtocolVersion.id.desc()))
    return [
        ProtocolVersionOut(
            version=p.version, title=p.title, change_note=p.change_note,
            effective_date=p.effective_date, published_by=p.published_by,
            is_current=p.is_current, created_at=p.created_at,
        )
        for p in rows
    ]


# ---------------------------------------------------------------------------
# 总览
# ---------------------------------------------------------------------------
@router.get("/visit-plan", response_model=VisitPlanOut)
def visit_plan(
    view: str = Query(default="month", pattern="^(month|week)$"),
    anchor: date | None = None,
    site_id: int | None = None,
    subject_id: int | None = None,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    if site_id is not None:
        assert_site_access(current, site_id)

    # 网格参照时区：指定中心/受试者用其中心时区；DM 跨中心用东八区统一呈现
    ref_tz = "Asia/Shanghai"
    site_name = "全部研究中心（DM 视图，日期按北京时间统一呈现）"
    if subject_id is not None:
        target = db.get(Subject, subject_id)
        if target is None:
            raise HTTPException(status_code=404, detail="受试者不存在。")
        assert_site_access(current, target.site_id)
        ref_tz = target.site.timezone
        site_name = f"{target.site.name} · 单受试者视图"
    elif site_id is not None:
        site = db.get(Site, site_id)
        if site:
            ref_tz = site.timezone
            site_name = site.name

    today = site_local_today(ref_tz)
    anchor_local = anchor or today
    days_grid = _grid_days(view, anchor_local)

    all_subjects = _load_subjects(db, current, site_id, subject_id)
    rows_subjects = [s for s in all_subjects if s.visits]

    # 三种空局面
    if not rows_subjects:
        # 筛选中的受试者存在但无访视 => 明确「尚无任何访视」
        empty_reason = "no_visits"
        summaries = []
    else:
        summaries = [svc.subject_summary(s, today) for s in rows_subjects]
        all_skipped = all(
            len(s["visits"]) > 0
            and all(v["status"] == VisitStatus.SKIPPED.value for v in s["visits"])
            for s in summaries
        )
        empty_reason = "all_skipped" if all_skipped else None

    # 附带排程留痕（最近 20 条/受试者）
    audit_rows = db.scalars(
        select(VisitScheduleAudit).order_by(VisitScheduleAudit.id.desc())
    ).all()
    audits_by_subject: dict[int, list] = {}
    for a in audit_rows:
        audits_by_subject.setdefault(a.subject_id, []).append(svc._audit_item(a))
    for s in summaries:
        s["schedule_audits"] = audits_by_subject.get(s["subject_id"], [])[:20]

    # 每天落在该日本地日期的访视
    day_set = set(days_grid)
    day_visits: dict[date, list[int]] = {d: [] for d in days_grid}
    for s in summaries:
        for v in s["visits"]:
            if v["planned_date"] in day_set:
                day_visits[v["planned_date"]].append(v["id"])

    current_version = svc.get_current_version(db)
    return VisitPlanOut(
        generated_at=datetime.now(),
        view=view,
        anchor_date=anchor_local,
        timezone=ref_tz,
        site_id=site_id,
        site_name=site_name,
        policy=svc.STUDY_POLICY.value,
        policy_label=sch.ANCHOR_POLICY_LABELS[svc.STUDY_POLICY],
        completion_basis=svc.COMPLETION_BASIS,
        current_version=current_version.version if current_version else "v1.0",
        versions=_versions(db),
        subjects=summaries,
        days=[
            CalendarDay(date=d, in_range=(view == "month" and d.month == anchor_local.month) or view == "week",
                        visit_ids=day_visits[d])
            for d in days_grid
        ],
        empty_reason=empty_reason,
        today_local=today,
        scope_note=(
            "日期一律按 UTC 存储，按研究中心所在时区展示；跨中心 DM 视图统一按北京时间。"
            f"当前参照时区：{ref_tz}，中心本地今日：{today.isoformat()}。"
        ),
    )


# ---------------------------------------------------------------------------
# 访视详情
# ---------------------------------------------------------------------------
@router.get("/visits/{visit_id}", response_model=VisitDetailOut)
def visit_detail(
    visit_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    visit, subject = _get_visit_subject(db, visit_id, current)
    tz = subject.site.timezone
    today = site_local_today(tz)

    rand, insts = svc.subject_insts(subject)
    ordered = sorted(insts, key=lambda x: (x.order_index, x.visit_no))
    idx = next(i for i, x in enumerate(ordered) if x.visit_no == visit.visit_no
               and x.inst_id == visit.id)
    anchor_res = sch.resolve_anchor(ordered[idx], idx, ordered, rand, svc.STUDY_POLICY)

    visit_out = svc.serialize_visit(visit, tz, today, anchor_res=anchor_res)

    audits = [
        svc._audit_item(a)
        for a in db.scalars(
            select(VisitScheduleAudit)
            .where(VisitScheduleAudit.subject_id == subject.id)
            .order_by(VisitScheduleAudit.id.desc())
            .limit(30)
        )
    ]

    from ..domain import mask_name
    mixed = sch.subject_mixed_versions(insts)
    return VisitDetailOut(
        visit=visit_out,
        subject_id=subject.id,
        subject_code=subject.subject_code,
        screening_no=subject.screening_no,
        masked_name=mask_name(subject.full_name, subject.subject_code),
        site_name=subject.site.name,
        timezone=tz,
        randomization_date=rand,
        active_version=subject.active_version,
        mixed_versions=mixed,
        policy=svc.STUDY_POLICY.value,
        policy_label=sch.ANCHOR_POLICY_LABELS[svc.STUDY_POLICY],
        completion_basis=svc.COMPLETION_BASIS,
        audits=audits,
    )


# ---------------------------------------------------------------------------
# 改期（超窗必须二次确认 + 强制原因 + 留痕）
# ---------------------------------------------------------------------------
@router.post("/visits/{visit_id}/reschedule")
def reschedule_visit(
    visit_id: int,
    body: RescheduleIn,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    if current.role not in ("investigator", "dm"):
        raise HTTPException(status_code=403, detail="仅研究者/数据管理员可调整访视日期。")
    visit, subject = _get_visit_subject(db, visit_id, current)
    try:
        out_of_window, message = svc.reschedule(
            db, subject, current, visit, body.new_date,
            body.reason.strip(), body.confirm_out_of_window,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        # 超窗未二次确认：409 业务冲突，前端弹强制确认
        raise HTTPException(status_code=409, detail=str(exc))
    return {
        "out_of_window": out_of_window,
        "planned_date": body.new_date.isoformat(),
        "message": message,
    }


@router.post("/visits/{visit_id}/skip")
def skip_visit(
    visit_id: int,
    body: SkipIn,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    if current.role not in ("investigator", "dm"):
        raise HTTPException(status_code=403, detail="仅研究者/数据管理员可跳过访视。")
    visit, subject = _get_visit_subject(db, visit_id, current)
    try:
        svc.set_skipped(db, subject, current, visit, body.reason.strip())
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"message": f"访视 {visit.visit_no} 已跳过，下游访视计划已链式重算并留痕。"}


@router.post("/visits/{visit_id}/restore")
def restore_visit(
    visit_id: int,
    body: SkipIn,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    if current.role not in ("investigator", "dm"):
        raise HTTPException(status_code=403, detail="仅研究者/数据管理员可恢复访视。")
    visit, subject = _get_visit_subject(db, visit_id, current)
    try:
        svc.set_restored(db, subject, current, visit, body.reason.strip())
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"message": f"访视 {visit.visit_no} 已恢复，下游访视计划已链式重算并留痕。"}


@router.post("/visit-plan/unscheduled")
def add_unscheduled(
    body: UnscheduledIn,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    if current.role not in ("investigator", "dm"):
        raise HTTPException(status_code=403, detail="仅研究者/数据管理员可插入计划外访视。")
    subject = db.scalar(
        select(Subject)
        .options(selectinload(Subject.site), selectinload(Subject.visits).selectinload(Visit.forms))
        .where(Subject.id == body.subject_id)
    )
    if not subject:
        raise HTTPException(status_code=404, detail="受试者不存在。")
    assert_site_access(current, subject.site_id)
    visit = svc.insert_unscheduled(
        db, subject, current, body.name.strip(), body.date,
        body.window_before, body.window_after, body.reason.strip(),
    )
    return {"visit_id": visit.id, "visit_no": visit.visit_no,
            "message": f"已插入计划外访视 {visit.visit_no}，下游访视计划已重算并留痕。"}


@router.post("/visits/{visit_id}/lock")
def lock_visit(
    visit_id: int,
    body: LockIn,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    if current.role not in ("investigator", "dm"):
        raise HTTPException(status_code=403, detail="仅研究者/数据管理员可操作锁库。")
    visit, subject = _get_visit_subject(db, visit_id, current)
    svc.set_locked(db, subject, current, visit, body.locked, body.reason.strip())
    return {"locked": body.locked,
            "message": "访视已锁库，计划/实际日期与表单全部冻结。" if body.locked
            else "访视已解锁，可在留痕前提下继续修改。"}


# ---------------------------------------------------------------------------
# 方案修订发布（仅 DM）
# ---------------------------------------------------------------------------
@router.get("/protocol-versions/{version}/template")
def get_version_template(
    version: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    pv = db.scalar(select(ProtocolVersion).where(ProtocolVersion.version == version))
    if not pv:
        raise HTTPException(status_code=404, detail=f"方案版本 {version} 不存在。")
    return {
        "version": pv.version,
        "title": pv.title,
        "change_note": pv.change_note,
        "effective_date": pv.effective_date,
        "visits": [
            {
                "visit_no": t.visit_no,
                "name": t.name,
                "order_index": t.order_index,
                "offset_days": t.offset_days,
                "anchor_mode": t.anchor_mode,
                "window_before": t.window_before,
                "window_after": t.window_after,
                "forms": [
                    {"form_key": f.form_key, "name": f.name, "is_key": f.is_key,
                     "total_fields": f.total_fields}
                    for f in t.forms
                ],
            }
            for t in sorted(pv.templates, key=lambda x: x.order_index)
        ],
    }


@router.post("/visit-plan/revision", response_model=RevisionResultOut)
def publish_revision(
    body: RevisionPublishIn,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    if current.role != "dm":
        raise HTTPException(
            status_code=403,
            detail="仅申办方/CRO 数据管理员可发布方案修订；研究者如发现方案问题请提交 DM 评估。",
        )
    if body.effective_date < site_local_today("Asia/Shanghai"):
        raise HTTPException(status_code=400, detail="修订生效日不能早于今天。")
    if not body.visits:
        raise HTTPException(status_code=400, detail="新方案至少要包含一个访视模板。")
    nos = [v.visit_no for v in body.visits]
    if len(set(nos)) != len(nos):
        raise HTTPException(status_code=400, detail="访视号在同一方案版本内不能重复。")
    try:
        result = svc.publish_revision(
            db, current, version=body.version.strip(), title=body.title.strip(),
            change_note=body.change_note.strip(), effective_date=body.effective_date,
            visits_in=body.visits,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return RevisionResultOut(**result)


# ---------------------------------------------------------------------------
# CSV 导出（与总览/详情同源）
# ---------------------------------------------------------------------------
@router.get("/visit-plan/export")
def export_plan(
    site_id: int | None = None,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    if site_id is not None:
        assert_site_access(current, site_id)
    ref_tz = "Asia/Shanghai"
    if site_id is not None:
        site = db.get(Site, site_id)
        if site:
            ref_tz = site.timezone
    today = site_local_today(ref_tz)
    subjects = [s for s in _load_subjects(db, current, site_id) if s.visits]
    csv_text = svc.export_csv(subjects, today, ref_tz)
    fname = f"visit-plan-{today.isoformat()}.csv"
    return StreamingResponse(
        iter([csv_text.encode("utf-8-sig")]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
