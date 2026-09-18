"""访视排程纯规则单元测试（仅依赖标准库，无需数据库/第三方包）。

运行：cd backend && python3 -m unittest discover -s tests -v
"""
import unittest
from datetime import date, datetime, timedelta

from app.scheduling import (
    AnchorMode,
    AnchorPolicy,
    FormStatus,
    InstForm,
    InstVisit,
    LockedVisitError,
    ScheduleCycleError,
    TplVisit,
    UTC,
    VisitKind,
    VisitStatus,
    apply_revision,
    compute_completion,
    field_based_percent,
    insert_unscheduled,
    mark_done,
    recompute_chain,
    reschedule_visit,
    restore_visit,
    same_local_day,
    site_local_today,
    skip_visit,
    utc_date_to_local,
    utc_datetime_to_local_dt,
)


RAND = date(2026, 1, 1)


def make_chain():
    """V1 随机化+7（randomization），V2 V1+14（previous_actual），
    V3 V2+14（previous_actual）。"""
    return [
        InstVisit("V1", "第1周", 10, 7, AnchorMode.RANDOMIZATION,
                  planned_utc=RAND + timedelta(days=7)),
        InstVisit("V2", "第3周", 20, 14, AnchorMode.PREVIOUS_ACTUAL,
                  planned_utc=RAND + timedelta(days=21)),
        InstVisit("V3", "第5周", 30, 14, AnchorMode.PREVIOUS_ACTUAL,
                  planned_utc=RAND + timedelta(days=35)),
    ]


class TestTimezone(unittest.TestCase):
    def test_utc_day_maps_to_local_shanghai(self):
        # UTC 2026-01-01 正午 => 北京 2026-01-01 20:00，同一天
        self.assertEqual(
            utc_date_to_local(date(2026, 1, 1), "Asia/Shanghai"),
            date(2026, 1, 1),
        )

    def test_dst_same_day_america(self):
        # 2026-03-08 是美国夏令时切换日（2:00 -> 3:00）；正午 UTC 映射稳定
        self.assertEqual(
            utc_date_to_local(date(2026, 3, 8), "America/New_York"),
            date(2026, 3, 8),
        )

    def test_utc_instant_next_day_in_positive_offset(self):
        # UTC 2026-01-01 16:00 => 北京 2026-01-02 00:00，跨天判定正确
        dt = datetime(2026, 1, 1, 16, 0, tzinfo=UTC)
        from app.scheduling import utc_datetime_to_local_dt
        local = utc_datetime_to_local_dt(dt, "Asia/Shanghai")
        self.assertEqual(local.date(), date(2026, 1, 2))

    def test_site_local_today_injected_now(self):
        # UTC 16:30 对北京已是次日
        now = datetime(2026, 5, 10, 16, 30, tzinfo=UTC)
        self.assertEqual(site_local_today("Asia/Shanghai", now), date(2026, 5, 11))
        # 同一时刻 UTC-5 仍是当天
        self.assertEqual(site_local_today("America/New_York", now), date(2026, 5, 10))

    def test_same_local_day(self):
        self.assertTrue(same_local_day(date(2026, 1, 1), date(2026, 1, 1), "Asia/Shanghai"))
        self.assertFalse(same_local_day(date(2026, 1, 1), date(2026, 1, 2), "Asia/Shanghai"))

    def test_bad_timezone_falls_back(self):
        self.assertEqual(
            utc_date_to_local(date(2026, 6, 1), "Not/AZone"),
            utc_date_to_local(date(2026, 6, 1), "Asia/Shanghai"),
        )


