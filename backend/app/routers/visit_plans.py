"""访视计划路由：甘特总览 / 受试者访视详情 / 改期 / 跳过 / 计划外访视 /
方案修订发布 / CSV 导出 / 口径与方案定义。

所有完成度均来自 visit_service（与详情、导出同一函数）；
“今天”按研究中心所在时区取当地日历日；
改期落点超窗必须二次确认并强制填写原因，全部写入 VisitAudit 留痕。
"""
from __future__ import annotations

import csv
import io
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import tz
from ..database import get_db
from ..deps import assert_site_access, get_current_user, visible_site_ids
from ..domain import (
    AMENDMENT_FREEZE_TEXT,
    ANCHOR_POLICY_TEXT,
    COMPLETION_POLICY_TEXT,
    VISIT_UNSCHEDULED,
    ScheduleError,
    in_window,
    insert_unscheduled,
    reschedule_chain,
    skip_visit,
)
from ..models import (
    ProtocolFormDef,
    ProtocolVersion,
    ProtocolVisitDef,
    Site,
    Subject,
    User,
    Visit,
    VisitAudit,
)
from .. import visit_service as svc

router = APIRouter(prefix="/api/visit-plans", tags=["visit-plans"])

REASON_MIN = 5


# ---------------------------------------------------------------------------
# 请求体
# ---------------------------------------------------------------------------
class RescheduleIn(BaseModel):
    new_date: date
    reason: str | None = None
    confirm_out_of_window: bool = False


class SkipIn(BaseModel):
    reason: str = Field(min_length=5, max_length=200)


class UnscheduledIn(BaseModel):
    the_date: date
    name: str = Field(min_length=2, max_length=64)
    reason: str = Field(min_length=5, max_length=200)


class PublishAmendmentIn(BaseModel):
    version: str = Field(min_length=2, max_length=16)
    effective_date: date
    change_summary: str = Field(min_length=5, max_length=1000)
    # visit_no -> {day_offset, window_before, window_after, name?}
    visits: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------
def _require_editor(user: User, site_id: int) -> None:
    if user.role not in ("investigator", "dm"):
        raise HTTPException(
            status_code=403,
            detail="仅研究者/数据管理员可调整访视计划（监查员为只读角色）。",
        )
    assert_site_access(user, site_id)


def _load_subject(db: Session, subject_id: int, user: User) -> Subject:
    subject = db.scalar(
        select(Subject)
        .options(
            selectinload(Subject.site),
            selectinload(Subject.visits).selectinload(Visit.forms),
        )
        .where(Subject.id == subject_id)
    )
    if not subject:
        raise HTTPException(status_code=404, detail="受试者不存在或已被删除。")
    assert_site_access(user, subject.site_id)
    return subject


def _load_visit(db: Session, visit_id: int, user: User) -> tuple[Visit, Subject]:
    """读取访视 + 受试者（含中心、全部访视与表单），并做中心隔离校验。"""
    visit = db.get(Visit, visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="访视不存在或已被删除。")
    subject = db.scalar(
        select(Subject)
        .options(
            selectinload(Subject.site),
            selectinload(Subject.visits).selectinload(Visit.forms),
        )
        .where(Subject.id == visit.subject_id)
    )
    assert_site_access(user, visit.site_id)
    return visit, subject


def _apply_chain_changes(db, subject, changes: dict[int, date], operator: User,
                         trigger_visit_id: int, detail: str) -> None:
    """把链式重算结果落库，并为每个被带动的访视写 chain_recompute 留痕。"""
    visits = {v.id: v for v in subject.visits}
    for vid, new_d in changes.items():
        v = visits[vid]
        if vid == trigger_visit_id:
            continue
        old_d = v.planned_date
        v.planned_date = new_d
        db.add(VisitAudit(
            visit_id=v.id, subject_id=subject.id, site_id=subject.site_id,
            action="chain_recompute", old_date=old_d, new_date=new_d,
            detail=detail, operator_id=operator.id, operator_name=operator.full_name,
        ))


