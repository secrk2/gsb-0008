"""幂等种子数据：中心 / 三类账号 / 多状态受试者 / 方案版本与访视模板 /
访视实例与关键表单 / 作废号 / PII 查看留痕 / 排程留痕。

访视计划相关事实：
- 方案版本 v1.0 与修订版 v1.1（当前）；在研受试者呈「已完成访视冻结 v1.0、
  未发生访视切换 v1.1」的新旧并存状态，甘特图有醒目提示。
- 访视日期相对“今天”生成，任何一天拉起都能看到今日应随访 / 逾期 / 超窗红点。
- 含锁库访视、计划外访视、全部跳过受试者、只填了半张关键表单的访视等演示局面。
"""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from . import scheduling as sch
from .database import Base, SessionLocal, engine
from .domain import Action, SubjectStatus, format_screening_no, format_subject_code
from .models import (
    NumberAudit,
    PiiViewLog,
    ProtocolVersion,
    Site,
    Subject,
    SubjectStatusHistory,
    TemplateForm,
    User,
    Visit,
    VisitForm,
    VisitScheduleAudit,
    VisitTemplate,
)
from .scheduling import AnchorMode, AnchorPolicy, FormStatus, VisitKind, VisitStatus
from .security import hash_password

PASSWORD = "Suyuan@2026"
TODAY = date.today()


def d(offset: int) -> date:
    return TODAY + timedelta(days=offset)


def wait_for_db(retries: int = 30, delay: float = 2.0) -> None:
    for i in range(retries):
        try:
            with engine.connect() as conn:
                conn.exec_driver_sql("SELECT 1")
            return
        except OperationalError:
            print(f"[seed] 等待数据库就绪…({i + 1}/{retries})")
            time.sleep(delay)
    raise RuntimeError("数据库在限定时间内未就绪")


def add_history(db, subject, action, to_status, operator, reason=None, from_status=None):
    db.add(
        SubjectStatusHistory(
            subject_id=subject.id,
            from_status=from_status,
            action=action,
            to_status=to_status,
            reason=reason,
            operator_id=operator.id,
            operator_name=operator.full_name,
        )
    )


def add_number_audit(db, site, kind, seq, operator, subject_id=None,
                     status="assigned", reason=None):
    number = (
        format_screening_no(site.prefix, seq)
        if kind == "screening"
        else format_subject_code(site.prefix, seq)
    )
    db.add(
        NumberAudit(
            site_id=site.id,
            kind=kind,
            number=number,
            seq=seq,
            status=status,
            subject_id=subject_id,
            reason=reason,
            operator_id=operator.id,
            operator_name=operator.full_name,
        )
    )


def make_subject(db, site, spec, operator):
    """spec: dict(sseq, name, gender, birth, phone, screen_offset,
    status, eseq=None, enroll_offset=None, end_offset=None, completion_offset=None,
    rand_offset=None)"""
    subject = Subject(
        site_id=site.id,
        screening_no=format_screening_no(site.prefix, spec["sseq"]),
        screen_seq=spec["sseq"],
        full_name=spec["name"],
        gender=spec["gender"],
        birth_date=spec["birth"],
        phone=spec["phone"],
        status=spec["status"],
        screen_date=d(spec["screen_offset"]),
        created_by=operator.id,
    )
    db.add(subject)
    db.flush()
    add_number_audit(db, site, "screening", spec["sseq"], operator, subject.id)
    add_history(db, subject, "register", SubjectStatus.SCREENING.value,
                operator, reason="筛选登记")

    eseq = spec.get("eseq")
    if eseq is not None:
        subject.subject_code = format_subject_code(site.prefix, eseq)
        subject.enroll_seq = eseq
        subject.enroll_date = d(spec["enroll_offset"])
        # 随机化日主锚点（默认等于入组日；个别受试者演示导入期差异）
        subject.randomization_date = d(spec.get("rand_offset", spec["enroll_offset"]))
        add_number_audit(db, site, "subject", eseq, operator, subject.id,
                         reason="入组分配")
        add_history(db, subject, Action.ENROLL.value,
                    SubjectStatus.ENROLLED.value, operator,
                    from_status=SubjectStatus.SCREENING.value)

    status = spec["status"]
    if status == SubjectStatus.SCREEN_FAILED.value:
        subject.end_date = d(spec["end_offset"])
        add_history(db, subject, Action.SCREEN_FAIL.value, status, operator,
                    reason=spec["reason"],
                    from_status=SubjectStatus.SCREENING.value)
    elif status in (SubjectStatus.DROPPED.value, SubjectStatus.TERMINATED.value,
                    SubjectStatus.REMOVED.value):
        subject.end_date = d(spec["end_offset"])
        action = {
            SubjectStatus.DROPPED.value: Action.DROPOUT.value,
            SubjectStatus.TERMINATED.value: Action.TERMINATE.value,
            SubjectStatus.REMOVED.value: Action.REMOVE.value,
        }[status]
        add_history(db, subject, action, status, operator, reason=spec["reason"],
                    from_status=SubjectStatus.ENROLLED.value)
    elif status == SubjectStatus.COMPLETED.value:
        subject.completion_date = d(spec["completion_offset"])
        add_history(db, subject, Action.COMPLETE.value, status, operator,
                    from_status=SubjectStatus.ENROLLED.value)
    return subject


