import io
import math
import os
import re
import subprocess
import time
import unicodedata
from typing import TYPE_CHECKING

from onyx.file_processing.models import PdfOcrSettings

if TYPE_CHECKING:
    from pypdfium2 import PdfPage

OCR_LANGUAGES = "chi_sim+eng"
OCR_DPI = 200


def load_pdf_ocr_settings() -> PdfOcrSettings:
    return PdfOcrSettings(
        enabled=os.environ.get("PDF_OCR_ENABLED", "false").lower() == "true",
        max_pages=min(20, max(0, int(os.environ.get("PDF_OCR_MAX_PAGES", "20")))),
        max_file_bytes=min(
            50 * 1024 * 1024,
            max(
                0, int(os.environ.get("PDF_OCR_MAX_FILE_BYTES", str(50 * 1024 * 1024)))
            ),
        ),
        max_render_pixels=min(
            8_000_000,
            max(1, int(os.environ.get("PDF_OCR_MAX_RENDER_PIXELS", "8000000"))),
        ),
        page_timeout_seconds=min(
            15, float(os.environ.get("PDF_OCR_PAGE_TIMEOUT_SECONDS", "15"))
        ),
        document_timeout_seconds=min(
            90, float(os.environ.get("PDF_OCR_DOCUMENT_TIMEOUT_SECONDS", "90"))
        ),
    )


def normalize_pdf_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    text = "".join(
        char
        for char in text
        if char in "\n\t" or not unicodedata.category(char).startswith("C")
    )
    # Tesseract can place one space between Chinese characters. Keep table gaps.
    text = re.sub(r"(?<=[\u3400-\u9fff]) (?=[\u3400-\u9fff])", "", text)
    return text.strip()


def page_needs_ocr(page: "PdfPage", native_text: str, settings: PdfOcrSettings) -> bool:
    from pypdfium2 import raw

    text_characters = sum(char.isalnum() for char in native_text)
    if text_characters >= settings.min_native_text_characters:
        return False
    return next(page.get_objects(filter=[raw.FPDF_PAGEOBJ_IMAGE]), None) is not None


def ocr_pdf_page(
    page: "PdfPage", settings: PdfOcrSettings, remaining_seconds: float
) -> str:
    start = time.monotonic()
    deadline = start + min(settings.page_timeout_seconds, remaining_seconds)
    width, height = page.get_size()
    if width <= 0 or height <= 0:
        return ""
    scale = min(OCR_DPI / 72, math.sqrt(settings.max_render_pixels / (width * height)))
    while (
        math.ceil(width * scale) * math.ceil(height * scale)
        > settings.max_render_pixels
    ):
        scale *= 0.99
    bitmap = page.render(scale=scale)
    try:
        image = bitmap.to_pil()
        try:
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
        finally:
            image.close()
    finally:
        bitmap.close()
    best_text = ""
    image_bytes = buffer.getvalue()
    # Automatic layout can miss short Chinese blocks. Retry within the same deadline.
    for segmentation_mode in (3, 6):
        remaining_seconds = deadline - time.monotonic()
        if remaining_seconds <= 0:
            break
        try:
            result = subprocess.run(
                [
                    "tesseract",
                    "stdin",
                    "stdout",
                    "-l",
                    OCR_LANGUAGES,
                    "--dpi",
                    str(OCR_DPI),
                    "--psm",
                    str(segmentation_mode),
                ],
                input=image_bytes,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
                timeout=remaining_seconds,
            )
        except subprocess.TimeoutExpired:
            if best_text:
                return best_text
            raise
        text = normalize_pdf_text(result.stdout.decode("utf-8", errors="replace"))
        if len(text) > len(best_text):
            best_text = text
        if (
            sum(char.isalnum() for char in best_text)
            >= settings.min_native_text_characters
        ):
            break
    return best_text


def ensure_ocr_languages(timeout_seconds: float) -> None:
    result = subprocess.run(
        ["tesseract", "--list-langs"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
        timeout=timeout_seconds,
    )
    languages = set(result.stdout.decode("utf-8", errors="replace").splitlines())
    if not {"chi_sim", "eng"}.issubset(languages):
        raise RuntimeError(
            "Local PDF OCR requires Tesseract chi_sim and eng language data"
        )


def merge_native_and_ocr_text(native_text: str, ocr_text: str) -> str:
    if not native_text:
        return ocr_text
    native_lines = {line.strip() for line in native_text.splitlines() if line.strip()}
    new_lines = [
        line for line in ocr_text.splitlines() if line.strip() not in native_lines
    ]
    return "\n".join([native_text, *new_lines])
