from functools import lru_cache
from typing import Optional

from core.config import settings
from core.logging import get_logger

logger = get_logger(__name__)

SUPPORTED_LANG_SET = set(settings.SUPPORTED_LANGUAGES)


@lru_cache(maxsize=1)
def _get_detector():
    from lingua import Language, LanguageDetectorBuilder
    languages = [
        Language.FRENCH,
        Language.DUTCH,
        Language.ENGLISH,
        Language.GERMAN,
        Language.SPANISH,
        Language.ITALIAN,
        Language.PORTUGUESE,
    ]
    return LanguageDetectorBuilder.from_languages(*languages).build()


def detect_language(text: str) -> Optional[str]:
    """
    Detect language using lingua-py (more accurate than langdetect for short EU texts).
    Returns ISO 639-1 code (fr, nl, en, de) or None if uncertain.
    """
    if not text or len(text.strip()) < 10:
        return None
    try:
        detector = _get_detector()
        result = detector.detect_language_of(text)
        if result is None:
            return None
        lang_map = {
            "FRENCH": "fr",
            "DUTCH": "nl",
            "ENGLISH": "en",
            "GERMAN": "de",
            "SPANISH": "es",
            "ITALIAN": "it",
            "PORTUGUESE": "pt",
        }
        lang_code = lang_map.get(result.name)
        return lang_code
    except Exception as exc:
        logger.warning("language_detection_failed", error=str(exc))
        return None


def is_supported_language(lang_code: Optional[str]) -> bool:
    return lang_code in SUPPORTED_LANG_SET