def _today_for(db: Session, user: User) -> date:
    if user.site_id is None:
        return tz.local_today("Asia/Shanghai")
    site = db.get(Site, user.site_id)
    return tz.local_today(site.timezone if site else "Asia/Shanghai")


# ---------------------------------------------------------------------------
# 口径与方案定义（界面明示，不让研究者猜）
# ---------------------------------------------------------------------------
@router.get("/policy")
def policy(db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    versions = []
    for ver in svc.all_protocol_versions(db):
        versions.append({
            "id": ver.id,
            "version": ver.version,
            "status": ver.status,
            "effective_date": ver.effective_date.isoformat(),
            "change_summary": ver.change_summary,
            "published_at": ver.published_at.isoformat() if ver.published_at else None,
            "visit_defs": [
                {
                    "visit_no": vd.visit_no, "name": vd.name,
                    "day_offset": vd.day_offset,
                    "window_before": vd.window_before, "window_after": vd.window_after,
                }
                for vd in sorted(ver.visit_defs, key=lambda x: x.seq)
            ],
        })
    return {
        "completion_basis": "key_forms",
        "completion_policy_text": COMPLETION_POLICY_TEXT,
        "anchor_policy_text": ANCHOR_POLICY_TEXT,
        "amendment_freeze_text": AMENDMENT_FREEZE_TEXT,
        "storage_tz_note": (
            "所有日期时刻按 UTC 存储，按研究中心所在时区展示；"
            "“今天/是否同一天/窗期”均以研究中心当地日历日判定（含夏令时）。"
        ),
        "versions": versions,
    }


# ---------------------------------------------------------------------------
# 甘特总览
# ---------------------------------------------------------------------------
@router.get("/gantt")
def gantt(
    site_id: int | None = None,
    subject_id: int | None = None,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    # 读前先跑幂等清扫：到生效日的修订把未发生访视切到新版（逐条留痕）
    svc.activate_due_amendments(db)

    scope = visible_site_ids(current)
    if site_id is not None:
        assert_site_access(current, site_id)
        scope = [site_id]
    pairs = svc.load_subjects(db, scope)
    if subject_id is not None:
        pairs = [p for p in pairs if p[0].id == subject_id]
        if not pairs:
            raise HTTPException(status_code=404, detail="受试者不存在或无权访问。")

    # 每个中心按其所在时区分别取“今天”，避免跨时区 DM 看到错误的窗期红点
    rows_by_site: dict[int, list[dict]] = {}
    for subject, site in pairs:
        today = tz.local_today(site.timezone)
        rows_by_site.setdefault(site.id, []).append(
            svc.serialize_subject_row(subject, site, today)
        )
    rows = [
        r for site_rows in rows_by_site.values()
        for r in sorted(site_rows, key=lambda x: x["subject_id"])
    ]
    return {
        "today": date.today().isoformat(),
        "completion_basis": "key_forms",
        "subjects": rows,
    }


# ---------------------------------------------------------------------------
# 受试者访视详情
# ---------------------------------------------------------------------------
AUDIT_ACTION_LABELS = {
    "reschedule": "窗内改期",
    "reschedule_out_of_window": "超窗改期（强制留痕）",
    "skip": "跳过访视",
    "insert_unscheduled": "插入计划外访视",
    "chain_recompute": "链式重算",
    "amendment_switch": "方案修订切换",
    "lock": "访视锁库",
    "complete": "完成访视",
}


@router.get("/subjects/{subject_id}/visits")
def subject_visits(
    subject_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    svc.activate_due_amendments(db)
    subject = _load_subject(db, subject_id, current)
    today = tz.local_today(subject.site.timezone)
    row = svc.serialize_subject_row(subject, subject.site, today)

    audits = db.scalars(
        select(VisitAudit)
        .where(VisitAudit.subject_id == subject_id)
        .order_by(VisitAudit.id.desc())
        .limit(100)
    )
    row["audits"] = [
        {
            "id": a.id,
            "visit_id": a.visit_id,
            "action": a.action,
            "action_label": AUDIT_ACTION_LABELS.get(a.action, a.action),
            "old_date": a.old_date.isoformat() if a.old_date else None,
            "new_date": a.new_date.isoformat() if a.new_date else None,
            "reason": a.reason,
            "detail": a.detail,
            "operator_name": a.operator_name,
            "created_at": tz.format_local(a.created_at, subject.site.timezone),
        }
        for a in audits
    ]
    row["can_edit"] = current.role in ("investigator", "dm")
    row["today"] = today.isoformat()
    return row


# ---------------------------------------------------------------------------
# 改期（拖拽落点）
# ---------------------------------------------------------------------------
@router.post("/visits/{visit_id}/reschedule")
def reschedule(
    visit_id: int,
    body: RescheduleIn,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    visit0, subject = _load_visit(db, visit_id, current)
    _require_editor(current, visit0.site_id)
    visit = next(v for v in subject.visits if v.id == visit_id)

    if visit.planned_date == body.new_date:
        raise HTTPException(status_code=400, detail="新日期与现行计划日相同，无需改期。")

    out_of_window = not in_window(
        visit.planned_date, body.new_date, visit.window_before, visit.window_after
    )
    if out_of_window:
        if not body.confirm_out_of_window:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "OUT_OF_WINDOW_CONFIRM",
                    "message": (
                        f"落点 {body.new_date} 超出该访视窗口"
                        f"（计划 {visit.planned_date}，允许 前{visit.window_before}/"
                        f"后{visit.window_after} 天）。超窗改期构成方案偏离，"
                        "必须二次确认并强制填写原因，留痕后才能执行。"
                    ),
                },
            )
        if not (body.reason and body.reason.strip() and len(body.reason.strip()) >= REASON_MIN):
            raise HTTPException(
                status_code=400,
                detail="超窗改期必须填写不少于 5 个字的原因（将写入稽查轨迹）。",
            )

    nodes = [svc.build_node(v) for v in svc.ordered_visits(subject)]
    old_date = visit.planned_date
    try:
        changes = reschedule_chain(nodes, visit_id, body.new_date)
    except ScheduleError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))

    visit.planned_date = body.new_date
    db.add(VisitAudit(
        visit_id=visit.id, subject_id=subject.id, site_id=subject.site_id,
        action="reschedule_out_of_window" if out_of_window else "reschedule",
        old_date=old_date, new_date=body.new_date,
        reason=body.reason.strip() if body.reason else None,
        detail=(
            f"超窗改期：原计划 {old_date}（窗口 前{visit.window_before}/"
            f"后{visit.window_after} 天）→ {body.new_date}，已二次确认。"
            if out_of_window else
            f"窗内改期：{old_date} → {body.new_date}。"
        ),
        operator_id=current.id, operator_name=current.full_name,
    ))
    chain_ids = [vid for vid in changes if vid != visit_id]
    if chain_ids:
        _apply_chain_changes(
            db, subject, {k: changes[k] for k in chain_ids}, current, visit_id,
            detail=f"由访视 {visit.visit_no} 改期（{old_date}→{body.new_date}）"
                   f"触发的链式重算，已保持方案相对间隔，未改动已完成/已锁库访视。",
        )
    db.commit()
    return {
        "message": (
            f"改期成功：{visit.name} {old_date} → {body.new_date}"
            + ("（超窗，原因已留痕）" if out_of_window else "（窗内）")
            + (f"，并链式重算 {len(chain_ids)} 次后续访视。" if chain_ids else "。")
        ),
        "out_of_window": out_of_window,
        "chain_changed": len(chain_ids),
    }


