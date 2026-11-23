"""质保权利：原机保护期与换件保障共同适用、来源与适用日期可追溯。"""

import unittest
from datetime import date

from warehouse.rights import EXPIRED

from _helpers import build, index, serving


class RightsTests(unittest.TestCase):
    def setUp(self):
        self.w = build()
        self.rights = self.w["fact_rights"]

    def _part_rights(self, vehicle):
        return [r for r in self.rights if r["vehicle"] == vehicle and r["right_type"] == "replacement_part"]

    def test_vehicle_base_warranty_uses_sale_date(self):
        base = index([r for r in self.rights if r["right_type"] == "vehicle_base"], "vehicle")
        self.assertEqual(base["CAR-1"]["applies_from"], "2025-06-01")
        self.assertEqual(base["CAR-1"]["applies_to"], "2028-05-31")
        self.assertEqual(base["CAR-3"]["status_as_of_run"], EXPIRED)
        self.assertEqual(base["CAR-3"]["applies_to"], "2025-01-09")

    def test_replacement_right_follows_installed_part_and_work_order_source(self):
        rows = self._part_rights("CAR-2")
        wo19 = next(r for r in rows if r["work_order"] == "WO-19")
        self.assertEqual(wo19["part_key"], "V-A/PART-77")
        self.assertEqual(wo19["applies_from"], "2026-11-10")
        self.assertEqual(wo19["applies_to"], "2028-11-09")
        self.assertEqual(wo19["source"]["vendor"], "V-A")
        self.assertEqual(wo19["correction_received"], "2026-11-18")

    def test_both_protections_coexist_on_same_vehicle(self):
        view = serving().vehicle_warranties("CAR-2", date(2026, 11, 23))
        types = {r["right_type"] for r in view["determined_rights"]}
        self.assertEqual(types, {"vehicle_base", "replacement_part"})

    def test_superseded_installation_does_not_emit_current_right(self):
        # WO-501 修订后，旧陈述（CAR-1）不再产生权利；当前权利挂在 CAR-2 上。
        rows = [r for r in self.rights if r["work_order"] == "WO-501"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["vehicle"], "CAR-2")

    def test_disputed_window_right_is_undetermined_but_others_still_visible(self):
        view = serving().vehicle_warranties("CAR-1", date(2026, 11, 23))
        undetermined_parts = {r["part_key"] for r in view["undetermined_rights"]}
        self.assertIn("V-A/P-201", undetermined_parts)
        determined_parts = {r["part_key"] for r in view["determined_rights"]}
        self.assertIn("V-A/P-301", determined_parts)
        # 原机保护期不受配件争议影响。
        self.assertTrue(any(r["right_type"] == "vehicle_base" for r in view["determined_rights"]))

    def test_historical_rights_query_keeps_sources_and_dates(self):
        view = serving().vehicle_warranties("CAR-1", date(2025, 7, 1))
        wo9 = next(r for r in view["determined_rights"] if r["work_order"] == "WO-9")
        self.assertEqual(wo9["applies_from"], "2025-06-01")
        self.assertEqual(wo9["source"]["kind"], "installation")

    def test_vehicle_rule_override_flows_into_rights_and_warehouse(self):
        from _helpers import load_raw
        from warehouse import run

        raw = load_raw("extended_facts.json")
        raw["rules"] = {"vehicle_warranty_months": 12}
        w = run(raw, date(2026, 11, 23))
        base = next(r for r in w["fact_rights"] if r["right_id"] == "RIGHT-V-CAR-1")
        self.assertEqual(base["applies_to"], "2026-05-31")
        self.assertEqual(base["status_as_of_run"], EXPIRED)
        self.assertEqual(w["applied_rules"]["vehicle_warranty_months"], 12)


if __name__ == "__main__":
    unittest.main()
