"""访视计划共享服务层：甘特总览 / 受试者详情 / CSV 导出三处共用同一套计算，

保证：
1. 完成度数字三处一致（均由 domain.compute_visit_completion 同一函数产出）；
2. “今天/窗期”按研究中心所在时区取当地日历日；
3. 链式重算（改期/跳过/计划外）复用 domain 纯规则，落库前不改锁库数据。
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from . import tz
from .domain import (
    FORM_FORMULA,
    STATUS_LABELS as SUBJECT_STATUS_LABELS,
    VISIT_SCHEDULED,
    VISIT_SKIPPED,
    FormProgress,
    SubjectStatus,
    VisitNode,
    compute_subject_completion,
    compute_visit_completion,
    mask_name,
    visit_state,
)
from .models import (
    ProtocolVersion,
    Site,
    Subject,
    User,
    Visit,
    VisitAudit,
    VisitForm,
)

VISIT_STATE_LABELS = {
    "upcoming": "未到窗",
    "in_window": "窗内可随访",
    "due_today": "今日应随访",
    "overdue": "逾期",
    "out_of_window": "超窗",
    "done": "已完成",
    "skipped": "已跳过",
    "missed": "已失访",
}
VISIT_STATUS_LABELS = {
    "scheduled": "已计划",
    "done": "已完成",
    "skipped": "已跳过",
    "unscheduled": "计划外",
    "missed": "已失访",
    "locked": "已锁库",
}
FORM_STATUS_LABELS = {
    "pending": "未开始",
    "in_progress": "填写中",
    "complete": "已完成",
    "formula": "系统自动计算",
}


def build_node(v: Visit) -> VisitNode:
    return VisitNode(
        id=v.id,
        seq=float(v.seq if v.seq is not None else 0),
        day=v.day_offset,
        planned_date=v.planned_date,
        status="locked" if v.locked and v.status == "done" else v.status,
        actual_date=v.actual_date,
        nominal_date=v.nominal_date or v.planned_date,
        locked=bool(v.locked),
        kind=v.kind,
        window_before=v.window_before,
        window_after=v.window_after,
    )


def ordered_visits(subject: Subject) -> list[Visit]:
    return sorted(
        subject.visits,
        key=lambda x: (x.seq if x.seq is not None else 0, x.id),
    )


def _forms_progress(forms: list[VisitForm]) -> list[FormProgress]:
    return [
        FormProgress(
            status=FORM_FORMULA if f.status == "formula" else f.status,
            submitted_fields=f.submitted_fields or 0,
            total_fields=f.field_total or 0,
            is_key=bool(f.is_key),
        )
        for f in forms
    ]


def completion_payload(v: Visit) -> dict:
    """单次访视完成度（关键表单个口径）。甘特/详情/导出唯一入口。"""
    vc = compute_visit_completion(v.id, v.status, _forms_progress(v.forms))
    return {
        "basis": "key_forms",
        "key_total": vc.key_total,
        "key_done": vc.key_done,
        "rate": vc.rate,
        "field_total": vc.field_total,
        "field_submitted": vc.field_submitted,
        "field_rate": vc.field_rate,
        "is_complete": vc.is_complete,
    }


def subject_completion_payload(subject: Subject) -> dict:
    vcs = [
        compute_visit_completion(v.id, v.status, _forms_progress(v.forms))
        for v in subject.visits
    ]
    return compute_subject_completion(vcs)


def serialize_visit(v: Visit, today: date) -> dict:
    state = visit_state(
        v.planned_date, today, v.window_before, v.window_after,
        "skipped" if v.status == VISIT_SKIPPED else v.status,
    )
    nominal = v.nominal_date or v.planned_date
    comp = completion_payload(v)
    return {
        "id": v.id,
        "visit_no": v.visit_no,
        "name": v.name,
        "status": v.status,
        "status_label": VISIT_STATUS_LABELS.get(v.status, v.status),
        "kind": v.kind,
        "kind_label": "计划外访视" if v.kind == "unscheduled" else "方案访视",
        "locked": bool(v.locked),
        "planned_date": v.planned_date.isoformat(),
        "nominal_date": nominal.isoformat(),
        "divergence_days": (v.planned_date - nominal).days,
        "actual_date": v.actual_date.isoformat() if v.actual_date else None,
        "window_before": v.window_before,
        "window_after": v.window_after,
        "day_offset": v.day_offset,
        "visit_state": state.value,
        "visit_state_label": VISIT_STATE_LABELS[state.value],
        "version_label": v.version_label,
        "insert_reason": v.insert_reason,
        "completion": comp,
        "can_edit": v.status == VISIT_SCHEDULED and not v.locked,
        "can_skip": v.status == VISIT_SCHEDULED and not v.locked,
        "forms": [
            {
                "form_code": f.form_code,
                "form_name": f.form_name,
                "is_key": bool(f.is_key),
                "status": f.status,
                "status_label": FORM_STATUS_LABELS.get(f.status, f.status),
                "field_total": f.field_total,
                "submitted_fields": f.submitted_fields,
            }
            for f in sorted(v.forms, key=lambda x: x.id)
        ],
    }


def empty_kind(subject: Subject) -> str | None:
    """三种空局面区分：无任何访视 / 全部跳过 / None（有在途访视）。"""
    visits = subject.visits
    if not visits:
        return "no_visits"
    if all(v.status == VISIT_SKIPPED for v in visits):
        return "all_skipped"
    return None


def mixed_versions(subject: Subject) -> dict | None:
    labels = sorted({
        v.version_label for v in subject.visits
        if v.kind == "protocol" and v.version_label
    })
    if len(labels) < 2:
        return None
    return {
        "labels": labels,
        "old_label": labels[0],
        "new_label": labels[-1],
        "frozen_visit_nos": [
            v.visit_no for v in ordered_visits(subject)
            if v.version_label == labels[0]
            and v.status in ("done", "locked", "missed")
        ],
    }


def serialize_subject_row(subject: Subject, site: Site, today: date) -> dict:
    visits = [serialize_visit(v, today) for v in ordered_visits(subject)]
    comp = subject_completion_payload(subject)
    try:
        status_label = SUBJECT_STATUS_LABELS[SubjectStatus(subject.status)]
    except Exception:
        status_label = subject.status
    return {
        "subject_id": subject.id,
        "subject_code": subject.subject_code,
        "screening_no": subject.screening_no,
        "masked_name": mask_name(subject.full_name, subject.subject_code),
        "site_id": site.id,
        "site_code": site.code,
        "site_name": site.name,
        "site_timezone": site.timezone,
        # 该行所有窗期/今日判定所用的“今天”（研究中心当地日历日）
        "local_today": today.isoformat(),
        "subject_status": subject.status,
        "subject_status_label": status_label,
        "enroll_date": subject.enroll_date.isoformat() if subject.enroll_date else None,
        "mixed_versions": mixed_versions(subject),
        "empty_kind": empty_kind(subject),
        "completion": comp,
        "visits": visits,
    }


def load_subjects(db, site_ids: list[int] | None) -> list[tuple[Subject, Site]]:
    q = (
        select(Subject)
        .options(
            selectinload(Subject.visits).selectinload(Visit.forms),
            selectinload(Subject.site),
        )
        .order_by(Subject.site_id, Subject.id)
    )
    if site_ids is not None:
        q = q.where(Subject.site_id.in_(site_ids))
    subjects = list(db.scalars(q))
    return [(s, s.site) for s in subjects]


def current_protocol(db) -> ProtocolVersion | None:
    return db.scalar(
        select(ProtocolVersion)
        .where(ProtocolVersion.status == "effective")
        .order_by(ProtocolVersion.effective_date.desc())
    )


def all_protocol_versions(db) -> list[ProtocolVersion]:
    return list(
        db.scalars(
            select(ProtocolVersion).order_by(
                ProtocolVersion.effective_date.desc(), ProtocolVersion.id.desc()
            )
        )
    )


def activate_due_amendments(db) -> int:
    """修订生效清扫（幂等）：到生效日后，把待生效版本转为现行，并把尚未发生的
    方案访视切换到新版本。

    - 版本状态：scheduled（待生效）→ effective；原 effective → superseded；
    - 只切换 status=scheduled 的方案访视；done/locked/skipped/missed 冻结旧版不动；
    - 切换：版本号、相对天数、窗口、名称取新版定义；名义日与现行计划日重置为
      随机化日+新相对天数（新方案节奏重新起算，不继承旧版下的手工改期）；
    - 每次切换写 amendment_switch 留痕，杜绝“静默改版”；
    - 访视是否已到生效日按其研究中心当地日历日判断（跨时区/DST 正确）。
    返回切换的访视条数。
    """
    versions = all_protocol_versions(db)
    system = db.scalar(select(User).where(User.username == "dm"))
    switched_total = 0

    for new_ver in versions:
        if new_ver.status != "scheduled":
            continue
        # 全局状态转换以北京日期为准（本研究中心均在国内时区）；
        # 单条访视的切换另按各中心当地日历日判定
        if tz.local_today("Asia/Shanghai") < new_ver.effective_date:
            continue
        older = [v for v in versions
                 if v.status == "effective"
                 and v.effective_date < new_ver.effective_date]
        old_ver = older[0] if older else None
        if old_ver:
            old_ver.status = "superseded"
        new_ver.status = "effective"

        new_defs = {vd.visit_no: vd for vd in new_ver.visit_defs}
        if not old_ver:
            db.commit()
            continue
        pending = db.scalars(
            select(Visit)
            .options(selectinload(Visit.subject).selectinload(Subject.site))
            .where(
                Visit.protocol_version_id == old_ver.id,
                Visit.kind == "protocol",
                Visit.status == "scheduled",
            )
        ).all()
        for v in pending:
            if tz.local_today(v.subject.site.timezone) < new_ver.effective_date:
                continue
            new_def = new_defs.get(v.visit_no)
            if not new_def or not v.subject.enroll_date:
                continue
            new_date = v.subject.enroll_date + timedelta(days=new_def.day_offset)
            old_planned = v.planned_date
            v.protocol_version_id = new_ver.id
            v.version_label = new_ver.version
            v.day_offset = new_def.day_offset
            v.window_before = new_def.window_before
            v.window_after = new_def.window_after
            v.name = new_def.name
            v.nominal_date = new_date
            v.planned_date = new_date
            db.add(VisitAudit(
                visit_id=v.id, subject_id=v.subject_id, site_id=v.site_id,
                action="amendment_switch",
                old_date=old_planned, new_date=new_date,
                detail=(f"方案修订 {new_ver.version} 于 {new_ver.effective_date} 生效，"
                        f"该访视当时尚未发生，自动由 {old_ver.version} 切换到 "
                        f"{new_ver.version}（相对天数/窗口按新版重算）；已完成与锁库访视"
                        "冻结旧版不受影响。"),
                operator_id=system.id if system else 0,
                operator_name=system.full_name if system else "系统",
            ))
            switched_total += 1
    db.commit()
    return switched_total