# ---------------------------------------------------------------------------
# 跳过
# ---------------------------------------------------------------------------
@router.post("/visits/{visit_id}/skip")
def skip(
    visit_id: int,
    body: SkipIn,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    visit0, subject = _load_visit(db, visit_id, current)
    _require_editor(current, visit0.site_id)
    visit = next(v for v in subject.visits if v.id == visit_id)

    nodes = [svc.build_node(v) for v in svc.ordered_visits(subject)]
    old_date = visit.planned_date
    try:
        changes = skip_visit(nodes, visit_id)
    except ScheduleError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))

    visit.status = "skipped"
    visit.actual_date = None
    db.add(VisitAudit(
        visit_id=visit.id, subject_id=subject.id, site_id=subject.site_id,
        action="skip", old_date=old_date, new_date=old_date,
        reason=body.reason.strip(),
        detail="访视按方案允许被跳过（不删除、不占执行）；后续访视按链式口径保持。",
        operator_id=current.id, operator_name=current.full_name,
    ))
    chain_ids = [vid for vid in changes if vid != visit_id]
    if chain_ids:
        _apply_chain_changes(
            db, subject, {k: changes[k] for k in chain_ids}, current, visit_id,
            detail=f"由跳过 {visit.visit_no} 触发的链式重算。",
        )
    db.commit()
    return {"message": f"已跳过「{visit.name}」，原因已留痕；访视保留在方案序列中。"}