# ---------------------------------------------------------------------------
# 方案模板定义
# ---------------------------------------------------------------------------
# (visit_no, 名称, 顺序, 相对天数, 锚点, 窗前, 窗后, 关键表单[(key,名称,字段数)])
V10_TEMPLATE = [
    ("V1", "基线访视", 10, 0, "randomization", 3, 3, [
        ("demog", "人口学资料", 10), ("medhx", "既往病史与合并用药", 8)]),
    ("V2", "第2周访视", 20, 14, "previous_actual", 3, 3, [
        ("vitals", "生命体征", 6), ("lab", "实验室检查", 12)]),
    ("V3", "第4周访视", 30, 14, "previous_actual", 3, 3, [
        ("vitals", "生命体征", 6), ("lab", "实验室检查", 12),
        ("adherence", "用药依从性", 8)]),
    ("V4", "第8周访视", 40, 28, "previous_actual", 5, 5, [
        ("lab", "实验室检查", 12), ("ecg", "心电图", 5)]),
    ("V5", "末次访视", 50, 84, "randomization", 5, 5, [
        ("efficacy", "疗效评估", 10), ("safety", "安全性总结", 8)]),
]

# v1.1：新增第6周电话安全性随访（V45），其余访视号不变（偏移/窗口微调）
V11_EXTRA = ("V45", "第6周电话安全性随访", 35, 14, "previous_actual", 2, 2, [
    ("safety_call", "电话安全性随访问卷", 6)])

V11_TEMPLATE = sorted(V10_TEMPLATE + [V11_EXTRA], key=lambda r: r[2])


def create_protocol(db):
    def build(version, title, note, effective, current, rows):
        pv = ProtocolVersion(
            version=version, title=title, change_note=note,
            effective_date=effective, published_by="何敏（数据管理员）",
            is_current=current,
        )
        db.add(pv)
        db.flush()
        for no, name, order, off, anchor, wb, wa, forms in rows:
            tpl = VisitTemplate(
                protocol_version_id=pv.id, visit_no=no, name=name, order_index=order,
                offset_days=off, anchor_mode=anchor, window_before=wb, window_after=wa,
            )
            db.add(tpl)
            db.flush()
            for key, fname, fields in forms:
                db.add(TemplateForm(
                    template_id=tpl.id, form_key=key, name=fname, is_key=True,
                    total_fields=fields,
                ))
        return pv

    v10 = build(
        "v1.0", "研究方案 v1.0（初始版）", "首次生效方案。",
        d(-180), False, V10_TEMPLATE,
    )
    v11_rows = [r for r in V10_TEMPLATE]
    v11_rows = sorted(v11_rows + [V11_EXTRA], key=lambda r: r[2])
    v11 = build(
        "v1.1", "研究方案 v1.1（增加第6周电话随访）",
        "1) 新增第6周电话安全性随访（V45）；2) 第8周窗期由±3天放宽至±5天；"
        "3) 已完成/已跳过/锁库访视冻结 v1.0 原样保留，未发生访视自生效日起切换本版。",
        d(-7), True, v11_rows,
    )
    return v10, v11


