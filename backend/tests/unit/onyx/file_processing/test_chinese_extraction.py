from io import BytesIO
from pathlib import Path
from typing import cast

import openpyxl
from openpyxl.worksheet.worksheet import Worksheet

from onyx.file_processing.extract_file_text import read_pdf_file, xlsx_to_text
from onyx.file_processing.pdf_ocr import normalize_pdf_text

FIXTURES = Path(__file__).parent / "fixtures"


def test_native_chinese_pdf_preserves_paragraph_and_table_text() -> None:
    text, _, _ = read_pdf_file(
        BytesIO((FIXTURES / "chinese_native.pdf").read_bytes()), isolate_pdfium=False
    )
    for expected in [
        "差旅报销制度",
        "五个工作日",
        "费用类型",
        "交通费",
        "500元",
        "住宿费",
        "800元",
    ]:
        assert expected in text


def test_chinese_xlsx_preserves_rows_headers_and_amounts() -> None:
    workbook = openpyxl.Workbook()
    sheet = cast(Worksheet, workbook.active)
    sheet.title = "费用明细"
    sheet.append(["费用类型", "金额上限"])
    sheet.append(["交通费", "500元"])
    sheet.append(["住宿费", "800元"])
    file = BytesIO()
    workbook.save(file)
    file.seek(0)
    text = xlsx_to_text(file)
    assert "费用类型,金额上限" in text
    assert "交通费,500元" in text
    assert "住宿费,800元" in text


def test_pdf_text_normalization_preserves_table_spacing() -> None:
    assert (
        normalize_pdf_text("报销\x00制度\r\n交通费\t500元\r\n\r\n")
        == "报销制度\n交通费\t500元"
    )


def test_ocr_byte_limit_preserves_native_text() -> None:
    from unittest.mock import patch

    with patch.dict(
        "os.environ", {"PDF_OCR_ENABLED": "true", "PDF_OCR_MAX_FILE_BYTES": "0"}
    ):
        text, _, _ = read_pdf_file(
            BytesIO((FIXTURES / "chinese_mixed.pdf").read_bytes()), isolate_pdfium=False
        )
    assert "差旅报销制度" in text
    assert "500元" in text
    assert "员工报销申请" not in text


def test_real_pdf_pages_choose_ocr_only_for_low_text_images() -> None:
    import pypdfium2 as pdfium

    from onyx.file_processing.models import PdfOcrSettings
    from onyx.file_processing.pdf_ocr import page_needs_ocr

    settings = PdfOcrSettings(enabled=True)
    pdf = pdfium.PdfDocument((FIXTURES / "chinese_mixed.pdf").read_bytes())
    try:
        for index, page in enumerate(pdf):
            try:
                text_page = page.get_textpage()
                try:
                    text = text_page.get_text_range()
                finally:
                    text_page.close()
                assert page_needs_ocr(page, text, settings) == (index == 1)
            finally:
                page.close()
    finally:
        pdf.close()