# ---------------------------------------------------------------------------
# 插入计划外访视
# ---------------------------------------------------------------------------
@router.post("/subjects/{subject_id}/unscheduled-visits", status_code=201)
def add_unscheduled(
    subject_id: int,
    body: UnscheduledIn,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    subject = _load_subject(db, subject_id, current)
    _require_editor(current, subject.site_id)

    ver = svc.current_protocol(db)
    existing_u = sum(1 for v in subject.visits if v.kind == VISIT_UNSCHEDULED)
    visit_no = f"U{existing_u + 1}"

    # 先只基于“既有访视”算序位与链式顺延（领域函数会自行追加临时节点），
    # 避免新建 ORM 对象经反向关系混入 subject.visits 造成重复节点
    nodes = [svc.build_node(v) for v in svc.ordered_visits(subject)]
    try:
        new_node, changes = insert_unscheduled(nodes, -1, body.the_date)
    except ScheduleError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))

    new_visit = Visit(
        subject_id=subject.id, site_id=subject.site_id,
        visit_no=visit_no, name=body.name.strip(),
        planned_date=body.the_date, nominal_date=body.the_date,
        seq=new_node.seq,
        window_before=0, window_after=0, status=VISIT_UNSCHEDULED,
        actual_date=body.the_date, kind=VISIT_UNSCHEDULED,
        protocol_version_id=ver.id if ver else None,
        version_label=ver.version if ver else None,
        insert_reason=body.reason.strip(),
    )
    db.add(new_visit)
    db.flush()

    db.add(VisitAudit(
        visit_id=new_visit.id, subject_id=subject.id, site_id=subject.site_id,
        action="insert_unscheduled", new_date=body.the_date,
        reason=body.reason.strip(),
        detail=f"插入计划外访视「{body.name.strip()}」于 {body.the_date}；"
               f"后续未发生访视顺延 {len(changes)} 次。",
        operator_id=current.id, operator_name=current.full_name,
    ))
    _apply_chain_changes(
        db, subject, changes, current, new_visit.id,
        detail=f"由计划外访视 {visit_no}（{body.the_date}）触发的链式顺延，"
               "已完成/已锁库访视未改动。",
    )
    db.commit()
    return {
        "id": new_visit.id,
        "visit_no": visit_no,
        "message": f"已插入计划外访视「{body.name}」，并顺延 {len(changes)} 次后续访视。",
    }


