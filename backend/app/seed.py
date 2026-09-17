"""幂等种子数据：中心 / 三类账号 / 多状态受试者 / 访视 / 作废号与查看留痕。

所有访视日期相对“今天”生成，保证作战台任何一天拉起都能看到
今日应随访、逾期、超窗的真实样例数据。
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
    Site,
    Subject,
    SubjectStatusHistory,
    User,
    Visit,
)
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


def add_visit(db, subject, site, visit_no, name, offset, wb=3, wa=3,
              status="scheduled", actual_offset=None):
    db.add(
        Visit(
            subject_id=subject.id,
            site_id=site.id,
            visit_no=visit_no,
            name=name,
            planned_date=d(offset),
            window_before=wb,
            window_after=wa,
            status=status,
            actual_date=d(actual_offset) if actual_offset is not None else None,
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


SITE_SEED = [
    {
        "code": "SITE01", "prefix": "BJ", "city": "北京",
        "name": "北京协和临床研究中心", "pi": "陈建华", "target": 30,
    },
    {
        "code": "SITE02", "prefix": "SH", "city": "上海",
        "name": "上海瑞金临床药理中心", "pi": "黄志明", "target": 24,
    },
    {
        "code": "SITE03", "prefix": "GZ", "city": "广州",
        "name": "广州中山医学研究中心", "pi": "林国栋", "target": 20,
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
                 status=SubjectStatus.SCREENING.value),
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

        # BJ-S005 筛选号作废留痕（号码不复用，游标推进到 6）
        add_number_audit(
            db, s1, "screening", 5, inv1, status="voided",
            reason="受试者登记当日撤回知情同意，筛选表作废，号码按SOP不复用",
        )
        # BJ-007 受试者编号作废留痕
        add_number_audit(
            db, s1, "subject", 7, inv1, status="voided",
            reason="编号误操作预占，经复核未实际入组，按SOP作废且永不再分配",
        )

        completed, bj2, bj3, _, bj6 = (
            bj_subjects[0], bj_subjects[1], bj_subjects[2], bj_subjects[3], bj_subjects[4]
        )
        bj11 = bj_subjects[-1]
        # 已完成者：5 次访视全部完成
        for no, name, off, act in [
            ("V0", "筛选访视", -115, -114), ("V1", "基线访视", -100, -99),
            ("V2", "第4周访视", -70, -71), ("V3", "第8周访视", -40, -40),
            ("V4", "末次访视", -12, -12),
        ]:
            add_visit(db, completed, s1, no, name, off, status="done", actual_offset=act)
        # 在研：1 次超窗（计划-10，窗后3天）+ 今日应随访 + 未来访视
        add_visit(db, bj2, s1, "V0", "基线访视", -30, status="done", actual_offset=-29)
        add_visit(db, bj2, s1, "V1", "第2周访视", -10)          # 超窗红点
        add_visit(db, bj2, s1, "V2", "第4周访视", 0)            # 今日应随访
        add_visit(db, bj2, s1, "V3", "第8周访视", 28)
        # 在研：逾期（计划-2，窗后5天内）
        add_visit(db, bj3, s1, "V0", "基线访视", -45, status="done", actual_offset=-44)
        add_visit(db, bj3, s1, "V1", "第2周访视", -3, wa=5)     # 逾期红点（计划已过2天，仍在5天窗内）
        add_visit(db, bj3, s1, "V2", "第6周访视", 14)
        add_visit(db, bj11, s1, "V0", "基线访视", 2)            # 窗内将至
        add_visit(db, bj11, s1, "V1", "第4周访视", 24)
        add_visit(db, bj6, s1, "V0", "筛选访视", 0)             # 筛选者今日应随访

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
                 completion_offset=-6),
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
        for no, name, off, act in [
            ("V0", "筛选访视", -97, -96), ("V1", "基线访视", -85, -84),
            ("V2", "第4周访视", -50, -50), ("V3", "末次访视", -7, -6),
        ]:
            add_visit(db, sh_done, s2, no, name, off, status="done", actual_offset=act)
        add_visit(db, sh2, s2, "V0", "基线访视", -40, status="done", actual_offset=-39)
        add_visit(db, sh2, s2, "V1", "第2周访视", -8)          # 超窗
        add_visit(db, sh2, s2, "V2", "第4周访视", 0)           # 今日应随访
        add_visit(db, sh3, s2, "V0", "基线访视", -20,
                  status="done", actual_offset=-19)
        add_visit(db, sh3, s2, "V1", "第2周访视", -1)          # 逾期
        add_visit(db, sh3, s2, "V2", "第6周访视", 20)
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
            # sseq=4 作废：弱网重复提交
            dict(sseq=5, name="白露", gender="女", birth=date(1981, 6, 30),
                 phone="13602044455", screen_offset=-1,
                 status=SubjectStatus.SCREENING.value),
            dict(sseq=6, name="龚建平", gender="男", birth=date(1966, 1, 11),
                 phone="13502055566", screen_offset=-45, eseq=3,
                 enroll_offset=-38, status=SubjectStatus.TERMINATED.value,
                 end_offset=-5, reason="方案偏离经PI评估后中止该受试者继续参与"),
        ]
        gz_subjects = [make_subject(db, s3, sp, inv3) for sp in specs_gz]
        add_number_audit(
            db, s3, "screening", 4, inv3, status="voided",
            reason="iPad弱网下重复提交筛选登记，作废该号码并保留操作痕迹",
        )
        gz1, gz2 = gz_subjects[0], gz_subjects[1]
        add_visit(db, gz1, s3, "V0", "基线访视", -24, status="done", actual_offset=-23)
        add_visit(db, gz1, s3, "V1", "第2周访视", 0)           # 今日应随访
        add_visit(db, gz1, s3, "V2", "第6周访视", 21)
        add_visit(db, gz2, s3, "V0", "基线访视", 4)            # 未到窗/窗内
        s3.screen_cursor = 6
        s3.enroll_cursor = 3

        db.commit()
        print("[seed] 种子数据写入完成：3 家中心 / 8 个账号 / 多状态受试者与访视")
    finally:
        db.close()


if __name__ == "__main__":
    wait_for_db()
    seed()
