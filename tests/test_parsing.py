"""解析层测试：供给、需求、转述、否定、附条件、许可、澄清合并。"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from exchange.models import Visibility
from exchange.parsing import MessageParser, ProfileBuilder

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
SESSIONS = {"early": 1, "late": 2}
SENSITIVE = ["云码头", "灯雀"]


def load_messages():
    rows = json.loads((DATA_DIR / "messages.json").read_text(encoding="utf-8"))
    return {row["id"]: row for row in rows}


class ParseMessagesTest(unittest.TestCase):
    def setUp(self):
        self.messages = load_messages()
        self.parser = MessageParser(sessions=SESSIONS, sensitive_terms=SENSITIVE)

    def parse(self, msg_id):
        row = self.messages[msg_id]
        return self.parser.parse(row["who"], row["text"], msg_id=msg_id)

    def test_n1_supply_demand_permission_in_one_message(self):
        """同一条留言里同时出现的供给、需求与许可范围。"""
        parsed = self.parse("N1")
        self.assertEqual([o.capability.key for o in parsed.offers], ["温区标定"])
        self.assertEqual(len(parsed.exchanges), 1)
        wish = parsed.exchanges[0]
        self.assertEqual(wish.want.key, "视觉设计")
        self.assertTrue(wish.one_slot)  # 只给一个时段内能做完的安排
        denied = [r for r in parsed.permissions if not r.allowed]
        self.assertEqual(denied[0].target, "灯雀")
        self.assertEqual(parsed.attributes["商品代号"], "灯雀")
        self.assertEqual(parsed.attribute_visibility["商品代号"], Visibility.CONTACT)

    def test_n2_exchange_condition_and_private_inquiry(self):
        parsed = self.parse("N2")
        self.assertEqual(parsed.offers[0].capability.key, "视觉设计")
        wish = parsed.exchanges[0]
        self.assertEqual(wish.require_counter.key, "温区标定")
        # 涉私打听被记录，且不得进入公开内容。
        self.assertEqual(len(parsed.inquiries), 1)
        self.assertIn("云码头", parsed.inquiries[0].terms)
        allow = [r for r in parsed.permissions if r.allowed]
        self.assertEqual(allow[0].visibility, Visibility.MATCHED)

    def test_n3_reported_speech_is_not_own_offer(self):
        """转述不算本人供给；否定声明被单独记录。"""
        parsed = self.parse("N3")
        self.assertEqual(len(parsed.reported_leads), 1)
        lead = parsed.reported_leads[0]
        self.assertEqual(lead.source, "reported")
        self.assertEqual(lead.reported_from, "云梢的朋友")
        self.assertEqual(lead.capability.key, "温区标定")
        self.assertEqual([n.capability.key for n in parsed.non_offers], ["温区标定"])
        self.assertEqual([o.capability.key for o in parsed.offers], ["贴标"])
        # 附条件“别让赞助方看到定位图”落实为许可规则。
        rule = parsed.permissions[0]
        self.assertFalse(rule.allowed)
        self.assertIn("赞助方", rule.parties)
        self.assertEqual(parsed.conditions[0].status, "satisfied")

    def test_n4_registration_need_and_material_condition(self):
        parsed = self.parse("N4")
        self.assertEqual(parsed.sessions, ["early"])  # 先行场 → 优先级最高的场次
        self.assertEqual(parsed.offers[0].capability.key, "样品")
        need = parsed.needs[0]
        self.assertEqual(need.capability.key, "贴标")
        self.assertEqual(set(need.accept_from), {"墨舟", "望北"})
        material = [c for c in parsed.conditions if c.kind == "material"]
        self.assertEqual(material[0].ref, "定位图")
        self.assertEqual(material[0].status, "unknown")

    def test_n5_grant_denial_and_combo_permission(self):
        parsed = self.parse("N5")
        grant = parsed.grants[0]
        self.assertEqual(grant.material, "定位图")
        self.assertEqual(set(grant.audience), {"橙子", "望北"})
        self.assertEqual(grant.purpose, "贴标")
        self.assertEqual(parsed.denials[0].parties, frozenset({"墨舟"}))
        alone = [r for r in parsed.permissions if r.allowed and r.target == "云码头"]
        self.assertTrue(alone)
        combo = [r for r in parsed.permissions
                 if not r.allowed and r.target == "灯雀"]
        self.assertTrue(combo)  # 不能和灯雀一起说

    def test_n6_negation_and_lock_condition(self):
        parsed = self.parse("N6")
        self.assertEqual([n.capability.key for n in parsed.non_offers], ["贴标"])
        lock = [c for c in parsed.conditions if c.kind == "lock"]
        self.assertEqual(lock[0].status, "unknown")  # 还没同意锁时段
        fallback = [c for c in parsed.conditions if c.kind == "fallback"]
        self.assertTrue(fallback)

    def test_n7_withdrawal(self):
        parsed = self.parse("N7")
        self.assertEqual(len(parsed.withdrawals), 1)
        self.assertEqual(parsed.withdrawals[0].material, "定位图")
        self.assertIn("已约好的事先联系我", parsed.withdrawals[0].note)

    def test_consent_parsing(self):
        consents = {row["id"]: row for row in json.loads(
            (DATA_DIR / "consents.json").read_text(encoding="utf-8"))}
        k3 = self.parser.parse_consent("云梢", "late", consents["K3"]["text"])
        self.assertFalse(k3.allow_lock)  # 时段先别锁
        k2 = self.parser.parse_consent("望北", "early", consents["K2"]["text"])
        self.assertTrue(k2.allow_lock)
        self.assertFalse(k2.permissions[0].allowed)  # 不同意别人转发
        k4 = self.parser.parse_consent("墨舟", "late", consents["K4"]["text"])
        self.assertEqual(k4.capabilities, {"温区标定", "视觉设计"})


class ClarificationMergeTest(unittest.TestCase):
    def test_clarifications_merge_into_profile(self):
        """随后的澄清并入档案：否定、锁时段条件后到的为准。"""
        messages = load_messages()
        builder = ProfileBuilder(MessageParser(sessions=SESSIONS))
        builder.add("墨舟", messages["N1"]["text"], msg_id="N1")
        builder.add("墨舟", messages["N6"]["text"], msg_id="N6")
        profile = builder.profiles()["墨舟"]
        self.assertTrue(profile.declines("贴标"))
        self.assertIsNotNone(profile.offer_for("温区标定"))
        lock = [c for c in profile.conditions if c.kind == "lock"]
        self.assertEqual(len(lock), 1)  # 同类条件不重复堆积
        self.assertEqual(len(profile.raw), 2)  # 原文都保留

    def test_prompt_example_colloquial_message(self):
        """题目示例：口语里同时识别供给、许可与附条件。"""
        builder = ProfileBuilder(MessageParser())
        builder.add("某成员", "做过冷链方向，可以帮看方案，先别用项目真名，"
                             "时间得等我拿到测试档后定")
        profile = builder.profiles()["某成员"]
        keys = {o.capability.key for o in profile.offers}
        self.assertIn("冷链方向", keys)
        self.assertIn("看方案", keys)
        denied = [r for r in profile.permissions if not r.allowed]
        self.assertEqual(denied[0].target, "项目真名")
        timing = [c for c in profile.conditions if c.kind == "timing"]
        self.assertEqual(timing[0].status, "unknown")  # 未知条件 → 待问


if __name__ == "__main__":
    unittest.main()