# ---------------------------------------------------------------------------
# 方案修订发布（DM）
# ---------------------------------------------------------------------------
@router.post("/amendments/publish")
def publish_amendment(
    body: PublishAmendmentIn,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    if current.role != "dm":
        raise HTTPException(status_code=403, detail="仅数据管理员可发布方案修订版本。")
    if db.scalar(select(ProtocolVersion).where(ProtocolVersion.version == body.version)):
        raise HTTPException(status_code=400, detail=f"版本号 {body.version} 已存在。")
    if body.effective_date < _today_for(db, current):
        raise HTTPException(status_code=400, detail="修订生效日不能早于今天（不允许追溯发布）。")

    old = svc.current_protocol(db)
    new_ver = ProtocolVersion(
        # scheduled 待生效：生效日到达前旧版仍为 effective，不影响新入组排程
        version=body.version, status="scheduled",
        effective_date=body.effective_date, change_summary=body.change_summary,
        published_by=current.id, published_at=tz.now_utc(),
    )
    db.add(new_ver)
    db.flush()
    for seq, item in enumerate(body.visits):
        db.add(ProtocolVisitDef(
            version_id=new_ver.id, visit_no=item["visit_no"],
            name=item.get("name", item["visit_no"]),
            day_offset=int(item["day_offset"]),
            window_before=int(item.get("window_before", 3)),
            window_after=int(item.get("window_after", 3)), seq=seq,
        ))
    # 关键表单目录沿用上一版（按访视号匹配），保证新版访视仍有完成度分母
    if old:
        for fd in old.form_defs:
            db.add(ProtocolFormDef(
                version_id=new_ver.id, visit_no=fd.visit_no, form_code=fd.form_code,
                form_name=fd.form_name, is_key=fd.is_key, field_count=fd.field_count,
                kind=fd.kind, seq=fd.seq,
            ))
    # 旧版不在此刻置 superseded —— 由生效清扫在生效日当天切换
    db.commit()
    return {
        "message": (
            f"方案修订 {body.version} 已发布，将于 {body.effective_date} 生效。"
            "生效日之前已完成/已锁库的访视继续冻结在旧版本，"
            "生效日尚未发生的访视自动切换到新版本，跨版本受试者界面将挂显着眼横幅。"
        )
    }


# ---------------------------------------------------------------------------
# CSV 导出（与总览、详情同一完成度计算）
# ---------------------------------------------------------------------------
@router.get("/export.csv")
def export_csv(
    site_id: int | None = None,
    subject_id: int | None = None,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    scope = visible_site_ids(current)
    if site_id is not None:
        assert_site_access(current, site_id)
        scope = [site_id]
    pairs = svc.load_subjects(db, scope)
    if subject_id is not None:
        pairs = [p for p in pairs if p[0].id == subject_id]

    buf = io.StringIO()
    buf.write("﻿")  # Excel UTF-8 BOM
    writer = csv.writer(buf)
    writer.writerow([
        "中心", "筛选号", "受试者编号", "脱敏姓名", "访视号", "访视名称", "类型",
        "方案版本", "相对随机化天数", "名义计划日(随机化口径)", "现行计划日(执行口径)",
        "口径差异天数", "窗口(前/后)", "实际访视日", "访视状态", "窗期判定",
        "已完成关键表单数", "关键表单总数", "完成度%(关键表单口径)",
        "已提交字段数", "字段总数", "字段口径对照%(不作为正式数字)", "锁库",
    ])
    for subject, site in pairs:
        today = tz.local_today(site.timezone)
        row = svc.serialize_subject_row(subject, site, today)
        for v in row["visits"]:
            c = v["completion"]
            writer.writerow([
                site.name, subject.screening_no, subject.subject_code or "",
                row["masked_name"], v["visit_no"], v["name"], v["kind_label"],
                v["version_label"] or "", v["day_offset"] if v["day_offset"] is not None else "",
                v["nominal_date"], v["planned_date"], v["divergence_days"],
                f"前{v['window_before']}/后{v['window_after']}",
                v["actual_date"] or "", v["status_label"], v["visit_state_label"],
                c["key_done"], c["key_total"], c["rate"],
                c["field_submitted"], c["field_total"], c["field_rate"],
                "是" if v["locked"] else "否",
            ])
        # 每个受试者一行汇总，保证导出里的受试者完成度与界面完全同源
        c = row["completion"]
        writer.writerow([
            site.name, subject.screening_no, subject.subject_code or "",
            row["masked_name"], "—", "【受试者汇总】", "", "", "", "", "", "", "", "",
            row["subject_status_label"], "",
            c["key_done"], c["key_total"], c["rate"],
            c["field_submitted"], c["field_total"], c["field_rate"], "",
        ])

    filename = f"visit-plan-export-{date.today().isoformat()}.csv"
    return Response(
        buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
