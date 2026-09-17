"""溯源方核心领域规则（不依赖任何第三方库，便于离线单元测试）。

包含：受试者状态机、访视窗期判定、编号规则、姓名脱敏、
访视排程链式重算（跳过/计划外/锁库/环检测）、关键表单完成度口径、方案修订冻结。
"""
from __future__ import annotations

from dataclasses import dataclass, field
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
    SKIPPED = "skipped"        # 已跳过（方案允许，不计完成）
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
    if status == "unscheduled":
        # 计划外访视为既成事实（实际日即插入日），不参与窗期红点判定
        return VisitState.DONE
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


# ---------------------------------------------------------------------------
# 访视排程：链式重算（跳过 / 计划外 / 改期）、锁库保护、环形依赖检测
# ---------------------------------------------------------------------------
# 访视业务状态（区别于状态机式的窗期“观感” visit_state）：
#   scheduled 已计划 / done 已完成 / skipped 已跳过（方案允许）/
#   unscheduled 计划外访视 / missed 失访 / locked 已锁库（冻结，禁止任何改动）
VISIT_SCHEDULED = "scheduled"
VISIT_DONE = "done"
VISIT_SKIPPED = "skipped"
VISIT_UNSCHEDULED = "unscheduled"
VISIT_MISSED = "missed"
VISIT_LOCKED = "locked"

EDITABLE_STATUSES = {VISIT_SCHEDULED}  # 只有“已计划、未发生、未锁库”可被改期/跳过

# 排程锚点口径（冲突时必须界面明示，见 ANCHOR_POLICY_TEXT）：
#   randomization 一律以随机化（入组）日为锚 —— 方案定义的名义计划，修订对比基准；
#   previous_actual 以上一次实际访视日为锚 —— 现场执行口径，链式重算默认采用。
ANCHOR_RANDOMIZATION = "randomization"
ANCHOR_PREVIOUS_ACTUAL = "previous_actual"

ANCHOR_POLICY_TEXT = (
    "排程口径（两种口径冲突时以此为准）：访视名义计划日一律以「随机化日期 + 相对天数」"
    "推算并写在方案上；当研究者改期、跳过或插入计划外访视后，后续未发生访视改按"
    "「上一次实际访视日期 + 相对天数差」链式重算。两者不一致时，甘特图以浅色虚线显示"
    "随机化口径的名义日、以实线显示执行口径的现行计划日，并逐日标注两个日期，"
    "不以其中一个静默覆盖另一个。已完成/已锁库访视不参与重算。"
)


class VisitNode:
    """排程计算用的访视节点（纯数据，可在单测中直接构造，不依赖 ORM）。

    关键不变量：
    - ``day`` 仅来自方案版本定义（相对随机化日的天数）；计划外访视无方案定义，
      ``day`` 为 None；
    - ``nominal_date`` = 随机化日 + day（方案名义日，永不被执行操作改写）；
    - ``planned_date`` 为当前执行计划日；链式重算只写这个字段。
    """

    __slots__ = (
        "id", "seq", "day", "planned_date", "actual_date", "status",
        "nominal_date", "locked", "kind", "window_before", "window_after",
        "prev_id",
    )

    def __init__(
        self,
        id: int,
        seq: float,
        day: int | None,
        planned_date: date,
        status: str = VISIT_SCHEDULED,
        *,
        actual_date: date | None = None,
        nominal_date: date | None = None,
        locked: bool = False,
        kind: str = "protocol",
        window_before: int = 3,
        window_after: int = 3,
        prev_id: int | None = None,
    ):
        self.id = id
        self.seq = seq
        self.day = day
        self.planned_date = planned_date
        self.actual_date = actual_date
        self.status = status
        self.nominal_date = nominal_date if nominal_date is not None else planned_date
        self.locked = locked or status == VISIT_LOCKED
        self.kind = kind  # protocol / unscheduled
        self.window_before = window_before
        self.window_after = window_after
        self.prev_id = prev_id

    @property
    def anchor_date(self) -> date:
        """执行口径锚点：实际发生过（完成/锁库）取实际日，否则取现行计划日。"""
        if self.status == VISIT_DONE and self.actual_date is not None:
            return self.actual_date
        if self.locked and self.actual_date is not None:
            return self.actual_date
        return self.planned_date

    @property
    def is_fixed(self) -> bool:
        """固定节点：已完成/已跳过/已锁库/失访/计划外 —— 重算不得改写。"""
        return self.status in (
            VISIT_DONE, VISIT_SKIPPED, VISIT_LOCKED, VISIT_MISSED,
        ) or self.locked or self.kind == "unscheduled"


class ScheduleError(Exception):
    """排程非法操作，message 可直接展示给研究者。"""


