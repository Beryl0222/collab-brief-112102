"""解释测试：内部理由与公告安全措辞分层。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from exchange.confidentiality import ConfidentialityList, SensitiveCombo
from exchange.explain import ExplainService
from exchange.materials import Material, MaterialRegistry
from exchange.models import Inquiry


class ExplainTest(unittest.TestCase):
    def setUp(self):
        materials = MaterialRegistry()
        materials.register(Material(
            id="R2", name="定位图", owner="丘柳",
            audience={"橙子", "望北"}, purpose="贴标",
            denied={"墨舟"}))
        lexicon = ConfidentialityList(
            [SensitiveCombo(terms=frozenset({"云码头", "灯雀"}), note="R1")])
        self.explain = ExplainService(materials, lexicon)

    def test_material_access_denied(self):
        explanation = self.explain.material_access("墨舟", "R2")
        self.assertIn("墨舟", explanation.internal)
        self.assertIn("排除", explanation.internal)
        # 公开措辞不暴露授权细节与私密原因。
        self.assertNotIn("墨舟", explanation.public)
        self.assertNotIn("定位图", explanation.public)

    def test_material_access_allowed(self):
        explanation = self.explain.material_access("橙子", "R2")
        self.assertIn("可以看到", explanation.internal)

    def test_inquiry_about_sensitive_combo(self):
        inquiry = Inquiry(text="能不能告诉我他是不是云码头那间？",
                          terms=["云码头"])
        explanation = self.explain.inquiry(inquiry)
        self.assertIn("云码头", explanation.internal)
        # 公告措辞不得补全组合，也不得带出打听内容。
        self.assertNotIn("灯雀", explanation.public)
        self.assertNotIn("云码头", explanation.public)

    def test_lock_pending(self):
        from exchange.commitments import Commitment
        from exchange.matching import HelpEdge, Proposal
        proposal = Proposal(
            id="P1", kind="mutual", session="late", parties=("甲", "乙"),
            edges=[HelpEdge(giver="甲", receiver="乙", capability="贴标")])
        commitment = Commitment(id="C1", proposal=proposal,
                                confirmations={"甲": True, "乙": True},
                                lock_ok={"甲": True, "乙": False})
        explanation = self.explain.lock_pending(commitment)
        self.assertIn("乙", explanation.internal)
        self.assertNotIn("乙", explanation.public)


if __name__ == "__main__":
    unittest.main()
