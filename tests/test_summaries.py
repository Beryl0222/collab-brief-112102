"""安全摘要测试：分层可见与成员确认。"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from exchange.confidentiality import ConfidentialityList
from exchange.models import Visibility
from exchange.parsing import MessageParser, ProfileBuilder
from exchange.summaries import SummaryService

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def build_profiles():
    messages = {row["id"]: row for row in json.loads(
        (DATA_DIR / "messages.json").read_text(encoding="utf-8"))}
    builder = ProfileBuilder(MessageParser(sessions={"early": 1, "late": 2}))
    for msg_id in ("N1", "N2", "N3", "N4", "N5"):
        builder.add(messages[msg_id]["who"], messages[msg_id]["text"], msg_id=msg_id)
    return builder.profiles()


class SummaryTest(unittest.TestCase):
    def setUp(self):
        resources = json.loads((DATA_DIR / "resources.json").read_text(encoding="utf-8"))
        self.service = SummaryService(ConfidentialityList.from_resources(resources))
        self.profiles = build_profiles()
        for profile in self.profiles.values():
            self.service.draft(profile)

    def test_public_section_only_allows_permitted_terms(self):
        summary = self.service.get("丘柳")
        self.assertIn("云码头", summary.sections[Visibility.PUBLIC])
        mozhou = self.service.get("墨舟")
        # 商品代号“灯雀”被本人拒绝公开，不得出现在公开层。
        self.assertNotIn("灯雀", mozhou.sections[Visibility.PUBLIC])
        self.assertEqual(mozhou.sections[Visibility.PUBLIC], [])

    def test_raw_text_and_inquiry_stay_contact_only(self):
        summary = self.service.get("云梢")
        contact = summary.sections[Visibility.CONTACT]
        self.assertTrue(any("云码头" in line for line in contact))  # 涉私打听
        self.assertFalse(any("云码头" in line
                             for line in summary.sections[Visibility.PUBLIC]))

    def test_others_see_only_public_before_member_confirms(self):
        """成员确认前，其他人能看到的仅限允许公开的部分。"""
        self.service.invite_confirm("望北")
        view, _ = self.service.view("望北", "橙子", is_matched=True)
        self.assertNotIn(Visibility.MATCHED, view)
        self.service.confirm("望北")
        view, _ = self.service.view("望北", "橙子", is_matched=True)
        self.assertIn(Visibility.MATCHED, view)
        self.assertTrue(any("贴标" in line
                            for line in view[Visibility.MATCHED]))

    def test_contact_sees_withheld_reasons(self):
        _, withheld = self.service.view("丘柳", "联络人", is_contact=True)
        self.assertEqual(withheld, [])  # 丘柳公开层未凑齐组合
        # 构造一个会凑齐组合的档案：同时允许云码头与灯雀公开。
        profile = self.profiles["丘柳"]
        from exchange.models import PermissionRule
        profile.permissions.append(PermissionRule(
            target="灯雀", allowed=True, visibility=Visibility.PUBLIC))
        self.service.draft(profile)
        summary = self.service.get("丘柳")
        self.assertNotIn("灯雀", summary.sections[Visibility.PUBLIC])
        self.assertEqual(summary.withheld[0].term, "灯雀")

    def test_announcement_never_completes_combo(self):
        announcement = self.service.announcement()
        self.assertIn("云码头", announcement)
        self.assertNotIn("灯雀", announcement)


if __name__ == "__main__":
    unittest.main()
