from datetime import date, datetime

from pydantic import BaseModel, Field


class LoginIn(BaseModel):
    username: str
    password: str


class SiteOut(BaseModel):
    id: int
    code: str
    name: str
    prefix: str
    city: str
    pi_name: str
    target_enrollment: int


class UserOut(BaseModel):
    id: int
    username: str
    full_name: str
    role: str
    role_label: str
    site_id: int | None
    site: SiteOut | None = None


class LoginOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class FunnelStage(BaseModel):
    key: str
    label: str
    count: int


class SiteFunnel(BaseModel):
    site: SiteOut
    target: int
    screened: int
    enrolled: int
    completed: int
    dropped: int
    terminated: int
    screen_failed: int
    removed: int
    active: int
    enrollment_rate: float
    completion_rate: float


class VisitItem(BaseModel):
    id: int
    subject_id: int
    subject_code: str | None
    screening_no: str
    masked_name: str
    site_id: int
    site_name: str
    visit_no: str
    name: str
    planned_date: date
    window_before: int
    window_after: int
    visit_state: str
    visit_state_label: str
    days_offset: int
    status: str


class DashboardOut(BaseModel):
    generated_at: datetime
    sites: list[SiteFunnel]
    funnel_total: list[FunnelStage]
    today_visits: list[VisitItem]
    overdue_visits: list[VisitItem]
    out_of_window_visits: list[VisitItem]
    alerts: dict[str, int]
    subject_status_counts: dict[str, int]


class SubjectListItem(BaseModel):
    id: int
    site_id: int
    site_code: str
    site_name: str
    screening_no: str
    subject_code: str | None
    display_name: str
    gender: str
    status: str
    status_label: str
    screen_date: date
    enroll_date: date | None
    end_date: date | None
    can_reveal: bool
    next_visit_date: date | None = None
    next_visit_state: str | None = None


class HistoryItem(BaseModel):
    id: int
    from_status: str | None
    from_status_label: str | None
    action: str
    action_label: str
    to_status: str
    to_status_label: str
    reason: str | None
    operator_name: str
    created_at: datetime


class NumberAuditItem(BaseModel):
    id: int
    site_id: int | None = None
    site_name: str | None = None
    kind: str
    kind_label: str
    number: str
    seq: int
    status: str
    status_label: str
    reason: str | None
    operator_name: str
    created_at: datetime


class PiiViewLogItem(BaseModel):
    id: int
    viewer_name: str
    viewer_username: str
    reason: str
    created_at: datetime


class VisitFormOut(BaseModel):
    form_key: str
    name: str
    is_key: bool
    status: str            # pending / incomplete / complete
    status_label: str
    total_fields: int
    filled_fields: int


class AnchorInfo(BaseModel):
    """计划日推算依据（界面明示口径，冲突时给出两个日期）。"""

    base_label: str
    base_date: date | None = None
    policy: str
    policy_label: str
    conflict: bool = False
    winner: str = ""
    alternative_date: date | None = None
    alternative_label: str = ""


class VisitOut(BaseModel):
    id: int
    visit_no: str
    name: str
    planned_date: date
    window_before: int
    window_after: int
    status: str
    visit_state: str
    visit_state_label: str
    actual_date: date | None
    # 访视计划扩展字段（受试者详情页复用同一序列化，保证三处一致）
    subject_id: int | None = None
    order_index: int = 0
    kind: str = "protocol"
    kind_label: str = "方案访视"
    version: str = "v1.0"
    offset_days: int = 0
    anchor_mode: str = "randomization"
    anchor_mode_label: str = "相对随机化日"
    locked: bool = False
    pinned: bool = False
    can_edit: bool = True
    anchor: AnchorInfo | None = None
    forms: list[VisitFormOut] = []
    key_form_done: int = 0
    key_form_total: int = 0
    completion_percent: float = 0.0


class ScheduleAuditItem(BaseModel):
    id: int
    visit_no: str | None
    action: str
    action_label: str
    old_date: date | None
    new_date: date | None
    reason: str | None
    out_of_window: bool
    detail: str | None
    operator_name: str
    created_at: datetime


class SubjectVisitSummary(BaseModel):
    """甘特/列表中每个受试者一行（月/周视图共用）。"""

    subject_id: int
    subject_code: str | None
    screening_no: str
    masked_name: str
    site_id: int
    site_name: str
    timezone: str
    status: str
    status_label: str
    active_version: str
    mixed_versions: bool
    visits: list[VisitOut]
    # 完成度（关键表单口径），总览/详情/导出同源
    completion_percent: float
    completion_label: str
    key_form_done: int
    key_form_total: int
    skipped_count: int
    schedule_audits: list[ScheduleAuditItem] = []