def _order_nodes(nodes: list[VisitNode]) -> list[VisitNode]:
    ordered = sorted(nodes, key=lambda n: (n.seq, n.id))
    # 环检测：显式 prev_id 链不允许成环（排序兜底之外，链式依赖也要无环）
    seen: set[int] = set()
    by_id = {n.id: n for n in nodes}
    for n in ordered:
        cur, path = n.prev_id, []
        while cur is not None:
            if cur in path:
                raise ScheduleError(
                    "访视依赖链检测到环形引用，链式重算已中止："
                    f"访视节点 {cur} 的前驱关系形成闭环。请联系数据管理员核查排程定义。"
                )
            path.append(cur)
            if cur in seen or cur not in by_id:
                break
            cur = by_id[cur].prev_id
        seen.add(n.id)
    return ordered


def reschedule_chain(
    nodes: list[VisitNode],
    changed_id: int | None,
    changed_date: date | None = None,
) -> dict[int, date]:
    """链式重算后续未发生访视的计划日。

    规则：
    - 被改期节点 ``changed_id`` 的计划日置为 ``changed_date``（仅 scheduled 可改）；
    - 从该节点向后，每个**仍可编辑**（scheduled、未锁库、方案内）的访视，按
      「上一锚点日 + (本次方案相对天数 − 上一节点方案相对天数)」重算；
      相对天数差来自方案定义（``day``），因此无论前面被平移多少天，
      方案周期间隔（如 V2−V1=14 天）始终保持；
    - 跳过 / 已完成 / 已锁库 / 失访 / 计划外节点固定不动，但会成为后续链的新锚点；
      因此链式重算永远不会改写已锁库访视（防御性检查在发现将要改动锁库日时整体中止）。

    返回 ``{visit_id: 新计划日}``（只含发生变化的节点）。
    """
    ordered = _order_nodes(nodes)
    if changed_id is None:
        return {}
    by_id = {n.id: n for n in ordered}
    target = by_id.get(changed_id)
    if target is None:
        raise ScheduleError("待改期的访视不存在或已不属于本受试者方案。")
    if target.locked or target.status == VISIT_LOCKED:
        raise ScheduleError("该访视已锁库，计划日期被冻结，不能改期或参与链式重算。")
    if target.status not in EDITABLE_STATUSES:
        label = {
            VISIT_DONE: "已完成", VISIT_SKIPPED: "已跳过",
            VISIT_MISSED: "已失访", VISIT_UNSCHEDULED: "计划外访视",
        }.get(target.status, target.status)
        raise ScheduleError(f"访视当前为「{label}」，不能改期；仅未发生的已计划访视可改期。")
    target.planned_date = changed_date
    changes: dict[int, date] = {changed_id: changed_date}
    start_idx = next(i for i, n in enumerate(ordered) if n.id == changed_id)

    prev = ordered[start_idx]
    for n in ordered[start_idx + 1:]:
        if n.is_fixed:
            prev = n  # 固定节点成为后续链的新锚点
            continue
        if n.day is None or prev.day is None:
            # 计划外节点之后缺少方案相对天数：顺延一天，保证不挤成同一天
            new_date = prev.anchor_date + timedelta(days=1)
        else:
            new_date = prev.anchor_date + timedelta(days=n.day - prev.day)
        if n.locked and new_date != n.planned_date:
            raise ScheduleError(
                "链式重算将改动已锁库访视的计划日，系统已整体中止本次重算，"
                "锁库数据保持原样。如需调整，请先按SOP申请解锁并留痕。"
            )
        if new_date != n.planned_date:
            changes[n.id] = new_date
            n.planned_date = new_date
        prev = n
    return changes


def skip_visit(nodes: list[VisitNode], visit_id: int) -> dict[int, date]:
    """跳过一次方案访视：状态置 skipped（固定），后续链以其原计划日为锚继续重算。

    被跳过的访视不删除、不消失——它仍占据方案序列与相对天数位置，
    只是不再要求执行；这样既不产生环，也不会让后续访视整体提前。
    """
    by_id = {n.id: n for n in nodes}
    node = by_id.get(visit_id)
    if node is None:
        raise ScheduleError("待跳过的访视不存在。")
    if node.locked or node.status == VISIT_LOCKED:
        raise ScheduleError("该访视已锁库，不能跳过。")
    if node.status == VISIT_DONE:
        raise ScheduleError("访视已完成，不能跳过；如属误完成请按数据更正流程处理。")
    if node.status == VISIT_SKIPPED:
        raise ScheduleError("该访视已处于跳过状态，请勿重复操作。")
    anchor = node.planned_date
    node.status = VISIT_SKIPPED
    node.actual_date = None
    # 跳过点本身不移动后续节奏：以其原计划日作为固定锚再跑一次链
    return _recompute_after(nodes, node.id, anchor)


