from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base
from .tz import now_utc


class Site(Base):
    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    prefix: Mapped[str] = mapped_column(String(8), unique=True)
    city: Mapped[str] = mapped_column(String(32))
    # IANA 时区名（日期 UTC 存储、按此时区展示与判定“今天/同一天”）
    timezone: Mapped[str] = mapped_column(String(48), default="Asia/Shanghai")
    pi_name: Mapped[str] = mapped_column(String(32))
    target_enrollment: Mapped[int] = mapped_column(Integer, default=0)
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
    completion_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    site: Mapped["Site"] = relationship(back_populates="subjects")
    visits: Mapped[list["Visit"]] = relationship(
        back_populates="subject", cascade="all, delete-orphan"
    )
    histories: Mapped[list["SubjectStatusHistory"]] = relationship(
        back_populates="subject", cascade="all, delete-orphan"
    )
    number_audits: Mapped[list["NumberAudit"]] = relationship(
        primaryjoin="foreign(NumberAudit.subject_id) == Subject.id",
        viewonly=True,
        order_by="NumberAudit.id",
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
    """方案版本。修订发布后：已完成访视冻结在旧版，未发生访视切换到新版。"""

    __tablename__ = "protocol_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[str] = mapped_column(String(16), unique=True, index=True)  # v1.0 / v1.1
    # draft 草案 / effective 现行 / superseded 已被取代
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    effective_date: Mapped[date] = mapped_column(Date)
    change_summary: Mapped[str] = mapped_column(Text, default="")
    published_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    visit_defs: Mapped[list["ProtocolVisitDef"]] = relationship(
        back_populates="version", cascade="all, delete-orphan"
    )
    form_defs: Mapped[list["ProtocolFormDef"]] = relationship(
        back_populates="version", cascade="all, delete-orphan"
    )


class ProtocolVisitDef(Base):
    """方案版本中的访视定义：相对随机化日的天数 + 窗口（相对天数表达，不存绝对日期）。"""

    __tablename__ = "protocol_visit_defs"
    __table_args__ = (UniqueConstraint("version_id", "visit_no", name="uq_visit_def_version_no"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("protocol_versions.id"), index=True)
    visit_no: Mapped[str] = mapped_column(String(8))
    name: Mapped[str] = mapped_column(String(64))
    day_offset: Mapped[int] = mapped_column(Integer)       # 相对随机化日（可负，筛选访视）
    window_before: Mapped[int] = mapped_column(Integer, default=3)
    window_after: Mapped[int] = mapped_column(Integer, default=3)
    seq: Mapped[int] = mapped_column(Integer)

    version: Mapped["ProtocolVersion"] = relationship(back_populates="visit_defs")


class ProtocolFormDef(Base):
    """访视关键表单目录：完成度按“关键表单个”计算，字段数仅用于对照展示。"""

    __tablename__ = "protocol_form_defs"
    __table_args__ = (
        UniqueConstraint("version_id", "visit_no", "form_code",
                         name="uq_form_def_version_visit_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("protocol_versions.id"), index=True)
    visit_no: Mapped[str] = mapped_column(String(8), index=True)
    form_code: Mapped[str] = mapped_column(String(32))
    form_name: Mapped[str] = mapped_column(String(64))
    is_key: Mapped[bool] = mapped_column(Boolean, default=True)
    field_count: Mapped[int] = mapped_column(Integer, default=0)
    # formula 表示系统自动计算/衍生表单，不占人工完成度分母
    kind: Mapped[str] = mapped_column(String(16), default="entry")  # entry / formula
    seq: Mapped[int] = mapped_column(Integer)

    version: Mapped["ProtocolVersion"] = relationship(back_populates="form_defs")


class Visit(Base):
    __tablename__ = "visits"
    __table_args__ = (
        UniqueConstraint("subject_id", "visit_no", "kind", name="uq_visit_subject_no_kind"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), index=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), index=True)
    visit_no: Mapped[str] = mapped_column(String(8))
    name: Mapped[str] = mapped_column(String(64))
    planned_date: Mapped[date] = mapped_column(Date, index=True)
    # 随机化口径名义日（随机化日 + 方案相对天数），永不因执行操作改写；可能为空（旧数据）
    nominal_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # 序位：方案访视为整数，计划外访视插入时取相邻中点（浮点）
    seq: Mapped[float] = mapped_column(Float, default=0)
    window_before: Mapped[int] = mapped_column(Integer, default=3)
    window_after: Mapped[int] = mapped_column(Integer, default=3)
    # scheduled / done / skipped / unscheduled / missed / locked
    status: Mapped[str] = mapped_column(String(16), default="scheduled", index=True)
    actual_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # protocol 方案访视 / unscheduled 计划外访视
    kind: Mapped[str] = mapped_column(String(16), default="protocol")
    # 锁库：冻结计划日/状态/表单，禁止改期、跳过与重算
    locked: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 该访视执行时所依据的方案版本（修订冻结的落点）
    protocol_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("protocol_versions.id"), nullable=True, index=True
    )
    version_label: Mapped[str | None] = mapped_column(String(16), nullable=True)
    day_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    insert_reason: Mapped[str | None] = mapped_column(Text, nullable=True)  # 计划外访视原因
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc
    )

    subject: Mapped["Subject"] = relationship(back_populates="visits")
    forms: Mapped[list["VisitForm"]] = relationship(
        back_populates="visit", cascade="all, delete-orphan"
    )
    audits: Mapped[list["VisitAudit"]] = relationship(
        back_populates="visit", cascade="all, delete-orphan",
        order_by="VisitAudit.id.desc()",
    )


class VisitForm(Base):
    """访视下的表单实例（完成度唯一数据源；三处口径一致由服务端同一函数计算）。"""

    __tablename__ = "visit_forms"
    __table_args__ = (UniqueConstraint("visit_id", "form_code", name="uq_form_visit_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    visit_id: Mapped[int] = mapped_column(ForeignKey("visits.id"), index=True)
    form_code: Mapped[str] = mapped_column(String(32))
    form_name: Mapped[str] = mapped_column(String(64))
    is_key: Mapped[bool] = mapped_column(Boolean, default=True)
    field_total: Mapped[int] = mapped_column(Integer, default=0)
    submitted_fields: Mapped[int] = mapped_column(Integer, default=0)
    # pending / in_progress / complete / formula
    status: Mapped[str] = mapped_column(String(16), default="pending")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc
    )

    visit: Mapped["Visit"] = relationship(back_populates="forms")


class VisitAudit(Base):
    """访视排程留痕（只追加）：改期/超窗改期/跳过/计划外插入/锁库/状态变更。"""

    __tablename__ = "visit_audits"

    id: Mapped[int] = mapped_column(primary_key=True)
    visit_id: Mapped[int] = mapped_column(ForeignKey("visits.id"), index=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), index=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), index=True)
    # reschedule / reschedule_out_of_window / skip / insert_unscheduled /
    # lock / complete / chain_recompute
    action: Mapped[str] = mapped_column(String(32))
    old_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    new_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    operator_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    operator_name: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, index=True
    )

    visit: Mapped["Visit"] = relationship(back_populates="audits")


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
