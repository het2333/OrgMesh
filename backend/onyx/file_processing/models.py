from pydantic import BaseModel, Field


class PdfOcrSettings(BaseModel):
    enabled: bool = False
    max_pages: int = Field(default=20, ge=0, le=20)
    max_file_bytes: int = Field(default=50 * 1024 * 1024, ge=0, le=50 * 1024 * 1024)
    max_render_pixels: int = Field(default=8_000_000, ge=1, le=8_000_000)
    page_timeout_seconds: float = Field(default=15, gt=0, le=15)
    document_timeout_seconds: float = Field(default=90, gt=0, le=90)
    min_native_text_characters: int = Field(default=24, ge=0, le=100)
