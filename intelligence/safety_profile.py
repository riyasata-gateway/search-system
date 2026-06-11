"""Product-safety profile — the "Yuka for medicines" layer.

Not a black-box score: for a given brand it surfaces *why*, across four pillars,
each with its **source** and a **confidence** level, and is honest ("insufficient
data") rather than faking confidence when a pillar has no signal:

  1. Regulatory watch   — EMA additional-monitoring (▲) + EudraVigilance, from SAM
  2. Side effects       — patient-reported reactions (openFDA/FAERS BE + forums)
  3. Supply / availability — shortage / stock risk (Belgian retail)
  4. Recent signal      — recalls / warnings / label changes in recent news/EMA

This is the trustworthiness contract: a signal always carries a source and a
confidence, and the system says when it doesn't know.
"""
from __future__ import annotations

from typing import Dict

from sqlalchemy import text
from sqlalchemy.orm import Session

from intelligence.inn_resolver import is_belgian_medicine, sam_meta
from intelligence.retail import retail_meta

_RECALL_TERMS = ["recall", "rappel", "terugroep", "withdrawn", "retrait", "intrekking",
                 "suspended", "suspension", "geschorst", "warning", "avertissement",
                 "waarschuwing", "safety", "sécurité", "veiligheid", "defect", "contamin"]


def _conf(n: int) -> str:
    return "high" if n >= 20 else "medium" if n >= 5 else "low" if n >= 1 else "none"