def insert_unscheduled(
    nodes: list[VisitNode],
    new_id: int,
    the_date: date,
    name_day: int | None = None,
) -> tuple[VisitNode, dict[int, date]]:
    """插入计划外访视，并链式重算其后尚未发生的方案访视。

    计划外访视作为固定锚点（实际/计划日即插入日），按日期自动排入序列中间
    （seq 取相邻节点中点，避免重排既有节点序位）；其后第一个固定节点
    （完成/跳过/锁库）之前的未发生访视整体顺延，顺延天数 = 插入日 − 前一锚点日
    （只推不拉：插入日早于前锚点时不顺延，避免把未到窗访视改到过去）。
    """
    ordered = _order_nodes(nodes)
    pos = 0
    while pos < len(ordered) and ordered[pos].anchor_date <= the_date:
        pos += 1
    if pos == 0:
        seq = ordered[0].seq - 1 if ordered else 0
    elif pos == len(ordered):
        seq = ordered[-1].seq + 1
    else:
        seq = (ordered[pos - 1].seq + ordered[pos].seq) / 2
    node = VisitNode(
        id=new_id, seq=seq, day=name_day, planned_date=the_date,
        status=VISIT_UNSCHEDULED, kind="unscheduled",
        actual_date=the_date, nominal_date=the_date,
    )
    nodes.append(node)
    ordered = _order_nodes(nodes)
    idx = next(i for i, n in enumerate(ordered) if n.id == new_id)
    prev = ordered[idx - 1] if idx > 0 else None
    if prev is None:
        return node, {}
    shift = (the_date - prev.anchor_date).days
    changes: dict[int, date] = {}
    if shift > 0:
        for n in ordered[idx + 1:]:
            if n.is_fixed:
                # 遇到完成/跳过/锁库即停止顺延：固定节点及其后以它为锚，不被改动
                break
            new_date = n.planned_date + timedelta(days=shift)
            changes[n.id] = new_date
            n.planned_date = new_date
    return node, changes


def _recompute_after(nodes: list[VisitNode], fixed_id: int, anchor: date) -> dict[int, date]:
    """以某固定节点原计划日为锚，重算其后可编辑节点（保持方案间隔）。"""
    ordered = _order_nodes(nodes)
    idx = next(i for i, n in enumerate(ordered) if n.id == fixed_id)
    changes: dict[int, date] = {}
    fixed_node = ordered[idx]
    prev = fixed_node
    prev_anchor = anchor  # 固定节点用其原计划日，而非可能为 None 的实际日
    for n in ordered[idx + 1:]:
        if n.is_fixed:
            prev, prev_anchor = n, n.anchor_date
            continue
        if n.day is not None and prev.day is not None:
            base = prev_anchor
            new_date = base + timedelta(days=n.day - prev.day)
        else:
            new_date = prev_anchor + timedelta(days=1)
        if new_date != n.planned_date:
            if n.locked:
                raise ScheduleError("链式重算将改动已锁库访视，已整体中止。")
            changes[n.id] = new_date
            n.planned_date = new_date
        prev, prev_anchor = n, new_date
    return changes


# ---------------------------------------------------------------------------
# 完成度口径：关键表单（key forms）
# ---------------------------------------------------------------------------
# 自决结论（需展示在界面上，见 COMPLETION_POLICY_TEXT）：
# 采用「已完成关键表单数 / 关键表单总数」，不采用「已提交字段数 / 字段总数」。
# 理由：临床数据库锁/SDV 与 GCP 溯源以“表单个”为单位（签字、稽查、质疑都挂在表单上），
# 半张表在医学上不可用；按字段数会把“只填了半张表”的访视算成 50% 完成，
# 给出虚假进度，按关键表单则算 0，如实反映“该访视尚不可交付”。
COMPLETION_BASIS = "key_forms"
COMPLETION_POLICY_TEXT = (
    "完成度口径（全平台统一）：按「已完成关键表单数 ÷ 关键表单总数」计算，"
    "不按已提交字段数计算。一张关键表单必须全部必填项完成并提交才算 1 张；"
    "只填了半张表的访视，按字段口径会显示约 50%（看似有进度），"
    "按本平台口径计 0 张、该访视不计完成——因为半张表无法用于医学判断与锁库。"
    "非关键表单（如可选的合并用药备注）不计入分母。总览页、访视详情页、"
    "导出结果三处使用同一服务端计算，数字必然一致。"
)

