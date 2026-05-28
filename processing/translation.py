from functools import lru_cache
from typing import Optional

from core.config import settings
from core.logging import get_logger

logger = get_logger(__name__)

TRANSLATION_PAIRS = {
    ("fr", "en"): f"{settings.TRANSLATION_MODEL_PREFIX}-fr-en",
    ("nl", "en"): f"{settings.TRANSLATION_MODEL_PREFIX}-nl-en",
    ("de", "en"): f"{settings.TRANSLATION_MODEL_PREFIX}-de-en",
    ("es", "en"): f"{settings.TRANSLATION_MODEL_PREFIX}-es-en",
    ("it", "en"): f"{settings.TRANSLATION_MODEL_PREFIX}-it-en",
}


@lru_cache(maxsize=10)
def _get_pipeline(src_lang: str, tgt_lang: str = "en"):
    from transformers import pipeline
    model_name = TRANSLATION_PAIRS.get((src_lang, tgt_lang))
    if not model_name:
        return None
    return pipeline("translation", model=model_name, device=-1)


def translate_to_english(text: str, src_lang: str) -> Optional[str]:
    """
    Translate text from src_lang to English using Helsinki-NLP opus-mt models.
    Used before NLP classification to normalise multilingual input.
    Returns None if translation unavailable or fails.
    """
    if src_lang == "en":
        return text
    if not text or len(text.strip()) < 5:
        return text
    try:
        pipe = _get_pipeline(src_lang, "en")
        if pipe is None:
            logger.debug("translation_not_available", src_lang=src_lang)
            return None
        result = pipe(text[:512], max_length=512)
        if result and isinstance(result, list):
            return result[0].get("translation_text")
        return None
    except Exception as exc:
        logger.warning("translation_failed", src_lang=src_lang, error=str(exc))
        return None