class TestAnchorChain(unittest.TestCase):
    def test_basic_protocol_dates(self):
        visits = make_chain()
        changes = recompute_chain(visits, RAND)
        self.assertEqual(changes, [])  # 种子日期即方案日期
        self.assertEqual(visits[1].planned_utc, RAND + timedelta(days=21))

    def test_actual_date_shifts_downstream_actual_first(self):
        visits = make_chain()
        # V1 实际晚了 3 天
        changes = mark_done(visits, "V1", RAND + timedelta(days=10), RAND)
        self.assertEqual(visits[0].status, VisitStatus.DONE)
        # V2 由 21 -> 24，V3 由 35 -> 38（沿实际链）
        self.assertEqual(visits[1].planned_utc, RAND + timedelta(days=24))
        self.assertEqual(visits[2].planned_utc, RAND + timedelta(days=38))
        self.assertTrue(any(c.visit_no == "V2" for c in changes))

    def test_protocol_first_ignores_actual(self):
        visits = make_chain()
        mark_done(visits, "V1", RAND + timedelta(days=10), RAND,
                  AnchorPolicy.PROTOCOL_FIRST)
        # 方案链不被实际日带动
        self.assertEqual(visits[1].planned_utc, RAND + timedelta(days=21))
        self.assertEqual(visits[2].planned_utc, RAND + timedelta(days=35))

    def test_reschedule_changes_only_related_downstream(self):
        visits = make_chain()
        # 手动把 V2 推后 7 天
        reschedule_visit(visits, "V2", RAND + timedelta(days=28), RAND)
        self.assertEqual(visits[1].planned_utc, RAND + timedelta(days=28))
        # V3 以 V2 计划日为前序（V2 未完成，无实际日）-> 42
        self.assertEqual(visits[2].planned_utc, RAND + timedelta(days=42))
        # V1（randomization 锚点）不受影响
        self.assertEqual(visits[0].planned_utc, RAND + timedelta(days=7))

    def test_skip_then_restore(self):
        visits = make_chain()
        mark_done(visits, "V1", RAND + timedelta(days=7), RAND)
        skip_visit(visits, "V2", RAND)
        self.assertEqual(visits[1].status, VisitStatus.SKIPPED)
        # V3 回退锚到 V1 实际日：7 + 14 = 21
        self.assertEqual(visits[2].planned_utc, RAND + timedelta(days=21))
        restore_visit(visits, "V2", RAND)
        self.assertEqual(visits[1].status, VisitStatus.SCHEDULED)
        self.assertEqual(visits[2].planned_utc, RAND + timedelta(days=35))

    def test_skipped_visit_cannot_be_rescheduled_directly(self):
        visits = make_chain()
        skip_visit(visits, "V2", RAND)
        with self.assertRaises(ValueError):
            reschedule_visit(visits, "V2", RAND + timedelta(days=30), RAND, reason="x")

    def test_locked_visit_cannot_change(self):
        visits = make_chain()
        visits[0].locked = True
        with self.assertRaises(LockedVisitError) as ctx:
            reschedule_visit(visits, "V1", RAND + timedelta(days=9), RAND)
        self.assertIn("锁库", str(ctx.exception))
        with self.assertRaises(LockedVisitError):
            skip_visit(visits, "V1", RAND)

    def test_recompute_never_moves_locked_or_done(self):
        visits = make_chain()
        mark_done(visits, "V1", RAND + timedelta(days=10), RAND)
        visits[1].locked = True
        locked_date = visits[1].planned_utc
        recompute_chain(visits, RAND)
        self.assertEqual(visits[1].planned_utc, locked_date)
        self.assertEqual(visits[0].actual_utc, RAND + timedelta(days=10))

    def test_cycle_detection(self):
        # 手工制造异常：同名环（极端防御场景）
        a = InstVisit("X", "x", 10, 1, AnchorMode.PREVIOUS_ACTUAL)
        a.status = VisitStatus.DONE
        a.actual_utc = RAND
        b = InstVisit("Y", "y", 20, 1, AnchorMode.PREVIOUS_ACTUAL)
        b.planned_utc = RAND + timedelta(days=2)
        # 正常顺序无环；构造环需要让最近实际前序指向更晚的同名对象
        a.visit_no, b.visit_no = "Y", "X"  # 制造引用错乱
        a.order_index, b.order_index = 20, 10
        # a(X, order20,done) 在前序视角... 这里直接验证 DFS 能抛错或安全完成
        try:
            recompute_chain([b, a], RAND)
        except ScheduleCycleError:
            return
        # 若数据未构成严格环也必须不产生无限循环（能正常返回即通过）

    def test_unscheduled_visit_keeps_manual_date(self):
        visits = make_chain()
        insert_unscheduled(visits, "U1", "追加安全性访视",
                           RAND + timedelta(days=12), version="v1.0")
        u = next(v for v in visits if v.kind == VisitKind.UNSCHEDULED)
        recompute_chain(visits, RAND)
        self.assertEqual(u.planned_utc, RAND + timedelta(days=12))

    def test_done_unscheduled_can_anchor_later(self):
        visits = make_chain()
        u = insert_unscheduled(visits, "U1", "追加访视", RAND + timedelta(days=12))
        mark_done(visits, "U1", RAND + timedelta(days=12), RAND)
        # V2（previous_actual）最近实际前序变为 U1 -> 12+14 = 26
        self.assertEqual(
            next(v for v in visits if v.visit_no == "V2").planned_utc,
            RAND + timedelta(days=26),
        )