FORM_PENDING = "pending"          # 未开始
FORM_IN_PROGRESS = "in_progress"  # 填写中（有已提交字段但表单未整体完成）
FORM_COMPLETE = "complete"        # 已完成并提交
FORM_FORMULA = "formula"          # 系统自动计算/衍生表单（如 eGFR），不占人工完成度分母


@dataclass
class FormProgress:
    status: str
    submitted_fields: int = 0
    total_fields: int = 0
    is_key: bool = True


@dataclass
class VisitCompletion:
    visit_id: int
    visit_status: str
    key_total: int = 0
    key_done: int = 0
    field_total: int = 0
    field_submitted: int = 0
    forms: list[FormProgress] = field(default_factory=list)

    @property
    def rate(self) -> float:
        """关键表单完成率，百分数保留 1 位。无关键表单返回 0（不伪造 100%）。"""
        if self.key_total == 0:
            return 0.0
        return round(self.key_done / self.key_total * 100, 1)

    @property
    def field_rate(self) -> float:
        """对照口径（仅用于界面展示“若按字段会是多少”，不参与任何正式数字）。"""
        if self.field_total == 0:
            return 0.0
        return round(self.field_submitted / self.field_total * 100, 1)

    @property
    def is_complete(self) -> bool:
        return self.key_total > 0 and self.key_done == self.key_total


def compute_visit_completion(
    visit_id: int, visit_status: str, forms: list[FormProgress]
) -> VisitCompletion:
    vc = VisitCompletion(visit_id=visit_id, visit_status=visit_status, forms=list(forms))
    for f in forms:
        if not f.is_key or f.status == FORM_FORMULA:
            continue
        vc.key_total += 1
        vc.field_total += f.total_fields
        vc.field_submitted += min(f.submitted_fields, f.total_fields)
        if f.status == FORM_COMPLETE:
            vc.key_done += 1
    return vc


def compute_subject_completion(visits: list[VisitCompletion]) -> dict:
    """受试者级完成度：关键表单口径汇总。跳过的访视从分母中剔除并单独计数。"""
    counted = [v for v in visits if v.visit_status != VISIT_SKIPPED]
    key_total = sum(v.key_total for v in counted)
    key_done = sum(v.key_done for v in counted)
    field_total = sum(v.field_total for v in counted)
    field_submitted = sum(v.field_submitted for v in counted)
    skipped = len(visits) - len(counted)
    rate = round(key_done / key_total * 100, 1) if key_total else 0.0
    field_rate = round(field_submitted / field_total * 100, 1) if field_total else 0.0
    return {
        "basis": COMPLETION_BASIS,
        "key_total": key_total,
        "key_done": key_done,
        "rate": rate,
        "field_total": field_total,
        "field_submitted": field_submitted,
        "field_rate": field_rate,
        "skipped_visits": skipped,
        "visits_total": len(visits),
    }


# ---------------------------------------------------------------------------
# 方案修订冻结
# ---------------------------------------------------------------------------
AMENDMENT_FREEZE_TEXT = (
    "方案修订冻结规则：修订版本发布后，已完成（含已锁库）的访视冻结在其执行时的"
    "旧版本上原样保留、不重算不迁移；发布日之后尚未发生的访视自动切换到新版本的"
    "相对天数与窗口。同一受试者同时存在新旧两版访视时，甘特图与详情页以深色横幅"
    "显式标注「跨方案版本」，旧版访视带版本角标（如 v1），任何人不得静默改版。"
)


def effective_version(
    visit_actual_date: date | None,
    visit_status: str,
    amendment_effective_date: date,
) -> str:
    """判定单次访视冻结在哪一版（仅示意两版；实际版本号由调用方传入）。

    已完成/锁库/失访且实际日早于修订生效日 → 旧版冻结；
    其余（修订生效后才发生，或尚未发生）→ 新版。
    """
    frozen_statuses = {VISIT_DONE, VISIT_LOCKED, VISIT_MISSED, VISIT_SKIPPED}
    if visit_status in frozen_statuses and visit_actual_date is not None:
        return "old" if visit_actual_date < amendment_effective_date else "new"
    return "new"


def split_visits_by_amendment(
    nodes: list[VisitNode], effective_date: date
) -> tuple[list[VisitNode], list[VisitNode]]:
    """把受试者访视拆成 (旧版冻结, 新版执行) 两组，供界面判断是否“跨版本并存”。"""
    old, new = [], []
    for n in nodes:
        if effective_version(n.actual_date, n.status, effective_date) == "old":
            old.append(n)
        else:
            new.append(n)
    return old, new


def in_window(planned: date, target: date, window_before: int, window_after: int) -> bool:
    """target 是否落在 [planned-before, planned+after] 窗内（含端点，日历日）。"""
    return planned - timedelta(days=window_before) <= target <= planned + timedelta(
        days=window_after
    )
