"""Generate synthetic Chinese documents without external document data."""

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader, PdfWriter


def _native_pdf() -> bytes:
    lines = [
        "差旅报销制度：员工提交发票后，财务部门在五个工作日内审核。",
        "费用类型    金额上限",
        "交通费      500元",
        "住宿费      800元",
    ]
    operators = []
    for index, line in enumerate(lines):
        encoded = line.encode("utf-16-be").hex().upper()
        operators.append(f"BT /F1 16 Tf 50 {750 - index * 30} Td <{encoded}> Tj ET")
    stream = "\n".join(operators).encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 6 0 R >>",
        b"<< /Type /Font /Subtype /Type0 /BaseFont /STSong-Light /Encoding /UniGB-UCS2-H /DescendantFonts [5 0 R] >>",
        b"<< /Type /Font /Subtype /CIDFontType0 /BaseFont /STSong-Light /CIDSystemInfo << /Registry (Adobe) /Ordering (GB1) /Supplement 4 >> /DW 1000 >>",
        f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream",
    ]
    document = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(document))
        document.extend(f"{number} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref_offset = len(document)
    document.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        document.extend(f"{offset:010d} 00000 n \n".encode())
    document.extend(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode()
    )
    return bytes(document)


def generate_all(output_dir: Path, font_path: str) -> None:
    native_bytes = _native_pdf()
    (output_dir / "chinese_native.pdf").write_bytes(native_bytes)
    image = Image.new("RGB", (1500, 900), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(font_path, 56)
    for index, line in enumerate(
        ["员工报销申请", "请提供发票和费用明细", "财务审核需要五个工作日"]
    ):
        draw.text((90, 100 + index * 120), line, fill="black", font=font)
    scan_buffer = io.BytesIO()
    image.save(scan_buffer, format="PDF", resolution=150)
    scanned_bytes = scan_buffer.getvalue()
    (output_dir / "chinese_scanned.pdf").write_bytes(scanned_bytes)
    writer = PdfWriter()
    writer.append(PdfReader(io.BytesIO(native_bytes)))
    writer.append(PdfReader(io.BytesIO(scanned_bytes)))
    writer.write(output_dir / "chinese_mixed.pdf")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--font", required=True)
    parser.add_argument("--output", type=Path, default=Path(__file__).parent)
    args = parser.parse_args()
    generate_all(args.output, args.font)
