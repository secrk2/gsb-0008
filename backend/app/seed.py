"""幂等种子数据：中心 / 三类账号 / 多状态受试者 / 方案两版 / 访视与关键表单 /
作废号 / 锁库 / 计划外访视 / 排程留痕 / 全名查看留痕。

所有访视日期相对“今天”生成，保证作战台任何一天拉起都能看到
今日应随访、逾期、超窗的真实样例数据。

方案两版（修订冻结演示）：
- v1.0 生效于 150 天前：V3 第4周(day28) / V4 第8周(day56) / V5 末次(day84)；
- v2.0 生效于 20 天前：随访间隔拉长，V3 第6周(day42) / V4 第10周(day70) /
  V5 末次(day98)，窗口同步放宽。修订生效前已完成的访视冻结在 v1，
  尚未发生的访视切换到 v2 —— 跨版本受试者身上新旧并存（甘特图挂横幅）。
"""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from .database import Base, SessionLocal, engine
from .domain import Action, SubjectStatus, format_screening_no, format_subject_code
from .models import (
    NumberAudit,
    PiiViewLog,
    ProtocolFormDef,
    ProtocolVersion,
    ProtocolVisitDef,
    Site,
    Subject,
    SubjectStatusHistory,
    User,
    Visit,
    VisitAudit,
    VisitForm,
)
from .security import hash_password
from .tz import now_utc

