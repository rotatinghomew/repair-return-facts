"""追偿状态机、证据吻合、争认人工确认、收回与冲正。"""

import unittest

from warehouse.claims import (
    ELIGIBLE_TO_SETTLE,
    MANUAL_REVIEW,
    PENDING_VERIFICATION,
    REVERSED,
    WITHDRAWN,
    REV_REVERSAL,
    REV_WITHDRAWAL,
)

from _helpers import build, index


class ClaimTests(unittest.TestCase):
    def setUp(self):
        self.w = build()
        self.claims = index(self.w["fact_claims"], "claim_id")
        self.reversals = index(self.w["fact_reversals"], "claim_id")

    def test_work_order_done_but_old_part_in_transit_is_pending_verification(self):
        claim = self.claims["CLM-19"]
        self.assertEqual(claim["derived_state"], PENDING_VERIFICATION)
        self.assertEqual(claim["physical_state_at_run"], "in-transit")
        self.assertFalse(claim["evidence_matches_work_order"])

    def test_late_in_transit_feed_never_promotes_a_claim(self):
        # P-701 / P-301 的在途单再晚入仓，也不能把任何待核追偿推成可结算。
        for claim in self.w["fact_claims"]:
            if claim["physical_state_at_run"] == "in-transit":
                self.assertNotEqual(claim["derived_state"], ELIGIBLE_TO_SETTLE)

    def test_factory_receipt_matching_work_order_is_eligible_to_settle(self):
        claim = self.claims["CLM-401"]
        self.assertEqual(claim["derived_state"], ELIGIBLE_TO_SETTLE)
        self.assertEqual(claim["physical_state_at_run"], "at-factory")
        self.assertTrue(claim["evidence_matches_work_order"])
        self.assertEqual(claim["return_id"], "RET-401")
        self.assertEqual(claim["factory_receipt_at"], "2026-09-08")

    def test_two_work_orders_contending_same_old_part_go_manual_review(self):
        for cid in ("CLM-201", "CLM-202"):
            self.assertEqual(self.claims[cid]["derived_state"], MANUAL_REVIEW)
            self.assertIn("人工", self.claims[cid]["hold_reason"])

    def test_sequential_swaps_are_not_contention(self):
        # P-401 两张工单是先后换装，只有一张追偿，正常进入可结算。
        self.assertNotIn("CLM-402", self.claims)

    def test_correction_withdraws_unsettled_claim(self):
        claim = self.claims["CLM-501"]
        self.assertEqual(claim["derived_state"], WITHDRAWN)
        self.assertEqual(claim["superseded_by"]["revision"], 2)
        self.assertIn("收回", claim["hold_reason"])
        rev = self.reversals["CLM-501"]
        self.assertEqual(rev["reversal_type"], REV_WITHDRAWAL)
        self.assertEqual(rev["effective_at"], "2026-10-01")
        self.assertIsNone(rev["original_receipt"])

    def test_correction_reverses_accepted_claim_but_keeps_original_receipt(self):
        claim = self.claims["CLM-601"]
        self.assertEqual(claim["derived_state"], REVERSED)
        # 原始追偿行不删除，源状态与回执保留。
        self.assertEqual(claim["source_state"], "accepted")
        self.assertEqual(claim["source_receipt"], "VENDOR-ACK-601")
        rev = self.reversals["CLM-601"]
        self.assertEqual(rev["reversal_type"], REV_REVERSAL)
        self.assertEqual(rev["original_receipt"], "VENDOR-ACK-601")
        self.assertEqual(rev["effective_at"], "2026-10-05")

    def test_claim_carries_vendor_reason_and_physical_state(self):
        claim = self.claims["CLM-401"]
        self.assertEqual(claim["vendor"], "V-B")
        self.assertEqual(claim["reason"], "制造缺陷")
        self.assertEqual(claim["physical_state_at_run"], "at-factory")

    def test_reconciliation_workbench_buckets(self):
        from warehouse import Serving

        buckets = Serving(self.w).claims_awaiting_action()
        ids = {state: {c["claim_id"] for c in rows} for state, rows in buckets.items()}
        self.assertIn("CLM-401", ids[ELIGIBLE_TO_SETTLE])
        self.assertIn("CLM-201", ids[MANUAL_REVIEW])
        self.assertIn("CLM-19", ids[PENDING_VERIFICATION])

    def test_state_machine_branches_directly(self):
        from datetime import date

        from warehouse.claims import _derive_state, _Evidence
        from warehouse.loader import ClaimRecord

        claim = ClaimRecord("C", "V/P", "CAR", "WO", "pending", None, "原因")
        # 已到厂但证据不吻合 → 人工核对，不允许结算。
        state, reason = _derive_state(
            claim, _Evidence("at-factory", date(2026, 9, 8), "RET-1", False), None, False
        )
        self.assertEqual(state, MANUAL_REVIEW)
        self.assertIn("不吻合", reason)
        # 无任何实物流水且源端待核 → 保持待核，不推断位置。
        state, _ = _derive_state(claim, _Evidence("installed", None, None, False), None, False)
        self.assertEqual(state, PENDING_VERIFICATION)
        # 源端已接收且证据吻合 → 已结算。
        accepted = ClaimRecord("C2", "V/P", "CAR", "WO", "accepted", "ACK-1", "原因")
        state, _ = _derive_state(
            accepted, _Evidence("at-factory", date(2026, 9, 8), "RET-1", True), None, False
        )
        self.assertEqual(state, "settled")


if __name__ == "__main__":
    unittest.main()
