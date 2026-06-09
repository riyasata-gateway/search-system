from functools import lru_cache
from typing import Dict, List, Optional, Tuple

from core.config import settings
from core.logging import get_logger
from processing.brand_match import text_mentions_brand

logger = get_logger(__name__)

SPACY_MODEL_MAP = {
    "fr": "fr_core_news_sm",
    "nl": "nl_core_news_sm",
    "en": "en_core_web_sm",
    "de": "de_core_news_sm",
}


@lru_cache(maxsize=4)
def _get_nlp(lang: str):
    import spacy
    model_name = SPACY_MODEL_MAP.get(lang, "en_core_web_sm")
    return spacy.load(model_name)


class PharmaEntityDictionary:
    """
    In-memory pharma entity dictionary loaded from DB.
    Maps aliases (including misspellings, local names, ingredients, country-specific names)
    to canonical entity IDs.
    Supports country-specific lookup for EU multi-country product name handling.
    """

    def __init__(self):
        self._brand_map: Dict[str, Tuple[int, float]] = {}
        self._product_map: Dict[str, Tuple[int, float]] = {}
        self._category_map: Dict[str, Tuple[int, float]] = {}
        self._loaded = False

    def load(self, db_sync_url: str):
        """Load all aliases from DB into memory. Call once at worker startup."""
        from sqlalchemy import create_engine, select
        from sqlalchemy.orm import Session
        from models.product import ProductAlias
        from models.brand import Brand

        engine = create_engine(db_sync_url)
        with Session(engine) as session:
            aliases = session.execute(select(ProductAlias)).scalars().all()
            for alias in aliases:
                key = alias.alias.lower().strip()
                confidence = 1.0 if alias.alias_type.value in ("brand", "generic") else 0.85
                self._product_map[key] = (alias.product_id, confidence)

            brands = session.execute(select(Brand)).scalars().all()
            for brand in brands:
                key = brand.name.lower().strip()
                self._brand_map[key] = (brand.id, 1.0)

        self._loaded = True
        logger.info(
            "pharma_dictionary_loaded",
            brands=len(self._brand_map),
            products=len(self._product_map),
        )

    def resolve_entities(
        self,
        text: str,
        lang: str = "en",
        country: Optional[str] = None,
    ) -> List[Dict]:
        """
        Find pharma entities in text. Returns list of:
        {entity_type, entity_id, matched_alias, confidence}
        """
        if not self._loaded:
            return []

        found = []
        text_lower = text.lower()

        # Word-boundary match (not raw substring): "roc" must not match "maroc",
        # "life" must not match "lifestyle". Short aliases are too collision-prone
        # to attribute a free-text mention and are skipped here.
        for alias, (entity_id, confidence) in self._brand_map.items():
            if text_mentions_brand(text_lower, [alias]):
                found.append({
                    "entity_type": "brand",
                    "entity_id": entity_id,
                    "matched_alias": alias,
                    "confidence": confidence,
                })

        for alias, (entity_id, confidence) in self._product_map.items():
            if text_mentions_brand(text_lower, [alias]):
                if not any(f["entity_type"] == "product" and f["entity_id"] == entity_id for f in found):
                    found.append({
                        "entity_type": "product",
                        "entity_id": entity_id,
                        "matched_alias": alias,
                        "confidence": confidence,
                    })

        return found


_dictionary: Optional[PharmaEntityDictionary] = None


def get_dictionary() -> PharmaEntityDictionary:
    global _dictionary
    if _dictionary is None:
        _dictionary = PharmaEntityDictionary()
        _dictionary.load(settings.DATABASE_SYNC_URL)
    return _dictionary


def resolve(text: str, lang: str = "en", country: Optional[str] = None) -> List[Dict]:
    return get_dictionary().resolve_entities(text, lang=lang, country=country)
