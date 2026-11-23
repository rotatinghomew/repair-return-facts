"""流水线幂等性、服务层一次换装可追溯、更正血缘。"""

import json
import unittest
from datetime import date

from warehouse import Serving, run

from _helpers import build, load_raw, serving


class PipelineIdempotencyTests(unittest.TestCase):
    def test_same_input_same_run_date_produces_identical_warehouse(self):
        raw = load_raw("extended_facts.json")
        first = run(raw, date(2026, 11, 23))
        second = run(json.loads(json.dumps(raw)), date(2026, 11, 23))
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))

    def test_rerun_is_full_rebuild_without_accumulation(self):
        raw = load_raw("extended_facts.json")
        once = run(raw, date(2026, 11, 23))
        twice = run(once and raw, date(2026, 11, 23))
        self.assertEqual(len(once["fact_reversals"]), len(twice["fact_reversals"]))
        self.assertEqual(len(once["fact_ownership"]), len(twice["fact_ownership"]))

    def test_run_date_changes_only_as_of_status_not_event_facts(self):
        raw = load_raw("extended_facts.json")
        now = run(raw, date(2026, 11, 23))
        later = run(raw, date(2029, 1, 1))
        # 事件事实不变（归属/签收/冲正均以业务时间为准）。
        self.assertEqual(now["fact_ownership"], later["fact_ownership"])
        self.assertEqual(now["fact_reversals"], later["fact_reversals"])
        # 到期判断随运行日变化。
        base_now = next(r for r in now["fact_rights"] if r["right_id"] == "RIGHT-V-CAR-1")
        base_later = next(r for r in later["fact_rights"] if r["right_id"] == "RIGHT-V-CAR-1")
        self.assertEqual(base_now["status_as_of_run"], "active")
        self.assertEqual(base_later["status_as_of_run"], "expired")


class ServingTraceTests(unittest.TestCase):
    def test_part_trace_covers_ownership_rights_physical_claims_and_changes(self):
        trace = serving().part_trace("V-A/P-601")
        work_orders = {s["work_order"] for s in trace["ownership"]}
        self.assertIn("WO-601", work_orders)
        self.assertTrue(any(r["work_order"] == "WO-601" for r in trace["rights"]))
        self.assertEqual(trace["current_physical_state"], "in-transit")
        self.assertTrue(any(c["claim_id"] == "CLM-601" for c in trace["claims"]))
        self.assertTrue(any(r["reversal_id"] == "REV-CLM-601" for r in trace["reversals"]))
        self.assertTrue(trace["lineage"])

    def test_lineage_records_which_correction_changed_the_fact(self):
        s = serving()
        changes = s.changes_affecting_work_order("WO-501")
        self.assertEqual(len(changes), 1)
        entry = changes[0]
        self.assertEqual(entry["old_vehicle"], "CAR-1")
        self.assertEqual(entry["new_vehicle"], "CAR-2")
        self.assertTrue(entry["business_date_unchanged"])
        self.assertEqual(entry["backfilled_to"], "2026-04-01")
        self.assertEqual(entry["correction_received"], "2026-10-01")
        self.assertIn("REV-CLM-501", entry["reversal_ids"])

    def test_vehicle_parts_excludes_superseded_segments(self):
        parts = serving().vehicle_parts("CAR-1")
        self.assertFalse(any(s["work_order"] == "WO-501" for s in parts))

    def test_original_fixture_still_supported(self):
        w = build("facts.json", date(2026, 11, 23))
        s = Serving(w)
        trace = s.part_trace("V-A/PART-77")
        self.assertEqual(trace["current_physical_state"], "in-transit")
        # 同件两张工单追偿且无重叠归属：在途 → 待核（原夹具 RET-7 未挂工单，证据不吻合）。
        states = {c["claim_id"]: c["derived_state"] for c in trace["claims"]}
        self.assertEqual(states["CLM-19"], "pending_verification")
        # CLM-9 源端已 accepted，但旧件仍在途，事实仓按实物证据降级为待核，保留原始回执。
        clm9 = s.claim("CLM-9")
        self.assertEqual(clm9["source_state"], "accepted")
        self.assertEqual(clm9["source_receipt"], "VENDOR-ACK-9")


if __name__ == "__main__":
    unittest.main()
