"""端到端测试：按时间线处理 data/ 下的全部资料。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from exchange.pipeline import run_pipeline

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


class PipelineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = run_pipeline(DATA_DIR)

    def test_announcement_respects_confidentiality(self):
        """公开公告不含被拒绝公开的商品代号，敏感组合不凑齐。"""
        self.assertIn("云码头", self.result.announcement)
        self.assertNotIn("灯雀", self.result.announcement)

    def test_registration_keeps_only_codename_and_session(self):
        """报名表只存项目代号和场次。"""
        for row in self.result.registrations.rows():
            self.assertEqual(set(row), {"codename", "session"})
        self.assertEqual(self.result.registrations.sessions_of("橙子"), ["early"])

    def test_two_proposals_generated(self):
        kinds = {p.id: p.kind for p in self.result.proposals}
        self.assertEqual(sorted(kinds.values()), ["mutual", "one_way"])

    def test_dependent_commitment_locked_then_invalidated(self):
        """依赖定位图的承诺先锁定，资料撤回后失效并改约。"""
        states = {c.id: c.state for c in self.result.commitments.all().values()}
        self.assertEqual(states["C1"], "superseded")   # 原约失效后改约
        self.assertEqual(states["C3"], "locked")       # 新约重新确认后锁定

    def test_mutual_commitment_never_locked_without_lock_consent(self):
        """云梢要求先别锁时段：互助提议始终不锁，也不耗时段。"""
        commitments = self.result.commitments.all()
        c2 = commitments["C2"]
        self.assertEqual(c2.state, "confirming")
        self.assertFalse(all(c2.lock_ok.values()))
        # 墨舟的时段没有被这份未锁定提议真正占用（锁定才占用）。
        self.assertEqual(self.result.scheduler.locked_count("墨舟"), 0)

    def test_capacity_accounting(self):
        """望北唯一时段最终由改约后的新约占用。"""
        self.assertEqual(self.result.scheduler.capacity_left("望北"), 0)

    def test_reported_lead_listed_for_contact(self):
        self.assertTrue(any("云梢的朋友" in lead for lead in self.result.leads))

    def test_explanations_split_internal_and_public(self):
        inquiry = self.result.explanations["inquiry"]
        self.assertIn("云码头", inquiry.internal)
        self.assertNotIn("灯雀", inquiry.public)
        material = self.result.explanations["material_墨舟"]
        self.assertIn("排除", material.internal)
        self.assertNotIn("墨舟", material.public)

    def test_events_narrate_each_stage(self):
        text = "\n".join(self.result.events)
        for keyword in ("解析 N1", "报名", "分别申请确认", "锁定时段",
                        "撤回资料", "改约", "重新确认"):
            self.assertIn(keyword, text)


if __name__ == "__main__":
    unittest.main()
