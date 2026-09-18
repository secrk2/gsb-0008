"""访视排程服务：ORM 模型 ↔ scheduling 纯规则之间的桥梁。

所有需要展示/导出完成度与访视计划的地方（访视计划总览、访视详情、CSV 导出、
受试者详情页）都必须调用本模块的序列化函数，不得自行计算，以此保证「三处一致」。
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import scheduling as sch
from .domain import (
    STATUS_LABELS,
    SubjectStatus,
    VisitState,
    mask_name,
    visit_state,
)
from .models import (
    ProtocolVersion,
    Subject,
    Site,
    TemplateForm,
    User,
    Visit,
    VisitForm,
    VisitScheduleAudit,
    VisitTemplate,
)
from .scheduling import (
    AnchorMode,
    AnchorPolicy,
    FormStatus,
    InstForm,
    InstVisit,
    LockedVisitError,
    TplForm,
    TplVisit,
    VisitKind,
    VisitStatus,
    get_zone,
)

# 研究级口径：双锚点冲突时以哪个为准（界面明示，不让研究者猜）
STUDY_POLICY = AnchorPolicy.ACTUAL_FIRST

# 完成度口径说明（界面与导出原样展示）
COMPLETION_BASIS = (
    "完成度口径：按「已完成并提交的关键表单（CRF）数 / 关键表单总数」计算。"
    "仅填写了部分字段、未完成提交的表单计为 0（不计半张表）；已跳过访视不计入分母。"
    "因此「只填了半张表的访视」在本口径下为 0%，与按已提交字段数（约 50%）的口径结论相反。"
    "总览、访视详情、导出三处数字同源一致。"
)

ANCHOR_MODE_LABELS = {
    AnchorMode.RANDOMIZATION: "相对随机化日",
    AnchorMode.PREVIOUS_ACTUAL: "相对上一次实际访视日",
}
KIND_LABELS = {VisitKind.PROTOCOL: "方案访视", VisitKind.UNSCHEDULED: "计划外访视"}
FORM_STATUS_LABELS = {
    FormStatus.PENDING: "未开始",
    FormStatus.INCOMPLETE: "填写中（未提交）",
    FormStatus.COMPLETE: "已完成提交",
}
AUDIT_ACTION_LABELS = {
    "reschedule": "改期",
    "skip": "跳过访视",
    "restore": "恢复访视",
    "insert_unscheduled": "插入计划外访视",
    "chain_recompute": "链式重算",
    "revision": "方案修订切版",
    "lock": "锁库",
    "unlock": "解锁",
    "done": "记录完成",
}

VISIT_STATE_PLAN_LABELS = {
    VisitState.UPCOMING: "未到窗",
    VisitState.IN_WINDOW: "窗内可随访",
    VisitState.DUE_TODAY: "今日应随访",
    VisitState.OVERDUE: "逾期",
    VisitState.OUT_OF_WINDOW: "已超窗",
    VisitState.DONE: "已完成",
    VisitState.SKIPPED: "已跳过",
    VisitState.MISSED: "已失访",
}


# ---------------------------------------------------------------------------
# 本地日 <-> UTC 日历日
# ---------------------------------------------------------------------------
def local_date_to_utc(local_day: date, tz_name: str | None) -> date:
    """中心本地日历日 -> 规范存储用 UTC 日历日（取本地正午换 UTC，与读取口径互逆）。"""
    local_noon = datetime.combine(local_day, time(12, 0), tzinfo=get_zone(tz_name))
    return local_noon.astimezone(sch.UTC).date()


def planned_local(v: Visit, tz_name: str | None) -> date:
    return sch.utc_date_to_local(v.planned_date, tz_name)


# ---------------------------------------------------------------------------
# ORM -> 纯结构
# ---------------------------------------------------------------------------
def randomization_date(subject: Subject) -> date:
    return subject.randomization_date or subject.enroll_date or subject.screen_date


def orm_visit_to_inst(v: Visit) -> InstVisit:
    return InstVisit(
        visit_no=v.visit_no,
        name=v.name,
        order_index=v.order_index,
        offset_days=v.offset_days,
        anchor_mode=AnchorMode(v.anchor_mode),
        kind=VisitKind(v.kind),
        status=VisitStatus(v.status),
        planned_utc=v.planned_date,
        actual_utc=v.actual_date,
        window_before=v.window_before,
        window_after=v.window_after,
        locked=v.locked,
        pinned=v.pinned,
        version=v.version,
        inst_id=v.id,
        forms=[
            InstForm(
                form_key=f.form_key,
                name=f.name,
                is_key=f.is_key,
                status=FormStatus(f.status),
                total_fields=f.total_fields,
                filled_fields=f.filled_fields,
            )
            for f in v.forms
        ],
    )


def subject_insts(subject: Subject) -> tuple[date, list[InstVisit]]:
    rand = randomization_date(subject)
    insts = [orm_visit_to_inst(v) for v in subject.visits]
    return rand, insts


def template_to_tpls(version: ProtocolVersion) -> list[TplVisit]:
    out = []
    for t in version.templates:
        out.append(
            TplVisit(
                visit_no=t.visit_no,
                name=t.name,
                order_index=t.order_index,
                offset_days=t.offset_days,
                anchor_mode=AnchorMode(t.anchor_mode),
                window_before=t.window_before,
                window_after=t.window_after,
                forms=[
                    TplForm(f.form_key, f.name, f.is_key, f.total_fields)
                    for f in t.forms
                ],
            )
        )
    return out


# ---------------------------------------------------------------------------
# 统一序列化（总览 / 详情 / 导出的唯一出口）
# ---------------------------------------------------------------------------
def _anchor_info(res: sch.AnchorResolution, tz_name: str | None):
    from .schemas import AnchorInfo

    if res is None:
        return None
    return AnchorInfo(
        base_label=res.base_label,
        base_date=sch.utc_date_to_local(res.base_utc, tz_name) if res.base_utc else None,
        policy=STUDY_POLICY.value,
        policy_label=sch.ANCHOR_POLICY_LABELS[STUDY_POLICY],
        conflict=res.conflict,
        winner=res.winner,
        alternative_date=(
            sch.utc_date_to_local(res.alternative_utc, tz_name)
            if res.alternative_utc
            else None
        ),
        alternative_label=res.alternative_label,
    )


def _visit_key_form_counts(v: Visit) -> tuple[int, int]:
    done = total = 0
    for f in v.forms:
        if not f.is_key:
            continue
        total += 1
        if f.status == FormStatus.COMPLETE.value:
            done += 1
    return done, total


def serialize_visit(
    v: Visit,
    tz_name: str | None,
    today_local: date,
    *,
    anchor_res: sch.AnchorResolution | None = None,
    subject_id: int | None = None,
) -> dict:
    local_planned = planned_local(v, tz_name)
    local_actual = (
        sch.utc_date_to_local(v.actual_date, tz_name) if v.actual_date else None
    )
    state = visit_state(
        local_planned, today_local, v.window_before, v.window_after, v.status
    )
    key_done, key_total = _visit_key_form_counts(v)
    return {
        "id": v.id,
        "subject_id": subject_id if subject_id is not None else v.subject_id,
        "visit_no": v.visit_no,
        "name": v.name,
        "planned_date": local_planned,
        "window_before": v.window_before,
        "window_after": v.window_after,
        "status": v.status,
        "visit_state": state.value,
        "visit_state_label": VISIT_STATE_PLAN_LABELS[state],
        "actual_date": local_actual,
        "order_index": v.order_index,
        "kind": v.kind,
        "kind_label": KIND_LABELS[VisitKind(v.kind)],
        "version": v.version,
        "offset_days": v.offset_days,
        "anchor_mode": v.anchor_mode,
        "anchor_mode_label": ANCHOR_MODE_LABELS[AnchorMode(v.anchor_mode)],
        "locked": v.locked,
        "pinned": v.pinned,
        "can_edit": not v.locked,
        "anchor": _anchor_info(anchor_res, tz_name),
        "forms": [
            {
                "form_key": f.form_key,
                "name": f.name,
                "is_key": f.is_key,
                "status": f.status,
                "status_label": FORM_STATUS_LABELS[FormStatus(f.status)],
                "total_fields": f.total_fields,
                "filled_fields": f.filled_fields,
            }
            for f in v.forms
        ],
        "key_form_done": key_done,
        "key_form_total": key_total,
        "completion_percent": round(key_done * 100 / key_total, 1) if key_total else 0.0,
    }


def _audit_item(a: VisitScheduleAudit) -> dict:
    return {
        "id": a.id,
        "visit_no": a.visit_no,
        "action": a.action,
        "action_label": AUDIT_ACTION_LABELS.get(a.action, a.action),
        "old_date": a.old_date,
        "new_date": a.new_date,
        "reason": a.reason,
        "out_of_window": a.out_of_window,
        "detail": a.detail,
        "operator_name": a.operator_name,
        "created_at": a.created_at,
    }


def subject_summary(subject: Subject, today_local: date) -> dict:
    """构建一个受试者的完整访视计划视图（三处一致的数据来源）。"""
    tz_name = subject.site.timezone
    rand, insts = subject_insts(subject)
    ordered = sorted(insts, key=lambda x: (x.order_index, x.visit_no))

    # 每个访视的锚点依据（含双口径冲突标记）
    anchor_map: dict[int, sch.AnchorResolution] = {}
    for idx, iv in enumerate(ordered):
        res = sch.resolve_anchor(iv, idx, ordered, rand, STUDY_POLICY)
        if iv.inst_id is not None:
            anchor_map[iv.inst_id] = res

    visits_out = [
        serialize_visit(
            v, tz_name, today_local,
            anchor_res=anchor_map.get(v.id),
            subject_id=subject.id,
        )
        for v in sorted(subject.visits, key=lambda x: (x.order_index, x.visit_no))
    ]

    completion = sch.compute_completion(insts)
    mixed = sch.subject_mixed_versions(insts)

    return {
        "subject_id": subject.id,
        "subject_code": subject.subject_code,
        "screening_no": subject.screening_no,
        "masked_name": mask_name(subject.full_name, subject.subject_code),
        "site_id": subject.site_id,
        "site_name": subject.site.name if subject.site else "",
        "timezone": tz_name,
        "status": subject.status,
        "status_label": STATUS_LABELS[SubjectStatus(subject.status)],
        "active_version": subject.active_version,
        "mixed_versions": mixed,
        "visits": visits_out,
        "completion_percent": completion.percent,
        "completion_label": completion.label,
        "key_form_done": completion.key_form_done,
        "key_form_total": completion.key_form_total,
        "skipped_count": completion.skipped_visits,
        "schedule_audits": [],
    }


# ---------------------------------------------------------------------------
# 留痕
# ---------------------------------------------------------------------------
def add_audit(
    db: Session, subject: Subject, user: User, action: str, *,
    visit: Visit | None = None, visit_no: str | None = None,
    old_date: date | None = None, new_date: date | None = None,
    reason: str | None = None, out_of_window: bool = False,
    detail: str | None = None,
) -> None:
    db.add(
        VisitScheduleAudit(
            subject_id=subject.id,
            site_id=subject.site_id,
            visit_id=visit.id if visit else None,
            visit_no=visit.visit_no if visit else visit_no,
            action=action,
            old_date=old_date,
            new_date=new_date,
            reason=reason,
            out_of_window=out_of_window,
            detail=detail,
            operator_id=user.id,
            operator_name=user.full_name,
        )
    )


# ---------------------------------------------------------------------------
# 实例化（入组 / 种子）
# ---------------------------------------------------------------------------
def instantiate_subject_visits(
    db: Session, subject: Subject, version: ProtocolVersion,
    *, rand: date | None = None,
) -> list[Visit]:
    """按方案版本模板为受试者生成访视与关键表单实例。"""
    rand = rand or randomization_date(subject)
    created: list[Visit] = []
    for tpl in version.templates:
        v = Visit(
            subject_id=subject.id,
            site_id=subject.site_id,
            visit_no=tpl.visit_no,
            name=tpl.name,
            order_index=tpl.order_index,
            kind=VisitKind.PROTOCOL.value,
            version=version.version,
            offset_days=tpl.offset_days,
            anchor_mode=tpl.anchor_mode,
            planned_date=rand + timedelta(days=tpl.offset_days),
            window_before=tpl.window_before,
            window_after=tpl.window_after,
            status=VisitStatus.SCHEDULED.value,
        )
        db.add(v)
        db.flush()
        for tf in tpl.forms:
            db.add(
                VisitForm(
                    visit_id=v.id,
                    form_key=tf.form_key,
                    name=tf.name,
                    is_key=tf.is_key,
                    total_fields=tf.total_fields,
                    status=FormStatus.PENDING.value,
                    filled_fields=0,
                )
            )
        created.append(v)
    subject.active_version = version.version
    return created


def next_unscheduled_no(subject: Subject) -> str:
    existing = [
        v.visit_no for v in subject.visits
        if v.kind == VisitKind.UNSCHEDULED.value
        and v.visit_no.startswith("U")
    ]
    max_n = 0
    for no in existing:
        try:
            max_n = max(max_n, int(no[1:]))
        except ValueError:
            continue
    return f"U{max_n + 1}"


# ---------------------------------------------------------------------------
# 排程操作（改期 / 跳过 / 恢复 / 计划外 / 锁库）
# ---------------------------------------------------------------------------
def reschedule(
    db: Session, subject: Subject, user: User, visit: Visit,
    new_date_local: date, reason: str, confirm_oow: bool,
) -> tuple[bool, str]:
    """返回 (是否超窗, 提示)。超窗且未二次确认 -> 抛 ValueError（路由转 409）。"""
    if visit.status == VisitStatus.SKIPPED.value:
        raise ValueError(f"访视 {visit.visit_no} 已跳过，不能改期；请先「恢复访视」后再调整日期。")
    tz = subject.site.timezone
    today = sch.site_local_today(tz)
    new_utc = local_date_to_utc(new_date_local, tz)
    old_local = planned_local(visit, tz)
    old_utc = visit.planned_date

    in_window = (
        old_local - timedelta(days=visit.window_before)
        <= new_date_local
        <= old_local + timedelta(days=visit.window_after)
    )
    if not in_window and not confirm_oow:
        raise ValueError(
            f"落点 {new_date_local.isoformat()} 已超出访视 {visit.visit_no} 的随访窗"
            f"（{ (old_local - timedelta(days=visit.window_before)).isoformat() } ~ "
            f"{ (old_local + timedelta(days=visit.window_after)).isoformat() }）。"
            "超窗改期必须二次确认并填写原因，系统将按方案偏离留痕。"
        )

    rand, insts = subject_insts(subject)
    try:
        changes = sch.reschedule_visit(
            insts, visit.visit_no, new_utc, rand, STUDY_POLICY, reason=reason
        )
    except LockedVisitError as exc:
        raise PermissionError(str(exc))

    # 主访视改期
    visit.planned_date = new_utc
    # 下游链式重算（排除主访视自身）
    for ch in changes:
        if ch.inst_id and ch.inst_id != visit.id:
            target = db.get(Visit, ch.inst_id)
            if target and not target.locked:
                old = target.planned_date
                target.planned_date = ch.new_planned_utc
                add_audit(
                    db, subject, user, "chain_recompute", visit=target,
                    old_date=old, new_date=ch.new_planned_utc,
                    reason=f"因上游访视 {visit.visit_no} 改期，按锚点规则链式重算",
                )

    add_audit(
        db, subject, user, "reschedule", visit=visit,
        old_date=old_utc,
        new_date=new_utc, reason=reason, out_of_window=not in_window,
        detail=("超窗改期（方案偏离）" if not in_window else "窗内改期"),
    )
    db.commit()
    return (not in_window), (
        "改期成功，落点超窗已按方案偏离记录，请同步完成 PD 评估。"
        if not in_window else "改期成功，下游访视已按锚点规则链式重算。"
    )


def set_skipped(
    db: Session, subject: Subject, user: User, visit: Visit, reason: str
) -> None:
    if visit.status == VisitStatus.DONE.value:
        raise ValueError("已完成的访视不能跳过。")
    rand, insts = subject_insts(subject)
    try:
        changes = sch.skip_visit(insts, visit.visit_no, rand, STUDY_POLICY)
    except LockedVisitError as exc:
        raise PermissionError(str(exc))
    visit.status = VisitStatus.SKIPPED.value
    _apply_chain_changes(db, subject, user, changes)
    add_audit(db, subject, user, "skip", visit=visit, reason=reason,
              detail="访视标记跳过，不计入完成度分母；下游计划链式重算")
    db.commit()


def set_restored(
    db: Session, subject: Subject, user: User, visit: Visit, reason: str
) -> None:
    rand, insts = subject_insts(subject)
    try:
        changes = sch.restore_visit(insts, visit.visit_no, rand, STUDY_POLICY)
    except LockedVisitError as exc:
        raise PermissionError(str(exc))
    visit.status = VisitStatus.SCHEDULED.value
    _apply_chain_changes(db, subject, user, changes)
    add_audit(db, subject, user, "restore", visit=visit, reason=reason,
              detail="恢复已跳过访视，重新计入完成度分母；下游计划链式重算")
    db.commit()


def _apply_chain_changes(db, subject, user, changes) -> None:
    for ch in changes:
        if not ch.inst_id:
            continue
        target = db.get(Visit, ch.inst_id)
        if target and not target.locked and target.status == VisitStatus.SCHEDULED.value:
            old = target.planned_date
            target.planned_date = ch.new_planned_utc
            add_audit(
                db, subject, user, "chain_recompute", visit=target,
                old_date=old, new_date=ch.new_planned_utc, reason=ch.reason,
            )


def insert_unscheduled(
    db: Session, subject: Subject, user: User, name: str,
    date_local: date, wb: int, wa: int, reason: str,
) -> Visit:
    tz = subject.site.timezone
    planned_utc = local_date_to_utc(date_local, tz)
    rand, insts = subject_insts(subject)

    no = next_unscheduled_no(subject)
    sch.insert_unscheduled(
        insts, no, name, planned_utc, window_before=wb, window_after=wa,
        version=subject.active_version,
    )
    # 落库新访视
    new_inst = next(i for i in insts if i.visit_no == no)
    visit = Visit(
        subject_id=subject.id,
        site_id=subject.site_id,
        visit_no=no,
        name=name,
        order_index=new_inst.order_index,
        kind=VisitKind.UNSCHEDULED.value,
        version=subject.active_version,
        offset_days=0,
        anchor_mode=AnchorMode.PREVIOUS_ACTUAL.value,
        planned_date=planned_utc,
        window_before=wb,
        window_after=wa,
        status=VisitStatus.SCHEDULED.value,
    )
    db.add(visit)
    db.flush()

    # 重排 order + 下游链式重算
    for iv in insts:
        if iv.inst_id:
            target = db.get(Visit, iv.inst_id)
            if target and not target.locked and target.order_index != iv.order_index:
                target.order_index = iv.order_index
    changes = sch.recompute_chain(insts, rand, STUDY_POLICY)
    _apply_chain_changes(db, subject, user, changes)
    add_audit(
        db, subject, user, "insert_unscheduled", visit=visit,
        new_date=planned_utc, reason=reason, detail=f"插入计划外访视：{name}",
    )
    db.commit()
    return visit


def set_locked(
    db: Session, subject: Subject, user: User, visit: Visit,
    locked: bool, reason: str,
) -> None:
    visit.locked = locked
    visit.locked_at = datetime.now() if locked else None
    visit.locked_by = user.full_name if locked else None
    add_audit(
        db, subject, user, "lock" if locked else "unlock",
        visit=visit, reason=reason,
        detail="锁库后访视计划/实际日期/表单全部冻结" if locked else "审批通过后解锁",
    )
    db.commit()


# ---------------------------------------------------------------------------
# 方案修订发布（研究级）
# ---------------------------------------------------------------------------
def get_current_version(db: Session) -> ProtocolVersion | None:
    return db.scalar(
        select(ProtocolVersion).where(ProtocolVersion.is_current.is_(True))
    )


def publish_revision(
    db: Session, user: User, *, version: str, title: str, change_note: str,
    effective_date: date, visits_in: list,
) -> dict:
    if db.scalar(select(ProtocolVersion).where(ProtocolVersion.version == version)):
        raise ValueError(f"方案版本号 {version} 已存在，不能重复发布。")

    current = get_current_version(db)
    if current:
        current.is_current = False

    pv = ProtocolVersion(
        version=version, title=title, change_note=change_note,
        effective_date=effective_date, published_by=user.full_name,
        is_current=True,
    )
    db.add(pv)
    db.flush()

    for tv in visits_in:
        tpl = VisitTemplate(
            protocol_version_id=pv.id,
            visit_no=tv.visit_no, name=tv.name, order_index=tv.order_index,
            offset_days=tv.offset_days, anchor_mode=tv.anchor_mode,
            window_before=tv.window_before, window_after=tv.window_after,
        )
        db.add(tpl)
        db.flush()
        for ff in tv.forms:
            db.add(
                TemplateForm(
                    template_id=tpl.id, form_key=ff.form_key, name=ff.name,
                    is_key=ff.is_key, total_fields=ff.total_fields,
                )
            )

    # 对所有已有访视的受试者切版（研究级修订）
    subjects = list(db.scalars(
        select(Subject)
        .where(Subject.visits.any())
        .execution_options(populate_existing=True)
    ))
    # 去重（any() 不会重复，但稳妥起见）
    seen: set[int] = set()
    upgraded_subjects = 0
    n_frozen = n_upgraded = n_dropped = 0
    affected: list[int] = []

    new_tpls = template_to_tpls(pv)
    tpl_by_no = {t.visit_no: t for t in new_tpls}

    for subject in subjects:
        if subject.id in seen:
            continue
        seen.add(subject.id)
        rand, insts = subject_insts(subject)
        old_versions = {i.version for i in insts if i.kind == VisitKind.PROTOCOL}
        result = sch.apply_revision(
            insts, new_tpls, version, effective_date, rand, STUDY_POLICY
        )
        if not result.mixed_versions and not result.dropped and old_versions == {version}:
            continue

        upgraded_subjects += 1
        affected.append(subject.id)
        subject.active_version = version

        n_frozen += sum(
            1 for i in result.kept if i.kind == VisitKind.PROTOCOL
        )

        for iv in result.upgraded:
            if iv.inst_id:
                orm = db.get(Visit, iv.inst_id)
                if orm:
                    orm.name = iv.name
                    orm.order_index = iv.order_index
                    orm.offset_days = iv.offset_days
                    orm.anchor_mode = iv.anchor_mode.value
                    orm.window_before = iv.window_before
                    orm.window_after = iv.window_after
                    orm.version = version
                    orm.pinned = False
                    if orm.status == VisitStatus.SCHEDULED.value and not orm.locked:
                        orm.planned_date = iv.planned_utc
                    n_upgraded += 1
            else:
                # 新版新增访视：实例化访视 + 新模板关键表单
                created = Visit(
                    subject_id=subject.id, site_id=subject.site_id,
                    visit_no=iv.visit_no, name=iv.name, order_index=iv.order_index,
                    kind=VisitKind.PROTOCOL.value, version=version,
                    offset_days=iv.offset_days, anchor_mode=iv.anchor_mode.value,
                    planned_date=iv.planned_utc,
                    window_before=iv.window_before, window_after=iv.window_after,
                    status=VisitStatus.SCHEDULED.value,
                )
                db.add(created)
                db.flush()
                tpl = tpl_by_no.get(iv.visit_no)
                if tpl:
                    for tf in tpl.forms:
                        db.add(
                            VisitForm(
                                visit_id=created.id, form_key=tf.form_key, name=tf.name,
                                is_key=tf.is_key, total_fields=tf.total_fields,
                                status=FormStatus.PENDING.value, filled_fields=0,
                            )
                        )
                n_upgraded += 1

        for iv in result.dropped:
            if iv.inst_id:
                orm = db.get(Visit, iv.inst_id)
                if orm and orm.status == VisitStatus.SCHEDULED.value and not orm.locked:
                    db.delete(orm)
                    n_dropped += 1

        add_audit(
            db, subject, user, "revision",
            visit_no=None,
            detail=(
                f"方案修订发布 {version}（{title}）：已完成/已跳过/锁库访视冻结旧版原样保留，"
                f"未发生访视切换新版；新增/升级 {n_upgraded}，删除 {n_dropped}。{change_note}"
            ),
        )

    db.commit()
    return {
        "version": version,
        "upgraded_subjects": upgraded_subjects,
        "frozen_visits": n_frozen,
        "upgraded_visits": n_upgraded,
        "dropped_visits": n_dropped,
        "affected_subject_ids": affected,
        "message": (
            f"方案 {version} 已发布：{upgraded_subjects} 名受试者存在新旧版本并存，"
            f"其已完成/已跳过/锁库访视冻结旧版，未发生访视已切换新版并在甘特图醒目标记。"
        ),
    }


# ---------------------------------------------------------------------------
# CSV 导出（与总览/详情同一数据源、同一完成度口径）
# ---------------------------------------------------------------------------
def export_csv(subjects: list[Subject], today_local: date, site_tz: str) -> str:
    buf = io.StringIO()
    buf.write("﻿")  # Excel 中文 BOM
    writer = csv.writer(buf)
    writer.writerow([
        "中心", "受试者编号", "筛选号", "访视号", "访视名称", "类型", "方案版本",
        "计划日期(中心本地)", "窗口起", "窗口止", "状态", "实际日期(中心本地)",
        "关键表单完成", "本访视完成度%", "受试者总完成度%", "锚点口径", "锁库",
    ])
    for subject in subjects:
        summary = subject_summary(subject, today_local)
        tz = subject.site.timezone
        for v in summary["visits"]:
            writer.writerow([
                summary["site_name"],
                subject.subject_code or "",
                subject.screening_no,
                v["visit_no"], v["name"], v["kind_label"], v["version"],
                v["planned_date"].isoformat(),
                (v["planned_date"] - timedelta(days=v["window_before"])).isoformat(),
                (v["planned_date"] + timedelta(days=v["window_after"])).isoformat(),
                v["visit_state_label"],
                v["actual_date"].isoformat() if v["actual_date"] else "",
                f'{v["key_form_done"]}/{v["key_form_total"]}',
                v["completion_percent"],
                summary["completion_percent"],
                v["anchor_mode_label"],
                "是" if v["locked"] else "否",
            ])
    return buf.getvalue()
