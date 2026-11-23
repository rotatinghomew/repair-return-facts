"""配件归属：修订回补、相撞待裁、同件唯一。"""

import unittest

from _helpers import build, index


class OwnershipTests(unittest.TestCase):
    def setUp(self):
        self.w = build()
        self.segs = self.w["fact_ownership"]

    def test_one_part_one_vehicle_at_any_business_time_when_chain_is_sequential(self):
        # PART-77 在 CAR-1 / CAR-2 上首尾相接，均为 effective，不算冲突。
        rows = [s for s in self.segs if s["part_key"] == "V-A/PART-77"]
        self.assertEqual([s["status"] for s in rows], ["effective", "effective"])
        self.assertEqual(rows[0]["valid_to"], rows[1]["valid_from"])

    def test_overlapping_ownership_is_disputed_with_undetermined_window(self):
        rows = [s for s in self.segs if s["part_key"] == "V-A/P-201"]
        self.assertEqual({s["status"] for s in rows}, {"disputed"})
        for seg in rows:
            self.assertEqual(seg["undetermined_windows"], [{"from": "2026-03-01", "to": None}])
            self.assertTrue(seg["conflict_with"])

    def test_correction_backfills_business_date_but_keeps_system_time(self):
        # WO-501 的修订把配件改挂 CAR-2，业务有效期回补到原维修日 2026-04-01；
        # 更正到达的系统时间保留为 2026-10-01。
        rows = sorted([s for s in self.segs if s["work_order"] == "WO-501"], key=lambda s: s["revision"])
        old, new = rows
        self.assertEqual(old["status"], "superseded")
        self.assertEqual(new["status"], "effective")
        self.assertEqual(old["valid_from"], new["valid_from"])
        self.assertEqual(old["vehicle"], "CAR-1")
        self.assertEqual(new["vehicle"], "CAR-2")
        self.assertEqual(new["correction_received"], "2026-10-01")
        self.assertIsNone(old["correction_received"])

    def test_other_defined_objects_remain_queryable_while_one_window_undetermined(self):
        # CAR-1 上 P-201 有未定窗口，但同一整机的 P-301 仍是明确归属。
        car1 = [s for s in self.segs if s["vehicle"] == "CAR-1" and s["status"] != "superseded"]
        statuses = index(car1, "part_key")
        self.assertEqual(statuses["V-A/P-301"]["status"], "effective")
        self.assertEqual(statuses["V-A/P-201"]["status"], "disputed")

    def test_late_in_transit_feed_never_changes_ownership(self):
        # P-301 的在途流水 11-20 才入仓，归属段仍只有装机一条，且状态 effective。
        rows = [s for s in self.segs if s["part_key"] == "V-A/P-301"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "effective")
        self.assertIsNone(rows[0]["valid_to"])


if __name__ == "__main__":
    unittest.main()