def provision_visits(db, subject, template_rows, version):
    """按模板为入组受试者实例化访视与关键表单（计划日=随机化日+相对天数的
    方案链初值，previous_actual 按前序方案日递推）。"""
    rand = subject.randomization_date or subject.enroll_date
    prev_planned = None
    created = {}
    for no, name, order, off, anchor, wb, wa, forms in template_rows:
        if anchor == "randomization" or prev_planned is None:
            planned = rand + timedelta(days=off)
        else:
            planned = prev_planned + timedelta(days=off)
        prev_planned = planned
        v = Visit(
            subject_id=subject.id, site_id=subject.site_id, visit_no=no, name=name,
            order_index=order, kind=VisitKind.PROTOCOL.value, version=version,
            offset_days=off, anchor_mode=anchor, planned_date=planned,
            window_before=wb, window_after=wa, status=VisitStatus.SCHEDULED.value,
        )
        db.add(v)
        db.flush()
        for key, fname, fields in forms:
            db.add(VisitForm(
                visit_id=v.id, form_key=key, name=fname, is_key=True,
                status=FormStatus.PENDING.value, total_fields=fields, filled_fields=0,
            ))
        created[no] = v
    subject.active_version = version
    return created


def getv(subject, no):
    """按访视号取访视（直接查库，避免 subject_id= 直插导致关系集合未即时回填）。"""
    return db_scalar_visit(subject.id, no)


def db_scalar_visit(subject_id, no):
    from sqlalchemy import select as _select
    return _SESSION.scalar(
        _select(Visit).where(Visit.subject_id == subject_id, Visit.visit_no == no)
    )


_SESSION = None


def set_done(v, planned_off, actual_off):
    v.status = VisitStatus.DONE.value
    v.planned_date = d(planned_off)
    v.actual_date = d(actual_off)
    for f in v.forms:
        f.status = FormStatus.COMPLETE.value
        f.filled_fields = f.total_fields


def set_scheduled(v, planned_off, *, pin=False, window=None, incomplete=None):
    v.status = VisitStatus.SCHEDULED.value
    v.planned_date = d(planned_off)
    v.actual_date = None
    v.pinned = pin
    if window:
        v.window_before, v.window_after = window
    for f in v.forms:
        f.status = FormStatus.PENDING.value
        f.filled_fields = 0
    if incomplete:
        key, filled = incomplete
        ff = next((x for x in v.forms if x.form_key == key), None)
        if ff:
            ff.status = FormStatus.INCOMPLETE.value
            ff.filled_fields = filled


def set_skipped(v):
    v.status = VisitStatus.SKIPPED.value
    v.actual_date = None
    for f in v.forms:
        f.status = FormStatus.PENDING.value
        f.filled_fields = 0


def add_unscheduled(db, subject, no, name, planned_off, actual_off=None,
                    wb=3, wa=3, version="v1.0"):
    status = VisitStatus.DONE.value if actual_off is not None else VisitStatus.SCHEDULED.value
    v = Visit(
        subject_id=subject.id, site_id=subject.site_id, visit_no=no, name=name,
        order_index=25, kind=VisitKind.UNSCHEDULED.value, version=version,
        offset_days=0, anchor_mode=AnchorMode.PREVIOUS_ACTUAL.value,
        planned_date=d(planned_off), window_before=wb, window_after=wa,
        status=status, actual_date=d(actual_off) if actual_off is not None else None,
    )
    db.add(v)
    db.flush()
    db.add(VisitForm(
        visit_id=v.id, form_key="ae_assess", name="不良事件评估表", is_key=True,
        status=FormStatus.COMPLETE.value if actual_off is not None else FormStatus.PENDING.value,
        total_fields=6, filled_fields=6 if actual_off is not None else 0,
    ))
    return v


