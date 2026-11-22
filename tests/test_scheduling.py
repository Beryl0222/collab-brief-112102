"""排班测试：先行场次优先、唯一时段竞争、提议不耗时段、待问视图。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from exchange.matching import HelpEdge, Proposal
from exchange.materials import Material, MaterialRegistry
from exchange.scheduling import Availability, Scheduler, SessionInfo


def make_proposal(pid, session, parties, covers=0, material_refs=(), questions=()):
    return Proposal(
        id=pid, kind="mutual" if len(parties) > 1 else "one_way",
        session=session, parties=tuple(parties),
        edges=[HelpEdge(giver=parties[0], receiver=parties[-1],
                        capability="贴标")],
        material_refs=list(material_refs), covers=covers,
        questions=list(questions))


class SchedulingTest(unittest.TestCase):
    def setUp(self):
        self.sessions = {
            "early": SessionInfo(id="early", priority=1, who=["甲", "乙", "丙"]),
            "late": SessionInfo(id="late", priority=2, who=["甲", "乙", "丙"]),
        }
        self.avail = [Availability(who="乙", times=["early", "late"], max_sessions=1)]
        self.materials = MaterialRegistry()
        self.materials.register(Material(
            id="M1", name="演示材料", owner="第三方",
            audience={"甲", "乙"}, purpose="评审",
            prerequisite_sessions=["early"]))
        self.scheduler = Scheduler(self.sessions, self.avail, self.materials)

    def test_prerequisite_session_first(self):
        """材料指定的先行场次优先排。"""
        late_p = make_proposal("PL", "late", ["甲", "乙"], covers=5)
        early_p = make_proposal("PE", "early", ["甲", "丙"], covers=1,
                                material_refs=["M1"])
        planned, _ = self.scheduler.plan([late_p, early_p])
        self.assertEqual(planned[0].id, "PE")  # 先行场次优先于覆盖数

    def test_coverage_maximization_after_prerequisites(self):
        """先行场次之后，尽量覆盖更多已准备的需求。"""
        small = make_proposal("PS", "late", ["甲", "丙"], covers=1)
        big = make_proposal("PB", "late", ["乙", "丙"], covers=3)
        planned, _ = self.scheduler.plan([small, big])
        self.assertEqual(planned[0].id, "PB")

    def test_unique_slot_competition(self):
        """不同组候选竞争同一成员的唯一时段，只能排下一组。"""
        first = make_proposal("P1", "early", ["甲", "乙"], covers=2)
        second = make_proposal("P2", "late", ["丙", "乙"], covers=1)
        planned, skipped = self.scheduler.plan([first, second])
        self.assertEqual([p.id for p in planned], ["P1"])
        self.assertEqual(skipped[0].id, "P2")
        self.assertIn("竞争", skipped[0].note)

    def test_proposal_does_not_consume_slot_until_locked(self):
        """提议本身不耗时段：排定后容量只是暂定，锁定才真正占用。"""
        proposal = make_proposal("P1", "early", ["甲", "乙"])
        self.scheduler.plan([proposal])
        self.assertEqual(self.scheduler.capacity_left("乙"), 0)  # 暂定占用
        rival = make_proposal("P2", "late", ["丙", "乙"])
        _, skipped = self.scheduler.plan([rival])
        self.assertEqual(skipped[0].id, "P2")
        # 取消 P1（未锁定）后，容量回到候选。
        self.scheduler.release_planned(proposal)
        self.assertEqual(self.scheduler.capacity_left("乙"), 1)
        planned, _ = self.scheduler.replan([rival])
        self.assertEqual([p.id for p in planned], ["P2"])

    def test_pending_questions_and_appliable_views(self):
        """待问与可分别申请确认的提议分开呈现。"""
        unknown = make_proposal("PU", "early", ["甲", "丙"],
                                questions=["丙：时间得等拿到测试档后定"])
        ready = make_proposal("PR", "late", ["甲", "乙"])
        self.scheduler.plan([unknown, ready])
        pending = self.scheduler.pending_questions([unknown, ready])
        self.assertEqual(list(pending), ["PU"])
        appliable = self.scheduler.appliable([unknown, ready])
        self.assertEqual([p.id for p in appliable], ["PR"])

    def test_mutual_proposal_is_atomic(self):
        """互助提议不拆开：任一方容量不够就整组不排。"""
        self.scheduler.consume_planned(make_proposal("P0", "early", ["甲", "乙"]))
        mutual = make_proposal("PM", "late", ["乙", "丙"], covers=4)
        planned, skipped = self.scheduler.plan([mutual])
        self.assertEqual(planned, [])
        self.assertEqual(skipped[0].id, "PM")


if __name__ == "__main__":
    unittest.main()
