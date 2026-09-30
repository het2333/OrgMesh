import re
import unicodedata
from collections.abc import Iterator

from onyx.server.manage.chinese_retrieval.models import ChineseRetrievalSettings

MAX_EXPANSION_CHARACTERS = 256
MAX_EXPANSION_TERMS = 8
MAX_QUERY_MATCH_CHARACTERS = 4096


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


def _is_identifier_character(char: str) -> bool:
    # Chinese words can directly border a Latin abbreviation.
    code_point = ord(char)
    is_chinese = 0x3400 <= code_point <= 0x9FFF or 0x20000 <= code_point <= 0x323AF
    return char == "_" or (char.isalnum() and not is_chinese)


def _matching_spans(query: str, term: str) -> Iterator[tuple[int, int]]:
    for match in re.finditer(re.escape(term), query):
        start, end = match.span()
        if (
            _is_identifier_character(term[0])
            and start > 0
            and _is_identifier_character(query[start - 1])
        ) or (
            _is_identifier_character(term[-1])
            and end < len(query)
            and _is_identifier_character(query[end])
        ):
            continue
        yield start, end


def expand_chinese_query(query: str, settings: ChineseRetrievalSettings) -> str:
    """Append bounded glossary terms without replacing the user's query."""
    max_expansions = max(0, min(MAX_EXPANSION_TERMS, settings.max_expansions))
    if (
        not settings.enabled
        or not max_expansions
        or not settings.glossary
        or len(query) > MAX_QUERY_MATCH_CHARACTERS
    ):
        return query

    normalized_query = _normalize(query)
    if len(normalized_query) > MAX_QUERY_MATCH_CHARACTERS:
        return query
    candidates = [
        (start, end, entry_index)
        for entry_index, entry in enumerate(settings.glossary)
        for start, end in _matching_spans(normalized_query, _normalize(entry.term))
    ]
    selected_spans: list[tuple[int, int]] = []
    matched_entries: set[int] = set()
    for start, end, entry_index in sorted(
        candidates, key=lambda match: (-(match[1] - match[0]), match[0], match[2])
    ):
        if any(
            start < other_end and end > other_start
            for other_start, other_end in selected_spans
        ):
            continue
        selected_spans.append((start, end))
        matched_entries.add(entry_index)

    expansions: list[str] = []
    seen: set[str] = set()
    added_characters = 0
    for entry_index, entry in enumerate(settings.glossary):
        if entry_index not in matched_entries:
            continue
        for expansion in entry.expansions:
            normalized_expansion = _normalize(expansion)
            if (
                normalized_expansion in seen
                or next(_matching_spans(normalized_query, normalized_expansion), None)
                is not None
            ):
                continue
            seen.add(normalized_expansion)
            added_length = len(expansion) + 1
            if added_characters + added_length > MAX_EXPANSION_CHARACTERS:
                continue
            expansions.append(expansion)
            added_characters += added_length
            if len(expansions) >= max_expansions:
                return query + " " + " ".join(expansions)
    return query + " " + " ".join(expansions) if expansions else query
