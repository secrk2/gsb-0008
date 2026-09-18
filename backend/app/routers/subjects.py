from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import schedule_service as svc
from .. import scheduling as sch
from ..database import get_db
from ..deps import assert_site_access, get_current_user, visible_site_ids
from ..domain import (
    ACTION_LABELS,
    Action,
    ALLOWED_TRANSITIONS,
    IllegalTransitionError,
    STATUS_LABELS,
    SubjectStatus,
    format_screening_no,
    format_subject_code,
    mask_name,
    transition,
    visit_state,
)
from ..models import (
    NumberAudit,
    PiiViewLog,
    ProtocolVersion,
    Site,
    Subject,
    SubjectStatusHistory,
    User,
    Visit,
)
from ..schemas import (
    HistoryItem,
    NumberAuditItem,
    PiiViewLogItem,
    RevealIn,
    RevealOut,
    SubjectCreateIn,
    SubjectDetail,
    SubjectListItem,
    SubjectOutCreated,
    TransitionIn,
    VisitOut,
)

router = APIRouter(prefix="/api/subjects", tags=["subjects"])

KIND_LABELS = {"screening": "筛选号", "subject": "受试者编号"}
NUMBER_STATUS_LABELS = {"assigned": "已分配", "voided": "已作废"}


def _mask_phone(phone: str | None) -> str | None:
    if not phone:
        return None
    if len(phone) <= 4:
        return "****"
    return phone[:3] + "*" * (len(phone) - 5) + phone[-2:]


def _next_visit_state(subject: Subject, today: date) -> tuple[date | None, str | None]:
    tz = subject.site.timezone if subject.site else "Asia/Shanghai"

    def local_day(v: Visit) -> date:
        return sch.utc_date_to_local(v.planned_date, tz)

    upcoming = [
        (v, local_day(v))
        for v in subject.visits
        if v.status == "scheduled" and local_day(v) >= today
    ]
    if not upcoming:
        # 窗内但计划日已过的也算待办
        pending = [(v, local_day(v)) for v in subject.visits if v.status == "scheduled"]
        if not pending:
            return None, None
        v, planned = sorted(pending, key=lambda x: x[1], reverse=True)[0]
    else:
        v, planned = sorted(upcoming, key=lambda x: x[1])[0]
    state = visit_state(planned, today, v.window_before, v.window_after, v.status)
    return planned, state.value


def _list_item(db: Session, subj: Subject, user: User, today: date) -> SubjectListItem:
    local_today = sch.site_local_today(subj.site.timezone if subj.site else "Asia/Shanghai")
    return SubjectListItem(
        id=subj.id,
        site_id=subj.site_id,
        site_code=subj.site.code,
        site_name=subj.site.name,
        screening_no=subj.screening_no,
        subject_code=subj.subject_code,
        display_name=mask_name(subj.full_name, subj.subject_code),
        gender=subj.gender,
        status=subj.status,
        status_label=STATUS_LABELS[SubjectStatus(subj.status)],
        screen_date=subj.screen_date,
        enroll_date=subj.enroll_date,
        end_date=subj.end_date,
        can_reveal=user.role == "investigator" and user.site_id == subj.site_id,
        next_visit_date=_next_visit_state(subj, local_today)[0],
        next_visit_state=_next_visit_state(subj, local_today)[1],
    )


@router.get("", response_model=list[SubjectListItem])
def list_subjects(
    status_filter: str | None = Query(default=None, alias="status"),
    site_id: int | None = None,
    keyword: str | None = None,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    if site_id is not None:
        assert_site_access(current, site_id)

    q = select(Subject).options(selectinload(Subject.visits), selectinload(Subject.site))
    scope = visible_site_ids(current)
    if scope is not None:
        q = q.where(Subject.site_id.in_(scope))
    if site_id is not None:
        q = q.where(Subject.site_id == site_id)
    if status_filter:
        try:
            SubjectStatus(status_filter)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"未知的受试者状态：{status_filter}")
        q = q.where(Subject.status == status_filter)
    if keyword:
        like = f"%{keyword.strip()}%"
        # 关键字只匹配编号，不参与明文姓名检索（避免脱敏绕过）
        q = q.where(
            Subject.screening_no.ilike(like) | Subject.subject_code.ilike(like)
        )

    subjects = list(db.scalars(q.order_by(Subject.id.desc())))
    today = date.today()
    return [_list_item(db, s, current, today) for s in subjects]


