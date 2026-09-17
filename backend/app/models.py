from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, func
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


class Visit(Base):
    __tablename__ = "visits"

    id: Mapped[int] = mapped_column(primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), index=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), index=True)
    visit_no: Mapped[str] = mapped_column(String(8))
    name: Mapped[str] = mapped_column(String(64))
    planned_date: Mapped[date] = mapped_column(Date, index=True)
    window_before: Mapped[int] = mapped_column(Integer, default=3)
    window_after: Mapped[int] = mapped_column(Integer, default=3)
    # scheduled / done / missed
    status: Mapped[str] = mapped_column(String(16), default="scheduled")
    actual_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    subject: Mapped["Subject"] = relationship(back_populates="visits")


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
