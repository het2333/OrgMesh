import unicodedata

from pydantic import BaseModel, Field, field_validator


class GlossaryEntry(BaseModel):
    term: str = Field(min_length=1, max_length=80)
    expansions: list[str] = Field(min_length=1, max_length=5)

    @field_validator("term")
    @classmethod
    def validate_term(cls, value: str) -> str:
        return cls.validate_text(value)

    @field_validator("expansions")
    @classmethod
    def validate_expansions(cls, values: list[str]) -> list[str]:
        return [cls.validate_text(value) for value in values]

    @staticmethod
    def validate_text(value: str) -> str:
        value = value.strip()
        if not value or len(value) > 80:
            raise ValueError("Glossary text must contain 1 to 80 characters")
        if any(unicodedata.category(char).startswith("C") for char in value):
            raise ValueError("Glossary text must not contain control characters")
        return value


class ChineseRetrievalSettings(BaseModel):
    enabled: bool = True
    glossary: list[GlossaryEntry] = Field(default_factory=list, max_length=200)
    max_expansions: int = Field(default=8, ge=0, le=8)

    @field_validator("glossary")
    @classmethod
    def validate_unique_terms(cls, entries: list[GlossaryEntry]) -> list[GlossaryEntry]:
        terms = [
            unicodedata.normalize("NFKC", entry.term).casefold() for entry in entries
        ]
        if len(terms) != len(set(terms)):
            raise ValueError("Glossary terms must be unique")
        return entries
