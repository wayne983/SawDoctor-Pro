import importlib.util
import sqlite3
import sys
import unittest
from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from pypdf import PdfReader


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

spec = importlib.util.spec_from_file_location("sawdoctor_app", PROJECT_ROOT / "鋸片醫生.py")
app = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(app)

from quote_domain import QuoteLineDraft


def batch(customer="甲"):
    return app.QuoteBatch(
        id="Q-260813-001",
        customer=customer,
        month_range="2026-08",
        created_at=datetime(2026, 8, 13, 9, 30).isoformat(),
        created_by="測試人員",
        price_version_id="PV-20260813",
        subtotal=780,
        output_file="",
    )


def confirmed_line(index, *, customer="甲", note=""):
    is_first = index == 0
    return QuoteLineDraft(
        blade_id=4012 + index,
        customer=customer,
        brand_id=str(4012 + index),
        od="305",
        thickness="3.0",
        teeth="100",
        spec="305 x 3.0 x 100T",
        source_grind="是",
        source_supp_teeth="2",
        source_fanban="是",
        grinding_qty=1,
        grinding_unit=240,
        tooth_qty=0,
        tooth_unit=0,
        fanban_qty=1 if is_first else 0,
        fanban_unit=300 if is_first else 0,
        note=note or ("補座與鋼面已由技師人工確認" if is_first else "一般研磨"),
    )


def two_confirmed_lines():
    return [confirmed_line(0), confirmed_line(1)]


def many_confirmed_lines(count):
    return [
        confirmed_line(
            index,
            note=f"第 {index + 1} 片人工確認：補座、鋼面及特殊處理內容均保留於備註。",
        )
        for index in range(count)
    ]


def extract_pdf_text(path):
    return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)


def extract_pdf_text_page(path, page_number):
    return PdfReader(path).pages[page_number - 1].extract_text() or ""


def pdf_page_count(path):
    return len(PdfReader(path).pages)


class QuotePdfTests(unittest.TestCase):
    def test_production_coordinator_uses_default_pdf_exporter_and_commits(self):
        with TemporaryDirectory() as directory:
            conn = sqlite3.connect(Path(directory) / "quote.db")
            conn.row_factory = sqlite3.Row
            output_dir = Path(directory) / "output"
            try:
                app.ensure_quote_schema(conn)

                saved_batch, outputs = app.save_and_export_customer_quote(
                    conn,
                    output_dir,
                    "甲",
                    [(2026, 8)],
                    [confirmed_line(0)],
                    "測試人員",
                    quote_date=date(2026, 8, 13),
                    output_formats=("pdf",),
                    now=datetime(2026, 8, 13, 9, 30),
                )

                output = outputs["pdf"]
                self.assertEqual(output.suffix, ".pdf")
                self.assertGreaterEqual(len(PdfReader(output).pages), 1)
                self.assertEqual(
                    tuple(conn.execute(
                        "SELECT format, filename FROM quote_output_files WHERE batch_id = ?",
                        (saved_batch.id,),
                    ).fetchone()),
                    ("pdf", output.name),
                )
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM quote_batches").fetchone()[0], 1
                )
                self.assertFalse(conn.in_transaction)
            finally:
                conn.close()

    def test_pdf_keeps_every_blade_and_untaxed_total(self):
        with TemporaryDirectory() as directory:
            output = app.export_customer_quote_pdf(
                Path(directory), batch(), two_confirmed_lines()
            )
            text = extract_pdf_text(output.path)

            self.assertIsInstance(output, app.PublishedQuoteOutput)
            self.assertIn("鋸片醫生", text)
            self.assertIn("客戶：甲", text)
            self.assertIn("4012", text)
            self.assertIn("4013", text)
            self.assertIn("未稅總計", text)
            self.assertIn("780", text)

    def test_pdf_repeats_table_header_on_second_page(self):
        with TemporaryDirectory() as directory:
            output = app.export_customer_quote_pdf(
                Path(directory), batch(), many_confirmed_lines(80)
            )

            self.assertGreaterEqual(pdf_page_count(output.path), 2)
            self.assertIn("項次", extract_pdf_text_page(output.path, 2))

    def test_pdf_rejects_mismatched_customer_without_creating_output_directory(self):
        with TemporaryDirectory() as directory:
            output_dir = Path(directory) / "quote-output"

            with self.assertRaisesRegex(ValueError, "客戶"):
                app.export_customer_quote_pdf(
                    output_dir, batch(), [confirmed_line(0, customer="乙")]
                )

            self.assertFalse(output_dir.exists())

    def test_pdf_preserves_manual_confirmation_text_in_notes(self):
        with TemporaryDirectory() as directory:
            output = app.export_customer_quote_pdf(
                Path(directory), batch(), [confirmed_line(0)]
            )

            self.assertIn("補座與鋼面已由技師人工確認", extract_pdf_text(output.path))


if __name__ == "__main__":
    unittest.main()