PASSWORD = "Suyuan@2026"
TODAY = date.today()
AMEND_OFFSET = -20  # v2.0 修订生效日（相对今天）


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
    status, eseq=None, enroll_offset=None, end_offset=None, completion_offset=None)"""
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
# 方案定义（两版）
# ---------------------------------------------------------------------------
# (visit_no, name, day_offset, window_before, window_after)
V1_DEFS = [
    ("V0", "筛选访视", -7, 3, 3),
    ("V1", "基线访视", 0, 3, 3),
    ("V2", "第2周访视", 14, 3, 3),
    ("V3", "第4周访视", 28, 3, 3),
    ("V4", "第8周访视", 56, 3, 3),
    ("V5", "末次访视", 84, 3, 3),
]
V2_DEFS = [
    ("V0", "筛选访视", -7, 3, 3),
    ("V1", "基线访视", 0, 2, 5),
    ("V2", "第2周访视", 14, 3, 3),
    ("V3", "第6周访视", 42, 5, 5),
    ("V4", "第10周访视", 70, 5, 5),
    ("V5", "末次访视", 98, 5, 7),
]

# 关键表单目录：visit_no -> [(code, name, is_key, field_count, kind)]
FORM_CATALOG = {
    "V0": [("incl_excl", "入选/排除标准表", True, 10, "entry"),
           ("medical_hx", "病史记录表", True, 8, "entry"),
           ("lab_screen", "筛选期实验室检查", True, 20, "entry")],
    "V1": [("demog", "入组基本信息表", True, 12, "entry"),
           ("vitals", "生命体征检查表", True, 10, "entry"),
           ("conmeds", "合并用药记录表", True, 6, "entry"),
           ("egfr", "eGFR 自动计算表", True, 0, "formula")],
    "V2": [("followup", "随访记录表", True, 8, "entry"),
           ("efficacy", "疗效评估表", True, 12, "entry"),
           ("ae", "不良事件记录表", True, 10, "entry")],
    "V3": [("followup", "随访记录表", True, 8, "entry"),
           ("lab_follow", "复查实验室检查", True, 18, "entry"),
           ("egfr", "eGFR 自动计算表", True, 0, "formula")],
    "V4": [("followup", "随访记录表", True, 8, "entry"),
           ("efficacy", "疗效评估表", True, 12, "entry"),
           ("ecg", "心电图记录表", True, 10, "entry")],
    "V5": [("final_follow", "末次随访记录表", True, 10, "entry"),
           ("conclusion", "研究总结论表", True, 8, "entry"),
           ("safety", "总体安全性评估表", True, 12, "entry")],
}


def build_protocol(db):
    v1 = ProtocolVersion(
        version="v1.0", status="superseded", effective_date=d(-150),
        change_summary="研究首次批准的方案版本。",
    )
    v2 = ProtocolVersion(
        version="v2.0", status="effective", effective_date=d(AMEND_OFFSET),
        change_summary=(
            "方案修订（行政性+安全性）：第4周/第8周两次随访调整为第6周/第10周，"
            "末次访视由第12周延后至第14周；基线与复查随访窗放宽（基线 前2/后5天，"
            "复查 前5/后5天，末次 前5/后7天）。修订生效前已完成的访视冻结在 v1.0，"
            "尚未发生的访视按 v2.0 执行。"
        ),
    )
    db.add_all([v1, v2])
    db.flush()
    for ver, defs in ((v1, V1_DEFS), (v2, V2_DEFS)):
        for seq, (no, name, day, wb, wa) in enumerate(defs):
            db.add(ProtocolVisitDef(
                version_id=ver.id, visit_no=no, name=name, day_offset=day,
                window_before=wb, window_after=wa, seq=seq,
            ))
        for no, forms in FORM_CATALOG.items():
            for fseq, (code, fname, is_key, fields, kind) in enumerate(forms):
                db.add(ProtocolFormDef(
                    version_id=ver.id, visit_no=no, form_code=code, form_name=fname,
                    is_key=is_key, field_count=fields, kind=kind, seq=fseq,
                ))
    db.flush()
    return v1, v2


def _def_map(ver):
    return {vd.visit_no: vd for vd in ver.visit_defs}


def add_visit(db, subject, site, *, no, name, planned_off, wb=3, wa=3,
              status="scheduled", actual_off=None, version=None, seq=None,
              kind="protocol", nominal_off=None, locked=False, reason=None,
              day_offset=None):
    """新增访视。protocol 访视 nominal = 随机化日+方案相对天数（显式传入）。"""
    if seq is None:
        seq = int(no[1:]) if no[1:].isdigit() else 0
    v = Visit(
        subject_id=subject.id, site_id=site.id, visit_no=no, name=name,
        planned_date=d(planned_off),
        nominal_date=d(nominal_off) if nominal_off is not None else None,
        seq=seq, window_before=wb, window_after=wa, status=status,
        actual_date=d(actual_off) if actual_off is not None else None,
        kind=kind, locked=locked,
        locked_at=now_utc() if locked else None,
        protocol_version_id=version.id if version is not None else None,
        version_label=version.version if version is not None else None,
        day_offset=day_offset, insert_reason=reason,
    )
    db.add(v)
    db.flush()
    return v


def add_forms(db, visit, version, *, mode="complete"):
    """按方案目录为访视生成表单实例。

    mode: complete 全部完成 / half 只填半张表（关键表单 0 张完成）/
          mixed 一张完成+一张半填 / pending 全部未开始 / none 不建表单
    """
    if mode == "none":
        return
    for code, fname, is_key, fields, kind in FORM_CATALOG.get(visit.visit_no, []):
        if kind == "formula":
            status, submitted = "formula", 0
        elif mode == "complete":
            status, submitted = "complete", fields
        elif mode == "pending":
            status, submitted = "pending", 0
        elif mode == "half":
            # 第一张人工录入关键表单只填一半，其余未开始 → 关键表单完成 0 张
            entry_codes = [c for c, _, _, _, k in FORM_CATALOG[visit.visit_no]
                           if k != "formula"]
            if code == entry_codes[0]:
                status, submitted = "in_progress", fields // 2
            else:
                status, submitted = "pending", 0
        else:  # mixed：第一张完成、第二张半填
            ordered = [f for f in FORM_CATALOG[visit.visit_no] if f[4] != "formula"]
            first_code, second_code = ordered[0][0], ordered[1][0]
            if code == first_code:
                status, submitted = "complete", fields
            elif code == second_code:
                status, submitted = "in_progress", fields // 2
            elif kind == "formula":
                status, submitted = "formula", 0
            else:
                status, submitted = "pending", 0
        db.add(VisitForm(
            visit_id=visit.id, form_code=code, form_name=fname, is_key=is_key,
            field_total=fields, submitted_fields=submitted, status=status,
            completed_at=now_utc() if status == "complete" else None,
        ))


def add_audit(db, visit, subject, site, operator, action, *,
              old_off=None, new_off=None, reason=None, detail=None, at_off=None):
    audit = VisitAudit(
        visit_id=visit.id, subject_id=subject.id, site_id=site.id, action=action,
        old_date=d(old_off) if old_off is not None else None,
        new_date=d(new_off) if new_off is not None else None,
        reason=reason, detail=detail,
        operator_id=operator.id, operator_name=operator.full_name,
    )
    db.add(audit)
    db.flush()
    if at_off is not None:
        audit.created_at = datetime.combine(d(at_off), datetime.min.time()).replace(
            hour=10
        ) + timedelta(hours=2)
    return audit


def protocol_visit(db, subject, site, ver, no, *, planned_off, status="scheduled",
                   actual_off=None, locked=False, forms=None,
                   seq_override=None, nominal_off=None):
    """按某方案版本的访视定义实例化一次访视。

    表单进度默认随访视状态：done/locked → 全部完成；scheduled → 全部未开始
    （未来访视绝不允许显示成已完成）；可用 forms= 显式覆盖（如 half/mixed）。
    """
    vd = _def_map(ver)[no]
    nom = planned_off if nominal_off is None else nominal_off
    if forms is None:
        forms = "complete" if status in ("done", "locked") else "pending"
    v = add_visit(
        db, subject, site, no=vd.visit_no, name=vd.name,
        planned_off=planned_off, wb=vd.window_before, wa=vd.window_after,
        status=status, actual_off=actual_off, version=ver,
        seq=seq_override if seq_override is not None else vd.seq,
        nominal_off=nom, locked=locked, day_offset=vd.day_offset,
    )
    add_forms(db, v, ver, mode=forms)
    return v


SITE_SEED = [
    {
        "code": "SITE01", "prefix": "BJ", "city": "北京",
        "name": "北京协和临床研究中心", "pi": "陈建华", "target": 30,
        "timezone": "Asia/Shanghai",
    },
    {
        "code": "SITE02", "prefix": "SH", "city": "上海",
        "name": "上海瑞金临床药理中心", "pi": "黄志明", "target": 24,
        "timezone": "Asia/Shanghai",
    },
    {
        "code": "SITE03", "prefix": "GZ", "city": "广州",
        "name": "广州中山医学研究中心", "pi": "林国栋", "target": 20,
        "timezone": "Asia/Shanghai",
    },
]


def seed() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if db.scalar(select(User).where(User.username == "dm")):
            print("[seed] 数据已存在，跳过种子（幂等）")
            return

        dm = User(
            username="dm",
            password_hash=hash_password(PASSWORD),
            full_name="何敏",
            role="dm",
            site_id=None,
        )
        db.add(dm)
        sites: list[Site] = []
        investigators: dict[str, User] = {}
        for idx, s in enumerate(SITE_SEED, start=1):
            site = Site(
                code=s["code"], prefix=s["prefix"], name=s["name"], city=s["city"],
                pi_name=s["pi"], target_enrollment=s["target"],
                timezone=s["timezone"],
            )
            db.add(site)
            db.flush()
            sites.append(site)
            inv = User(
                username=f"inv{idx:02d}",
                password_hash=hash_password(PASSWORD),
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

        v1, v2 = build_protocol(db)
        v1map, v2map = _def_map(v1), _def_map(v2)

        # ---------------- 中心1（BJ）----------------
        s1, inv1 = sites[0], investigators["BJ"]
        specs_bj = [
            dict(sseq=1, name="王建国", gender="男", birth=date(1968, 4, 12),
                 phone="13801011234", screen_offset=-120, eseq=1,
                 enroll_offset=-110, status=SubjectStatus.COMPLETED.value,
                 completion_offset=-10),
            dict(sseq=2, name="李雪梅", gender="女", birth=date(1975, 9, 3),
                 phone="13901022233", screen_offset=-60, eseq=2,
                 enroll_offset=-52, status=SubjectStatus.ENROLLED.value),
            dict(sseq=3, name="张志强", gender="男", birth=date(1982, 1, 25),
                 phone="13701033344", screen_offset=-48, eseq=3,
                 enroll_offset=-40, status=SubjectStatus.ENROLLED.value),
            dict(sseq=4, name="刘思远", gender="男", birth=date(1990, 7, 8),
                 phone="13601044455", screen_offset=-3,
                 status=SubjectStatus.SCREENING.value),  # 尚无任何访视 → 空态
            # sseq=5 作废：撤回知情同意
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
            # 受试者编号 007 作废（误分配），下一位入组者取 008
            dict(sseq=11, name="冯磊", gender="男", birth=date(1984, 10, 5),
                 phone="13001100011", screen_offset=-20, eseq=8,
                 enroll_offset=-12, status=SubjectStatus.ENROLLED.value),
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

        bj1, bj2, bj3, _, bj6, bj7, bj8, bj9, bj10, bj11 = bj_subjects

        # BJ-001 已完成：v1 方案 6 次访视全部完成（修订前完成，冻结 v1）
        for no, actual_adj in [("V0", 1), ("V1", 1), ("V2", -1), ("V3", 0),
                               ("V4", 0), ("V5", 0)]:
            vd = v1map[no]
            off = -110 + vd.day_offset
            protocol_visit(db, bj1, s1, v1, no,
                           planned_off=off, status="done",
                           actual_off=off + actual_adj, forms="complete")

        # BJ-002 跨版本并存：V1/V2 修订前完成（冻结 v1），V3+ 未发生已切到 v2
        protocol_visit(db, bj2, s1, v1, "V1", planned_off=-52,
                       status="done", actual_off=-51, forms="complete")
        v2_done = protocol_visit(db, bj2, s1, v1, "V2", planned_off=-38,
                                 status="done", actual_off=-37, forms="half")
        # V3 切到 v2：第6周 day42 → -10，窗口 ±5，今天已超窗
        protocol_visit(db, bj2, s1, v2, "V3", planned_off=-10)
        protocol_visit(db, bj2, s1, v2, "V4", planned_off=18)
        protocol_visit(db, bj2, s1, v2, "V5", planned_off=46)

        # BJ-003：V1 完成（v1 冻结）；V2 经一次超窗改期（强填原因留痕），
        # 今天逾期但仍在 v2 放宽后的窗口内；后续访视链式重算
        protocol_visit(db, bj3, s1, v1, "V1", planned_off=-40,
                       status="done", actual_off=-39)
        v_bj3_v2_nominal = -40 + v2map["V2"].day_offset  # -26
        v_bj3_v2 = protocol_visit(
            db, bj3, s1, v2, "V2", planned_off=-3, nominal_off=v_bj3_v2_nominal,
        )
        add_audit(
            db, v_bj3_v2, bj3, s1, inv1, "reschedule_out_of_window",
            old_off=v_bj3_v2_nominal, new_off=-3, at_off=-2,
            reason="受试者回乡探亲无法按计划返院，经PI评估安全性后延后至本周，"
                   "已构成方案偏离并上报监查员；后续访视已由系统链式顺延。",
            detail=f"原计划 {d(v_bj3_v2_nominal)}（v2.0 窗口 前3/后3天），"
                   f"改期至 {d(-3)} 超出窗口，二次确认后强制留痕；V3/V4/V5 链式重算。",
        )
        # 链式重算后的后续访视（nominal 保留 v2 名义日，planned 为执行口径）
        protocol_visit(db, bj3, s1, v2, "V3", planned_off=25,
                       nominal_off=-40 + v2map["V3"].day_offset)
        protocol_visit(db, bj3, s1, v2, "V4", planned_off=53,
                       nominal_off=-40 + v2map["V4"].day_offset)
        protocol_visit(db, bj3, s1, v2, "V5", planned_off=81,
                       nominal_off=-40 + v2map["V5"].day_offset)

        # BJ-S006 筛选者：筛选访视明天
        add_visit(db, bj6, s1, no="V0", name="筛选访视", planned_off=1,
                  wb=3, wa=3, version=v2, seq=0, nominal_off=1, day_offset=-7)

        # BJ-S007 筛选失败：筛选访视已做（v1 时期）
        sf = add_visit(db, bj7, s1, no="V0", name="筛选访视", planned_off=-24,
                       wb=3, wa=3, status="done", actual_off=-24,
                       version=v1, seq=0, nominal_off=-24, day_offset=-7)
        add_forms(db, sf, v1, mode="complete")

        # BJ-004 脱落：V1/V2 完成（v1），脱落日之后无未来访视
        protocol_visit(db, bj8, s1, v1, "V1", planned_off=-62,
                       status="done", actual_off=-61)
        protocol_visit(db, bj8, s1, v1, "V2", planned_off=-48,
                       status="done", actual_off=-48)

        # BJ-005 中止：V1/V2 完成（v1 冻结）
        protocol_visit(db, bj9, s1, v1, "V1", planned_off=-47,
                       status="done", actual_off=-46)
        protocol_visit(db, bj9, s1, v1, "V2", planned_off=-33,
                       status="done", actual_off=-33)

        # BJ-006 剔除：仅 V1 完成（v1 冻结）
        protocol_visit(db, bj10, s1, v1, "V1", planned_off=-33,
                       status="done", actual_off=-32)

        # BJ-008 修订后入组：全部 v2；V1 已完成，V2 窗内将至（+2）
        protocol_visit(db, bj11, s1, v2, "V1", planned_off=-12,
                       status="done", actual_off=-11)
        protocol_visit(db, bj11, s1, v2, "V2", planned_off=2)
        protocol_visit(db, bj11, s1, v2, "V3", planned_off=30)

        # 全名查看留痕示例（两天前的一次 SDV 核查查看）
        pii_log = PiiViewLog(
            subject_id=bj2.id, site_id=s1.id,
            viewer_id=inv1.id, viewer_name=inv1.full_name,
            viewer_username=inv1.username,
            reason="SDV源数据核查：核对门诊病历与CRF中的受试者姓名一致性",
        )
        db.add(pii_log)
        db.flush()
        pii_log.created_at = datetime.now() - timedelta(days=2)

        s1.screen_cursor = 11
        s1.enroll_cursor = 8

        # ---------------- 中心2（SH）----------------
        s2, inv2 = sites[1], investigators["SH"]
        specs_sh = [
            dict(sseq=1, name="褚红军", gender="男", birth=date(1970, 8, 18),
                 phone="13802111234", screen_offset=-100, eseq=1,
                 enroll_offset=-92, status=SubjectStatus.COMPLETED.value,
                 completion_offset=-4),
            dict(sseq=2, name="卫春晓", gender="女", birth=date(1983, 5, 6),
                 phone="13902122233", screen_offset=-50, eseq=2,
                 enroll_offset=-44, status=SubjectStatus.ENROLLED.value),
            dict(sseq=3, name="蒋涛", gender="男", birth=date(1977, 2, 14),
                 phone="13702133344", screen_offset=-30, eseq=3,
                 enroll_offset=-24, status=SubjectStatus.ENROLLED.value),
            dict(sseq=4, name="沈佳怡", gender="女", birth=date(1992, 9, 21),
                 phone="13602144455", screen_offset=-4,
                 status=SubjectStatus.SCREENING.value),
            # sseq=5 作废：重复登记
            dict(sseq=6, name="韩梅", gender="女", birth=date(1985, 12, 1),
                 phone="13702155566", screen_offset=-18,
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
        sh1, sh2, sh3, sh4, sh6, sh7 = sh_subjects

        # SH-001 已完成 + 全部锁库（v1 冻结，锁库于 4 天前）
        for no in ["V0", "V1", "V2", "V3", "V4", "V5"]:
            vd = v1map[no]
            off = -92 + vd.day_offset
            lv = protocol_visit(db, sh1, s2, v1, no, planned_off=off,
                                status="done", actual_off=off, locked=True)
            add_audit(db, lv, sh1, s2, inv2, "lock", old_off=off, new_off=off,
                      reason="该受试者数据已通过质控与SDV，按锁库SOP冻结，"
                             "此后任何改期/跳过/链式重算均被系统拒绝。",
                      detail="锁库后表单与计划日期只读。", at_off=-4)

        # SH-002 跨版本：V1 v1 完成冻结；V2 切 v2 后今天已超窗（-30，窗 ±3）
        protocol_visit(db, sh2, s2, v1, "V1", planned_off=-44,
                       status="done", actual_off=-43)
        protocol_visit(db, sh2, s2, v2, "V2", planned_off=-30)
        protocol_visit(db, sh2, s2, v2, "V3", planned_off=-2)
        protocol_visit(db, sh2, s2, v2, "V4", planned_off=26)
        protocol_visit(db, sh2, s2, v2, "V5", planned_off=54)

        # SH-003：V1 在修订生效后完成（v2）；V2 已超窗
        protocol_visit(db, sh3, s2, v2, "V1", planned_off=-24,
                       status="done", actual_off=-19)
        protocol_visit(db, sh3, s2, v2, "V2", planned_off=-10)
        protocol_visit(db, sh3, s2, v2, "V3", planned_off=18)
        protocol_visit(db, sh3, s2, v2, "V4", planned_off=46)

        # SH-S004 筛选者：筛选访视 +2
        add_visit(db, sh4, s2, no="V0", name="筛选访视",
                  planned_off=2, wb=3, wa=3, version=v2, seq=0,
                  nominal_off=2, day_offset=-7)

        # SH-S006 筛选失败：筛选访视已做
        sf2 = add_visit(db, sh6, s2, no="V0", name="筛选访视", planned_off=-17,
                        wb=3, wa=3, status="done", actual_off=-17,
                        version=v1, seq=0, nominal_off=-17, day_offset=-7)
        add_forms(db, sf2, v1, mode="complete")

        # SH-004 脱落：3 次 v1 完成访视
        for no, off, act in [("V1", -58, -57), ("V2", -44, -44), ("V3", -30, -29)]:
            protocol_visit(db, sh7, s2, v1, no, planned_off=off,
                           status="done", actual_off=act)

        s2.screen_cursor = 7
        s2.enroll_cursor = 4

        # ---------------- 中心3（GZ）----------------
        s3, inv3 = sites[2], investigators["GZ"]
        specs_gz = [
            dict(sseq=1, name="唐绍文", gender="男", birth=date(1972, 10, 9),
                 phone="13802011234", screen_offset=-35, eseq=1,
                 enroll_offset=-28, status=SubjectStatus.ENROLLED.value),
            dict(sseq=2, name="罗婉婷", gender="女", birth=date(1989, 4, 17),
                 phone="13802022233", screen_offset=-15, eseq=2,
                 enroll_offset=-9, status=SubjectStatus.ENROLLED.value),
            dict(sseq=3, name="尹浩", gender="男", birth=date(1995, 8, 23),
                 phone="13702033344", screen_offset=-2,
                 status=SubjectStatus.SCREENING.value),
            # sseq=4 作废：弱网重复提交
            dict(sseq=5, name="白露", gender="女", birth=date(1981, 6, 30),
                 phone="13602044455", screen_offset=-1,
                 status=SubjectStatus.SCREENING.value),
            dict(sseq=6, name="龚建平", gender="男", birth=date(1966, 1, 11),
                 phone="13802055566", screen_offset=-45, eseq=3,
                 enroll_offset=-38, status=SubjectStatus.TERMINATED.value,
                 end_offset=-5, reason="方案偏离经PI评估后中止该受试者继续参与"),
            # 全部访视被跳过的在研受试者（等待行政结案）→ “全部跳过”空态
            dict(sseq=7, name="袁航", gender="男", birth=date(1993, 3, 8),
                 phone="13502066677", screen_offset=-22, eseq=4,
                 enroll_offset=-15, status=SubjectStatus.ENROLLED.value),
        ]
        gz_subjects = [make_subject(db, s3, sp, inv3) for sp in specs_gz]
        add_number_audit(
            db, s3, "screening", 4, inv3, status="voided",
            reason="iPad弱网下重复提交筛选登记，作废该号码并保留操作痕迹",
        )
        gz1, gz2, gz3, gz5, gz6, gz7 = gz_subjects

        # GZ-001 跨版本 + 计划外访视 + 链式重算 + 窗内改期（今日应随访）
        protocol_visit(db, gz1, s3, v1, "V1", planned_off=-28,
                       status="done", actual_off=-23, forms="mixed")
        # -7 天插入计划外安全性加诊（其后未发生访视顺延 16 天）
        unsched = add_visit(
            db, gz1, s3, no="U1", name="计划外·安全性复查", planned_off=-7,
            wb=0, wa=0, status="unscheduled", actual_off=-7, version=v2,
            seq=1.5, kind="unscheduled", nominal_off=-7,
            reason="受试者用药后出现轻度皮疹，PI 安排加诊评估并复查血常规；"
                   "评估为轻度非严重不良事件，继续随访。",
        )
        add_audit(db, unsched, gz1, s3, inv3, "insert_unscheduled",
                  new_off=-7, at_off=-7,
                  reason="轻度皮疹加诊（计划外访视）",
                  detail="插入计划外访视后，其后尚未发生的 V2/V3/V4/V5 按执行口径链式顺延 16 天。")
        v2_nominal_gz1 = -28 + v2map["V2"].day_offset  # -14
        gz1_v2 = protocol_visit(db, gz1, s3, v2, "V2", planned_off=2,
                                nominal_off=v2_nominal_gz1)
        add_audit(db, gz1_v2, gz1, s3, inv3, "chain_recompute",
                  old_off=v2_nominal_gz1, new_off=2, at_off=-7,
                  detail="计划外加诊导致链式顺延；名义计划日保留为随机化口径，"
                         "现行计划日为执行口径。")
        # 研究者再把 V2 从 +2 窗内改到今天 0（窗内改期，留痕但不强制原因，仍记录说明）
        gz1_v2.planned_date = d(0)
        add_audit(db, gz1_v2, gz1, s3, inv3, "reschedule",
                  old_off=2, new_off=0, at_off=-1,
                  reason="与受试者确认今日来院做第2周随访（落在窗口内的常规改期）。")
        protocol_visit(db, gz1, s3, v2, "V3", planned_off=30,
                       nominal_off=-28 + v2map["V3"].day_offset)
        protocol_visit(db, gz1, s3, v2, "V4", planned_off=58,
                       nominal_off=-28 + v2map["V4"].day_offset)
        protocol_visit(db, gz1, s3, v2, "V5", planned_off=86,
                       nominal_off=-28 + v2map["V5"].day_offset)

        # GZ-002 修订后入组：纯 v2，无跨版本横幅
        protocol_visit(db, gz2, s3, v2, "V1", planned_off=-9,
                       status="done", actual_off=-8)
        protocol_visit(db, gz2, s3, v2, "V2", planned_off=5)
        protocol_visit(db, gz2, s3, v2, "V3", planned_off=33)

        # GZ-S003 筛选者：筛选访视明天
        add_visit(db, gz3, s3, no="V0", name="筛选访视", planned_off=1,
                  wb=3, wa=3, version=v2, seq=0, nominal_off=1, day_offset=-7)
        # GZ-S005 筛选者：筛选访视今日（今日应随访）
        add_visit(db, gz5, s3, no="V0", name="筛选访视", planned_off=0,
                  wb=3, wa=3, version=v2, seq=0, nominal_off=0, day_offset=-7)

        # GZ-003 中止：V1 v1 完成冻结
        protocol_visit(db, gz6, s3, v1, "V1", planned_off=-38,
                       status="done", actual_off=-37)

        # GZ-004：全部访视跳过（附原因）→ “访视已全部跳过”空态
        skip_reason = "误纳复核期间暂停一切随访，待伦理与数据核查结论后按流程结案"
        for no, ver, off, sreason in [
            ("V1", v2, -15, "复核入组合规性，基线随访暂缓后跳过"),
            ("V2", v2, -1, "受试者暂不返院，第2周访视跳过"),
            ("V3", v2, 27, skip_reason),
            ("V4", v2, 55, skip_reason),
            ("V5", v2, 83, skip_reason),
        ]:
            vd = _def_map(ver)[no]
            sv = add_visit(
                db, gz7, s3, no=no, name=vd.name, planned_off=off,
                wb=vd.window_before, wa=vd.window_after, status="skipped",
                version=ver, seq=vd.seq, nominal_off=off, day_offset=vd.day_offset,
            )
            add_audit(db, sv, gz7, s3, inv3, "skip", old_off=off, new_off=off,
                      reason=sreason, detail="跳过不删除访视，后续计划按链式口径保持。",
                      at_off=off if off <= 0 else None)

        s3.screen_cursor = 7
        s3.enroll_cursor = 4

        # 方案 v2 发布留痕时间戳
        v2.published_by = dm.id
        v2.published_at = datetime.combine(d(AMEND_OFFSET), datetime.min.time()).replace(
            hour=9
        ) + timedelta(hours=2)

        db.commit()
        print("[seed] 种子数据写入完成：3 家中心 / 8 个账号 / 方案 v1.0+v2.0 / "
              "多状态受试者与访视（含锁库、计划外、全跳过、半张表、跨版本并存）")
    finally:
        db.close()


if __name__ == "__main__":
    wait_for_db()
    seed()
