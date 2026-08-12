import importlib.util
import sqlite3
import sys
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

spec = importlib.util.spec_from_file_location("sawdoctor_app", PROJECT_ROOT / "鋸片醫生.py")
app = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(app)

from quote_domain import QuoteLineDraft


def confirmed_305_line():
    return QuoteLineDraft(
        blade_id=1,
        customer="甲",
        brand_id="4012",
        od="305",
        thickness="3.0",
        teeth="100",
        spec="305 x 3.0 x 100T",
        source_grind="是",
        source_supp_teeth="2",
        source_fanban="-",
        grinding_qty=1,
        grinding_unit=240,
        tooth_qty=2,
        tooth_unit=150,
        fanban_qty=0,
        fanban_unit=0,
        note="待客戶確認",
    )


def read_line(conn, batch_id):
    return conn.execute(
        "SELECT * FROM quote_lines WHERE batch_id = ?", (batch_id,)
    ).fetchone()


class QuoteStorageTests(unittest.TestCase):
    def test_initializes_effective_price_version_and_never_replaces_it(self):
        with TemporaryDirectory() as directory:
            conn = sqlite3.connect(Path(directory) / "quote.db")
            conn.row_factory = sqlite3.Row
            try:
                app.ensure_quote_schema(conn)

                rule = app.load_effective_price_rules(conn, date(2026, 8, 13))["305"]
                self.assertEqual(rule.grinding_price, 240)
                conn.execute("UPDATE price_rules SET grinding_price=999 WHERE od_min=305")
                conn.commit()

                self.assertEqual(
                    app.load_effective_price_rules(conn, date(2026, 8, 13))["305"].grinding_price,
                    999,
                )
                self.assertEqual(app.load_effective_price_rules(conn, date(2026, 8, 12)), {})
            finally:
                conn.close()

    def test_saved_quote_line_keeps_price_snapshot_after_future_rule_changes(self):
        with TemporaryDirectory() as directory:
            conn = sqlite3.connect(Path(directory) / "quote.db")
            conn.row_factory = sqlite3.Row
            try:
                app.ensure_quote_schema(conn)

                batch = app.save_quote_batch(
                    conn, "甲", [(2026, 8)], [confirmed_305_line()], "技師甲"
                )
                conn.execute("UPDATE price_rules SET tooth_price=999 WHERE od_min=305")
                conn.commit()

                self.assertEqual(read_line(conn, batch.id)["tooth_unit"], 150)
            finally:
                conn.close()

    def test_quote_batch_id_increments_for_the_same_day(self):
        with TemporaryDirectory() as directory:
            conn = sqlite3.connect(Path(directory) / "quote.db")
            conn.row_factory = sqlite3.Row
            try:
                app.ensure_quote_schema(conn)

                first = app.save_quote_batch(conn, "甲", [(2026, 8)], [confirmed_305_line()], "技師甲")
                second = app.save_quote_batch(conn, "甲", [(2026, 8)], [confirmed_305_line()], "技師甲")

                self.assertEqual(first.id[:-3], second.id[:-3])
                self.assertEqual(int(second.id[-3:]), int(first.id[-3:]) + 1)
                self.assertEqual(second.subtotal, 540)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
