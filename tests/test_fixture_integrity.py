import json
from pathlib import Path
import unittest


class FixtureIntegrityTests(unittest.TestCase):
    def test_corrected_installation_and_claim_history_are_present(self):
        data = json.loads((Path(__file__).parents[1] / "data/facts.json").read_text(encoding="utf-8"))
        revisions = data["installations"]
        self.assertEqual(revisions[1]["revision"], 2)
        self.assertEqual(revisions[1]["part"], revisions[0]["part"])
        self.assertEqual({row["state"] for row in data["claims"]}, {"accepted", "pending"})


if __name__ == "__main__":
    unittest.main()
