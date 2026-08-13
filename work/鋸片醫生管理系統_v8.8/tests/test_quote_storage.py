import importlib.util
import os
import sqlite3
import sys
import unittest
from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


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
    return app.publish_quote_output(output, lambda temporary: temporary.write_bytes(b"xlsx"))


class QuoteStorageTests(unittest.TestCase):
    def test_quote_confirmation_size_fits_1147_pixel_wide_screen(self):
        width, height = app.quote_confirmation_dialog_size(1147, 768)

        self.assertEqual(width, 1123)
        self.assertEqual(height, 650)

    def test_open_failure_reports_generated_files_without_raising(self):
        outputs = {
            "xlsx": Path("客戶維修明細_甲.xlsx"),
            "pdf": Path("客戶維修明細_甲.pdf"),
        }

        def failing_opener(_path):
            raise OSError("no associated application")

        warning = app.open_generated_quote_output(
            outputs, ("xlsx", "pdf"), opener=failing_opener
        )

        self.assertIn("已成功產生", warning)
        self.assertIn("客戶維修明細_甲.xlsx", warning)
        self.assertIn("客戶維修明細_甲.pdf", warning)
        self.assertIn("無法自動開啟", warning)

    def test_primary_open_format_prefers_pdf_only_for_dual_output(self):
        self.assertEqual(app.quote_primary_open_format(("xlsx",)), "xlsx")
        self.assertEqual(app.quote_primary_open_format(("pdf",)), "pdf")
        self.assertEqual(app.quote_primary_open_format(("xlsx", "pdf")), "pdf")

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
                    return app.publish_quote_output(
                        output, lambda temporary: temporary.write_bytes(b"pdf")
                    )

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
                    return app.publish_quote_output(
                        output, lambda temporary: temporary.write_bytes(b"xlsx")
                    )

                def failing_pdf(target_dir, batch, lines):
                    output = Path(target_dir) / app.quote_output_filename(
                        batch.customer, batch.month_range, batch.id, "pdf"
                    )
                    def write_partial_pdf(temporary):
                        temporary.write_bytes(b"partial pdf")
                        raise RuntimeError("forced PDF export failure")
                    return app.publish_quote_output(output, write_partial_pdf)

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

    def test_cleanup_failure_raises_warning_with_remaining_path_after_rollback(self):
        with TemporaryDirectory() as directory:
            conn = sqlite3.connect(Path(directory) / "quote.db")
            conn.row_factory = sqlite3.Row
            output_dir = Path(directory) / "output"
            fixed_now = datetime(2026, 8, 13, 9, 30)
            try:
                app.ensure_quote_schema(conn)

                def failing_pdf(_target_dir, _batch, _lines):
                    raise RuntimeError("original PDF export failure")

                with patch.object(app, "_delete_published_quote_output", return_value=False):
                    with self.assertRaises(app.QuoteRollbackWarning) as raised:
                        app.save_and_export_customer_quote(
                            conn,
                            output_dir,
                            "甲",
                            [(2026, 8)],
                            [confirmed_305_line()],
                            "技師甲",
                            quote_date=date(2026, 8, 13),
                            output_formats=("xlsx", "pdf"),
                            exporters={
                                "xlsx": successful_excel_exporter,
                                "pdf": failing_pdf,
                            },
                            now=fixed_now,
                        )

                remaining = output_dir / app.quote_output_filename(
                    "甲", "2026-08", "Q-260813-001", "xlsx"
                )
                self.assertEqual(raised.exception.remaining_paths, (remaining,))
                self.assertIsInstance(raised.exception.__cause__, RuntimeError)
                self.assertIn("original PDF export failure", str(raised.exception.__cause__))
                self.assertIn(str(remaining), str(raised.exception))
                self.assertEqual(count_batches(conn), 0)
                self.assertFalse(conn.in_transaction)
                self.assertEqual(remaining.read_bytes(), b"xlsx")
            finally:
                conn.close()

    def test_collision_created_during_export_is_preserved(self):
        with TemporaryDirectory() as directory:
            conn = sqlite3.connect(Path(directory) / "quote.db")
            conn.row_factory = sqlite3.Row
            output_dir = Path(directory) / "output"
            fixed_now = datetime(2026, 8, 13, 9, 30)
            try:
                app.ensure_quote_schema(conn)

                def exporter_with_external_collision(target_dir, batch, lines):
                    target = Path(target_dir) / app.quote_output_filename(
                        batch.customer, batch.month_range, batch.id, "xlsx"
                    )
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open("xb") as collision_file:
                        collision_file.write(b"external workbook")
                    raise RuntimeError("external exporter stopped")

                with self.assertRaisesRegex(RuntimeError, "external exporter stopped"):
                    app.save_and_export_customer_quote(
                        conn, output_dir, "甲", [(2026, 8)], [confirmed_305_line()], "技師甲",
                        quote_date=date(2026, 8, 13), now=fixed_now,
                        exporters={"xlsx": exporter_with_external_collision},
                    )

                target = output_dir / app.quote_output_filename("甲", "2026-08", "Q-260813-001")
                self.assertEqual(target.read_bytes(), b"external workbook")
                self.assertEqual(count_batches(conn), 0)
            finally:
                conn.close()

    def test_replacement_after_successful_publish_is_preserved_on_later_failure(self):
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
                    return app.publish_quote_output(
                        output, lambda temporary: temporary.write_bytes(b"transaction workbook")
                    )

                def failing_pdf_after_external_replacement(target_dir, batch, lines):
                    excel_target = Path(target_dir) / app.quote_output_filename(
                        batch.customer, batch.month_range, batch.id, "xlsx"
                    )
                    excel_target.unlink()
                    excel_target.write_bytes(b"external replacement")
                    pdf_target = Path(target_dir) / app.quote_output_filename(
                        batch.customer, batch.month_range, batch.id, "pdf"
                    )
                    def fail_after_temporary_write(temporary):
                        temporary.write_bytes(b"partial pdf")
                        raise RuntimeError("forced PDF failure after replacement")
                    return app.publish_quote_output(pdf_target, fail_after_temporary_write)

                with self.assertRaises(app.QuoteRollbackWarning) as raised:
                    app.save_and_export_customer_quote(
                        conn, output_dir, "甲", [(2026, 8)], [confirmed_305_line()], "技師甲",
                        quote_date=date(2026, 8, 13), output_formats=("xlsx", "pdf"),
                        exporters={
                            "xlsx": successful_excel,
                            "pdf": failing_pdf_after_external_replacement,
                        },
                        now=fixed_now,
                    )

                target = output_dir / app.quote_output_filename("甲", "2026-08", "Q-260813-001")
                self.assertEqual(raised.exception.remaining_paths, (target,))
                self.assertIn(
                    "forced PDF failure after replacement", str(raised.exception.__cause__)
                )
                self.assertEqual(target.read_bytes(), b"external replacement")
                self.assertEqual(count_batches(conn), 0)
            finally:
                conn.close()

    @unittest.skipUnless(os.name == "nt", "Windows 檔案分享鎖定測試")
    def test_windows_file_identity_uses_volume_and_all_16_file_id_bytes(self):
        with TemporaryDirectory() as directory:
            target = Path(directory) / "quote.xlsx"
            hard_link = Path(directory) / "quote-link.xlsx"
            target.write_bytes(b"transaction workbook")
            os.link(target, hard_link)

            target_identity = app._windows_file_identity_from_path(target)
            hard_link_identity = app._windows_file_identity_from_path(hard_link)

            self.assertEqual(target_identity, hard_link_identity)
            self.assertIsInstance(target_identity[0], int)
            self.assertIsInstance(target_identity[1], bytes)
            self.assertEqual(len(target_identity[1]), 16)

            changed_last_byte = target_identity[1][:-1] + bytes(
                [target_identity[1][-1] ^ 0xFF]
            )
            wrong_identity = app.PublishedQuoteOutput(
                target, (target_identity[0], changed_last_byte)
            )
            self.assertFalse(app._delete_published_quote_output(wrong_identity))
            self.assertEqual(target.read_bytes(), b"transaction workbook")

    @unittest.skipUnless(os.name == "nt", "Windows 檔案分享鎖定測試")
    def test_windows_cleanup_handle_blocks_replacement_after_identity_check(self):
        with TemporaryDirectory() as directory:
            target = Path(directory) / "quote.xlsx"
            published = app.publish_quote_output(
                target, lambda temporary: temporary.write_bytes(b"transaction workbook")
            )
            handle = app._open_windows_published_output_for_cleanup(published)
            try:
                self.assertIsNotNone(handle)
                with self.assertRaises(PermissionError):
                    target.unlink()
            finally:
                if handle is not None:
                    app._close_windows_handle(handle)
            target.unlink()

    @unittest.skipUnless(os.name == "nt", "Windows 檔案分享鎖定測試")
    def test_cleanup_sharing_violation_warns_with_original_export_failure_as_cause(self):
        with TemporaryDirectory() as directory:
            conn = sqlite3.connect(Path(directory) / "quote.db")
            conn.row_factory = sqlite3.Row
            output_dir = Path(directory) / "output"
            fixed_now = datetime(2026, 8, 13, 9, 30)
            blocking_handles = []
            try:
                app.ensure_quote_schema(conn)

                def failing_pdf_with_locked_excel(target_dir, batch, lines):
                    excel_target = Path(target_dir) / app.quote_output_filename(
                        batch.customer, batch.month_range, batch.id, "xlsx"
                    )
                    blocking_handles.append(app._open_windows_file_handle(
                        excel_target,
                        access=0x80000000,
                        share_mode=0x00000001 | 0x00000002,
                    ))
                    raise RuntimeError("original PDF export failure")

                with self.assertRaises(app.QuoteRollbackWarning) as raised:
                    app.save_and_export_customer_quote(
                        conn, output_dir, "甲", [(2026, 8)], [confirmed_305_line()], "技師甲",
                        quote_date=date(2026, 8, 13), output_formats=("xlsx", "pdf"),
                        exporters={
                            "xlsx": successful_excel_exporter,
                            "pdf": failing_pdf_with_locked_excel,
                        },
                        now=fixed_now,
                    )

                self.assertEqual(count_batches(conn), 0)
                for handle in blocking_handles:
                    app._close_windows_handle(handle)
                blocking_handles.clear()
                excel_target = output_dir / app.quote_output_filename(
                    "甲", "2026-08", "Q-260813-001", "xlsx"
                )
                self.assertEqual(raised.exception.remaining_paths, (excel_target,))
                self.assertIn("original PDF export failure", str(raised.exception.__cause__))
                self.assertEqual(excel_target.read_bytes(), b"xlsx")
            finally:
                for handle in blocking_handles:
                    app._close_windows_handle(handle)
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
                    def write_partial_workbook(temporary):
                        temporary.write_bytes(b"partial workbook")
                        raise RuntimeError("forced export failure")
                    return app.publish_quote_output(target, write_partial_workbook)

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
