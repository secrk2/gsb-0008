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


class VisitCompletionOut(BaseModel):
    basis: str = "key_forms"
    key_total: int = 0
    key_done: int = 0
    rate: float = 0.0
    field_total: int = 0
    field_submitted: int = 0
    field_rate: float = 0.0
    is_complete: bool = False


class VisitOut(BaseModel):
    id: int
    visit_no: str
    name: str
    planned_date: date
    nominal_date: date | None = None
    divergence_days: int = 0
    window_before: int
    window_after: int
    status: str
    status_label: str | None = None
    kind: str = "protocol"
    locked: bool = False
    visit_state: str
    visit_state_label: str
    actual_date: date | None
    version_label: str | None = None
    day_offset: int | None = None
    insert_reason: str | None = None
    completion: VisitCompletionOut | None = None


class SubjectDetail(SubjectListItem):
    birth_date: date | None = None
    phone_masked: str | None = None
    completion_date: date | None
    histories: list[HistoryItem]
    number_audits: list[NumberAuditItem]
    visits: list[VisitOut]
    pii_view_logs: list[PiiViewLogItem]
    allowed_actions: list[str]
    # 访视计划：完成度（关键表单个口径）、跨版本并存标记与口径成文说明
    visit_completion: dict | None = None
    mixed_versions: dict | None = None
    visit_empty_kind: str | None = None
    completion_policy_text: str | None = None
    anchor_policy_text: str | None = None
    amendment_freeze_text: str | None = None
    site_timezone: str | None = None


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
