"""访视计划领域规则单测：链式重算 / 锁库 / 环检测 / 完成度口径 / 修订冻结 / 时区。

运行：cd backend && python3 -m unittest discover -s tests -v
"""
import unittest
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app import tz
from app.domain import (
    AMENDMENT_FREEZE_TEXT,
    ANCHOR_POLICY_TEXT,
    COMPLETION_BASIS,
    COMPLETION_POLICY_TEXT,
    FORM_COMPLETE,
    FORM_IN_PROGRESS,
    FORM_PENDING,
    FormProgress,
    ScheduleError,
    VISIT_DONE,
    VISIT_LOCKED,
    VISIT_SCHEDULED,
    VISIT_SKIPPED,
    VISIT_UNSCHEDULED,
    VisitNode,
    compute_subject_completion,
    compute_visit_completion,
    effective_version,
    in_window,
    insert_unscheduled,
    reschedule_chain,
    skip_visit,
    split_visits_by_amendment,
)


def chain(days, start=date(2026, 9, 1), statuses=None, locked=()):
    """造一条方案访视链：day 为相对随机化日天数，计划日 = start+day。"""
    statuses = statuses or {}
    nodes = []
    for i, day in enumerate(days):
        vid = i + 1
        nodes.append(
            VisitNode(
                id=vid, seq=i, day=day, planned_date=start + timedelta(days=day),
                status=statuses.get(vid, VISIT_SCHEDULED),
                actual_date=(start + timedelta(days=day))
                if statuses.get(vid) == VISIT_DONE else None,
                locked=vid in locked,
            )
        )
    return nodes


class TestRescheduleChain(unittest.TestCase):
    def test_drag_one_keeps_protocol_intervals(self):
        # V0=0, V1=14, V2=28。把 V1 从 9/15 拖到 9/20（+5），V2 必须同步 +5
        nodes = chain([0, 14, 28], start=date(2026, 9, 1))
        changes = reschedule_chain(nodes, 2, date(2026, 9, 20))
        self.assertEqual(nodes[0].planned_date, date(2026, 9, 1))   # 前置不动
        self.assertEqual(nodes[1].planned_date, date(2026, 9, 20))
        self.assertEqual(nodes[2].planned_date, date(2026, 10, 4))  # 28+5 → 10/4
        self.assertEqual(changes[3], date(2026, 10, 4))
        # 名义日不被改写
        self.assertEqual(nodes[2].nominal_date, date(2026, 9, 29))

    def test_done_visit_is_new_anchor_and_not_moved(self):
        nodes = chain([0, 14, 28], start=date(2026, 9, 1),
                      statuses={2: VISIT_DONE})
        # V1 已实际于 9/16 完成；把 V0 拖后不应改动 V1，V2 以实际日 9/16 为锚
        changes = reschedule_chain(nodes, 1, date(2026, 9, 5))
        self.assertEqual(nodes[1].planned_date, date(2026, 9, 15))  # 已完成不动
        self.assertEqual(nodes[1].actual_date, date(2026, 9, 15))
        self.assertEqual(nodes[2].planned_date, date(2026, 9, 29))  # 9/16 + 14

    def test_locked_visit_is_fixed_anchor_and_never_moved(self):
        # 锁库访视是固定锚点：改前面的访视不会改动它，其后的访视以它为锚重算
        nodes = chain([0, 14, 28], start=date(2026, 9, 1), locked=(3,))
        changes = reschedule_chain(nodes, 1, date(2026, 9, 10))
        self.assertEqual(nodes[2].planned_date, date(2026, 9, 29))  # 锁库原样
        # V2 scheduled：9/10 锚 + (28-14) = 9/24
        self.assertEqual(nodes[1].planned_date, date(2026, 9, 24))
        self.assertNotIn(3, changes)

    def test_cannot_drag_locked_visit(self):
        nodes = chain([0, 14], start=date(2026, 9, 1), locked=(2,))
        with self.assertRaises(ScheduleError):
            reschedule_chain(nodes, 2, date(2026, 9, 30))

    def test_cannot_drag_done_or_skipped(self):
        nodes = chain([0, 14, 28], start=date(2026, 9, 1),
                      statuses={1: VISIT_DONE})
        with self.assertRaises(ScheduleError):
            reschedule_chain(nodes, 1, date(2026, 9, 2))

    def test_skip_freezes_and_chain_keeps_rhythm(self):
        nodes = chain([0, 14, 28], start=date(2026, 9, 1))
        changes = skip_visit(nodes, 2)
        self.assertEqual(nodes[1].status, VISIT_SKIPPED)
        self.assertEqual(nodes[1].planned_date, date(2026, 9, 15))  # 跳过不删日
        # V2 仍按原节奏 9/29（跳过点作为锚，相对天数差不变）
        self.assertEqual(nodes[2].planned_date, date(2026, 9, 29))
        self.assertEqual(changes, {})
        # 已跳过不能重复跳过，已完成不能跳过
        with self.assertRaises(ScheduleError):
            skip_visit(nodes, 2)

    def test_skip_locked_rejected(self):
        nodes = chain([0, 14], start=date(2026, 9, 1), locked=(1,))
        with self.assertRaises(ScheduleError):
            skip_visit(nodes, 1)

    def test_insert_unscheduled_shifts_future(self):
        nodes = chain([0, 14, 28], start=date(2026, 9, 1))
        # 9/10 在 V0(9/1) 与 V1(9/15) 之间插入计划外访视（序位自动取中点）
        new_node, changes = insert_unscheduled(nodes, new_id=99,
                                               the_date=date(2026, 9, 10))
        self.assertEqual(new_node.kind, "unscheduled")
        self.assertTrue(0 < new_node.seq < 1)
        # shift = 9 天，后续两个未发生访视顺延 9 天
        self.assertEqual(nodes[1].planned_date, date(2026, 9, 24))
        self.assertEqual(nodes[2].planned_date, date(2026, 10, 8))

    def test_insert_unscheduled_does_not_pull_past(self):
        nodes = chain([0, 14], start=date(2026, 9, 1),
                      statuses={1: VISIT_DONE})
        # 插在已完成的 V1 之后：无可顺延的未发生访视
        _, changes = insert_unscheduled(
            nodes, new_id=99, the_date=date(2026, 9, 20)
        )
        self.assertEqual(changes, {})

    def test_cycle_in_prev_chain_rejected(self):
        a = VisitNode(id=1, seq=0, day=0, planned_date=date(2026, 9, 1), prev_id=2)
        b = VisitNode(id=2, seq=1, day=14, planned_date=date(2026, 9, 15), prev_id=1)
        with self.assertRaises(ScheduleError) as ctx:
            reschedule_chain([a, b], 1, date(2026, 9, 2))
        self.assertIn("环形", str(ctx.exception))


