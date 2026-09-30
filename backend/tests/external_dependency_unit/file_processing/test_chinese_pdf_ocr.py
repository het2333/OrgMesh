from io import BytesIO
from pathlib import Path

import pytest

from onyx.file_processing.extract_file_text import read_pdf_file

FIXTURES = Path(__file__).parents[2] / "unit/onyx/file_processing/fixtures"


@pytest.mark.parametrize("name", ["chinese_scanned.pdf", "chinese_mixed.pdf"])
def test_local_chinese_ocr_extracts_real_scan(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PDF_OCR_ENABLED", "true")
    text, _, _ = read_pdf_file(
        BytesIO((FIXTURES / name).read_bytes()), isolate_pdfium=False
    )
    assert "员工报销申请" in text
    assert "请提供发票" in text
    assert "财务审核需要五个工作日" in text
    if name == "chinese_mixed.pdf":
        assert "差旅报销制度" in text
        assert "500元" in text


def test_ocr_page_budget_preserves_native_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PDF_OCR_ENABLED", "true")
    monkeypatch.setenv("PDF_OCR_MAX_PAGES", "0")
    text, _, _ = read_pdf_file(
        BytesIO((FIXTURES / "chinese_mixed.pdf").read_bytes()), isolate_pdfium=False
    )
    assert "差旅报销制度" in text
    assert "500元" in text
    assert "员工报销申请" not in text


def test_scanned_chinese_pdf_ocr_in_default_isolated_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PDF_OCR_ENABLED", "true")
    text, _, _ = read_pdf_file(BytesIO((FIXTURES / "chinese_scanned.pdf").read_bytes()))
    assert "员工报销申请" in text
    assert "请提供发票" in text
    assert "财务审核需要五个工作日" in text
