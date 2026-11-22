"""保密词表测试：组合识别与公开内容净化。"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from exchange.confidentiality import ConfidentialityList, SensitiveCombo

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


class ConfidentialityTest(unittest.TestCase):
    def setUp(self):
        resources = json.loads((DATA_DIR / "resources.json").read_text(encoding="utf-8"))
        self.lexicon = ConfidentialityList.from_resources(resources)

    def test_combo_loaded_from_resources(self):
        self.assertEqual(self.lexicon.terms, {"云码头", "灯雀"})

    def test_single_term_is_safe(self):
        kept, withheld = self.lexicon.sanitize({"云码头"}, protected={"云码头"})
        self.assertEqual(kept, {"云码头"})
        self.assertEqual(withheld, [])

    def test_combination_is_broken(self):
        """地点加商品代号凑齐组合时，优先隐去未被允许单说的词。"""
        kept, withheld = self.lexicon.sanitize(
            {"云码头", "灯雀"}, protected={"云码头"})
        self.assertEqual(kept, {"云码头"})
        self.assertEqual(withheld[0].term, "灯雀")
        self.assertIn("暴露项目身份", withheld[0].reason)

    def test_combination_without_protected_drops_one(self):
        kept, withheld = self.lexicon.sanitize({"云码头", "灯雀"})
        self.assertEqual(len(kept), 1)
        self.assertEqual(len(withheld), 1)

    def test_unrelated_terms_untouched(self):
        kept, withheld = self.lexicon.sanitize({"温区标定", "贴标"})
        self.assertEqual(kept, {"温区标定", "贴标"})


if __name__ == "__main__":
    unittest.main()