class TestCompletionBasis(unittest.TestCase):
    def test_half_filled_form_counts_zero_not_fifty(self):
        # 访视两张关键表单：一张完成（20/20 字段），一张半张（10/20 字段，in_progress）
        forms = [
            FormProgress(FORM_COMPLETE, submitted_fields=20, total_fields=20),
            FormProgress(FORM_IN_PROGRESS, submitted_fields=10, total_fields=20),
        ]
        vc = compute_visit_completion(1, VISIT_SCHEDULED, forms)
        self.assertEqual(vc.key_total, 2)
        self.assertEqual(vc.key_done, 1)
        self.assertEqual(vc.rate, 50.0)          # 关键表单口径：50%
        self.assertEqual(vc.field_rate, 75.0)    # 字段口径会是 75%（虚高）
        self.assertFalse(vc.is_complete)

    def test_only_half_form_is_zero_visit(self):
        forms = [FormProgress(FORM_IN_PROGRESS, submitted_fields=9, total_fields=18)]
        vc = compute_visit_completion(1, VISIT_SCHEDULED, forms)
        self.assertEqual(vc.rate, 0.0)           # 半张表 → 0 张关键表单
        self.assertEqual(vc.field_rate, 50.0)    # 字段口径会谎称 50%
        self.assertFalse(vc.is_complete)

    def test_all_key_forms_done_is_complete(self):
        forms = [
            FormProgress(FORM_COMPLETE, 12, 12),
            FormProgress(FORM_PENDING, 0, 8),
            FormProgress(FORM_COMPLETE, 5, 5),
        ]
        vc = compute_visit_completion(1, VISIT_DONE, forms)
        self.assertEqual((vc.key_done, vc.key_total), (2, 3))
        self.assertFalse(vc.is_complete)         # 还有一张未完成
        forms[1] = FormProgress(FORM_COMPLETE, 8, 8)
        vc = compute_visit_completion(1, VISIT_DONE, forms)
        self.assertTrue(vc.is_complete)
        self.assertEqual(vc.rate, 100.0)

    def test_formula_forms_excluded_from_denominator(self):
        forms = [
            FormProgress("formula", 0, 0, is_key=True),
            FormProgress(FORM_COMPLETE, 3, 3),
        ]
        vc = compute_visit_completion(1, VISIT_DONE, forms)
        self.assertEqual(vc.key_total, 1)

    def test_subject_aggregate_excludes_skipped(self):
        v1 = compute_visit_completion(1, VISIT_DONE, [FormProgress(FORM_COMPLETE, 4, 4)])
        v2 = compute_visit_completion(2, VISIT_SKIPPED, [FormProgress(FORM_PENDING, 0, 4)])
        agg = compute_subject_completion([v1, v2])
        self.assertEqual(agg["key_total"], 1)   # 跳过访视的表单不进分母
        self.assertEqual(agg["key_done"], 1)
        self.assertEqual(agg["rate"], 100.0)
        self.assertEqual(agg["skipped_visits"], 1)
        self.assertEqual(agg["basis"], COMPLETION_BASIS)

    def test_policy_texts_present(self):
        # 口径与锚点规则必须有成文说明可直接放上界面
        self.assertIn("关键表单", COMPLETION_POLICY_TEXT)
        self.assertIn("半张表", COMPLETION_POLICY_TEXT)
        self.assertIn("随机化", ANCHOR_POLICY_TEXT)
        self.assertIn("冻结", AMENDMENT_FREEZE_TEXT)


