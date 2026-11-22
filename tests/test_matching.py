"""匹配测试：单向协助、双方互助、否定排除、转述线索、材料受众。"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from exchange.matching import Matcher
from exchange.materials import Material, MaterialRegistry
from exchange.parsing import MessageParser, ProfileBuilder

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
SESSIONS = {
    "early": {"priority": 1, "who": ["橙子", "望北", "墨舟", "丘柳"]},
    "late": {"priority": 2, "who": ["墨舟", "云梢", "望北"]},
}


def build():
    messages = {row["id"]: row for row in json.loads(
        (DATA_DIR / "messages.json").read_text(encoding="utf-8"))}
    builder = ProfileBuilder(MessageParser(sessions={"early": 1, "late": 2}))
    for msg_id in ("N1", "N2", "N3", "N4", "N5", "N6"):
        builder.add(messages[msg_id]["who"], messages[msg_id]["text"], msg_id=msg_id)
    materials = MaterialRegistry()
    materials.register(Material(
        id="R2", name="定位图", owner="丘柳",
        audience={"橙子", "望北"}, purpose="贴标"))
    for grant in builder.grants:
        materials.apply_grant(grant.material, grant.audience, grant.purpose)
    for denial in builder.denials:
        materials.apply_denial(denial.target, next(iter(denial.parties)))
    return builder.profiles(), materials


class MatchingTest(unittest.TestCase):
    def setUp(self):
        self.profiles, self.materials = build()
        self.matcher = Matcher(self.profiles, self.materials, sessions=SESSIONS)
        self.proposals = self.matcher.generate()

    def test_one_way_proposal_for_labeling(self):
        """单向协助：望北给橙子贴标，排在橙子报名的先行场。"""
        p1 = [p for p in self.proposals if p.kind == "one_way"]
        self.assertEqual(len(p1), 1)
        self.assertEqual(p1[0].parties, ("望北", "橙子"))
        self.assertEqual(p1[0].session, "early")
        self.assertEqual(p1[0].edges[0].capability, "贴标")
        # 橙子附带的样品供给进入提议。
        self.assertTrue(any(o.capability.key == "样品"
                            for o in p1[0].support_offers))

    def test_mutual_proposal_from_exchange_wishes(self):
        """双方互助：墨舟教标定换云梢的视觉设计。"""
        mutual = [p for p in self.proposals if p.kind == "mutual"]
        self.assertEqual(len(mutual), 1)
        edges = {(e.giver, e.receiver, e.capability) for e in mutual[0].edges}
        self.assertIn(("墨舟", "云梢", "温区标定"), edges)
        self.assertIn(("云梢", "墨舟", "视觉设计"), edges)
        self.assertEqual(mutual[0].session, "late")

    def test_negated_capability_is_never_offered(self):
        """墨舟明确说没法贴标，不得成为贴标供给方。"""
        for proposal in self.proposals:
            for edge in proposal.edges:
                self.assertFalse(
                    edge.giver == "墨舟" and edge.capability == "贴标")

    def test_exchange_condition_filters_counterparty(self):
        """云梢只想和会温区标定的人交换：望北明确不做温区，结不成对。"""
        for proposal in self.proposals:
            self.assertFalse(
                set(proposal.parties) == {"云梢", "望北"})

    def test_reported_lead_is_not_matched(self):
        """转述来的“云梢的朋友会冷柜”只是线索，不直接结队。"""
        self.assertTrue(any("云梢的朋友" in lead for lead in self.matcher.leads))
        for proposal in self.proposals:
            self.assertNotIn("云梢的朋友", proposal.parties)

    def test_material_dependency_registered_and_checked(self):
        """橙子的提议依赖定位图；授权受众与用途相符则条件满足。"""
        p1 = [p for p in self.proposals if p.kind == "one_way"][0]
        self.assertEqual(p1.material_refs, ["R2"])
        self.assertEqual(p1.questions, [])
        # 资料指定的先行场次来自使用成员报名的场次。
        self.assertIn("early", self.materials.get("R2").prerequisite_sessions)

    def test_material_audience_excludes_mozhou(self):
        """若提议把墨舟拉进用图的小组，授权核对必须拦住。"""
        problems = self.materials.check("R2", ["橙子", "墨舟"], "贴标")
        self.assertTrue(any("墨舟" in p for p in problems))

    def test_wrong_purpose_is_rejected(self):
        problems = self.materials.check("R2", ["橙子"], "公开讲解")
        self.assertTrue(any("用途" in p for p in problems))


if __name__ == "__main__":
    unittest.main()
