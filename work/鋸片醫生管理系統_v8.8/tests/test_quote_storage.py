import importlib.util
import sqlite3
import sys
import unittest
from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

spec = importlib.util.spec_from_file_location("sawdoctor_app", PROJECT_ROOT / "鋸片醫生.py")
app = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(app)

from quote_domain import QuoteLineDraft, apply_manual_quote, build_quote_line


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


def read_output_formats(conn, batch_id):
    return [
        (row["format"], row["filename"])
        for row in conn.execute(
            "SELECT format, filename FROM quote_output_files "
            "WHERE batch_id = ? ORDER BY format", (batch_id,)
        )
    ]


def count_batches(conn):
    return conn.execute("SELECT COUNT(*) FROM quote_batches").fetchone()[0]


def successful_excel_exporter(target_dir, batch, lines):
    output = Path(target_dir) / app.quote_output_filename(
        batch.customer, batch.month_range, batch.id, "xlsx"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"xlsx")
    return output


class QuoteStorageTests(unittest.TestCase):
    def test_pdf_only_records_pdf_and_keeps_legacy_output_file(self):
        with TemporaryDirectory() as directory:
            conn = sqlite3.connect(Path(directory) / "quote.db")
            conn.row_factory = sqlite3.Row
            output_dir = Path(directory) / "output"
            fixed_now = datetime(2026, 8, 13, 9, 30)
            try:
                app.ensure_quote_schema(conn)

                def pdf_exporter(target_dir, batch, lines):
                    output = Path(target_dir) / app.quote_output_filename(
                        batch.customer, batch.month_range, batch.id, "pdf"
                    )
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_bytes(b"pdf")
                    return output

                batch, outputs = app.save_and_export_customer_quote(
                    conn, output_dir, "甲", [(2026, 8)], [confirmed_305_line()], "技師甲",
                    quote_date=date(2026, 8, 13), output_formats=("pdf",),
                    exporters={"pdf": pdf_exporter}, now=fixed_now,
                )

                self.assertEqual(outputs["pdf"].suffix, ".pdf")
                self.assertEqual(batch.output_file, outputs["pdf"].name)
                self.assertEqual(read_output_formats(conn, batch.id), [("pdf", outputs["pdf"].name)])
            finally:
                conn.close()

    def test_excel_and_pdf_failure_rolls_back_all_outputs_and_snapshot(self):
        with TemporaryDirectory() as directory:
            conn = sqlite3.connect(Path(directory) / "quote.db")
            conn.row_factory = sqlite3.Row
            output_dir = Path(directory) / "output"
            fixed_now = datetime(2026, 8, 13, 9, 30)
            try:
                app.ensure_quote_schema(conn)

                def successful_excel(target_dir, batch, lines):
                    output = Path(target_dir) / app.quote_output_filename(
                        batch.customer, batch.month_range, batch.id, "xlsx"
                    )
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_bytes(b"xlsx")
                    return output

                def failing_pdf(target_dir, batch, lines):
                    output = Path(target_dir) / app.quote_output_filename(
                        batch.customer, batch.month_range, batch.id, "pdf"
                    )
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_bytes(b"partial pdf")
                    raise RuntimeError("forced PDF export failure")

                with self.assertRaisesRegex(RuntimeError, "forced PDF export failure"):
                    app.save_and_export_customer_quote(
                        conn, output_dir, "甲", [(2026, 8)], [confirmed_305_line()], "技師甲",
                        quote_date=date(2026, 8, 13), output_formats=("xlsx", "pdf"),
                        exporters={"xlsx": successful_excel, "pdf": failing_pdf}, now=fixed_now,
                    )

                self.assertEqual(count_batches(conn), 0)
                self.assertEqual(list(output_dir.glob("*")), [])
            finally:
                conn.close()

    def test_atomic_quote_success_commits_snapshot_matching_final_workbook_name(self):
        with TemporaryDirectory() as directory:
            conn = sqlite3.connect(Path(directory) / "quote.db")
            conn.row_factory = sqlite3.Row
            output_dir = Path(directory) / "output"
            try:
                app.ensure_quote_schema(conn)

                batch, outputs = app.save_and_export_customer_quote(
                    conn, output_dir, "甲", [(2026, 8)], [confirmed_305_line()], "技師甲",
                    quote_date=date(2026, 8, 13),
                    exporters={"xlsx": successful_excel_exporter},
                    now=datetime(2026, 8, 13, 9, 30),
                )
                output = outputs["xlsx"]

                self.assertTrue(output.is_file())
                self.assertEqual(output.name, batch.output_file)
                stored = conn.execute(
                    "SELECT output_file FROM quote_batches WHERE id=?", (batch.id,)
                ).fetchone()
                self.assertEqual(stored["output_file"], output.name)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM quote_lines").fetchone()[0], 1)
                self.assertFalse(conn.in_transaction)
            finally:
                conn.close()

    def test_atomic_quote_collision_preserves_existing_workbook_and_writes_nothing(self):
        with TemporaryDirectory() as directory:
            conn = sqlite3.connect(Path(directory) / "quote.db")
            output_dir = Path(directory) / "output"
            now = datetime(2026, 8, 13, 9, 30)
            try:
                app.ensure_quote_schema(conn)
                batch_id = app.preview_quote_batch_id(conn, now)
                target = output_dir / app.quote_output_filename("甲", "2026-08", batch_id)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"existing workbook")

                with self.assertRaises(app.QuoteCollisionError):
                    app.save_and_export_customer_quote(
                        conn, output_dir, "甲", [(2026, 8)], [confirmed_305_line()], "技師甲",
                        quote_date=date(2026, 8, 13), now=now,
                    )

                self.assertEqual(target.read_bytes(), b"existing workbook")
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM quote_batches").fetchone()[0], 0)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM quote_lines").fetchone()[0], 0)
            finally:
                conn.close()

    def test_atomic_quote_export_failure_rolls_back_database_and_removes_partial_file(self):
        with TemporaryDirectory() as directory:
            conn = sqlite3.connect(Path(directory) / "quote.db")
            conn.row_factory = sqlite3.Row
            output_dir = Path(directory) / "output"
            try:
                app.ensure_quote_schema(conn)

                def failing_exporter(target_dir, batch, lines):
                    target = Path(target_dir) / app.quote_output_filename(
                        batch.customer, batch.month_range, batch.id
                    )
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(b"partial workbook")
                    raise RuntimeError("forced export failure")

                with self.assertRaisesRegex(RuntimeError, "forced export failure"):
                    app.save_and_export_customer_quote(
                        conn, output_dir, "甲", [(2026, 8)], [confirmed_305_line()], "技師甲",
                        quote_date=date(2026, 8, 13),
                        now=datetime(2026, 8, 13, 9, 30),
                        exporters={"xlsx": failing_exporter},
                    )

                self.assertEqual(conn.execute("SELECT COUNT(*) FROM quote_batches").fetchone()[0], 0)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM quote_lines").fetchone()[0], 0)
                self.assertEqual(list(output_dir.glob("*.xlsx")), [])
            finally:
                conn.close()

    def test_atomic_quote_commit_failure_removes_workbook_and_rolls_back(self):
        with TemporaryDirectory() as directory:
            real_conn = sqlite3.connect(Path(directory) / "quote.db")
            real_conn.row_factory = sqlite3.Row
            output_dir = Path(directory) / "output"
            try:
                app.ensure_quote_schema(real_conn)

                class CommitFailingConnection:
                    def __init__(self, wrapped):
                        self.wrapped = wrapped

                    @property
                    def in_transaction(self):
                        return self.wrapped.in_transaction

                    def execute(self, *args, **kwargs):
                        return self.wrapped.execute(*args, **kwargs)

                    def commit(self):
                        raise sqlite3.OperationalError("forced commit failure")

                    def rollback(self):
                        return self.wrapped.rollback()

                with self.assertRaisesRegex(RuntimeError, "資料庫提交失敗"):
                    app.save_and_export_customer_quote(
                        CommitFailingConnection(real_conn),
                        output_dir, "甲", [(2026, 8)], [confirmed_305_line()], "技師甲",
                        quote_date=date(2026, 8, 13),
                        now=datetime(2026, 8, 13, 9, 30),
                        exporters={"xlsx": successful_excel_exporter},
                    )

                self.assertEqual(real_conn.execute("SELECT COUNT(*) FROM quote_batches").fetchone()[0], 0)
                self.assertEqual(real_conn.execute("SELECT COUNT(*) FROM quote_lines").fetchone()[0], 0)
                self.assertEqual(list(output_dir.glob("*.xlsx")), [])
            finally:
                real_conn.close()

    def test_save_quote_batch_rejects_mismatched_customer_without_writes(self):
        with TemporaryDirectory() as directory:
            conn = sqlite3.connect(Path(directory) / "quote.db")
            try:
                app.ensure_quote_schema(conn)
                mismatched = apply_manual_quote(confirmed_305_line(), note="乙客戶資料")
                mismatched = mismatched.__class__(
                    **{**mismatched.__dict__, "customer": "乙"}
                )

                with self.assertRaisesRegex(ValueError, "客戶"):
                    app.save_quote_batch(
                        conn, "甲", [(2026, 8)], [mismatched], "技師甲",
                        quote_date=date(2026, 8, 13), output_file="mismatch.xlsx",
                    )

                self.assertEqual(conn.execute("SELECT COUNT(*) FROM quote_batches").fetchone()[0], 0)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM quote_lines").fetchone()[0], 0)
            finally:
                conn.close()

    def test_save_quote_batch_rejects_all_excluded_lines_without_writes(self):
        with TemporaryDirectory() as directory:
            conn = sqlite3.connect(Path(directory) / "quote.db")
            try:
                app.ensure_quote_schema(conn)
                excluded = apply_manual_quote(confirmed_305_line(), included=False)

                with self.assertRaisesRegex(ValueError, "至少"):
                    app.save_quote_batch(
                        conn, "甲", [(2026, 8)], [excluded], "技師甲",
                        quote_date=date(2026, 8, 13), output_file="excluded.xlsx",
                    )

                self.assertEqual(conn.execute("SELECT COUNT(*) FROM quote_batches").fetchone()[0], 0)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM quote_lines").fetchone()[0], 0)
            finally:
                conn.close()

    def test_save_quote_batch_persists_only_included_lines(self):
        with TemporaryDirectory() as directory:
            conn = sqlite3.connect(Path(directory) / "quote.db")
            conn.row_factory = sqlite3.Row
            try:
                app.ensure_quote_schema(conn)
                excluded = confirmed_305_line().__class__(
                    **{
                        **confirmed_305_line().__dict__,
                        "blade_id": 2,
                        "brand_id": "4013",
                        "included": False,
                    }
                )

                batch = app.save_quote_batch(
                    conn, "甲", [(2026, 8)], [confirmed_305_line(), excluded], "技師甲",
                    quote_date=date(2026, 8, 13), output_file="included-only.xlsx",
                )

                stored = conn.execute(
                    "SELECT blade_id FROM quote_lines WHERE batch_id=?", (batch.id,)
                ).fetchall()
                self.assertEqual([row["blade_id"] for row in stored], [1])
                self.assertEqual(batch.subtotal, 540)
            finally:
                conn.close()

    def test_manual_only_repairs_require_a_visible_technician_note(self):
        blade = {
            "id": 9, "customer": "甲", "brand_id": "M-009", "od": "305",
            "thickness": "3.0", "teeth": "100", "grind": "是",
            "supp_teeth": "-", "supp_seats": "2", "fanban": "-", "steel": "是",
            "status": "in_progress", "raw_name": "305303100T(M-009)2P鋼面",
        }
        rules = {
            "305": app.PriceRule("PV-test", date(2026, 8, 13), 305, 305, 240, 150, 230)
        }

        labels = app.manual_only_repair_labels(blade)
        line = app.quote_line_from_blade(blade, rules)

        self.assertEqual(labels, ("補座 2座", "鋼面"))
        self.assertEqual(line.subtotal, 240)
        self.assertIn("待人工確認", app.quote_line_validation_error(line, labels))
        confirmed = app.quote_line_with_manual_confirmation(
            apply_manual_quote(line, note="補座與鋼面已由技師確認，另列處理"), labels
        )
        self.assertEqual(app.quote_line_validation_error(confirmed, labels), "")
        self.assertIn("人工確認（補座 2座、鋼面）", confirmed.note)

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
                    conn,
                    "甲",
                    [(2026, 8)],
                    [confirmed_305_line()],
                    "技師甲",
                    quote_date=date(2026, 8, 13),
                    output_file="甲_2026-08_維修報價.xlsx",
                )
                conn.execute("UPDATE price_rules SET tooth_price=999 WHERE od_min=305")
                conn.commit()

                self.assertEqual(read_line(conn, batch.id)["tooth_unit"], 150)
                self.assertEqual(
                    conn.execute(
                        "SELECT output_file FROM quote_batches WHERE id = ?", (batch.id,)
                    ).fetchone()["output_file"],
                    "甲_2026-08_維修報價.xlsx",
                )
            finally:
                conn.close()

    def test_saved_override_keeps_suggested_and_confirmed_price_snapshots(self):
        with TemporaryDirectory() as directory:
            conn = sqlite3.connect(Path(directory) / "quote.db")
            conn.row_factory = sqlite3.Row
            try:
                app.ensure_quote_schema(conn)
                blade = {
                    "id": 1, "customer": "甲", "brand_id": "4012", "od": "305",
                    "thickness": "3.0", "teeth": "100", "grind": "是",
                    "supp_teeth": "2", "fanban": "-",
                }
                suggested = build_quote_line(
                    blade, app.load_effective_price_rules(conn, date(2026, 8, 13))["305"]
                )
                confirmed = apply_manual_quote(suggested, tooth_qty=1, tooth_unit=120)

                batch = app.save_quote_batch(
                    conn, "甲", [(2026, 8)], [confirmed], "技師甲",
                    quote_date=date(2026, 8, 13), output_file="snapshot.xlsx",
                )
                conn.execute("UPDATE price_rules SET tooth_price=999 WHERE od_min=305")
                conn.commit()

                stored = read_line(conn, batch.id)
                self.assertEqual(stored["suggested_tooth_qty"], 2)
                self.assertEqual(stored["suggested_tooth_unit"], 150)
                self.assertEqual(stored["suggested_subtotal"], 540)
                self.assertEqual(stored["tooth_qty"], 1)
                self.assertEqual(stored["tooth_unit"], 120)
                self.assertEqual(stored["subtotal"], 360)
            finally:
                conn.close()

    def test_schema_migrates_existing_quote_lines_without_losing_rows(self):
        with TemporaryDirectory() as directory:
            conn = sqlite3.connect(Path(directory) / "quote.db")
            conn.row_factory = sqlite3.Row
            try:
                conn.execute("""CREATE TABLE quote_lines(
                    id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id TEXT NOT NULL, blade_id INTEGER NOT NULL,
                    display_order INTEGER NOT NULL, spec TEXT NOT NULL, brand_id TEXT NOT NULL,
                    source_grind TEXT NOT NULL, source_supp_teeth TEXT NOT NULL, source_fanban TEXT NOT NULL,
                    grinding_qty INTEGER NOT NULL, grinding_unit INTEGER NOT NULL,
                    tooth_qty INTEGER NOT NULL, tooth_unit INTEGER NOT NULL,
                    fanban_qty INTEGER NOT NULL, fanban_unit INTEGER NOT NULL,
                    subtotal INTEGER NOT NULL, note TEXT NOT NULL
                )""")
                conn.execute("""INSERT INTO quote_lines(
                    batch_id, blade_id, display_order, spec, brand_id,
                    source_grind, source_supp_teeth, source_fanban,
                    grinding_qty, grinding_unit, tooth_qty, tooth_unit,
                    fanban_qty, fanban_unit, subtotal, note
                ) VALUES ('舊批次', 7, 1, '305 x 3.0 x 100T', '4007',
                          '是', '2', '-', 1, 240, 2, 150, 0, 0, 540, '')""")
                conn.commit()

                app.ensure_quote_schema(conn)

                columns = {
                    row["name"] for row in conn.execute("PRAGMA table_info(quote_lines)")
                }
                self.assertTrue({
                    "suggested_grinding_qty", "suggested_grinding_unit",
                    "suggested_tooth_qty", "suggested_tooth_unit",
                    "suggested_fanban_qty", "suggested_fanban_unit", "suggested_subtotal",
                }.issubset(columns))
                self.assertEqual(
                    conn.execute("SELECT brand_id FROM quote_lines WHERE batch_id='舊批次'").fetchone()[0],
                    "4007",
                )
            finally:
                conn.close()

    def test_quote_batch_id_increments_for_the_same_day(self):
        with TemporaryDirectory() as directory:
            conn = sqlite3.connect(Path(directory) / "quote.db")
            conn.row_factory = sqlite3.Row
            try:
                app.ensure_quote_schema(conn)

                first = app.save_quote_batch(
                    conn, "甲", [(2026, 8)], [confirmed_305_line()], "技師甲",
                    quote_date=date(2026, 8, 13), output_file="first.xlsx",
                )
                second = app.save_quote_batch(
                    conn, "甲", [(2026, 8)], [confirmed_305_line()], "技師甲",
                    quote_date=date(2026, 8, 13), output_file="second.xlsx",
                )

                self.assertEqual(first.id[:-3], second.id[:-3])
                self.assertEqual(int(second.id[-3:]), int(first.id[-3:]) + 1)
                self.assertEqual(second.subtotal, 540)
            finally:
                conn.close()

    def test_previewed_batch_id_and_filename_are_saved_consistently(self):
        with TemporaryDirectory() as directory:
            conn = sqlite3.connect(Path(directory) / "quote.db")
            conn.row_factory = sqlite3.Row
            try:
                app.ensure_quote_schema(conn)
                now = datetime(2026, 8, 13, 9, 30)
                batch_id = app.preview_quote_batch_id(conn, now)
                filename = app.quote_output_filename("甲", "2026-08", batch_id)
                batch = app.save_quote_batch(
                    conn, "甲", [(2026, 8)], [confirmed_305_line()], "技師甲",
                    quote_date=date(2026, 8, 13), output_file=filename,
                    batch_id=batch_id, now=now,
                )

                self.assertEqual(batch.id, batch_id)
                self.assertEqual(batch.output_file, filename)
                self.assertIn(batch_id, filename)
                self.assertEqual(
                    app.preview_quote_batch_id(conn, now), "Q-260813-002"
                )
            finally:
                conn.close()

    def test_save_quote_batch_requires_effective_price_version(self):
        with TemporaryDirectory() as directory:
            conn = sqlite3.connect(Path(directory) / "quote.db")
            try:
                app.ensure_quote_schema(conn)

                with self.assertRaises(ValueError):
                    app.save_quote_batch(
                        conn, "甲", [(2026, 8)], [confirmed_305_line()], "技師甲",
                        quote_date=date(2026, 8, 12), output_file="before-effective.xlsx",
                    )
            finally:
                conn.close()

    def test_save_quote_batch_uses_effective_version_and_requires_output_file(self):
        with TemporaryDirectory() as directory:
            conn = sqlite3.connect(Path(directory) / "quote.db")
            conn.row_factory = sqlite3.Row
            try:
                app.ensure_quote_schema(conn)

                batch = app.save_quote_batch(
                    conn, "甲", [(2026, 8)], [confirmed_305_line()], "技師甲",
                    quote_date=date(2026, 8, 13), output_file="confirmed.xlsx",
                )

                self.assertEqual(batch.price_version_id, "PV-20260813")
                self.assertEqual(batch.output_file, "confirmed.xlsx")
                with self.assertRaises(ValueError):
                    app.save_quote_batch(
                        conn, "甲", [(2026, 8)], [confirmed_305_line()], "技師甲",
                        quote_date=date(2026, 8, 13), output_file="",
                    )
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