class TestAmendmentFreeze(unittest.TestCase):
    EFF = date(2026, 8, 1)

    def test_done_before_effective_frozen_on_old(self):
        self.assertEqual(
            effective_version(date(2026, 7, 20), VISIT_DONE, self.EFF), "old"
        )

    def test_upcoming_switches_to_new(self):
        self.assertEqual(effective_version(None, VISIT_SCHEDULED, self.EFF), "new")

    def test_done_after_effective_is_new(self):
        self.assertEqual(
            effective_version(date(2026, 8, 10), VISIT_DONE, self.EFF), "new"
        )

    def test_mixed_subject_flags_coexistence(self):
        nodes = [
            VisitNode(1, 0, 0, date(2026, 7, 1), VISIT_DONE,
                      actual_date=date(2026, 7, 2)),
            VisitNode(2, 1, 28, date(2026, 9, 10), VISIT_SCHEDULED),
        ]
        old, new = split_visits_by_amendment(nodes, self.EFF)
        self.assertEqual(len(old), 1)
        self.assertEqual(len(new), 1)  # 新旧并存 → 前端必须挂横幅

    def test_window_check_uses_calendar_days(self):
        planned = date(2026, 9, 17)
        self.assertTrue(in_window(planned, planned + timedelta(days=3), 3, 3))
        self.assertFalse(in_window(planned, planned + timedelta(days=4), 3, 3))
        self.assertTrue(in_window(planned, planned - timedelta(days=3), 3, 3))


class TestTimezoneBasis(unittest.TestCase):
    def test_storage_utc_display_site_tz(self):
        # UTC 2026-09-17 17:00 → 北京已是 9/18；纽约还是 9/17
        moment = datetime(2026, 9, 17, 17, 0, tzinfo=timezone.utc)
        self.assertEqual(tz.local_date(moment, "Asia/Shanghai"), date(2026, 9, 18))
        self.assertEqual(tz.local_date(moment, "America/New_York"), date(2026, 9, 17))

    def test_same_local_day_across_timezone(self):
        # 15:00 UTC = 北京 23:00（9/17）；17:00 UTC = 北京次日 01:00（9/18）
        a = datetime(2026, 9, 17, 15, 0, tzinfo=timezone.utc)
        b = datetime(2026, 9, 17, 17, 0, tzinfo=timezone.utc)
        self.assertFalse(tz.same_local_day(a, b, "Asia/Shanghai"))  # 北京跨天
        self.assertTrue(tz.same_local_day(a, b, "UTC"))             # UTC 同一天

    def test_dst_spring_forward_local_calendar_arithmetic_unaffected(self):
        # 美东 2026-03-08 春令时；当地日历日 +1 仍是下一自然日，不出现 23 小时歧义
        d = date(2026, 3, 7)
        self.assertEqual(tz.add_days(d, 1), date(2026, 3, 8))
        self.assertEqual(tz.add_days(d, 2), date(2026, 3, 9))

    def test_dst_day_anchor_is_noon(self):
        # 春令时当天正午的 UTC 锚点在转换回当地后仍是同一日
        iso = tz.date_display_anchor(date(2026, 3, 8), "America/New_York")
        back = datetime.fromisoformat(iso)
        self.assertEqual(tz.local_date(back, "America/New_York"), date(2026, 3, 8))

    def test_invalid_tz_falls_back_to_default(self):
        self.assertEqual(tz.get_zone("Mars/Olympus"), ZoneInfo(tz.DEFAULT_TIMEZONE))
        self.assertEqual(tz.local_today("Asia/Shanghai", now=datetime(
            2026, 9, 17, 17, tzinfo=timezone.utc)), date(2026, 9, 18))

    def test_naive_datetime_treated_as_utc(self):
        naive = datetime(2026, 9, 17, 17, 0)
        self.assertEqual(tz.local_date(naive, "Asia/Shanghai"), date(2026, 9, 18))


if __name__ == "__main__":
    unittest.main()
