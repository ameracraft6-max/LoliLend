from __future__ import annotations

import unicodedata


_MOJIBAKE_MARKERS = ("Р", "С", "Ð", "Ñ", "Â")


def normalize_ai_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    repaired, changed = repair_mojibake_text(normalized)
    final_text = repaired if changed else normalized
    return unicodedata.normalize("NFC", final_text)


def repair_mojibake_text(text: str) -> tuple[str, bool]:
    source = str(text)
    if not _looks_like_mojibake(source):
        return source, False

    best_candidate = source
    best_score = _repair_score(source)

    for encoding in ("cp1251", "latin1"):
        try:
            candidate = source.encode(encoding).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        score = _repair_score(candidate)
        if score > best_score and _is_safe_candidate(source, candidate):
            best_candidate = candidate
            best_score = score

    if best_candidate == source:
        return source, False
    return best_candidate, True


def _looks_like_mojibake(text: str) -> bool:
    if len(text) < 4:
        return False
    marker_count = sum(text.count(marker) for marker in _MOJIBAKE_MARKERS)
    return marker_count >= 2


def _repair_score(text: str) -> int:
    cyrillic = sum(1 for char in text if _is_cyrillic(char))
    latin = sum(1 for char in text if "A" <= char <= "z")
    markers = sum(text.count(marker) for marker in _MOJIBAKE_MARKERS)
    replacement = text.count("\ufffd")
    return (cyrillic * 3) + latin - (markers * 4) - (replacement * 8)


def _is_safe_candidate(source: str, candidate: str) -> bool:
    if "\ufffd" in candidate:
        return False
    candidate_cyrillic = sum(1 for char in candidate if _is_cyrillic(char))
    source_markers = sum(source.count(marker) for marker in _MOJIBAKE_MARKERS)
    candidate_markers = sum(candidate.count(marker) for marker in _MOJIBAKE_MARKERS)
    return candidate_cyrillic >= 2 and candidate_markers <= max(0, source_markers // 3)


def _is_cyrillic(char: str) -> bool:
    return "\u0400" <= char <= "\u04ff"
