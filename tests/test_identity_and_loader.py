"""标识范围与装载校验。"""

import unittest

from warehouse.identifiers import part_key, split_part_key
from warehouse.loader import load_bundle
from warehouse.timeutil import add_months, contains, inclusive_end, overlap

from _helpers import load_raw


class IdentifierScopeTests(unittest.TestCase):
    def test_part_serial_is_vendor_scoped(self):
        a = part_key("V-A", "SHARED-X")
        b = part_key("V-B", "SHARED-X")
        self.assertNotEqual(a, b)
        self.assertEqual(split_part_key(a), ("V-A", "SHARED-X"))

    def test_same_serial_under_different_vendors_both_loaded(self):
        bundle = load_bundle(load_raw("extended_facts.json"))
        self.assertIn("V-A/SHARED-X", bundle.parts)
        self.assertIn("V-B/SHARED-X", bundle.parts)

    def test_duplicate_part_within_vendor_rejected(self):
        raw = {
            "vehicles": [{"serial": "C1", "sold_at": "2026-01-01"}],
            "parts": [
                {"serial": "P1", "vendor": "V", "warranty_months": 12},
                {"serial": "P1", "vendor": "V", "warranty_months": 12},
            ],
        }
        with self.assertRaises(ValueError):
            load_bundle(raw)

    def test_duplicate_vehicle_rejected(self):
        raw = {"vehicles": [{"serial": "C1", "sold_at": "2026-01-01"}, {"serial": "C1", "sold_at": "2026-02-01"}], "parts": []}
        with self.assertRaises(ValueError):
            load_bundle(raw)

    def test_unknown_reference_rejected(self):
        raw = {
            "vehicles": [{"serial": "C1", "sold_at": "2026-01-01"}],
            "parts": [{"serial": "P1", "vendor": "V", "warranty_months": 12}],
            "installations": [
                {"part": "P1", "vendor": "V", "vehicle": "GHOST", "from": "2026-01-01", "work_order": "W1"}
            ],
        }
        with self.assertRaises(ValueError):
            load_bundle(raw)


class TimeIntervalTests(unittest.TestCase):
    def test_half_open_intervals_that_touch_do_not_overlap(self):
        # 换装链：旧段止于 11-10，新段起于 11-10，不应判为相撞。
        from datetime import date

        self.assertFalse(overlap(date(2026, 5, 1), date(2026, 9, 1), date(2026, 9, 1), None))
        self.assertTrue(overlap(date(2026, 2, 1), None, date(2026, 3, 1), None))
        self.assertTrue(contains(date(2026, 1, 1), None, date(2030, 1, 1)))
        self.assertFalse(contains(date(2026, 1, 1), date(2026, 2, 1), date(2026, 2, 1)))

    def test_month_arithmetics_and_inclusive_end(self):
        from datetime import date

        self.assertEqual(add_months(date(2026, 1, 31), 1), date(2026, 2, 28))
        self.assertEqual(inclusive_end(date(2025, 6, 1), 24), date(2027, 5, 31))
        self.assertEqual(inclusive_end(date(2025, 7, 1), 36), date(2028, 6, 30))


if __name__ == "__main__":
    unittest.main()
