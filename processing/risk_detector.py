import re
from dataclasses import dataclass
from typing import List, Optional

from core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class RiskResult:
    risk_type: str
    is_adverse_event_candidate: bool
    is_prescription_promotion: bool
    confidence: float
    matched_patterns: List[str]


ADVERSE_EVENT_PATTERNS = {
    "en": [
        r"\b(side effect|adverse effect|adverse reaction|made me (feel|sick|dizzy|nauseous))\b",
        r"\b(allergic reaction|rash|hives|swelling|difficulty breath)\b",
        r"\b(after taking|after using).{0,30}(pain|dizzy|nausea|vomit|bleed|faint|seizure)\b",
        r"\b(hospitalised|emergency|overdose|poisoning)\b",
        r"\btook .{0,20} and (now|then) (feel|felt|started)\b",
    ],
    "fr": [
        r"\b(effet secondaire|réaction indésirable|m'a rendu|me rend|j'ai eu mal)\b",
        r"\b(allergie|éruption|démangeaison|gonflement|difficultés à respirer)\b",
        r"\b(après avoir pris|après la prise).{0,60}(douleurs?|vertiges?|nausées?|vomissements?)\b",
        r"\b(hospitalisé|urgence|surdosage|intoxication)\b",
    ],
    "nl": [
        r"\b(bijwerking|bijwerkingen|maakte me ziek|werd er misselijk|na het nemen)\b",
        r"\b(allergische reactie|uitslag|zwelling|ademhalingsmoeilijkheden)\b",
        r"\b(ziekenhuis|spoedeisende|overdosering|vergiftiging)\b",
    ],
    "de": [
        r"\b(nebenwirkung|nebenwirkungen|unerwünschte wirkung|wurde mir schlecht)\b",
        r"\b(allergische reaktion|ausschlag|schwellung|atemnot)\b",
        r"\b(krankenhaus|notaufnahme|überdosierung|vergiftung)\b",
    ],
}

PRESCRIPTION_PROMOTION_PATTERNS = [
    r"\b(buy|order|purchase|get) .{0,30}(prescription|Rx)\b",
    r"\b(best (drug|medicine|medication)) .{0,30}(for|against)\b",
    r"\bdoctors (recommend|prescribe|suggest)\b",
]

SHORTAGE_PATTERNS = {
    "en": [r"\b(out of stock|unavailable|shortage|can't find|not available)\b"],
    "fr": [r"\b(rupture de stock|indisponible|pénurie|introuvable|pas disponible)\b"],
    "nl": [r"\b(uitverkocht|niet beschikbaar|tekort|onvindbaar)\b"],
    "de": [r"\b(ausverkauft|nicht verfügbar|knappheit|nicht erhältlich)\b"],
}

MISINFORMATION_PATTERNS = [
    r"\b(cure|cures|miracle|100% effective|doctors don't want you to know)\b",
    r"\b(gouvernement cache|médecins ne veulent pas)\b",
]


def detect_risk(text: str, lang: str = "en") -> RiskResult:
    """
    Rule-based risk detection.
    Prioritise HIGH RECALL for adverse events — it is better to flag
    too many than to miss a real adverse event.
    Final adverse event decisions require human review — never auto-close.
    """
    text_lower = text.lower()
    matched: List[str] = []
    risk_type = "none"
    is_ae = False
    is_promo = False
    confidence = 0.0

    ae_pats = ADVERSE_EVENT_PATTERNS.get(lang, ADVERSE_EVENT_PATTERNS["en"])
    for pat in ae_pats:
        if re.search(pat, text_lower):
            matched.append(f"ae:{pat[:40]}")
            is_ae = True
            risk_type = "adverse_event"
            confidence = max(confidence, 0.80)

    shortage_pats = SHORTAGE_PATTERNS.get(lang, SHORTAGE_PATTERNS["en"])
    for pat in shortage_pats:
        if re.search(pat, text_lower):
            matched.append(f"shortage:{pat[:40]}")
            if risk_type == "none":
                risk_type = "shortage"
                confidence = max(confidence, 0.75)

    for pat in MISINFORMATION_PATTERNS:
        if re.search(pat, text_lower):
            matched.append(f"misinfo:{pat[:40]}")
            if risk_type == "none":
                risk_type = "misinformation"
                confidence = max(confidence, 0.70)

    for pat in PRESCRIPTION_PROMOTION_PATTERNS:
        if re.search(pat, text_lower):
            matched.append(f"promo:{pat[:40]}")
            is_promo = True

    return RiskResult(
        risk_type=risk_type,
        is_adverse_event_candidate=is_ae,
        is_prescription_promotion=is_promo,
        confidence=confidence if matched else 1.0,
        matched_patterns=matched,
    )