def add_schedule_audit(db, subject, operator, action, no, old_off, new_off,
                       reason, oow=False, detail=None):
    visit = db_scalar_visit(subject.id, no)
    db.add(VisitScheduleAudit(
        subject_id=subject.id, site_id=subject.site_id,
        visit_id=visit.id if visit else None,
        visit_no=no, action=action,
        old_date=d(old_off) if old_off is not None else None,
        new_date=d(new_off) if new_off is not None else None,
        reason=reason, out_of_window=oow, detail=detail,
        operator_id=operator.id, operator_name=operator.full_name,
    ))


def ensure_v45(db, subject, site, planned_off):
    """补齐 v1.1 新增的「第6周电话安全性随访 V45」（未发生，切换新版）。"""
    v = Visit(
        subject_id=subject.id, site_id=site.id, visit_no="V45",
        name="第6周电话安全性随访", order_index=35,
        kind=VisitKind.PROTOCOL.value, version="v1.1", offset_days=14,
        anchor_mode=AnchorMode.PREVIOUS_ACTUAL.value, planned_date=d(planned_off),
        window_before=2, window_after=2, status=VisitStatus.SCHEDULED.value,
    )
    db.add(v)
    db.flush()
    db.add(VisitForm(
        visit_id=v.id, form_key="safety_call", name="电话安全性随访问卷",
        is_key=True, status=FormStatus.PENDING.value, total_fields=6, filled_fields=0,
    ))
    return v