def compute_safety_profile(db: Session, brand) -> Dict:
    bid = brand.id
    meta = sam_meta(brand.name)
    is_med = is_belgian_medicine(brand.name)
    pillars = []

    # 1 ── Regulatory watch (EMA additional monitoring + EudraVigilance) ─────
    if is_med:
        eudra = db.execute(text(
            "SELECT count(*) FROM mention_entities me JOIN mentions m ON m.id=me.mention_id "
            "WHERE me.entity_type='brand' AND me.entity_id=:b AND m.source_type='eudravigilance'"),
            {"b": bid}).scalar() or 0
        bt = bool(meta.get("black_triangle"))
        pillars.append({
            "key": "regulatory_watch", "title": "Regulatory watch",
            "level": "watch" if bt else ("monitored" if eudra else "clear"),
            "finding": ("▲ Under additional EU safety monitoring (black triangle)" if bt
                        else "Active substance is EU-pharmacovigilance monitored" if eudra
                        else "No EU additional-monitoring flag"),
            "source": "EMA / EudraVigilance · SAM (FAGG)", "confidence": "high",
            "evidence": [],
        })
    else:
        pillars.append({"key": "regulatory_watch", "title": "Regulatory watch", "level": "na",
                        "finding": "Not a medicine — no pharmacovigilance layer", "source": "SAM (FAGG)",
                        "confidence": "high", "evidence": []})

    # 2 ── Patient-reported side effects (openFDA FAERS BE + forums) ─────────
    rx = db.execute(text("""
        SELECT reaction, count(*) c FROM (
          SELECT jsonb_array_elements_text(m.raw_metadata->'reactions') reaction
          FROM mention_entities me JOIN mentions m ON m.id=me.mention_id
          WHERE me.entity_type='brand' AND me.entity_id=:b AND m.source_type='openfda'
            AND m.raw_metadata ? 'reactions'
        ) t GROUP BY reaction ORDER BY c DESC LIMIT 5
    """), {"b": bid}).mappings().all()
    fda_n = db.execute(text(
        "SELECT count(*) FROM mention_entities me JOIN mentions m ON m.id=me.mention_id "
        "WHERE me.entity_type='brand' AND me.entity_id=:b AND m.source_type='openfda'"),
        {"b": bid}).scalar() or 0
    serious = db.execute(text(
        "SELECT count(*) FROM mention_entities me JOIN mentions m ON m.id=me.mention_id "
        "WHERE me.entity_type='brand' AND me.entity_id=:b AND m.source_type='openfda' "
        "AND (m.raw_metadata->>'serious')='true'"), {"b": bid}).scalar() or 0
    forum_n = db.execute(text(
        "SELECT count(*) FROM mention_entities me JOIN mentions m ON m.id=me.mention_id "
        "WHERE me.entity_type='brand' AND me.entity_id=:b AND m.source_type='forum'"),
        {"b": bid}).scalar() or 0
    if not is_med:
        pillars.append({"key": "side_effects", "title": "Patient-reported side effects", "level": "na",
                        "finding": "Cosmetic/parapharmacy — gauge via reviews instead",
                        "source": "openFDA / forums", "confidence": "none", "evidence": []})
    elif fda_n:
        top = [r["reaction"].title() for r in rx]
        pillars.append({
            "key": "side_effects", "title": "Patient-reported side effects",
            "level": "watch" if serious else "caution",
            "finding": f"{fda_n} adverse-event reports (BE){', ' + str(serious) + ' serious' if serious else ''}; "
                       f"most reported: {', '.join(top[:3])}",
            "source": "openFDA / FAERS (Belgium-occurring)" + (f" · {forum_n} forum threads" if forum_n else ""),
            "confidence": _conf(fda_n), "evidence": top,
        })
    else:
        pillars.append({"key": "side_effects", "title": "Patient-reported side effects", "level": "clear",
                        "finding": "No Belgian adverse-event reports found", "source": "openFDA / FAERS (BE)",
                        "confidence": "low", "evidence": []})

    # 3 ── Supply / availability ────────────────────────────────────────────
    rt = retail_meta(brand.name)
    stock = rt.get("in_stock_pct")
    if stock is not None:
        lvl = "watch" if stock < 20 else "caution" if stock < 50 else "clear"
        pillars.append({
            "key": "supply", "title": "Supply / availability",
            "level": lvl, "finding": f"{stock}% of retail SKUs in stock"
            + (" — availability risk, order ahead / substitute" if lvl != "clear" else ""),
            "source": "Belgian pharmacy retail (Farmaline)",
            "confidence": "medium", "evidence": [],
        })
    else:
        pillars.append({"key": "supply", "title": "Supply / availability", "level": "unknown",
                        "finding": "No live availability feed connected (FAGG PharmaStatus needs a proxy)",
                        "source": "FAGG PharmaStatus", "confidence": "none", "evidence": []})

    # 4 ── Recent regulatory signal (recall / warning / label) ──────────────
    news = db.execute(text("""
        SELECT m.clean_text, m.source_url FROM mention_entities me JOIN mentions m ON m.id=me.mention_id
        WHERE me.entity_type='brand' AND me.entity_id=:b AND m.source_type IN ('rss','news','bcfi','ansm_safety')
        ORDER BY m.published_at DESC NULLS LAST LIMIT 60
    """), {"b": bid}).mappings().all()
    hits = []
    for r in news:
        t = (r["clean_text"] or "").lower()
        if any(term in t for term in _RECALL_TERMS):
            hits.append((r["clean_text"] or "")[:140])
        if len(hits) >= 3:
            break
    if hits:
        pillars.append({"key": "recent_signal", "title": "Recent regulatory signal",
                        "level": "caution", "finding": f"{len(hits)} recent recall/warning/safety item(s)",
                        "source": "News / EMA / BCFI / ANSM", "confidence": "medium", "evidence": hits})
    else:
        pillars.append({"key": "recent_signal", "title": "Recent regulatory signal", "level": "clear",
                        "finding": "No recent recall/warning detected in monitored news",
                        "source": "News / EMA / BCFI", "confidence": "low", "evidence": []})

    # Overall — worst pillar wins; honest about coverage.
    order = {"watch": 3, "caution": 2, "monitored": 1, "clear": 0, "unknown": 0, "na": 0}
    worst = max((p["level"] for p in pillars), key=lambda l: order.get(l, 0))
    overall = ("Watch" if worst == "watch" else "Caution" if worst == "caution"
               else "Clear" if is_med else "n/a (not a medicine)")
    drivers = [p["title"] for p in pillars if p["level"] in ("watch", "caution")]
    summary = (("Attention: " + ", ".join(drivers)) if drivers
               else ("No active safety signals across the four pillars" if is_med
                     else "Parapharmacy product — no medicine-safety layer applies"))
    return {
        "brand": {"id": brand.id, "name": brand.name, "is_medicine": is_med,
                  "substance": (meta.get("primary") or [None])[0], "atc": (meta.get("atc") or [{}])[0].get("code") if meta.get("atc") else None},
        "overall": {"level": overall, "summary": summary},
        "pillars": pillars,
    }
