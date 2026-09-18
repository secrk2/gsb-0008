from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Site(Base):
    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    prefix: Mapped[str] = mapped_column(String(8), unique=True)
    city: Mapped[str] = mapped_column(String(32))
    pi_name: Mapped[str] = mapped_column(String(32))
    target_enrollment: Mapped[int] = mapped_column(Integer, default=0)
    # 研究中心所在 IANA 时区；日期按 UTC 存、按此时区展示与判定「是否同一天」
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Shanghai")
    # 编号游标：作废号码同样推进游标，保证不复用
    screen_cursor: Mapped[int] = mapped_column(Integer, default=0)
    enroll_cursor: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    users: Mapped[list["User"]] = relationship(back_populates="site")
    subjects: Mapped[list["Subject"]] = relationship(back_populates="site")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(32))
    # investigator 研究者 / dm 数据管理员 / monitor 监查员
    role: Mapped[str] = mapped_column(String(16))
    # 申办方/CRO 级数据管理员 site_id 为空，可见全部中心；其余角色严格限本中心
    site_id: Mapped[int | None] = mapped_column(ForeignKey("sites.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    site: Mapped["Site | None"] = relationship(back_populates="users")


class Subject(Base):
    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), index=True)
    # 筛选号（登记即分配）；受试者编号（入组时分配）
    screening_no: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    subject_code: Mapped[str | None] = mapped_column(String(24), unique=True, nullable=True, index=True)
    screen_seq: Mapped[int] = mapped_column(Integer)
    enroll_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)

    full_name: Mapped[str] = mapped_column(String(32))  # PII 明文字段
    gender: Mapped[str] = mapped_column(String(4))
    birth_date: Mapped[date] = mapped_column(Date)
    phone: Mapped[str] = mapped_column(String(20))

    # screening / enrolled / completed / dropped / terminated / screen_failed / removed
    status: Mapped[str] = mapped_column(String(16), default="screening", index=True)

    screen_date: Mapped[date] = mapped_column(Date)
    enroll_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # 随机化日期：访视排程的主锚点。多数试验等于入组日；允许不同（如导入期）
    randomization_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    completion_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # 当前生效方案版本（修订发布后，新访视按此版本生成；已冻结访视保留各自版本）
    active_version: Mapped[str] = mapped_column(String(24), default="v1.0")

    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    site: Mapped["Site"] = relationship(back_populates="subjects")
    visits: Mapped[list["Visit"]] = relationship(
        back_populates="subject", cascade="all, delete-orphan",
        order_by="Visit.order_index",
    )
    histories: Mapped[list["SubjectStatusHistory"]] = relationship(
        back_populates="subject", cascade="all, delete-orphan"
    )
    number_audits: Mapped[list["NumberAudit"]] = relationship(
        primaryjoin="foreign(NumberAudit.subject_id) == Subject.id",
        viewonly=True,
        order_by="NumberAudit.id",
    )
    schedule_audits: Mapped[list["VisitScheduleAudit"]] = relationship(
        back_populates="subject", cascade="all, delete-orphan",
        order_by="VisitScheduleAudit.id.desc()",
    )