def seed() -> None:
    global _SESSION
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    _SESSION = db
    try:
        if db.scalar(select(User).where(User.username == "dm")):
            print("[seed] 数据已存在，跳过种子（幂等）")
            return

        dm = User(
            username="dm", password_hash=hash_password(PASSWORD),
            full_name="何敏", role="dm", site_id=None,
        )
        db.add(dm)
        sites: list[Site] = []
        investigators: dict[str, User] = {}
        for idx, s in enumerate([
            dict(code="SITE01", prefix="BJ", city="北京",
                 name="北京协和临床研究中心", pi="陈建华", target=30,
                 tz="Asia/Shanghai"),
            dict(code="SITE02", prefix="SH", city="上海",
                 name="上海瑞金临床药理中心", pi="黄志明", target=24,
                 tz="Asia/Shanghai"),
            dict(code="SITE03", prefix="GZ", city="广州",
                 name="广州中山医学研究中心", pi="林国栋", target=20,
                 tz="Asia/Shanghai"),
        ], start=1):
            site = Site(
                code=s["code"], prefix=s["prefix"], name=s["name"], city=s["city"],
                pi_name=s["pi"], target_enrollment=s["target"], timezone=s["tz"],
            )
            db.add(site)
            db.flush()
            sites.append(site)
            inv = User(
                username=f"inv{idx:02d}", password_hash=hash_password(PASSWORD),
                full_name=s["pi"], role="investigator", site_id=site.id,
            )
            mon = User(
                username=f"mon{idx:02d}",
                password_hash=hash_password(PASSWORD),
                full_name={1: "许静", 2: "马超", 3: "蒋帆"}[idx],
                role="monitor", site_id=site.id,
            )
            db.add_all([inv, mon])
            db.flush()
            investigators[s["prefix"]] = inv

        v10, v11 = create_protocol(db)
        db.flush()

        # ---------------- 中心1（BJ）----------------
        s1, inv1 = sites[0], investigators["BJ"]
        specs_bj = [
            dict(sseq=1, name="王建国", gender="男", birth=date(1968, 4, 12),
                 phone="13801011234", screen_offset=-120, eseq=1,
                 enroll_offset=-110, rand_offset=-110,
                 status=SubjectStatus.COMPLETED.value, completion_offset=-10),
            dict(sseq=2, name="李雪梅", gender="女", birth=date(1975, 9, 3),
                 phone="13901022233", screen_offset=-60, eseq=2,
                 enroll_offset=-28, status=SubjectStatus.ENROLLED.value),
            dict(sseq=3, name="张志强", gender="男", birth=date(1982, 1, 25),
                 phone="13701033344", screen_offset=-48, eseq=3,
                 enroll_offset=-17, status=SubjectStatus.ENROLLED.value),
            dict(sseq=4, name="刘思远", gender="男", birth=date(1990, 7, 8),
                 phone="13601044455", screen_offset=-3,
                 status=SubjectStatus.SCREENING.value),
            dict(sseq=6, name="赵雅琴", gender="女", birth=date(1986, 11, 19),
                 phone="13501055566", screen_offset=-2,
                 status=SubjectStatus.SCREENING.value),
            dict(sseq=7, name="孙浩然", gender="男", birth=date(1979, 3, 30),
                 phone="13401066677", screen_offset=-25,
                 status=SubjectStatus.SCREEN_FAILED.value, end_offset=-14,
                 reason="筛选期实验室检查不符合入排标准（HbA1c 超出允许范围）"),
            dict(sseq=8, name="周美玲", gender="女", birth=date(1971, 12, 2),
                 phone="13301077788", screen_offset=-70, eseq=4,
                 enroll_offset=-62, status=SubjectStatus.DROPPED.value,
                 end_offset=-20, reason="连续两次访视失访，电话/上门均无法联系，按方案判定脱落"),
            dict(sseq=9, name="吴凯", gender="男", birth=date(1964, 6, 15),
                 phone="13201088899", screen_offset=-55, eseq=5,
                 enroll_offset=-47, status=SubjectStatus.TERMINATED.value,
                 end_offset=-15, reason="发生严重不良事件（SAE），研究者从受试者安全出发中止其研究"),
            dict(sseq=10, name="郑丽娟", gender="女", birth=date(1988, 2, 27),
                 phone="13101099900", screen_offset=-40, eseq=6,
                 enroll_offset=-33, status=SubjectStatus.REMOVED.value,
                 end_offset=-8, reason="复核发现违反关键入选标准（误纳），按方案第6.3条剔除"),
            dict(sseq=11, name="冯磊", gender="男", birth=date(1984, 10, 5),
                 phone="13001100011", screen_offset=-20, eseq=8,
                 enroll_offset=-12, status=SubjectStatus.ENROLLED.value),
            # 全部访视已跳过的在研受试者（演示第三种空态）
            dict(sseq=12, name="许文静", gender="女", birth=date(1992, 3, 14),
                 phone="13001122233", screen_offset=-30, eseq=9,
                 enroll_offset=-22, status=SubjectStatus.ENROLLED.value),
        ]
        bj_subjects = [make_subject(db, s1, sp, inv1) for sp in specs_bj]

        add_number_audit(
            db, s1, "screening", 5, inv1, status="voided",
            reason="受试者登记当日撤回知情同意，筛选表作废，号码按SOP不复用",
        )
        add_number_audit(
            db, s1, "subject", 7, inv1, status="voided",
            reason="编号误操作预占，经复核未实际入组，按SOP作废且永不再分配",
        )

        bj_done, bj2, bj3 = bj_subjects[0], bj_subjects[1], bj_subjects[2]
        bj11, bj_skip = bj_subjects[9], bj_subjects[10]

        # 已完成：全部 v1.0、全部完成，末次访视锁库
        provision_visits(db, bj_done, V10_TEMPLATE, "v1.0")
        set_done(getv(bj_done, "V1"), -110, -109)
        set_done(getv(bj_done, "V2"), -96, -95)
        set_done(getv(bj_done, "V3"), -82, -83)
        set_done(getv(bj_done, "V4"), -54, -54)
        v5 = getv(bj_done, "V5")
        set_done(v5, -12, -12)
        v5.locked = True
        v5.locked_at = datetime.now() - timedelta(days=9)
        v5.locked_by = "何敏"
        bj_done.active_version = "v1.0"

        # 在研 bj2：V1 已完成（v1.0 冻结、锁库），V2 超窗（v1.1），
        # V3 今日应随访（v1.1，半张关键表单），V4/V5 未来；新增 V45；计划外 U1
        provision_visits(db, bj2, V10_TEMPLATE, "v1.0")
        set_done(getv(bj2, "V1"), -28, -27)
        getv(bj2, "V1").locked = True
        getv(bj2, "V1").locked_at = datetime.now() - timedelta(days=20)
        getv(bj2, "V1").locked_by = "何敏"
        set_scheduled(getv(bj2, "V2"), -10, pin=True)           # 超窗红点
        set_scheduled(getv(bj2, "V3"), 0, pin=True,
                      incomplete=("lab", 5))                     # 今日 + 半张表
        set_scheduled(getv(bj2, "V4"), 28)
        set_scheduled(getv(bj2, "V5"), 84)
        for no in ("V2", "V3", "V4", "V5"):
            getv(bj2, no).version = "v1.1"
        # v1.1 新增访视 V45（第6周电话安全性随访）
        ensure_v45(db, bj2, s1, 14)
        # 计划外访视（发热急诊评估，已完成）
        u1 = add_unscheduled(db, bj2, "U1", "计划外·发热急诊评估", -5, actual_off=-5)
        bj2.active_version = "v1.1"
        add_schedule_audit(
            db, bj2, inv1, "insert_unscheduled", "U1", None, -5,
            reason="受试者低热 38.2℃ 急诊就诊，研究者追加安全性评估访视",
            detail="插入计划外访视：计划外·发热急诊评估")
        add_schedule_audit(
            db, bj2, inv1, "reschedule", "V3", -2, 0,
            reason="受试者工作日无法到院，协调至今日周六随访，仍在原窗期内",
            detail="窗内改期")

        # 在研 bj3：V1 已完成（v1.0），V2 逾期（v1.1，窗后5天），V3 未来
        provision_visits(db, bj3, V10_TEMPLATE, "v1.0")
        set_done(getv(bj3, "V1"), -17, -16)
        set_scheduled(getv(bj3, "V2"), -2, pin=True, window=(3, 5))  # 逾期红点
        set_scheduled(getv(bj3, "V3"), 12)
        set_scheduled(getv(bj3, "V4"), 40)
        set_scheduled(getv(bj3, "V5"), 84)
        for no in ("V2", "V3", "V4", "V5"):
            getv(bj3, no).version = "v1.1"
        ensure_v45(db, bj3, s1, 26)
        bj3.active_version = "v1.1"

        # 脱落/中止/剔除：入组后已发生的访视完成（v1.0），其余跳过（v1.1）
        for subj in (bj_subjects[6], bj_subjects[7], bj_subjects[8]):
            provision_visits(db, subj, V10_TEMPLATE, "v1.0")
            set_done(getv(subj, "V1"), -60 if subj is bj_subjects[6] else -45,
                     -59 if subj is bj_subjects[6] else -44)
            for no in ("V2", "V3", "V4", "V5"):
                set_skipped(getv(subj, no))
                getv(subj, no).version = "v1.1"
            subj.active_version = "v1.1"

        # 在研 bj11：V1 窗内将至（+2），按当前 v1.1 模板（含第6周电话随访）
        provision_visits(db, bj11, V11_TEMPLATE, "v1.1")
        bj11.active_version = "v1.1"

        # 在研 bj_skip：全部访视跳过（演示第三种空态）
        provision_visits(db, bj_skip, V11_TEMPLATE, "v1.1")
        for no, *_ in V11_TEMPLATE:
            set_skipped(getv(bj_skip, no))
        add_schedule_audit(
            db, bj_skip, inv1, "skip", "V1", None, None,
            reason="受试者入组后因故长期异地，经沟通本次研究全部访视暂不执行，逐次标记跳过",
            detail="访视标记跳过，不计入完成度分母")

        # PII 查看留痕示例
        pii_log = PiiViewLog(
            subject_id=bj2.id, site_id=s1.id,
            viewer_id=inv1.id, viewer_name=inv1.full_name,
            viewer_username=inv1.username,
            reason="SDV源数据核查：核对门诊病历与CRF中的受试者姓名一致性",
        )
        db.add(pii_log)
        db.flush()
        pii_log.created_at = datetime.now() - timedelta(days=2)

        s1.screen_cursor = 12
        s1.enroll_cursor = 9

        # ---------------- 中心2（SH）----------------
        s2, inv2 = sites[1], investigators["SH"]
        specs_sh = [
            dict(sseq=1, name="褚红军", gender="男", birth=date(1970, 8, 18),
                 phone="13802111234", screen_offset=-100, eseq=1,
                 enroll_offset=-92, status=SubjectStatus.COMPLETED.value,
                 completion_offset=-6),
            dict(sseq=2, name="卫春晓", gender="女", birth=date(1983, 5, 6),
                 phone="13902122233", screen_offset=-50, eseq=2,
                 enroll_offset=-28, status=SubjectStatus.ENROLLED.value),
            dict(sseq=3, name="蒋涛", gender="男", birth=date(1977, 2, 14),
                 phone="13702133344", screen_offset=-30, eseq=3,
                 enroll_offset=-20, rand_offset=-27,  # 导入期：随机化早于入组7天
                 status=SubjectStatus.ENROLLED.value),
            dict(sseq=4, name="沈佳怡", gender="女", birth=date(1992, 9, 21),
                 phone="13602144455", screen_offset=-4,
                 status=SubjectStatus.SCREENING.value),
            dict(sseq=6, name="韩梅", gender="女", birth=date(1985, 12, 1),
                 phone="13502155566", screen_offset=-18,
                 status=SubjectStatus.SCREEN_FAILED.value, end_offset=-9,
                 reason="筛选期影像学复核发现排除项（活动性肝病）"),
            dict(sseq=7, name="杨光", gender="男", birth=date(1969, 3, 28),
                 phone="13402166677", screen_offset=-65, eseq=4,
                 enroll_offset=-58, status=SubjectStatus.DROPPED.value,
                 end_offset=-12, reason="受试者因个人原因主动撤回知情同意并退出研究"),
        ]
        sh_subjects = [make_subject(db, s2, sp, inv2) for sp in specs_sh]
        add_number_audit(
            db, s2, "screening", 5, inv2, status="voided",
            reason="同一受试者重复提交筛选登记，原表作废，号码锁定不复用",
        )
        sh_done, sh2, sh3 = sh_subjects[0], sh_subjects[1], sh_subjects[2]

        provision_visits(db, sh_done, V10_TEMPLATE, "v1.0")
        set_done(getv(sh_done, "V1"), -92, -91)
        set_done(getv(sh_done, "V2"), -78, -78)
        set_done(getv(sh_done, "V3"), -64, -64)
        set_done(getv(sh_done, "V4"), -36, -35)
        set_done(getv(sh_done, "V5"), -8, -7)
        sh_done.active_version = "v1.0"

        provision_visits(db, sh2, V10_TEMPLATE, "v1.0")
        set_done(getv(sh2, "V1"), -28, -27)
        set_scheduled(getv(sh2, "V2"), -8, pin=True)       # 超窗
        set_scheduled(getv(sh2, "V3"), 0, pin=True)        # 今日应随访
        set_scheduled(getv(sh2, "V4"), 28)
        set_scheduled(getv(sh2, "V5"), 84)
        for no in ("V2", "V3", "V4", "V5"):
            getv(sh2, no).version = "v1.1"
        ensure_v45(db, sh2, s2, 14)
        sh2.active_version = "v1.1"

        provision_visits(db, sh3, V10_TEMPLATE, "v1.0")
        set_done(getv(sh3, "V1"), -27, -26)
        set_scheduled(getv(sh3, "V2"), -1, pin=True)       # 逾期
        set_scheduled(getv(sh3, "V3"), 13)
        set_scheduled(getv(sh3, "V4"), 41)
        set_scheduled(getv(sh3, "V5"), 84)
        for no in ("V2", "V3", "V4", "V5"):
            getv(sh3, no).version = "v1.1"
        ensure_v45(db, sh3, s2, 27)
        sh3.active_version = "v1.1"

        sh_drop = sh_subjects[5]
        provision_visits(db, sh_drop, V10_TEMPLATE, "v1.0")
        set_done(getv(sh_drop, "V1"), -58, -57)
        for no in ("V2", "V3", "V4", "V5"):
            set_skipped(getv(sh_drop, no))
            getv(sh_drop, no).version = "v1.1"
        sh_drop.active_version = "v1.1"

        s2.screen_cursor = 7
        s2.enroll_cursor = 4

        # ---------------- 中心3（GZ）----------------
        s3, inv3 = sites[2], investigators["GZ"]
        specs_gz = [
            dict(sseq=1, name="唐绍文", gender="男", birth=date(1972, 10, 9),
                 phone="13802011234", screen_offset=-35, eseq=1,
                 enroll_offset=-28, status=SubjectStatus.ENROLLED.value),
            dict(sseq=2, name="罗婉婷", gender="女", birth=date(1989, 4, 17),
                 phone="13902022233", screen_offset=-15, eseq=2,
                 enroll_offset=-9, status=SubjectStatus.ENROLLED.value),
            dict(sseq=3, name="尹浩", gender="男", birth=date(1995, 8, 23),
                 phone="13702033344", screen_offset=-2,
                 status=SubjectStatus.SCREENING.value),
            dict(sseq=5, name="白露", gender="女", birth=date(1981, 6, 30),
                 phone="13602044455", screen_offset=-1,
                 status=SubjectStatus.SCREENING.value),
            dict(sseq=6, name="龚建平", gender="男", birth=date(1966, 1, 11),
                 phone="13602055566", screen_offset=-45, eseq=3,
                 enroll_offset=-38, status=SubjectStatus.TERMINATED.value,
                 end_offset=-5, reason="方案偏离经PI评估后中止该受试者继续参与"),
        ]
        gz_subjects = [make_subject(db, s3, sp, inv3) for sp in specs_gz]
        add_number_audit(
            db, s3, "screening", 4, inv3, status="voided",
            reason="iPad弱网下重复提交筛选登记，作废该号码并保留操作痕迹",
        )
        gz1, gz2 = gz_subjects[0], gz_subjects[1]

        provision_visits(db, gz1, V10_TEMPLATE, "v1.0")
        set_done(getv(gz1, "V1"), -28, -27)
        set_scheduled(getv(gz1, "V2"), 0, pin=True)        # 今日应随访
        set_scheduled(getv(gz1, "V3"), 14)
        set_scheduled(getv(gz1, "V4"), 42)
        set_scheduled(getv(gz1, "V5"), 84)
        for no in ("V2", "V3", "V4", "V5"):
            getv(gz1, no).version = "v1.1"
        ensure_v45(db, gz1, s3, 14)
        gz1.active_version = "v1.1"

        provision_visits(db, gz2, V11_TEMPLATE, "v1.1")
        gz2.active_version = "v1.1"

        gz_term = gz_subjects[4]
        provision_visits(db, gz_term, V10_TEMPLATE, "v1.0")
        set_done(getv(gz_term, "V1"), -38, -37)
        for no in ("V2", "V3", "V4", "V5"):
            set_skipped(getv(gz_term, no))
            getv(gz_term, no).version = "v1.1"
        gz_term.active_version = "v1.1"

        s3.screen_cursor = 6
        s3.enroll_cursor = 3

        db.commit()
        print("[seed] 种子完成：方案 v1.0/v1.1 · 3 中心 · 多状态受试者 · "
              "跨版本/锁库/计划外/全跳过/半张表演示数据")
    finally:
        db.close()


if __name__ == "__main__":
    wait_for_db()
    seed()