class CalendarDay(BaseModel):
    date: date                 # 中心本地日
    in_range: bool
    visit_ids: list[int]


class VisitPlanOut(BaseModel):
    generated_at: datetime
    view: str                  # month / week
    anchor_date: date          # 定位的中心本地日
    timezone: str
    site_id: int | None
    site_name: str
    policy: str
    policy_label: str
    completion_basis: str      # 完成度口径说明（界面原样展示）
    current_version: str
    versions: list["ProtocolVersionOut"] = []
    subjects: list[SubjectVisitSummary]
    days: list[CalendarDay]
    # 三种空局面各自的机器可读原因，前端据此给不同文案
    empty_reason: str | None   # no_subject / all_skipped / none
    today_local: date
    scope_note: str


class VisitDetailOut(BaseModel):
    visit: VisitOut
    subject_id: int
    subject_code: str | None
    screening_no: str
    masked_name: str
    site_name: str
    timezone: str
    randomization_date: date | None
    active_version: str
    mixed_versions: bool
    policy: str
    policy_label: str
    completion_basis: str
    audits: list[ScheduleAuditItem]


class RescheduleIn(BaseModel):
    new_date: date
    reason: str = Field(min_length=5, max_length=200)
    # 落点超窗时必须为 true（前端二次确认勾选），否则 409
    confirm_out_of_window: bool = False


class SkipIn(BaseModel):
    reason: str = Field(min_length=5, max_length=200)


class UnscheduledIn(BaseModel):
    subject_id: int
    name: str = Field(min_length=2, max_length=64)
    date: date
    window_before: int = Field(default=3, ge=0, le=60)
    window_after: int = Field(default=3, ge=0, le=60)
    reason: str = Field(min_length=5, max_length=200)


class RevisionPublishIn(BaseModel):
    version: str = Field(min_length=2, max_length=24)
    title: str = Field(min_length=2, max_length=128)
    change_note: str = Field(min_length=5, max_length=500)
    effective_date: date
    # 完整新模板：访视号/名称/顺序/相对天数/锚点/窗口/关键表单
    visits: list["TemplateVisitIn"]


class TemplateFormIn(BaseModel):
    form_key: str = Field(min_length=1, max_length=48)
    name: str = Field(min_length=1, max_length=64)
    is_key: bool = True
    total_fields: int = Field(default=0, ge=0, le=500)


class TemplateVisitIn(BaseModel):
    visit_no: str = Field(min_length=1, max_length=16)
    name: str = Field(min_length=1, max_length=64)
    order_index: int
    offset_days: int
    anchor_mode: str = "randomization"
    window_before: int = Field(default=3, ge=0, le=90)
    window_after: int = Field(default=3, ge=0, le=90)
    forms: list[TemplateFormIn] = []


class ProtocolVersionOut(BaseModel):
    version: str
    title: str
    change_note: str
    effective_date: date
    published_by: str
    is_current: bool
    created_at: datetime


class RevisionResultOut(BaseModel):
    version: str
    upgraded_subjects: int
    frozen_visits: int
    upgraded_visits: int
    dropped_visits: int
    affected_subject_ids: list[int]
    message: str


class LockIn(BaseModel):
    locked: bool
    reason: str = Field(min_length=5, max_length=200)


class SubjectDetail(SubjectListItem):
    birth_date: date | None = None
    phone_masked: str | None = None
    completion_date: date | None
    histories: list[HistoryItem]
    number_audits: list[NumberAuditItem]
    visits: list[VisitOut]
    pii_view_logs: list[PiiViewLogItem]
    allowed_actions: list[str]
    randomization_date: date | None = None
    active_version: str = "v1.0"
    mixed_versions: bool = False
    completion_percent: float = 0.0
    completion_label: str = "0/0"
    completion_basis: str = ""
    policy: str = "actual_first"
    policy_label: str = ""
    timezone: str = "Asia/Shanghai"


class SubjectCreateIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=32)
    gender: str = Field(pattern="^(男|女)$")
    birth_date: date
    phone: str = Field(min_length=6, max_length=20)
    site_id: int


class TransitionIn(BaseModel):
    action: str
    reason: str | None = None


class RevealIn(BaseModel):
    reason: str = Field(min_length=5, max_length=200)


class RevealOut(BaseModel):
    full_name: str
    logged_at: datetime
    message: str


class SubjectOutCreated(BaseModel):
    id: int
    screening_no: str
    status: str


# 前向引用（ProtocolVersionOut / TemplateVisitIn 定义顺序靠后）需显式重建
VisitPlanOut.model_rebuild()
RevisionPublishIn.model_rebuild()