class SubjectStatusHistory(Base):
    """状态迁移留痕（只追加，不修改/不删除）。"""

    __tablename__ = "subject_status_histories"

    id: Mapped[int] = mapped_column(primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    action: Mapped[str] = mapped_column(String(24))
    to_status: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    operator_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    operator_name: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    subject: Mapped["Subject"] = relationship(back_populates="histories")


class NumberAudit(Base):
    """号码分配/作废留痕（只追加）。作废号码不得复用。"""

    __tablename__ = "number_audits"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # screening / subject
    number: Mapped[str] = mapped_column(String(24), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    # assigned 已分配 / voided 已作废
    status: Mapped[str] = mapped_column(String(16), default="assigned")
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id"), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    operator_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    operator_name: Mapped[str] = mapped_column(String(32), default="系统")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ProtocolVersion(Base):
    """方案版本（只追加）。修订发布即新增一行并对未发生访视切版。"""

    __tablename__ = "protocol_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(128))
    change_note: Mapped[str] = mapped_column(Text, default="")
    # 生效日（UTC 日历日）：计划日早于该日的访视即使未完成也冻结旧版
    effective_date: Mapped[date] = mapped_column(Date)
    published_by: Mapped[str] = mapped_column(String(32), default="系统")
    is_current: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    templates: Mapped[list["VisitTemplate"]] = relationship(
        back_populates="protocol", cascade="all, delete-orphan",
        order_by="VisitTemplate.order_index",
    )


class VisitTemplate(Base):
    """方案访视模板：相对天数 + 窗口 + 锚点口径。每个方案版本一份完整访视表。"""

    __tablename__ = "visit_templates"
    __table_args__ = (
        UniqueConstraint("protocol_version_id", "visit_no", name="uq_tpl_visit_no"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    protocol_version_id: Mapped[int] = mapped_column(
        ForeignKey("protocol_versions.id"), index=True
    )
    visit_no: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(64))
    order_index: Mapped[int] = mapped_column(Integer)
    offset_days: Mapped[int] = mapped_column(Integer)
    # randomization / previous_actual
    anchor_mode: Mapped[str] = mapped_column(String(24), default="randomization")
    window_before: Mapped[int] = mapped_column(Integer, default=3)
    window_after: Mapped[int] = mapped_column(Integer, default=3)

    protocol: Mapped["ProtocolVersion"] = relationship(back_populates="templates")
    forms: Mapped[list["TemplateForm"]] = relationship(
        back_populates="template", cascade="all, delete-orphan"
    )


class TemplateForm(Base):
    """访视模板下的关键表单（CRF）定义，用于「已完成关键表单数」完成度口径。"""

    __tablename__ = "template_forms"

    id: Mapped[int] = mapped_column(primary_key=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("visit_templates.id"), index=True)
    form_key: Mapped[str] = mapped_column(String(48))
    name: Mapped[str] = mapped_column(String(64))
    is_key: Mapped[bool] = mapped_column(Boolean, default=True)
    total_fields: Mapped[int] = mapped_column(Integer, default=0)

    template: Mapped["VisitTemplate"] = relationship(back_populates="forms")


class Visit(Base):
    __tablename__ = "visits"
    __table_args__ = (
        UniqueConstraint("subject_id", "visit_no", name="uq_subject_visit_no"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), index=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), index=True)
    visit_no: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(64))
    order_index: Mapped[int] = mapped_column(Integer, default=0, index=True)
    # protocol / unscheduled（计划外）
    kind: Mapped[str] = mapped_column(String(16), default="protocol")
    # 所属方案版本；计划外访视记插入时的版本。修订后已冻结访视保留旧版本号
    version: Mapped[str] = mapped_column(String(24), default="v1.0", index=True)
    # 相对锚点天数与锚点口径（来自模板；计划外为 0/previous_actual）
    offset_days: Mapped[int] = mapped_column(Integer, default=0)
    anchor_mode: Mapped[str] = mapped_column(String(24), default="randomization")

    # 日期一律按 UTC 日历日存储，按中心时区展示
    planned_date: Mapped[date] = mapped_column(Date, index=True)
    window_before: Mapped[int] = mapped_column(Integer, default=3)
    window_after: Mapped[int] = mapped_column(Integer, default=3)
    # scheduled / done / skipped
    status: Mapped[str] = mapped_column(String(16), default="scheduled", index=True)
    actual_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # 手动改期后钉住，自动链式重算不覆盖本人工决定；切版时按新模板解除
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    # 锁库：计划/实际/表单全部冻结，任何变更需走解锁审批
    locked: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(32), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    subject: Mapped["Subject"] = relationship(back_populates="visits")
    forms: Mapped[list["VisitForm"]] = relationship(
        back_populates="visit", cascade="all, delete-orphan"
    )


class VisitForm(Base):
    """受试者访视上的表单实例与完成状态。"""

    __tablename__ = "visit_forms"
    __table_args__ = (
        UniqueConstraint("visit_id", "form_key", name="uq_visit_form_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    visit_id: Mapped[int] = mapped_column(ForeignKey("visits.id"), index=True)
    form_key: Mapped[str] = mapped_column(String(48))
    name: Mapped[str] = mapped_column(String(64))
    is_key: Mapped[bool] = mapped_column(Boolean, default=True)
    # pending / incomplete / complete
    status: Mapped[str] = mapped_column(String(16), default="pending")
    total_fields: Mapped[int] = mapped_column(Integer, default=0)
    filled_fields: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    visit: Mapped["Visit"] = relationship(back_populates="forms")


class VisitScheduleAudit(Base):
    """访视排程操作留痕（只追加）：改期/跳过/恢复/插入计划外/链式重算/切版/锁库。"""

    __tablename__ = "visit_schedule_audits"

    id: Mapped[int] = mapped_column(primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), index=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), index=True)
    visit_id: Mapped[int | None] = mapped_column(ForeignKey("visits.id"), nullable=True)
    visit_no: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # reschedule / skip / restore / insert_unscheduled / chain_recompute /
    # revision / lock / unlock / done
    action: Mapped[str] = mapped_column(String(32), index=True)
    old_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    new_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 改期落点是否超窗（超窗必须二次确认 + 强制原因）
    out_of_window: Mapped[bool] = mapped_column(Boolean, default=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    operator_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    operator_name: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    subject: Mapped["Subject"] = relationship(back_populates="schedule_audits")


class PiiViewLog(Base):
    """受试者全名查看留痕（只追加）。"""

    __tablename__ = "pii_view_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), index=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), index=True)
    viewer_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    viewer_name: Mapped[str] = mapped_column(String(32))
    viewer_username: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Query(Base):
    """数据质疑（本轮建表，后续菜单接入）。"""

    __tablename__ = "queries"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), index=True)
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(128))
    detail: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(8), default="normal")  # normal / major
    status: Mapped[str] = mapped_column(String(16), default="open")      # open/answered/closed
    raised_by: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
