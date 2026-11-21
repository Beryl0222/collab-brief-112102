"""检查交换资料的标识、文本和跨表引用。"""

import json
from pathlib import Path
import unittest


DATA_DIR = Path(__file__).resolve().parents[1] / "data"


class SourceDataTest(unittest.TestCase):
    def setUp(self):
        self.tables = {}
        for path in sorted(DATA_DIR.glob("*.json")):
            rows = json.loads(path.read_text(encoding="utf-8"))
            self.assertIsInstance(rows, list)
            self.assertTrue(rows, path.name)
            by_id = {}
            for row in rows:
                identifier = row["id"]
                self.assertIsInstance(identifier, str, path.name)
                self.assertNotIn(identifier, by_id, path.name)
                if "text" in row:
                    self.assertIsInstance(row["text"], str, path.name)
                by_id[identifier] = row
            self.tables[path.stem] = by_id

    def test_exchange_tables_present(self):
        self.assertEqual(set(self.tables), {'consents', 'messages', 'resources', 'timeline'})

    def test_related_source_records(self):
        data = self.tables
        refs = data["messages"].keys() | data["consents"].keys()
        for event in data["timeline"].values():
            self.assertTrue(set(event["refs"]) <= refs)
        early = data["resources"]["early"]["who"]
        late = data["resources"]["late"]["who"]
        self.assertIn("望北", set(early) & set(late))
        self.assertEqual(data["resources"]["R3"]["max_sessions"], 1)
        self.assertNotIn("墨舟", data["resources"]["R2"]["access"])
        self.assertTrue(all(row["accepted_for"] in data["resources"]
                            for row in data["consents"].values()))
