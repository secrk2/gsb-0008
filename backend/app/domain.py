"""溯源方核心领域规则（不依赖任何第三方库，便于离线单元测试）。

包含：受试者状态机、访视窗期判定、编号规则、姓名脱敏。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum


# ---------------------------------------------------------------------------
# 状态机
# ---------------------------------------------------------------------------
class SubjectStatus(str, Enum):
    SCREENING = "screening"        # 筛选登记
    ENROLLED = "enrolled"          # 已入组
    COMPLETED = "completed"        # 已完成
    DROPPED = "dropped"            # 脱落
    TERMINATED = "terminated"      # 中止
    SCREEN_FAILED = "screen_failed"  # 筛选失败
    REMOVED = "removed"            # 剔除

    @property
    def label(self) -> str:
        return STATUS_LABELS[self]


class ScreenStatus(str, Enum):
    SCREENING = "screening"
    PASS = "pass"
    FAIL = "fail"


class Action(str, Enum):
    ENROLL = "enroll"
    SCREEN_FAIL = "screen_fail"
    COMPLETE = "complete"
    DROPOUT = "dropout"
    TERMINATE = "terminate"
    REMOVE = "remove"

    @property
    def label(self) -> str:
        return ACTION_LABELS[self]


STATUS_LABELS: dict[SubjectStatus, str] = {
    SubjectStatus.SCREENING: "筛选中",
    SubjectStatus.ENROLLED: "已入组",
    SubjectStatus.COMPLETED: "已完成",
    SubjectStatus.DROPPED: "脱落",
    SubjectStatus.TERMINATED: "中止",
    SubjectStatus.SCREEN_FAILED: "筛选失败",
    SubjectStatus.REMOVED: "剔除",
}

ACTION_LABELS: dict[Action, str] = {
    Action.ENROLL: "入组",
    Action.SCREEN_FAIL: "筛选失败",
    Action.COMPLETE: "完成研究",
    Action.DROPOUT: "标记脱落",
    Action.TERMINATE: "中止研究",
    Action.REMOVE: "剔除",
}

# 终态：不允许任何回退/再迁移
TERMINAL_STATUSES = {
    SubjectStatus.COMPLETED,
    SubjectStatus.DROPPED,
    SubjectStatus.TERMINATED,
    SubjectStatus.SCREEN_FAILED,
    SubjectStatus.REMOVED,
}

# 合法迁移表（白名单）。任何不在表内的迁移一律拦截。
ALLOWED_TRANSITIONS: dict[SubjectStatus, set[Action]] = {
    SubjectStatus.SCREENING: {Action.ENROLL, Action.SCREEN_FAIL},
    SubjectStatus.ENROLLED: {
        Action.COMPLETE,
        Action.DROPOUT,
        Action.TERMINATE,
        Action.REMOVE,
    },
    SubjectStatus.COMPLETED: set(),
    SubjectStatus.DROPPED: set(),
    SubjectStatus.TERMINATED: set(),
    SubjectStatus.SCREEN_FAILED: set(),
    SubjectStatus.REMOVED: set(),
}

# 动作 -> 目标状态
ACTION_TARGET: dict[Action, SubjectStatus] = {
    Action.ENROLL: SubjectStatus.ENROLLED,
    Action.SCREEN_FAIL: SubjectStatus.SCREEN_FAILED,
    Action.COMPLETE: SubjectStatus.COMPLETED,
    Action.DROPOUT: SubjectStatus.DROPPED,
    Action.TERMINATE: SubjectStatus.TERMINATED,
    Action.REMOVE: SubjectStatus.REMOVED,
}

# 需要填写原因的动作
REASON_REQUIRED = {Action.DROPOUT, Action.TERMINATE, Action.REMOVE, Action.SCREEN_FAIL}


class IllegalTransitionError(Exception):
    """非法状态迁移，message 必须可直接展示给研究者。"""

    def __init__(self, current: SubjectStatus, action: Action):
        self.current = current
        self.action = action
        if current in TERMINAL_STATUSES:
            msg = (
                f"非法状态回退：受试者当前为「{current.label}」（终态），"
                f"不能执行「{action.label}」。终态受试者不允许回退或变更状态，"
                f"如属误操作请联系数据管理员核查并留痕。"
            )
        elif current == SubjectStatus.SCREENING:
            msg = (
                f"非法状态迁移：筛选中的受试者只能「入组」或标记「筛选失败」，"
                f"不能直接执行「{action.label}」。"
            )
        elif current == SubjectStatus.ENROLLED:
            msg = (
                f"非法状态迁移：已入组受试者不能执行「{action.label}」，"
                f"允许的后续动作为：完成研究 / 脱落 / 中止 / 剔除。"
            )
        else:
            msg = (
                f"非法状态迁移：「{current.label}」→「{action.label}」"
                f"不在允许的状态迁移范围内。"
            )
        super().__init__(msg)


def can_transition(current: SubjectStatus, action: Action) -> bool:
    return action in ALLOWED_TRANSITIONS.get(current, set())


def transition(current: SubjectStatus, action: Action, reason: str | None = None) -> SubjectStatus:
    """校验并返回目标状态；非法迁移抛 IllegalTransitionError。"""
    if not can_transition(current, action):
        raise IllegalTransitionError(current, action)
    if action in REASON_REQUIRED and not (reason and reason.strip()):
        raise ValueError(f"执行「{action.label}」必须填写原因并留痕。")
    return ACTION_TARGET[action]


# ---------------------------------------------------------------------------
# 编号规则
# ---------------------------------------------------------------------------
def format_screening_no(prefix: str, seq: int) -> str:
    return f"{prefix}-S{seq:03d}"


def format_subject_code(prefix: str, seq: int) -> str:
    return f"{prefix}-{seq:03d}"


def next_subject_code(prefix: str, used_seqs: set[int], cursor: int) -> tuple[str, int]:
    """作废号码永不复用：在游标之后顺序取号，跳过已作废/已使用号段。

    生产环境中以中心行上的游标 + 唯一约束为准（见 routers/subjects.py），
    本函数用于把规则显式化与单元测试。
    返回 (完整编号, 新游标)。
    """
    seq = cursor + 1
    while seq in used_seqs:  # pragma: no cover - 唯一约束兜底，正常不会命中
        seq += 1
    return format_subject_code(prefix, seq), seq


# ---------------------------------------------------------------------------
# 姓名脱敏：入组后 缩写 + 编号
# ---------------------------------------------------------------------------
def mask_name(full_name: str, subject_code: str | None) -> str:
    """入组后展示用脱敏名。

    - 中文姓名：保留姓氏首字（视为缩写），其余以 * 替代；
    - 英文姓名：取各单词首字母缩写；
    - 末尾拼受试者编号。
    筛选中（尚未编号）不展示真实姓名，统一返回「未编号-***」。
    """
    name = (full_name or "").strip()
    if not subject_code:
        return "未编号-***"
    if not name:
        return f"***（{subject_code}）"
    if all(ord(ch) < 128 for ch in name):
        parts = [p for p in name.replace(".", " ").split() if p]
        abbr = ".".join(p[0].upper() for p in parts) if parts else "***"
    else:
        abbr = name[0] + "*" * max(1, len(name) - 1)
    return f"{abbr}（{subject_code}）"


# ---------------------------------------------------------------------------
# 访视窗期
# ---------------------------------------------------------------------------
class VisitState(str, Enum):
    UPCOMING = "upcoming"      # 未到窗
    IN_WINDOW = "in_window"    # 窗内（含今日应随访）
    DUE_TODAY = "due_today"    # 今日应随访
    OVERDUE = "overdue"        # 逾期（仍在窗内）
    OUT_OF_WINDOW = "out_of_window"  # 超窗
    DONE = "done"
    SKIPPED = "skipped"        # 已跳过（经研究者确认未执行，区别于失访）
    MISSED = "missed"          # 已标记失访


def visit_state(
    planned: date,
    today: date,
    window_before: int,
    window_after: int,
    status: str = "scheduled",
) -> VisitState:
    if status == "done":
        return VisitState.DONE
    if status == "skipped":
        return VisitState.SKIPPED
    if status == "missed":
        return VisitState.MISSED
    early = planned - timedelta(days=window_before)
    late = planned + timedelta(days=window_after)
    if today == planned:
        return VisitState.DUE_TODAY
    if early <= today < planned:
        return VisitState.IN_WINDOW
    if planned < today <= late:
        return VisitState.OVERDUE
    if today > late:
        return VisitState.OUT_OF_WINDOW
    return VisitState.UPCOMING
