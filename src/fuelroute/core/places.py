"""Normalisation of US place names, so different spellings of one town compare equal."""

from __future__ import annotations

import re
import unicodedata

__all__ = ["place_key"]

_EXPANSIONS = {
    "e": "east",
    "ft": "fort",
    "mt": "mount",
    "n": "north",
    "s": "south",
    "st": "saint",
    "ste": "sainte",
    "w": "west",
}
_SEPARATORS = re.compile(r"[-./'`,()]")
_NOT_ALPHANUMERIC = re.compile(r"[^a-z0-9 ]")


def place_key(name: str) -> str:
    """Return the lookup key for a place name.

    The key ignores case, accents, punctuation and spaces, and expands common
    abbreviations, so "St. Louis", "Saint Louis" and "SAINT LOUIS " share a key,
    as do "Mc Calla" and "McCalla".

    >>> place_key("E St. Louis")
    'eastsaintlouis'
    """
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    words = _NOT_ALPHANUMERIC.sub("", _SEPARATORS.sub(" ", ascii_name.lower())).split()
    return "".join(_EXPANSIONS.get(word, word) for word in words)
