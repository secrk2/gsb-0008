"""访视排程纯规则模块（零三方依赖，便于离线单元测试）。

本模块是访视计划唯一的规则事实源，API 总览 / 访视详情 / 导出三处必须经由本模块
计算，禁止各自再算一遍，以保证「三处一致」。

覆盖：
1. 时区：日期一律以 UTC 日历日存储，按研究中心所在时区（IANA tz）展示；
   跨时区、夏令时「是否同一天」一律先把 UTC 日历日还原为时刻再转本地判定。
2. 方案与窗口期：相对天数 + 双锚点（随机化日 / 上一次实际访视日），口径冲突显式标记。
3. 链式重算：改期 / 跳过 / 恢复 / 插入计划外 / 回填实际日后的下游计划重算，
   带环依赖防御与锁库保护。
4. 方案修订冻结：已完成 / 已跳过 / 已锁库访视冻结旧版，未发生访视切换新版。
5. 完成度：按「已完成关键表单（CRF）数」口径，半张表不计入（见模块末说明）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from enum import Enum
from zoneinfo import ZoneInfo

UTC = ZoneInfo("UTC")

# 中心 -> IANA 时区。中国大陆不实行夏令时；此处仍统一走 zoneinfo，
# 海外中心（演示 DST 判定）可直接配 America/New_York 等。
SITE_TIMEZONES: dict[str, str] = {
    "BJ": "Asia/Shanghai",
    "SH": "Asia/Shanghai",
    "GZ": "Asia/Shanghai",
}
DEFAULT_TIMEZONE = "Asia/Shanghai"


# ---------------------------------------------------------------------------
# 时区：UTC 存、中心时区展示、DST 安全的「同一天」判定
# ---------------------------------------------------------------------------
# 存储约定：UTC 日历日取当天 12:00 UTC 作为规范时刻再转本地。
# 选择正午是因为：12:00 UTC 在全球所有常住时区（UTC-12 ~ UTC+14）都落在
# 当地 00:00–23:59 之间，夏令时 ±1 小时调整也不会越过午夜，从而
# 「UTC 存的是哪一天」与「中心本地看到哪一天」的映射稳定、无歧义。
_ANCHOR_CLOCK = time(12, 0)


def get_zone(tz_name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(tz_name or DEFAULT_TIMEZONE)
    except Exception:
        return ZoneInfo(DEFAULT_TIMEZONE)


def utc_date_to_local(utc_day: date, tz_name: str | None) -> date:
    """UTC 日历日 -> 研究中心本地日历日（DST 安全）。"""
    instant = datetime.combine(utc_day, _ANCHOR_CLOCK, tzinfo=UTC)
    return instant.astimezone(get_zone(tz_name)).date()


def utc_datetime_to_local_dt(utc_dt: datetime, tz_name: str | None) -> datetime:
    """感知/朴素 UTC 时刻 -> 中心本地时刻（朴素值按 UTC 处理）。"""
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=UTC)
    return utc_dt.astimezone(get_zone(tz_name))


def site_local_today(tz_name: str | None, now_utc: datetime | None = None) -> date:
    """中心本地今天。now_utc 可注入（测试/批量任务一致性）。"""
    now_utc = now_utc or datetime.now(tz=UTC)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=UTC)
    return now_utc.astimezone(get_zone(tz_name)).date()


def same_local_day(utc_day_a: date, utc_day_b: date, tz_name: str | None) -> bool:
    """两个 UTC 日历日在中心本地是否同一天（跨时区/DST 判定入口）。"""
    return utc_date_to_local(utc_day_a, tz_name) == utc_date_to_local(utc_day_b, tz_name)


# ---------------------------------------------------------------------------
# 枚举
# ---------------------------------------------------------------------------
class AnchorMode(str, Enum):
    RANDOMIZATION = "randomization"      # 相对随机化日
    PREVIOUS_ACTUAL = "previous_actual"  # 相对上一次实际访视日


class AnchorPolicy(str, Enum):
    """双锚点口径冲突时谁为准（研究级配置，必须在界面明示，不让研究者猜）。"""

    ACTUAL_FIRST = "actual_first"        # 有实际日 -> 实际日；否则方案链
    PROTOCOL_FIRST = "protocol_first"    # 一律方案链（随机化推算），实际日仅参考


ANCHOR_POLICY_LABELS = {
    AnchorPolicy.ACTUAL_FIRST: "实际上次访视日期优先（无实际记录时回退随机化方案日）",
    AnchorPolicy.PROTOCOL_FIRST: "随机化方案日优先（实际日期仅作参考，不改变计划）",
}

DEFAULT_ANCHOR_POLICY = AnchorPolicy.ACTUAL_FIRST


class VisitKind(str, Enum):
    PROTOCOL = "protocol"        # 方案内访视
    UNSCHEDULED = "unscheduled"  # 计划外访视


class VisitStatus(str, Enum):
    SCHEDULED = "scheduled"
    DONE = "done"
    SKIPPED = "skipped"


class FormStatus(str, Enum):
    PENDING = "pending"      # 未开始
    INCOMPLETE = "incomplete"  # 有已提交字段但表单未完成（半张表）
    COMPLETE = "complete"    # 关键表单已完成并提交


# ---------------------------------------------------------------------------
# 计划结构（纯数据，落库模型与计算之间的中立表示）
# ---------------------------------------------------------------------------
@dataclass
class TplForm:
    form_key: str
    name: str
    is_key: bool = True
    total_fields: int = 0


@dataclass
class TplVisit:
    visit_no: str
    name: str
    order_index: int
    offset_days: int                 # randomization: 距随机化日；previous_actual: 名义访视间隔
    anchor_mode: AnchorMode
    window_before: int = 3
    window_after: int = 3
    forms: list[TplForm] = field(default_factory=list)


@dataclass
class InstForm:
    form_key: str
    name: str
    is_key: bool = True
    status: FormStatus = FormStatus.PENDING
    total_fields: int = 0
    filled_fields: int = 0


@dataclass
class InstVisit:
    visit_no: str
    name: str
    order_index: int
    offset_days: int
    anchor_mode: AnchorMode
    kind: VisitKind = VisitKind.PROTOCOL
    status: VisitStatus = VisitStatus.SCHEDULED
    planned_utc: date | None = None
    actual_utc: date | None = None
    window_before: int = 3
    window_after: int = 3
    locked: bool = False
    pinned: bool = False          # 手动改期后钉住计划日，链式重算不再覆盖其本身
    version: str = ""
    inst_id: int | None = None
    tpl_visit_no: str | None = None  # 计划外访视为 None
    forms: list[InstForm] = field(default_factory=list)


@dataclass
class AnchorResolution:
    """一次计划推算的依据，供界面明示口径，杜绝研究者猜测。"""

    base_utc: date
    base_label: str
    planned_utc: date
    # 两种口径给出不同结果时非空
    conflict: bool = False
    winner: str = ""                 # actual / protocol
    alternative_utc: date | None = None
    alternative_label: str = ""


@dataclass
class PlanChange:
    inst_id: int | None
    visit_no: str
    old_planned_utc: date | None
    new_planned_utc: date
    reason: str = ""


class ScheduleCycleError(Exception):
    """锚点依赖出现环形引用。结构上锚点只允许指向更早的访视，正常不会发生。"""


class LockedVisitError(Exception):
    """对已锁库访视执行了会改变计划/留痕的操作。message 可直接展示。"""


# ---------------------------------------------------------------------------
# 锚点解析与链式推算
# ---------------------------------------------------------------------------
def _effective_predecessor(ordered: list[InstVisit], idx: int) -> tuple[InstVisit | None, int]:
    """最近的「未跳过」前序访视（protocol / unscheduled 均可）。

    已跳过访视不构成锚点（它没有发生），因此向下继续找更早的访视。
    """
    for j in range(idx - 1, -1, -1):
        p = ordered[j]
        if p.status == VisitStatus.SKIPPED:
            continue
        return p, j
    return None, -1


def _protocol_planned(v: InstVisit, idx: int, ordered: list[InstVisit],
                      rand_utc: date) -> date:
    """严格方案链日期（不被实际日期/手动改期带动）。

    randomization 锚点走随机化日；previous_actual 锚点走最近未跳过前序的
    「方案计划日」递推。计划外访视没有方案日，沿用其人工指定日。
    """
    if v.kind == VisitKind.UNSCHEDULED:
        return v.planned_utc or rand_utc
    if v.anchor_mode == AnchorMode.RANDOMIZATION or idx == 0:
        return rand_utc + timedelta(days=v.offset_days)
    pred, pidx = _effective_predecessor(ordered, idx)
    if pred is None:
        return rand_utc + timedelta(days=v.offset_days)
    return _protocol_planned(pred, pidx, ordered, rand_utc) + timedelta(days=v.offset_days)


def resolve_anchor(v: InstVisit, idx: int, ordered: list[InstVisit],
                   rand_utc: date, policy: AnchorPolicy = DEFAULT_ANCHOR_POLICY,
                   ) -> AnchorResolution:
    """计划外访视不参与推算；其余按锚点模式与口径策略给出计划日与冲突标记。"""
    if v.kind == VisitKind.UNSCHEDULED:
        return AnchorResolution(
            base_utc=v.planned_utc or rand_utc,
            base_label="计划外访视（日期由研究者指定，不参与方案锚点推算）",
            planned_utc=v.planned_utc or rand_utc,
        )

    protocol_date = _protocol_planned(v, idx, ordered, rand_utc)

    if v.anchor_mode == AnchorMode.RANDOMIZATION:
        return AnchorResolution(
            base_utc=rand_utc,
            base_label="随机化日",
            planned_utc=protocol_date,
        )

    # previous_actual：锚到最近未跳过前序的「实际日（优先）或计划日」
    pred, _ = _effective_predecessor(ordered, idx)
    if pred is None:
        return AnchorResolution(
            base_utc=rand_utc,
            base_label="随机化日（尚无已发生的前序访视，回退方案锚点）",
            planned_utc=protocol_date,
        )

    pred_effective = pred.actual_utc or pred.planned_utc or rand_utc
    actual_date = pred_effective + timedelta(days=v.offset_days)
    # 前序实际/人工日偏离其方案日 => 两种口径给出不同计划日，必须明示
    conflict = actual_date != protocol_date
    if policy == AnchorPolicy.PROTOCOL_FIRST:
        winner_date, winner = protocol_date, "protocol"
        alt_date, alt_label = actual_date, "按上一次实际访视日推算的备选日期"
        base_label = f"方案链：{pred.visit_no} {pred.name} 的方案计划日"
    else:
        winner_date, winner = actual_date, "actual"
        alt_date, alt_label = protocol_date, "按随机化方案链推算的备选日期"
        if pred.actual_utc is not None:
            base_label = f"上一次实际访视日（{pred.visit_no} {pred.name}）"
        else:
            base_label = f"上一次访视计划日（{pred.visit_no} {pred.name}，尚未发生）"

    return AnchorResolution(
        base_utc=pred_effective,
        base_label=base_label,
        planned_utc=winner_date,
        conflict=conflict,
        winner=winner,
        alternative_utc=alt_date if conflict else None,
        alternative_label=alt_label if conflict else "",
    )


def _assert_acyclic(ordered: list[InstVisit]) -> None:
    """防御性环检测：为每个访视构建锚点边并 DFS。

    正常结构上 previous_actual 只引用 order 更小的访视（天然无环）；
    插入/重排异常数据时在此硬失败，绝不带着环去重算。
    """
    by_no = {v.visit_no: v for v in ordered}
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {v.visit_no: WHITE for v in ordered}

    def edge_target(v: InstVisit, idx: int) -> str | None:
        if v.kind == VisitKind.UNSCHEDULED or v.anchor_mode == AnchorMode.RANDOMIZATION:
            return None
        pred, _ = _effective_predecessor(ordered, idx)
        if pred and pred.visit_no in by_no:
            return pred.visit_no
        return None

    def dfs(no: str) -> None:
        color[no] = GRAY
        idx = next(i for i, x in enumerate(ordered) if x.visit_no == no)
        target = edge_target(by_no[no], idx)
        if target is not None:
            if color[target] == GRAY:
                raise ScheduleCycleError(f"访视锚点存在环形依赖：{no} <-> {target}")
            if color[target] == WHITE:
                dfs(target)
        color[no] = BLACK

    for v in ordered:
        if color[v.visit_no] == WHITE:
            dfs(v.visit_no)


def recompute_chain(
    visits: list[InstVisit],
    rand_utc: date,
    policy: AnchorPolicy = DEFAULT_ANCHOR_POLICY,
    *,
    skip_locked: bool = True,
) -> list[PlanChange]:
    """按顺序重算所有「未完成、未跳过、未锁库」的方案内访视计划日。

    - done / skipped / 计划外 / 锁库 访视的计划日一律不动（计划外由人指定，
      锁库合规冻结，已完成/已跳过是历史事实）；
    - 已完成访视继续作为后续 previous_actual 锚点；
    - 返回发生变化的 PlanChange 列表，供写留痕。
    """
    ordered = sorted(visits, key=lambda x: (x.order_index, x.visit_no))
    _assert_acyclic(ordered)

    changes: list[PlanChange] = []
    for idx, v in enumerate(ordered):
        if (
            v.kind == VisitKind.UNSCHEDULED
            or v.status in (VisitStatus.DONE, VisitStatus.SKIPPED)
            or v.pinned
            or (v.locked and skip_locked)
        ):
            continue
        anchor = resolve_anchor(v, idx, ordered, rand_utc, policy)
        if v.planned_utc != anchor.planned_utc:
            changes.append(
                PlanChange(
                    inst_id=v.inst_id,
                    visit_no=v.visit_no,
                    old_planned_utc=v.planned_utc,
                    new_planned_utc=anchor.planned_utc,
                    reason="链式重算",
                )
            )
            v.planned_utc = anchor.planned_utc
    return changes


def assert_mutable(v: InstVisit, action: str) -> None:
    if v.locked:
        raise LockedVisitError(
            f"访视 {v.visit_no}（{v.name}）已锁库，不能{action}。"
            "锁库后的访视计划、实际日期与表单数据按合规要求冻结；"
            "如确需变更，请先走数据更正/解锁审批流程并留痕。"
        )


def skip_visit(
    visits: list[InstVisit], target_no: str, rand_utc: date,
    policy: AnchorPolicy = DEFAULT_ANCHOR_POLICY,
) -> list[PlanChange]:
    """跳过访视：标记 skipped（历史事实，不删除），随后链式重算下游。"""
    v = next(x for x in visits if x.visit_no == target_no)
    assert_mutable(v, "跳过")
    v.status = VisitStatus.SKIPPED
    return recompute_chain(visits, rand_utc, policy)


def restore_visit(
    visits: list[InstVisit], target_no: str, rand_utc: date,
    policy: AnchorPolicy = DEFAULT_ANCHOR_POLICY,
) -> list[PlanChange]:
    """恢复已跳过访视为待随访，并重算下游。"""
    v = next(x for x in visits if x.visit_no == target_no)
    assert_mutable(v, "恢复")
    v.status = VisitStatus.SCHEDULED
    return recompute_chain(visits, rand_utc, policy)


def reschedule_visit(
    visits: list[InstVisit], target_no: str, new_planned_utc: date,
    rand_utc: date, policy: AnchorPolicy = DEFAULT_ANCHOR_POLICY,
    *,
    reason: str = "",
) -> list[PlanChange]:
    """手动改期：只允许作用于未完成、未锁库访视；其本人工指定日期并钉住
    （pinned，后续自动链式重算不再覆盖本人工决定），下游按锚点规则重算。"""
    v = next(x for x in visits if x.visit_no == target_no)
    assert_mutable(v, "改期")
    if v.status == VisitStatus.DONE:
        raise LockedVisitError(f"访视 {v.visit_no} 已完成，不能直接拖拽改期，请走数据更正流程。")
    if v.status == VisitStatus.SKIPPED:
        raise ValueError(f"访视 {v.visit_no} 已跳过，不能改期；请先恢复后再调整日期。")
    changes: list[PlanChange] = []
    if v.planned_utc != new_planned_utc:
        changes.append(
            PlanChange(v.inst_id, v.visit_no, v.planned_utc, new_planned_utc,
                       reason or "手动改期")
        )
        v.planned_utc = new_planned_utc
    v.pinned = True
    changes.extend(recompute_chain(visits, rand_utc, policy))
    return changes


def mark_done(
    visits: list[InstVisit], target_no: str, actual_utc: date,
    rand_utc: date, policy: AnchorPolicy = DEFAULT_ANCHOR_POLICY,
) -> list[PlanChange]:
    """回填实际访视日并链式重算下游（previous_actual 口径由此生效）。"""
    v = next(x for x in visits if x.visit_no == target_no)
    assert_mutable(v, "回填实际日期")
    v.status = VisitStatus.DONE
    v.actual_utc = actual_utc
    return recompute_chain(visits, rand_utc, policy)


def insert_unscheduled(
    visits: list[InstVisit], visit_no: str, name: str, planned_utc: date,
    window_before: int = 3, window_after: int = 3, version: str = "",
    *, after_order: int | None = None,
) -> InstVisit:
    """插入计划外访视并重排 order_index（按计划日插入合适位置，步进 10 留余量）。

    计划外访视日期由研究者指定，不产生方案锚点；它一旦被标记完成，
    可成为后续 previous_actual 访视的锚点。
    """
    inst = InstVisit(
        visit_no=visit_no,
        name=name,
        order_index=(after_order if after_order is not None else 0) + 5,
        offset_days=0,
        anchor_mode=AnchorMode.PREVIOUS_ACTUAL,
        kind=VisitKind.UNSCHEDULED,
        planned_utc=planned_utc,
        window_before=window_before,
        window_after=window_after,
        version=version,
    )
    visits.append(inst)
    ordered = sorted(visits, key=lambda x: (x.planned_utc or date.min, x.order_index))
    for i, v in enumerate(ordered, start=1):
        v.order_index = i * 10
    return inst


# ---------------------------------------------------------------------------
# 方案修订冻结
# ---------------------------------------------------------------------------
@dataclass
class RevisionResult:
    kept: list[InstVisit]            # 冻结在旧版的访视
    upgraded: list[InstVisit]        # 切换到新版的访视
    dropped: list[InstVisit]         # 新版删除且尚未发生的旧版访视
    mixed_versions: bool             # 同一受试者新旧并存


def is_frozen(v: InstVisit, effective_utc: date) -> bool:
    """已完成 / 已跳过 / 已锁库，或计划日早于修订生效日的，冻结旧版原样不动。"""
    if v.status in (VisitStatus.DONE, VisitStatus.SKIPPED) or v.locked:
        return True
    if v.planned_utc is not None and v.planned_utc < effective_utc:
        return True
    return False


def apply_revision(
    visits: list[InstVisit],
    new_template: list[TplVisit],
    new_version: str,
    effective_utc: date,
    rand_utc: date,
    policy: AnchorPolicy = DEFAULT_ANCHOR_POLICY,
) -> RevisionResult:
    """修订发布后对单个受试者的访视实例做切版。

    - 冻结集（旧版）原样保留；
    - 尚未发生的方案访视：按 visit_no 与新版模板对齐，存在则升级版本并按新模板
      参数（偏移/窗口/锚点/表单）重算，不存在则丢弃（写留痕）；
    - 新版新增的访视 visit_no 实例化；
    - 计划外访视始终保留（不属于方案版本内容）。
    """
    kept = [v for v in visits if v.kind == VisitKind.UNSCHEDULED or is_frozen(v, effective_utc)]
    kept_ids = {id(v) for v in kept}
    old_pending = [
        v for v in visits
        if v.kind == VisitKind.PROTOCOL and not is_frozen(v, effective_utc)
    ]
    dropped: list[InstVisit] = []
    upgraded: list[InstVisit] = []

    old_by_no = {v.visit_no: v for v in old_pending}
    new_nos = {t.visit_no for t in new_template}
    # 已冻结（旧版保留）的方案访视号：新模板里即使仍包含，也原样保留、绝不重建
    kept_protocol_nos = {
        v.visit_no for v in kept if v.kind == VisitKind.PROTOCOL
    }

    for no, v in old_by_no.items():
        if no not in new_nos:
            dropped.append(v)

    for tpl in new_template:
        if tpl.visit_no in old_by_no:
            v = old_by_no[tpl.visit_no]
            v.name = tpl.name
            v.order_index = tpl.order_index
            v.offset_days = tpl.offset_days
            v.anchor_mode = tpl.anchor_mode
            v.window_before = tpl.window_before
            v.window_after = tpl.window_after
            v.version = new_version
            # 新版本模板优先：解除旧版手动改期的钉住，按新偏移重算
            v.pinned = False
            upgraded.append(v)
        elif tpl.visit_no in kept_protocol_nos:
            # 该访视已冻结在旧版（完成/跳过/锁库/早于生效日），保持原样不重建
            continue
        else:
            upgraded.append(
                InstVisit(
                    visit_no=tpl.visit_no,
                    name=tpl.name,
                    order_index=tpl.order_index,
                    offset_days=tpl.offset_days,
                    anchor_mode=tpl.anchor_mode,
                    window_before=tpl.window_before,
                    window_after=tpl.window_after,
                    version=new_version,
                    planned_utc=rand_utc + timedelta(days=tpl.offset_days),
                )
            )

    # 原地改写输入集合：冻结旧版（含计划外）+ 升级/新增新版
    visits.clear()
    visits.extend(kept + upgraded)
    recompute_chain(visits, rand_utc, policy)

    old_versions = {v.version for v in kept if v.kind == VisitKind.PROTOCOL}
    mixed = bool(old_versions) and bool(upgraded)
    return RevisionResult(kept=kept, upgraded=upgraded, dropped=dropped, mixed_versions=mixed)


def subject_mixed_versions(visits: list[InstVisit]) -> bool:
    versions = {v.version for v in visits if v.kind == VisitKind.PROTOCOL and v.version}
    return len(versions) > 1


# ---------------------------------------------------------------------------
# 完成度（关键表单口径）— 三处一致的唯一入口
# ---------------------------------------------------------------------------
@dataclass
class Completion:
    key_form_done: int
    key_form_total: int
    percent: float                     # 四舍五入到 1 位小数
    skipped_visits: int = 0

    @property
    def label(self) -> str:
        return f"{self.key_form_done}/{self.key_form_total}"


def compute_completion(visits: list[InstVisit]) -> Completion:
    """完成度 = 已完成关键表单数 / 关键表单总数。

    口径决策（界面同步明示）：采用「已完成关键表单数」，不采用「已提交字段数」。
    - 只填了部分字段、未完成提交的关键表单（FormStatus.INCOMPLETE）计 0；
    - 已跳过访视不进入分母（该访视依法未执行），单独计数提示；
    - 计划外访视如挂有关键表单同样计入；
    - 因此「只填了半张表的访视」在字段口径下约 50%，在本口径下为 0%，
      两种口径结论相反；本平台三处（总览/详情/导出）统一使用本函数结果。
    """
    done = total = 0
    skipped = 0
    for v in visits:
        if v.status == VisitStatus.SKIPPED:
            skipped += 1
            continue
        for f in v.forms:
            if not f.is_key:
                continue
            total += 1
            if f.status == FormStatus.COMPLETE:
                done += 1
    percent = round(done * 100 / total, 1) if total else 0.0
    return Completion(done, total, percent, skipped)


def field_based_percent(visits: list[InstVisit]) -> float | None:
    """字段口径参考值（仅用于界面对比演示，不作为任何正式完成度数字）。"""
    filled = total = 0
    for v in visits:
        if v.status == VisitStatus.SKIPPED:
            continue
        for f in v.forms:
            if not f.is_key or f.total_fields <= 0:
                continue
            total += f.total_fields
            filled += min(f.filled_fields, f.total_fields)
    if not total:
        return None
    return round(filled * 100 / total, 1)
