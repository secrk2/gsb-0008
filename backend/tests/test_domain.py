"""核心领域规则单元测试（仅依赖标准库，无需数据库/第三方包）。

运行：cd backend && python3 -m unittest discover -s tests -v
"""
import unittest
from datetime import date, timedelta

from app.domain import (
    Action,
    IllegalTransitionError,
    SubjectStatus,
    VisitState,
    format_screening_no,
    format_subject_code,
    mask_name,
    next_subject_code,
    transition,
    visit_state,
)


class TestStateMachine(unittest.TestCase):
    def test_happy_path_enroll_complete(self):
        s = transition(SubjectStatus.SCREENING, Action.ENROLL)
        self.assertEqual(s, SubjectStatus.ENROLLED)
        s = transition(s, Action.COMPLETE)
        self.assertEqual(s, SubjectStatus.COMPLETED)

    def test_screen_fail(self):
        self.assertEqual(
            transition(SubjectStatus.SCREENING, Action.SCREEN_FAIL, "不符合入排"),
            SubjectStatus.SCREEN_FAILED,
        )

    def test_enrolled_branches(self):
        for action, expect in [
            (Action.DROPOUT, SubjectStatus.DROPPED),
            (Action.TERMINATE, SubjectStatus.TERMINATED),
            (Action.REMOVE, SubjectStatus.REMOVED),
        ]:
            self.assertEqual(
                transition(SubjectStatus.ENROLLED, action, "书面原因"), expect
            )

    def test_terminal_states_block_any_rollback(self):
        for terminal in (
            SubjectStatus.COMPLETED,
            SubjectStatus.DROPPED,
            SubjectStatus.TERMINATED,
            SubjectStatus.SCREEN_FAILED,
            SubjectStatus.REMOVED,
        ):
            with self.assertRaises(IllegalTransitionError) as ctx:
                transition(terminal, Action.ENROLL, "想退回入组")
            # 错误信息必须说明原因（终态 + 拦截），可直接展示给研究者
            self.assertIn("终态", str(ctx.exception))
            self.assertIn("不能", str(ctx.exception))

    def test_screening_cannot_jump_to_terminal(self):
        with self.assertRaises(IllegalTransitionError) as ctx:
            transition(SubjectStatus.SCREENING, Action.COMPLETE)
        self.assertIn("只能", str(ctx.exception))

    def test_enrolled_cannot_enroll_again(self):
        with self.assertRaises(IllegalTransitionError):
            transition(SubjectStatus.ENROLLED, Action.ENROLL)

    def test_reason_required(self):
        for action in (Action.DROPOUT, Action.TERMINATE, Action.REMOVE):
            with self.assertRaises(ValueError):
                transition(SubjectStatus.ENROLLED, action, "  ")
        with self.assertRaises(ValueError):
            transition(SubjectStatus.SCREENING, Action.SCREEN_FAIL, None)


class TestNumbering(unittest.TestCase):
    def test_format(self):
        self.assertEqual(format_screening_no("BJ", 5), "BJ-S005")
        self.assertEqual(format_subject_code("SH", 12), "SH-012")

    def test_voided_number_never_reused(self):
        # 已分配/已作废号段：1,2,3（3作废）。游标到 3，下一个必须是 4，绝不复用 3
        used = {1, 2, 3}
        code, seq = next_subject_code("GZ", used, 3)
        self.assertEqual(code, "GZ-004")
        self.assertEqual(seq, 4)


class TestMasking(unittest.TestCase):
    def test_chinese_name_masked_with_code(self):
        self.assertEqual(mask_name("李雪梅", "BJ-002"), "李**（BJ-002）")
        self.assertEqual(mask_name("王建国", "BJ-001"), "王**（BJ-001）")

    def test_english_name_initials_with_code(self):
        self.assertEqual(mask_name("John Smith", "BJ-009"), "J.S（BJ-009）")

    def test_screening_no_code_hides_name(self):
        self.assertEqual(mask_name("刘思远", None), "未编号-***")


class TestVisitWindow(unittest.TestCase):
    planned = date(2026, 9, 17)

    def state_at(self, offset, status="scheduled", wb=3, wa=3):
        today = self.planned + timedelta(days=offset)
        return visit_state(self.planned, today, wb, wa, status)

    def test_due_today(self):
        self.assertEqual(self.state_at(0), VisitState.DUE_TODAY)

    def test_in_window_before(self):
        self.assertEqual(self.state_at(-2), VisitState.IN_WINDOW)

    def test_upcoming(self):
        self.assertEqual(self.state_at(-10), VisitState.UPCOMING)

    def test_overdue_within_window(self):
        self.assertEqual(self.state_at(2), VisitState.OVERDUE)

    def test_out_of_window_red(self):
        self.assertEqual(self.state_at(5), VisitState.OUT_OF_WINDOW)

    def test_done(self):
        self.assertEqual(self.state_at(9, status="done"), VisitState.DONE)


if __name__ == "__main__":
    unittest.main()
