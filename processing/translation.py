"""Backwards-compat shim — translation is now handled by the LLM classifier
module (processing.llm_classifier.translate_to_english). The old Helsinki
opus-mt pipelines required ~250MB per language pair to be downloaded; the
LLM route is zero-install and handles short consumer text better.
"""
from typing import Optional

from processing.llm_classifier import translate_to_english as _llm_translate


def translate_to_english(text: str, src_lang: str) -> Optional[str]:
    return _llm_translate(text, src_lang)