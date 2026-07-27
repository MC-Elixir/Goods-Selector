"""Shared brand-token matching and removal for supplier-facing text."""
from __future__ import annotations

import re


def brand_tokens(brand: str, excluded: list[str]) -> list[str]:
    """Return stable full-name and word tokens for brands and model aliases."""
    values = [*excluded, brand]
    tokens: list[str] = []
    for value in values:
        clean = value.strip()
        if clean:
            tokens.append(clean)
            tokens.extend(part for part in re.split(r"[^\w]+", clean) if len(part) >= 2)
    return list(dict.fromkeys(token.casefold() for token in tokens))


def _token_pattern(token: str) -> str:
    escaped = re.escape(token)
    if re.fullmatch(r"[\x00-\x7f]+", token) and any(char.isalnum() for char in token):
        return rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])"
    return escaped


def contains_brand_term(text: str, tokens: list[str]) -> bool:
    """Whether text contains a token under Latin-boundary/CJK-substring rules."""
    return any(
        re.search(_token_pattern(token), text, flags=re.IGNORECASE)
        for token in tokens
    )


def remove_brand_terms(text: str, tokens: list[str]) -> str:
    """Remove tokens without deleting short Latin tokens inside ordinary words."""
    cleaned = text
    for token in sorted(tokens, key=len, reverse=True):
        cleaned = re.sub(
            _token_pattern(token), " ", cleaned, flags=re.IGNORECASE
        )
    return cleaned
