import sys
import unittest
from datetime import date
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quote_domain import (
    UnsupportedDiameterError,
    apply_manual_quote,
    build_quote_line,
    price_rule_for,
)


class QuoteDomainTests(unittest.TestCase):
    def test_305_uses_new_price_from_2026_08_13(self):
        rule = price_rule_for("305", date(2026, 8, 13))
        self.assertEqual(
            (rule.grinding_price, rule.tooth_price, rule.fanban_price),
            (240, 150, 230),
        )

    def test_two_supplement_teeth_are_charged_per_tooth(self):
        blade = {
            "id": 1,
            "customer": "甲",
            "brand_id": "4012",
            "od": "305",
            "thickness": "3.0",
            "teeth": "100",
            "grind": "是",
            "supp_teeth": "2",
            "fanban": "-",
        }
        line = build_quote_line(blade, price_rule_for("305", date(2026, 8, 13)))
        self.assertEqual(line.subtotal, 540)

    def test_355_and_405_to_455_rules(self):
        self.assertEqual(
            price_rule_for("355", date(2026, 8, 13)).grinding_price,
            280,
        )
        self.assertEqual(
            price_rule_for("455", date(2026, 8, 13)).fanban_price,
            250,
        )

    def test_unsupported_diameter_requires_manual_price(self):
        with self.assertRaises(UnsupportedDiameterError):
            price_rule_for("3050", date(2026, 8, 13))

    def test_manual_quote_recalculates_subtotal_without_mutating_source(self):
        source = {
            "id": 1,
            "customer": "甲",
            "brand_id": "4012",
            "od": "305",
            "thickness": "3.0",
            "teeth": "100",
            "grind": "是",
            "supp_teeth": "2",
            "fanban": "-",
        }
        line = build_quote_line(source, price_rule_for("305", date(2026, 8, 13)))

        changed = apply_manual_quote(line, tooth_qty=1, tooth_unit=120)

        self.assertEqual(changed.subtotal, 360)
        self.assertEqual(line.subtotal, 540)
        self.assertEqual(source["supp_teeth"], "2")

    def test_manual_quote_keeps_original_automatic_suggestion(self):
        blade = {
            "id": 1,
            "customer": "甲",
            "brand_id": "4012",
            "od": "305",
            "thickness": "3.0",
            "teeth": "100",
            "grind": "是",
            "supp_teeth": "2",
            "fanban": "-",
        }
        line = build_quote_line(blade, price_rule_for("305", date(2026, 8, 13)))

        changed = apply_manual_quote(line, tooth_qty=1, tooth_unit=120)

        self.assertEqual(changed.suggested_grinding_qty, 1)
        self.assertEqual(changed.suggested_grinding_unit, 240)
        self.assertEqual(changed.suggested_tooth_qty, 2)
        self.assertEqual(changed.suggested_tooth_unit, 150)
        self.assertEqual(changed.suggested_fanban_qty, 0)
        self.assertEqual(changed.suggested_fanban_unit, 0)
        self.assertEqual(changed.suggested_subtotal, 540)
        self.assertEqual((changed.tooth_qty, changed.tooth_unit, changed.subtotal), (1, 120, 360))

    def test_manual_quote_rejects_nonnegative_integer_validation_failures(self):
        blade = {
            "id": 1,
            "customer": "甲",
            "brand_id": "4012",
            "od": "305",
            "thickness": "3.0",
            "teeth": "100",
            "grind": "是",
            "supp_teeth": "2",
            "fanban": "-",
        }
        line = build_quote_line(blade, price_rule_for("305", date(2026, 8, 13)))

        for invalid_value in (-1, "-1", "2.5", "", True):
            with self.subTest(invalid_value=invalid_value):
                with self.assertRaises(ValueError):
                    apply_manual_quote(line, tooth_unit=invalid_value)