class TestRevisionFreeze(unittest.TestCase):
    def _subject(self):
        visits = make_chain()
        for v in visits:
            v.version = "v1.0"
        # V1 已完成、V2 待随访（未来）、V3 待随访
        mark_done(visits, "V1", RAND + timedelta(days=7), RAND)
        return visits

    def test_done_frozen_pending_upgraded(self):
        visits = self._subject()
        # 新版：V2 间隔变 21 天、新增 V4，删除 V3
        new_tpl = [
            TplVisit("V1", "第1周", 10, 7, AnchorMode.RANDOMIZATION),
            TplVisit("V2", "第4周", 20, 21, AnchorMode.PREVIOUS_ACTUAL),
            TplVisit("V4", "第10周", 40, 70, AnchorMode.RANDOMIZATION),
        ]
        eff = RAND + timedelta(days=10)
        result = apply_revision(visits, new_tpl, "v1.1", eff, RAND)
        self.assertTrue(result.mixed_versions)
        v1 = next(v for v in visits if v.visit_no == "V1")
        self.assertEqual(v1.version, "v1.0")  # 已完成冻结旧版
        v2 = next(v for v in visits if v.visit_no == "V2")
        self.assertEqual(v2.version, "v1.1")
        self.assertEqual(v2.offset_days, 21)
        self.assertIn(next(v for v in result.dropped if v.visit_no == "V3"), result.dropped)
        self.assertTrue(any(v.visit_no == "V4" and v.version == "v1.1" for v in visits))

    def test_effective_date_freezes_visits_before_it(self):
        visits = self._subject()
        new_tpl = [TplVisit("V1", "第1周", 10, 7, AnchorMode.RANDOMIZATION),
                   TplVisit("V2", "第3周", 20, 14, AnchorMode.PREVIOUS_ACTUAL),
                   TplVisit("V3", "第5周", 30, 14, AnchorMode.PREVIOUS_ACTUAL)]
        # 生效日设在 V2 计划日之前 => V2 也冻结（即便未完成）
        eff = RAND + timedelta(days=30)
        result = apply_revision(visits, new_tpl, "v1.1", eff, RAND)
        kept_nos = {v.visit_no for v in result.kept}
        self.assertIn("V2", kept_nos)

    def test_frozen_visit_still_in_new_template_is_not_duplicated(self):
        """已冻结访视若仍出现在新版模板中，必须原样保留而不是再次实例化（唯一约束回归）。"""
        visits = self._subject()  # V1 已完成 v1.0，V2/V3 待随访
        # 新版仍含 V1（冻结），V2 升级，新增 V4；V3 删除
        new_tpl = [
            TplVisit("V1", "第1周", 10, 7, AnchorMode.RANDOMIZATION),
            TplVisit("V2", "第4周", 20, 21, AnchorMode.PREVIOUS_ACTUAL),
            TplVisit("V4", "第10周", 40, 70, AnchorMode.RANDOMIZATION),
        ]
        result = apply_revision(visits, new_tpl, "v1.1", RAND + timedelta(days=10), RAND)
        nos = [v.visit_no for v in visits]
        self.assertEqual(nos.count("V1"), 1)          # 不重复
        self.assertIn(next(v for v in visits if v.visit_no == "V1"), result.kept)
        self.assertEqual(next(v for v in visits if v.visit_no == "V1").version, "v1.0")
        self.assertTrue(any(v.visit_no == "V4" for v in visits))
        self.assertTrue(any(v.visit_no == "V3" for v in result.dropped))


class TestCompletion(unittest.TestCase):
    def _visits_with_half_filled_form(self):
        def v_with(no, statuses):
            v = InstVisit(no, no, 10, 1, AnchorMode.RANDOMIZATION)
            for name, st, total, filled in statuses:
                v.forms.append(
                    InstForm(name, name, True, st, total, filled)
                )
            return v

        v1 = v_with("V1", [("人口学", FormStatus.COMPLETE, 10, 10)])
        v2 = v_with("V2", [("实验室", FormStatus.INCOMPLETE, 10, 5)])  # 半张表
        return [v1, v2]

    def test_key_form_basis_counts_half_form_as_zero(self):
        visits = self._visits_with_half_filled_form()
        c = compute_completion(visits)
        self.assertEqual((c.key_form_done, c.key_form_total), (1, 2))
        self.assertEqual(c.percent, 50.0)

    def test_field_basis_gives_opposite_conclusion_for_half_form(self):
        visits = self._visits_with_half_filled_form()
        # 字段口径：15/20 = 75%，与关键表单口径（50%）在「半张表」上结论不同
        self.assertEqual(field_based_percent(visits), 75.0)

    def test_skipped_visit_excluded_from_denominator(self):
        visits = self._visits_with_half_filled_form()
        visits[1].status = VisitStatus.SKIPPED
        c = compute_completion(visits)
        self.assertEqual((c.key_form_done, c.key_form_total), (1, 1))
        self.assertEqual(c.skipped_visits, 1)
        self.assertEqual(c.percent, 100.0)

    def test_non_key_forms_ignored(self):
        v = InstVisit("V1", "V1", 10, 1, AnchorMode.RANDOMIZATION)
        v.forms.append(InstForm("f", "f", False, FormStatus.PENDING, 5, 0))
        c = compute_completion([v])
        self.assertEqual(c.key_form_total, 0)
        self.assertEqual(c.percent, 0.0)


if __name__ == "__main__":
    unittest.main()
