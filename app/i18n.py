"""Textos da interface em locales/<idioma>.json."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .config import LOCALES_DIR

FALLBACK = "pt-BR"


def available_languages(locales_dir: Path = LOCALES_DIR) -> list[str]:
    return sorted(p.stem for p in locales_dir.glob("*.json"))


@lru_cache(maxsize=8)
def load_locale(lang: str) -> dict[str, str]:
    base = json.loads((LOCALES_DIR / f"{FALLBACK}.json").read_text(encoding="utf-8"))
    path = LOCALES_DIR / f"{lang}.json"
    if lang != FALLBACK and path.exists():
        base.update(json.loads(path.read_text(encoding="utf-8")))
    return base


def t(lang: str, key: str, **kwargs) -> str:
    text = load_locale(lang).get(key, key)
    try:
        return text.format(**kwargs) if kwargs else text
    except (KeyError, IndexError):
        return text