@router.post("", response_model=SubjectOutCreated, status_code=201)
def create_subject(
    body: SubjectCreateIn,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """筛选登记：立即分配筛选号（中心前缀-S顺序号），作废号不复用。"""
    if current.role not in ("investigator", "dm"):
        raise HTTPException(status_code=403, detail="仅研究者/数据管理员可登记筛选受试者。")
    assert_site_access(current, body.site_id)

    if current.role == "investigator":
        body.site_id = current.site_id  # 研究者只能登记到本中心

    # 行级锁取号，杜绝并发重号
    site = db.scalar(select(Site).where(Site.id == body.site_id).with_for_update())
    if not site:
        raise HTTPException(status_code=404, detail="研究中心不存在。")

    site.screen_cursor += 1
    seq = site.screen_cursor
    screening_no = format_screening_no(site.prefix, seq)

    subject = Subject(
        site_id=site.id,
        screening_no=screening_no,
        screen_seq=seq,
        full_name=body.full_name,
        gender=body.gender,
        birth_date=body.birth_date,
        phone=body.phone,
        status=SubjectStatus.SCREENING.value,
        screen_date=date.today(),
        created_by=current.id,
    )
    db.add(subject)
    db.flush()
    db.add(
        NumberAudit(
            site_id=site.id,
            kind="screening",
            number=screening_no,
            seq=seq,
            status="assigned",
            subject_id=subject.id,
            operator_id=current.id,
            operator_name=current.full_name,
        )
    )
    db.add(
        SubjectStatusHistory(
            subject_id=subject.id,
            from_status=None,
            action="register",
            to_status=SubjectStatus.SCREENING.value,
            reason="筛选登记",
            operator_id=current.id,
            operator_name=current.full_name,
        )
    )
    db.commit()
    return SubjectOutCreated(id=subject.id, screening_no=screening_no, status=subject.status)


def _get_subject_or_403(db: Session, subject_id: int, user: User) -> Subject:
    """存在但跨中心 -> 明确 403 错误态；不存在 -> 404。前端均展示明确文案而非空白页。"""
    subject = db.scalar(
        select(Subject)
        .options(
            selectinload(Subject.site),
            selectinload(Subject.visits).selectinload(Visit.forms),
            selectinload(Subject.histories),
            selectinload(Subject.number_audits),
        )
        .where(Subject.id == subject_id)
    )
    if not subject:
        raise HTTPException(status_code=404, detail="受试者不存在或已被删除。")
    assert_site_access(user, subject.site_id)
    return subject


@router.get("/{subject_id}", response_model=SubjectDetail)
def subject_detail(
    subject_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    subject = _get_subject_or_403(db, subject_id, current)
    tz_name = subject.site.timezone
    today = sch.site_local_today(tz_name)
    next_date, next_state = _next_visit_state(subject, today)
    current_status = SubjectStatus(subject.status)

    # 访视与完成度统一走 schedule_service，保证与总览/导出三处一致
    summary = svc.subject_summary(subject, today)
    visits = [VisitOut(**v) for v in summary["visits"]]
    rand_date = svc.randomization_date(subject)

    ACTION_DISPLAY = {**{a.value: a.label for a in Action}, "register": "筛选登记"}
    histories = [
        HistoryItem(
            id=h.id,
            from_status=h.from_status,
            from_status_label=STATUS_LABELS[SubjectStatus(h.from_status)]
            if h.from_status
            else None,
            action=h.action,
            action_label=ACTION_DISPLAY.get(h.action, h.action),
            to_status=h.to_status,
            to_status_label=STATUS_LABELS[SubjectStatus(h.to_status)],
            reason=h.reason,
            operator_name=h.operator_name,
            created_at=h.created_at,
        )
        for h in sorted(subject.histories, key=lambda x: x.id)
    ]

    audits = [
        NumberAuditItem(
            id=a.id,
            kind=a.kind,
            kind_label=KIND_LABELS.get(a.kind, a.kind),
            number=a.number,
            seq=a.seq,
            status=a.status,
            status_label=NUMBER_STATUS_LABELS.get(a.status, a.status),
            reason=a.reason,
            operator_name=a.operator_name,
            created_at=a.created_at,
        )
        for a in sorted(subject.number_audits, key=lambda x: x.id)
    ]

    logs = db.scalars(
        select(PiiViewLog)
        .where(PiiViewLog.subject_id == subject.id)
        .order_by(PiiViewLog.id.desc())
        .limit(20)
    )
    pii_logs = [
        PiiViewLogItem(
            id=l.id,
            viewer_name=l.viewer_name,
            viewer_username=l.viewer_username,
            reason=l.reason,
            created_at=l.created_at,
        )
        for l in logs
    ]

    return SubjectDetail(
        id=subject.id,
        site_id=subject.site_id,
        site_code=subject.site.code,
        site_name=subject.site.name,
        screening_no=subject.screening_no,
        subject_code=subject.subject_code,
        display_name=mask_name(subject.full_name, subject.subject_code),
        gender=subject.gender,
        status=subject.status,
        status_label=STATUS_LABELS[current_status],
        screen_date=subject.screen_date,
        enroll_date=subject.enroll_date,
        end_date=subject.end_date,
        completion_date=subject.completion_date,
        can_reveal=current.role == "investigator" and current.site_id == subject.site_id,
        next_visit_date=next_date,
        next_visit_state=next_state,
        phone_masked=_mask_phone(subject.phone),
        histories=histories,
        number_audits=audits,
        visits=visits,
        pii_view_logs=pii_logs,
        allowed_actions=sorted(a.value for a in ALLOWED_TRANSITIONS[current_status]),
        randomization_date=rand_date,
        active_version=subject.active_version,
        mixed_versions=summary["mixed_versions"],
        completion_percent=summary["completion_percent"],
        completion_label=summary["completion_label"],
        completion_basis=svc.COMPLETION_BASIS,
        policy=svc.STUDY_POLICY.value,
        policy_label=sch.ANCHOR_POLICY_LABELS[svc.STUDY_POLICY],
        timezone=tz_name,
    )


@router.post("/{subject_id}/transition")
def transition_subject(
    subject_id: int,
    body: TransitionIn,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    if current.role not in ("investigator", "dm"):
        raise HTTPException(status_code=403, detail="仅研究者/数据管理员可变更受试者状态。")
    subject = _get_subject_or_403(db, subject_id, current)

    try:
        action = Action(body.action)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"未知操作：{body.action}")

    current_status = SubjectStatus(subject.status)
    try:
        target = transition(current_status, action, body.reason)
    except IllegalTransitionError as exc:
        # 非法状态回退必须拦截并说明原因（409 业务冲突，前端原样展示）
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # 入组：分配受试者编号（中心前缀+顺序号，作废不复用，行锁防重号）
    if action == Action.ENROLL:
        site = db.scalar(
            select(Site).where(Site.id == subject.site_id).with_for_update()
        )
        site.enroll_cursor += 1
        seq = site.enroll_cursor
        code = format_subject_code(site.prefix, seq)
        subject.subject_code = code
        subject.enroll_seq = seq
        local_today = sch.site_local_today(site.timezone)
        subject.enroll_date = local_today
        # 随机化日主锚点（默认等于入组日）
        subject.randomization_date = local_today
        db.add(
            NumberAudit(
                site_id=site.id,
                kind="subject",
                number=code,
                seq=seq,
                status="assigned",
                subject_id=subject.id,
                reason="入组分配",
                operator_id=current.id,
                operator_name=current.full_name,
            )
        )
        # 入组即按当前生效方案版本生成访视与关键表单实例
        current_pv = svc.get_current_version(db)
        if current_pv is not None:
            svc.instantiate_subject_visits(db, subject, current_pv, rand=local_today)

    today = date.today()
    if action == Action.COMPLETE:
        subject.completion_date = today
    if action in (Action.DROPOUT, Action.TERMINATE, Action.SCREEN_FAIL, Action.REMOVE):
        subject.end_date = today

    subject.status = target.value
    history = SubjectStatusHistory(
        subject_id=subject.id,
        from_status=current_status.value,
        action=action.value,
        to_status=target.value,
        reason=(body.reason.strip() if body.reason else None),
        operator_id=current.id,
        operator_name=current.full_name,
    )
    db.add(history)
    db.commit()
    return {
        "status": subject.status,
        "status_label": STATUS_LABELS[target],
        "subject_code": subject.subject_code,
        "message": f"操作成功：受试者已变更为「{STATUS_LABELS[target]}」。",
    }


@router.post("/{subject_id}/reveal", response_model=RevealOut)
def reveal_name(
    subject_id: int,
    body: RevealIn,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """全名查看：仅本中心研究者，二次确认+填写理由，查看行为留痕。"""
    subject = _get_subject_or_403(db, subject_id, current)

    if current.role != "investigator":
        role_name = {"dm": "数据管理员", "monitor": "监查员"}.get(current.role, current.role)
        raise HTTPException(
            status_code=403,
            detail=(
                f"{role_name}账号无权查看受试者全名（GCP 最小必要原则）。"
                "如因数据核查需要，请联系本中心研究者操作并留痕。"
            ),
        )
    if current.site_id != subject.site_id:
        # 理论上 assert_site_access 已拦截，此处双保险
        raise HTTPException(status_code=403, detail="仅可查看本中心受试者的全名。")
    if subject.subject_code is None:
        raise HTTPException(status_code=400, detail="受试者尚未入组编号，暂不提供脱敏解除。")

    log = PiiViewLog(
        subject_id=subject.id,
        site_id=subject.site_id,
        viewer_id=current.id,
        viewer_name=current.full_name,
        viewer_username=current.username,
        reason=body.reason.strip(),
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return RevealOut(
        full_name=subject.full_name,
        logged_at=log.created_at,
        message="本次全名查看已记录至稽查轨迹（操作人、时间、理由）。",
    )
