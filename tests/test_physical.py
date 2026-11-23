"""实物在途与厂方签收。"""

import unittest

from _helpers import build
from warehouse.pipeline import run


class PhysicalTests(unittest.TestCase):
    def setUp(self):
        self.w = build()

    def test_in_transit_remains_in_transit_even_when_feed_arrives_late(self):
        view = self.w["fact_physical"]["parts"]["V-A/P-301"]
        self.assertEqual(view["current_state"], "in-transit")
        self.assertEqual([e["event"] for e in view["events"]], ["ship"])
        # 绝不出现“已装回/已签收”的推断事件。
        self.assertNotIn("factory_receipt", [e["event"] for e in view["events"]])

    def test_factory_receipt_is_its_own_event_time(self):
        view = self.w["fact_physical"]["parts"]["V-B/P-401"]
        receipt = [e for e in view["events"] if e["event"] == "factory_receipt"]
        self.assertEqual(len(receipt), 1)
        self.assertEqual(receipt[0]["event_at"], "2026-09-08")
        self.assertEqual(view["current_state"], "at-factory")

    def test_return_facts_keep_raw_states(self):
        returns = index_returns(self.w)
        self.assertEqual(returns["RET-7"]["state"], "in-transit")
        self.assertIsNone(returns["RET-7"]["received_at"])
        self.assertEqual(returns["RET-401"]["state"], "received")

    def test_same_day_ship_and_receipt_ends_at_factory_not_transit(self):
        raw = {
            "vehicles": [{"serial": "C1", "sold_at": "2026-01-01"}],
            "parts": [{"serial": "P9", "vendor": "V", "warranty_months": 12}],
            "returns": [
                {
                    "id": "RET-9",
                    "part": "P9",
                    "vendor": "V",
                    "state": "received",
                    "sent_at": "2026-11-22",
                    "received_at": "2026-11-22",
                    "work_order": "WO-9",
                }
            ],
        }
        w = run(raw)
        view = w["fact_physical"]["parts"]["V/P9"]
        self.assertEqual([e["event"] for e in view["events"]], ["ship", "factory_receipt"])
        self.assertEqual(view["current_state"], "at-factory")


def index_returns(w):
    return {r["return_id"]: r for r in w["fact_physical"]["returns"]}


if __name__ == "__main__":
    unittest.main()
