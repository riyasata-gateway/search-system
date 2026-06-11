"""Resolve live values for the workbook KPI library, per brand.

The framework (`core/framework_catalog.KPI_LIBRARY`) declares, for each role, the
KPIs the Datatopia workbook says that role cares about — each tagged with a
`data_status`:

  • "live"        — we can compute a real number today from ingested data
  • "partial"     — an engine runs but the proprietary leg is thin
  • "data_needed" — a Tier-C feed (sell-out / IQVIA / Farmanet …) isn't connected

This module fills in the *values* for the live/partial KPIs of one brand, reusing
the existing intelligence engines and the linked review corpus. `data_needed`
KPIs get no value here — the API returns them with a "Connect feed" marker so the
UI is honest about what is and isn't wired, instead of fabricating a number.

Keyed by the stable `key` field on each KPI_LIBRARY entry.
"""
from __future__ import annotations

from typing import Dict, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from models.brand import Brand
from core.source_taxonomy import OPINION_SOURCE_TYPES

import bisect

MIN_TRUST_BASE = 10   # min classified opinions for a confident brand-trust index

# Cached recommendation-density distribution across all review brands, so the
# recommendation leg of brand-trust is a PERCENTILE RANK vs peers (a brand
# recommended more than its peers scores high) rather than a tiny raw share that
# can't move the index. Reviews are historical/static, so caching per-process is
# safe; None until first computed.
_REC_DENSITY_DIST = None


def _rec_density_percentile(db: Session, my_density: float) -> float:
    """Percentile rank (0–100) of a brand's recommendation density among all
    review brands with a trust-eligible opinion base. 50 when no distribution."""
    global _REC_DENSITY_DIST
    if _REC_DENSITY_DIST is None:
        rows = db.execute(text("""
            SELECT sum((((mc.topic = 'recommendation') OR (mc.intent = 'recommendation')))::int)::float
                     / nullif(count(mc.id), 0) AS dens
            FROM mention_entities me
            JOIN mentions m ON m.id = me.mention_id
            JOIN mention_classifications mc ON mc.mention_id = m.id
            WHERE me.entity_type = 'brand' AND m.source_type = ANY(:op)
            GROUP BY me.entity_id
            HAVING count(mc.id) >= :minb
        """), {"op": list(OPINION_SOURCE_TYPES), "minb": MIN_TRUST_BASE}).fetchall()
        _REC_DENSITY_DIST = sorted(float(r[0]) for r in rows if r[0] is not None)
    dist = _REC_DENSITY_DIST
    if not dist:
        return 50.0
    return 100.0 * bisect.bisect_right(dist, my_density) / len(dist)


def _human(n: float) -> str:
    """13629 -> '13.6k'; 950 -> '950'."""
    n = float(n)
    if n >= 1000:
        return f"{n/1000:.1f}k".replace(".0k", "k")
    return f"{int(round(n))}"


def _headline(engine_result) -> Optional[dict]:
    """First metric of an engine bundle, or None when the engine had no data."""
    if engine_result is None:
        return None
    try:
        metrics = engine_result.to_bundle().to_dict().get("metrics") or []
    except Exception:
        return None
    return metrics[0] if metrics else None


def compute_live_values(db: Session, brand: Brand) -> Dict[str, dict]:
    """Return {kpi_key: {value, display, detail}} for the live/partial KPIs.

    Only keys we can back with real data are returned; everything else falls
    through to the "Connect feed" path in the router.
    """
    bid = brand.id
    out: Dict[str, dict] = {}

    # ── Review base: linked reviews, avg rating, sentiment split ──────────────
    base = db.execute(text("""
        SELECT count(*)                                        AS linked,
               count(m.rating)                                 AS rated,
               coalesce(avg(m.rating), 0)                      AS avg_rating,
               count(mc.id) FILTER (WHERE m.source_type = ANY(:op))  AS classified,
               sum((mc.sentiment = 'positive' AND m.source_type = ANY(:op))::int) AS pos,
               sum((mc.sentiment = 'negative' AND m.source_type = ANY(:op))::int) AS neg,
               sum((((mc.topic = 'recommendation') OR (mc.intent = 'recommendation'))
                    AND m.source_type = ANY(:op))::int) AS rec
        FROM mention_entities me
        JOIN mentions m ON m.id = me.mention_id
        LEFT JOIN mention_classifications mc ON mc.mention_id = m.id
        WHERE me.entity_type = 'brand' AND me.entity_id = :bid
    """), {"bid": bid, "op": list(OPINION_SOURCE_TYPES)}).mappings().first()

    # Per-source counts for the ingested multi-source signals (PubMed, trials,
    # openFDA, news) linked to this brand.
    src = db.execute(text("""
        SELECT m.source_type, count(*) AS cnt
        FROM mention_entities me
        JOIN mentions m ON m.id = me.mention_id
        WHERE me.entity_type = 'brand' AND me.entity_id = :bid
        GROUP BY m.source_type
    """), {"bid": bid}).mappings().all()
    cmap = {r["source_type"]: int(r["cnt"]) for r in src}
    pubmed = cmap.get("pubmed", 0)
    trials = cmap.get("clinical_trials", 0)
    fda = cmap.get("openfda", 0)
    eudra = cmap.get("eudravigilance", 0)
    news = cmap.get("rss", 0) + cmap.get("news", 0)
    # Patient-forum discussion spans the generic forum scraper + Doctissimo (FR)
    # + Reddit — all are patient-voice sources feeding the same signal.
    forum = cmap.get("forum", 0) + cmap.get("doctissimo", 0) + cmap.get("reddit", 0)
    bcfi = cmap.get("bcfi", 0) + cmap.get("bcfi_cbip", 0)
    safety_gate = cmap.get("safety_gate", 0)
    fagg_short = cmap.get("fagg_shortage", 0)      # Belgian FAGG/AFMPS shortage list
    ansm_short = cmap.get("ansm_shortage", 0) + cmap.get("ansm", 0)  # French ANSM list

    # Authoritative medicine flag + SAM metadata (ATC, CNK packs).
    from core.framework_catalog import BRAND_INN
    from intelligence.inn_resolver import _normalise, is_belgian_medicine, sam_meta
    is_medicine = is_belgian_medicine(brand.name) or (brand.name in BRAND_INN)
    meta = sam_meta(brand.name)

    # Therapeutic class (ATC) — brand_manager. Pick the ATC that best represents
    # the primary single-substance: exact desc match first, then contains, then
    # the most specific (shortest desc) — so plain Paracetamol (N02BE01) wins over
    # the codeine combo (N02AJ06).
    atc_list = meta.get("atc") or []
    if atc_list:
        base_inn = _normalise(meta.get("primary") or [])

        def _atc_score(a):
            d = (a.get("desc") or "").lower()
            matches = any(k in d for k in base_inn)
            combo = any(t in d for t in (" and ", "combination", "excl", ","))
            # best = matches a primary substance AND is a single-substance class
            rank = 0 if (matches and not combo) else 1 if matches else 2 if not combo else 3
            return (rank, len(d))

        chosen = sorted(atc_list, key=_atc_score)[0]
        others = len(atc_list) - 1
        out["bm_atc_class"] = {
            "value": chosen["code"],
            "display": f"{chosen['code']} — {chosen.get('desc') or ''}".strip(" —"),
            "detail": f"+{others} related ATC class{'es' if others != 1 else ''}" if others else "WHO ATC (SAM)",
        }
    elif is_medicine:
        out["bm_atc_class"] = {"value": None, "display": "—", "detail": "no ATC in SAM"}
    else:
        out["bm_atc_class"] = {"value": None, "display": "n/a", "detail": "not a medicine"}

    # Tracked SKUs — count from the canonical CNK pack registry (deduped across
    # FR/NL and across SAM + retail), falling back to the SAM CNK set.
    pk = db.execute(text(
        "SELECT count(*) AS n, count(name_nl) AS bil FROM packs WHERE brand_id = :bid"),
        {"bid": bid}).mappings().first()
    n_packs = int(pk["n"]) if pk else 0
    if n_packs:
        out["bm_pack_count"] = {"value": n_packs, "display": f"{n_packs} packs",
                                "detail": f"canonical CNK packs (FR/NL-deduped) · {int(pk['bil'])} bilingual"}
    elif meta.get("cnk"):
        out["bm_pack_count"] = {"value": len(meta["cnk"]), "display": f"{len(meta['cnk'])} packs",
                                "detail": "CNK packs (SAM)"}
    else:
        out["bm_pack_count"] = {"value": None, "display": "—", "detail": "no packs tracked"}

    # Reimbursement (BE) — SAM Reimbursable flag + RMB category (A/B/C) detail.
    rp, tp = meta.get("reimbursed_packs", 0), meta.get("total_priced_packs", 0)
    rdet = meta.get("reimbursement") or {}
    cats = rdet.get("categories") or []
    if is_medicine and tp:
        pct = round(100 * rp / tp)
        cat_txt = f" · cat {'/'.join(cats)}" if cats else ""
        detail = f"{rp}/{tp} packs RIZIV-reimbursed" + ("" if rp else " — typical for OTC")
        if cats:
            detail += f" (category {'/'.join(cats)})"
        out["bm_reimbursement"] = {
            "value": pct,
            "display": (f"{pct}% reimbursed{cat_txt}") if rp else "Not reimbursed (OTC)",
            "detail": detail,
        }
    elif not is_medicine:
        out["bm_reimbursement"] = {"value": None, "display": "n/a", "detail": "parapharmacy — not reimbursable"}
    else:
        out["bm_reimbursement"] = {"value": None, "display": "—", "detail": "no pricing in SAM"}

    # Market status (BE) — authorisation + time on market (SAM).
    status = meta.get("status")
    since = meta.get("commercialised_since")
    if is_medicine and status:
        yr = since[:4] if since else None
        out["bm_market_status"] = {
            "value": status,
            "display": status.title() + (f" · since {yr}" if yr else ""),
            "detail": (f"on the Belgian market since {since}" if since else "registered in SAM"),
        }
    elif not is_medicine:
        out["bm_market_status"] = {"value": None, "display": "Parapharmacy",
                                   "detail": "non-medicinal — no marketing authorisation"}

    # ── Belgian retail layer (Farmaline catalogue) — price/promo + availability ─
    from intelligence.retail import retail_meta
    rt = retail_meta(brand.name)
    if rt.get("price"):
        p = rt["price"]
        promo = rt.get("promo_pct", 0)
        out["mk_price_competitiveness"] = {
            "value": promo,
            "display": f"€{p['min']}–{p['max']} · {promo}% on promo",
            "detail": f"avg €{p['avg']}, {rt.get('avg_discount', 0)}% avg discount across {rt.get('skus', 0)} Farmaline SKUs",
        }
    elif meta.get("price"):
        # No online-retail catalogue entry (typical for OTC/Rx medicines, which
        # the dermo-focused Farmaline scrape didn't cover) — fall back to the
        # authoritative SAM (FAGG) official list price so the KPI is real, not empty.
        p = meta["price"]
        out["mk_price_competitiveness"] = {
            "value": None,
            "display": f"€{p['min']}–{p['max']}",
            "detail": f"avg €{p['avg']} across {tp} packs — SAM (FAGG) official list price"
                      " (no online-promo feed for this brand)",
        }
    if rt.get("skus"):
        stock = rt.get("in_stock_pct", 0)
        out["bm_online_availability"] = {
            "value": stock,
            "display": f"{stock}% in stock",
            "detail": f"{rt['skus']} SKUs listed on Farmaline · online rating {rt.get('rating')}★ ({_human(rt.get('rating_count', 0))})",
        }
    # Claims & benefit profile (retail descriptions + brand sites).
    benefits = rt.get("benefits") or []
    if benefits:
        peers = [{"name": b["name"], "share": b["share"], "is_self": False} for b in benefits]
        for u in (rt.get("skin_types") or [])[:2]:
            peers.append({"name": f"Skin: {u['name']}", "share": u["share"], "is_self": False})
        top = ", ".join(b["name"] for b in benefits[:3])
        out["mk_claims_profile"] = {
            "value": benefits[0]["share"], "display": top,
            "detail": f"benefit themes across {rt.get('skus', 0)} retail SKUs",
            "peers": peers, "peers_label": "Benefit themes (% of range)",
        }

    # List price range (BE) — from SAM (brand_manager).
    pr = meta.get("price")
    if pr:
        out["bm_price"] = {"value": pr["avg"], "display": f"€{pr['min']}–{pr['max']}",
                           "detail": f"avg €{pr['avg']} across {tp} packs (SAM list price)"}
    elif not is_medicine:
        out["bm_price"] = {"value": None, "display": "n/a", "detail": "parapharmacy — free pricing"}
    else:
        out["bm_price"] = {"value": None, "display": "—", "detail": "no list price in SAM"}

    # Evidence base (PubMed) — marketing + brand_manager
    ev = {"value": pubmed, "display": f"{pubmed} papers", "detail": "PubMed publications naming the brand"}
    out["mk_evidence_base"] = dict(ev)
    out["bm_evidence_base"] = dict(ev)
    # Clinical pipeline (trials) — brand_manager
    out["bm_clinical_pipeline"] = {"value": trials, "display": f"{trials} trials",
                                   "detail": "registered / active clinical trials"}
    # Safety — EU-native (EudraVigilance) is primary in Belgium; FAERS is intl.
    if not is_medicine:
        na = {"value": None, "display": "n/a", "detail": "not a medicine — no pharmacovigilance"}
        out["ph_eu_safety"] = dict(na)
        out["ph_safety_signals"] = dict(na)
    else:
        bt = meta.get("black_triangle")
        eu_detail = ("active substance under EMA / EudraVigilance ADR monitoring" if eudra > 0
                     else "no EU adverse-reaction record for the substance")
        if bt:
            eu_detail = "▲ under additional EU safety monitoring (SAM black triangle) · " + eu_detail
        out["ph_eu_safety"] = {
            "value": eudra,
            "display": "▲ Monitored (EU)" if bt else ("Monitored (EU)" if eudra > 0 else "No EU signal"),
            "detail": eu_detail,
        }
        out["ph_safety_signals"] = {
            "value": fda,
            "display": "None found" if fda == 0 else f"{fda} reports",
            "detail": "Belgium-occurring adverse-event reports (FAERS)" + (" — clean" if fda == 0 else ""),
        }
    # News & PR volume — marketing
    out["mk_news_pr"] = {"value": news, "display": f"{news} articles",
                         "detail": "press / news naming the brand"}
    # Patient forum discussion — pharmacist
    out["ph_patient_questions"] = {"value": forum, "display": f"{forum} threads",
                                   "detail": "patient-forum threads naming the brand"}
    # BCFI/CBIP clinical guidance notes (interactions / older-patient / safety) — pharmacist
    if is_medicine:
        out["ph_clinical_notes"] = {
            "value": bcfi,
            "display": f"{bcfi} clinical notes" if bcfi else "None",
            "detail": "BCFI/CBIP commentary on the substance (interactions, geriatric, safety)"
                      if bcfi else "no BCFI clinical notes for the substance",
        }
    else:
        out["ph_clinical_notes"] = {"value": None, "display": "n/a", "detail": "not a medicine"}

    # ── Adverse-reaction breakdown (openFDA structured metadata) — pharmacist ──
    rx = db.execute(text("""
        SELECT reaction, count(*) AS c FROM (
            SELECT jsonb_array_elements_text(m.raw_metadata->'reactions') AS reaction
            FROM mention_entities me JOIN mentions m ON m.id = me.mention_id
            WHERE me.entity_type = 'brand' AND me.entity_id = :bid
              AND m.source_type = 'openfda' AND m.raw_metadata ? 'reactions'
        ) t GROUP BY reaction ORDER BY c DESC LIMIT 6
    """), {"bid": bid}).mappings().all()
    if not is_medicine:
        out["ph_adverse_reactions"] = {"value": None, "display": "n/a", "detail": "not a medicine — no pharmacovigilance"}
    elif fda > 0:
        rx_peers = [{"name": r["reaction"].title(), "share": round(100 * int(r["c"]) / fda), "is_self": False} for r in rx]
        out["ph_adverse_reactions"] = {
            "value": fda, "display": f"{fda} reports",
            "detail": "most-reported reactions (Belgium, FAERS)", "peers": rx_peers, "peers_label": "Top reactions",
        }
    else:
        out["ph_adverse_reactions"] = {"value": 0, "display": "None found", "detail": "no FAERS reports — clean"}

    # ── Trial & study mix (ClinicalTrials structured metadata) — brand_manager ─
    # Phases (1–4) only exist for *drug* trials. Cosmetic/supplement brands run
    # interventional non-drug efficacy studies or observational studies, which
    # genuinely have no phase — so we classify those by study type instead of
    # dumping them all into "Not applicable".
    if trials > 0:
        rows = db.execute(text("""
            SELECT coalesce(nullif(m.raw_metadata->>'phase', ''), 'NA') AS phase,
                   coalesce(m.raw_metadata->>'study_type', '') AS study_type,
                   count(*) AS c
            FROM mention_entities me JOIN mentions m ON m.id = me.mention_id
            WHERE me.entity_type = 'brand' AND me.entity_id = :bid AND m.source_type = 'clinical_trials'
            GROUP BY phase, study_type
        """), {"bid": bid}).mappings().all()

        def _phase_label(p):
            raw = (p or "").strip().upper()
            if raw in ("", "NA", "N/A", "PHASE NA", "NONE"):
                return None  # no phase
            parts = []
            for tok in raw.replace("/", ",").split(","):
                tok = tok.strip()
                if tok in ("", "NA", "N A", "N"):
                    continue
                tok = tok.replace("EARLY_PHASE1", "Early Phase 1").replace("EARLY PHASE 1", "Early Phase 1")
                tok = tok.replace("PHASE", "Phase ").replace("_", " ")
                parts.append(" ".join(tok.split()))
            return ", ".join(parts) if parts else None

        def _label(phase, st):
            pl = _phase_label(phase)
            if pl:
                return pl
            st = (st or "").upper()
            if st == "OBSERVATIONAL":
                return "Observational"
            if st == "INTERVENTIONAL":
                return "Interventional (non-drug)"
            return "Unspecified"

        agg: Dict[str, int] = {}
        for r in rows:
            lbl = _label(r["phase"], r["study_type"])
            agg[lbl] = agg.get(lbl, 0) + int(r["c"])
        # Plain-language meaning for each phase so the mix is self-explanatory.
        phase_tag = {
            "Early Phase 1": "exploratory / first-in-human",
            "Phase 1": "safety & dosing",
            "Phase 2": "efficacy & side-effects",
            "Phase 3": "large-scale confirmatory (pre-approval)",
            "Phase 4": "post-marketing surveillance",
            "Interventional (non-drug)": "device / cosmetic efficacy study",
            "Observational": "real-world, no intervention",
        }
        mix = [{"name": lbl + (f" · {phase_tag[lbl]}" if lbl in phase_tag else ""),
                "share": round(100 * c / trials), "is_self": False}
               for lbl, c in sorted(agg.items(), key=lambda x: -x[1])]
        # Headline: how many are actual phased drug trials.
        phased = sum(c for lbl, c in agg.items() if lbl.startswith(("Phase", "Early")))
        detail = (f"{phased} phased drug trial{'s' if phased != 1 else ''}"
                  if phased else "no phased drug trials — efficacy / observational studies")
        out["bm_trial_phases"] = {
            "value": trials, "display": f"{trials} studies",
            "detail": detail, "peers": mix, "peers_label": "Study mix",
        }

    linked = int(base["linked"] or 0)
    rated = int(base["rated"] or 0)
    avg_rating = round(float(base["avg_rating"] or 0), 2)
    classified = int(base["classified"] or 0)
    pos = int(base["pos"] or 0)
    neg = int(base["neg"] or 0)
    rec = int(base["rec"] or 0)

    # Non-review public attention (news + social + forum) — the fallback signal
    # for Rx products that have no consumer-review footprint.
    attention = (cmap.get("rss", 0) + cmap.get("news", 0) + cmap.get("forum", 0)
                 + cmap.get("youtube", 0) + cmap.get("doctissimo", 0) + cmap.get("reddit", 0))

    opinion_n = max(rated, classified)   # classified is opinion-scoped (see query)
    if rated >= 20:
        profile = "consumer"
    elif opinion_n >= 5:
        profile = "emerging"
    else:
        profile = "catalog"
    out["_profile"] = {"profile": profile, "reviews": rated,
                       "attention": attention, "opinion": opinion_n}

    # Review rating & volume (marketing) / public demand signal (pharmacist)
    if rated:
        out["mk_review_trend"] = {"value": avg_rating,
               "display": f"{avg_rating}★ · {_human(rated)} reviews",
               "detail": "avg rating across linked pharmacy reviews", "count": rated}
        out["ph_demand_signal"] = {"value": rated, "display": f"{_human(rated)} reviews",
               "detail": "patient-review volume = what people are asking about", "count": rated}
    elif attention:
        foot = ("Rx product" if is_medicine else "low consumer-review footprint")
        out["mk_review_trend"] = {"value": None, "display": "No consumer reviews",
               "detail": f"{foot} — {_human(attention)} news/social mentions instead (no review channel)"}
        out["ph_demand_signal"] = {"value": attention, "display": f"{_human(attention)} mentions",
               "detail": f"news / social / forum attention ({foot})", "count": attention}

    polar = pos + neg
    MIN_POLAR = 5
    MIN_REVIEW_BASE = 20    # min rated-review base for a stable derived rate
    if polar > 0:
        neutral = max(0, classified - polar)
        if polar < MIN_POLAR:
            sent = {"value": None,
                    "display": f"{_human(pos)} positive · {_human(neg)} negative",
                    "detail": f"only {polar} rated opinion(s) so far — raw counts, too few for a %",
                    "confidence": "low"}
        else:
            pct_pos = round(100 * pos / polar)
            sent = {"value": pct_pos,
                    "display": f"{pct_pos}% positive",
                    "detail": f"{_human(pos)} positive · {_human(neg)} negative"
                              + (f" ({_human(neutral)} neutral excluded)" if neutral else ""),
                    "confidence": "ok"}
        out["mk_sentiment_trend"] = sent
        out["ph_patient_sentiment"] = dict(sent)
    elif is_medicine:
        # Rx: no consumer reviews to derive sentiment from.
        na = {"value": None, "display": "n/a",
              "detail": "no consumer reviews (Rx) — gauge via safety, evidence & HCP channels instead"}
        out["mk_sentiment_trend"] = dict(na)
        out["ph_patient_sentiment"] = dict(na)

    comp_base = rated if rated else polar
    comp_lbl = "reviews" if rated else "classified opinions"
    if comp_base > 0:
        comp_neg = min(neg, comp_base)
        min_base = MIN_REVIEW_BASE if rated else MIN_POLAR
        if comp_base < min_base:
            out["ph_complaint_rate"] = {
                "value": None, "display": f"{_human(comp_neg)} negative of {_human(comp_base)}",
                "detail": f"raw counts — only {comp_base} {comp_lbl}, too few for a rate",
                "confidence": "low"}
        else:
            neg_pct = round(100 * comp_neg / comp_base)
            out["ph_complaint_rate"] = {
                "value": neg_pct, "display": f"{neg_pct}%",
                "detail": f"{_human(comp_neg)} negative of {_human(comp_base)} {comp_lbl}",
                "confidence": "ok"}

    # ── B2: Pharmacist "brand trust" — recommendation-led perception index.
    # 60% review positivity + 40% recommendation strength. Because reviews skew
    # ~99% positive for nearly every brand (so sentiment alone barely separates
    # brands), the recommendation leg is a PERCENTILE RANK of the brand's
    # recommendation density vs peers — that's what differentiates trusted brands.
    # Gated on a minimum opinion base so a handful of reviews can't fake an index.
    if classified >= MIN_TRUST_BASE and polar >= MIN_POLAR:
        pos_pct = 100.0 * pos / polar
        rec_density = rec / classified
        rec_rank = _rec_density_percentile(db, rec_density)
        trust = round(0.6 * pos_pct + 0.4 * rec_rank)
        out["ph_brand_trust"] = {
            "value": trust, "display": f"{trust}/100",
            "detail": (f"{round(pos_pct)}% positive · recommendation in the top "
                       f"{max(1, round(100 - rec_rank))}% of brands "
                       f"({_human(rec)} of {_human(classified)} opinions recommend)"),
            "confidence": "ok"}
    elif classified > 0:
        out["ph_brand_trust"] = {
            "value": None, "display": f"{_human(rec)} recommend of {_human(classified)}",
            "detail": f"raw counts — only {classified} classified opinions, too few for a trust index",
            "confidence": "low"}

    # ── Review momentum (last 90d vs prior 90d) — demand trend, marketing + BM ─
    mom = db.execute(text("""
        SELECT
          count(*) FILTER (WHERE m.published_at >= now() - interval '90 days') AS recent,
          count(*) FILTER (WHERE m.published_at >= now() - interval '180 days'
                             AND m.published_at <  now() - interval '90 days') AS prior
        FROM mention_entities me JOIN mentions m ON m.id = me.mention_id
        WHERE me.entity_type = 'brand' AND me.entity_id = :bid
          AND m.source_type IN ('farmaline', 'medimarket')
    """), {"bid": bid}).mappings().first()
    recent_n, prior_n = int(mom["recent"] or 0), int(mom["prior"] or 0)
    # Tracks review-PUBLISH cadence (subject to ingestion timing), not demand.
    # Shown whenever there's a prior base; flagged "thin base" below the threshold
    # rather than hidden, so a ±% off 1–5 reviews is covered but clearly caveated.
    # (MIN_REVIEW_BASE defined above, near MIN_POLAR.)
    if prior_n > 0:
        if prior_n < MIN_REVIEW_BASE:
            # Raw counts, not a % off a tiny base.
            rm = {"value": None, "display": f"{recent_n} vs {prior_n} reviews",
                  "detail": f"recent 90d {recent_n} vs prior {prior_n} reviews — too few for a % "
                            f"(review-publish cadence)", "confidence": "low"}
        else:
            pct = round(100 * (recent_n - prior_n) / prior_n)
            arrow = "▲" if pct > 0 else "▼" if pct < 0 else "■"
            rm = {"value": pct, "display": f"{arrow} {pct:+d}%",
                  "detail": f"{recent_n} reviews last 90d vs {prior_n} prior (review-publish cadence)",
                  "confidence": "ok"}
        out["mk_review_momentum"] = dict(rm)
        out["bm_review_momentum"] = dict(rm)

    # ── Regional split FR vs NL (bilingual Belgium) — public penetration proxy ─
    reg = db.execute(text("""
        SELECT m.language AS lang, count(*) AS n, coalesce(avg(m.rating), 0) AS avg_r
        FROM mention_entities me JOIN mentions m ON m.id = me.mention_id
        WHERE me.entity_type = 'brand' AND me.entity_id = :bid
          AND m.source_type IN ('farmaline', 'medimarket')
          AND m.language IN ('fr', 'nl')
        GROUP BY m.language
    """), {"bid": bid}).mappings().all()
    rmap = {r["lang"]: (int(r["n"]), round(float(r["avg_r"]), 1)) for r in reg}
    nl_n = rmap.get("nl", (0, 0))[0]
    fr_n = rmap.get("fr", (0, 0))[0]
    if nl_n + fr_n > 0:
        nl_pct = round(100 * nl_n / (nl_n + fr_n))
        out["bm_regional_split"] = {
            "value": nl_pct,
            "display": f"NL {nl_pct}% · FR {100 - nl_pct}%",
            "detail": f"NL {_human(nl_n)} reviews @ {rmap.get('nl', (0,0))[1]}★ · "
                      f"FR {_human(fr_n)} @ {rmap.get('fr', (0,0))[1]}★",
        }

    # ── Category Share of Voice (public side) — brand vs category peers ────────
    from core.framework_catalog import category_family, PRIMARY_CATEGORIES
    from intelligence.brand_potential_index import _atc_class_peers
    peer_rows, basis = None, None
    atc_ids = _atc_class_peers(db, brand)
    if len(atc_ids) > 1:
        rows = db.execute(text("""
            SELECT b.id, b.name, count(me.id) AS cnt
            FROM brands b
            LEFT JOIN mention_entities me ON me.entity_id = b.id AND me.entity_type = 'brand'
            WHERE b.id = ANY(:ids)
            GROUP BY b.id, b.name
        """), {"ids": atc_ids}).mappings().all()
        peer_rows = list(rows)
        basis = "ATC-class peers' voice"
    elif brand.category:
        fam = category_family(brand.category)
        rows = db.execute(text("""
            SELECT b.id, b.name, b.category,
                   (SELECT count(*) FROM mention_entities me
                      WHERE me.entity_type = 'brand' AND me.entity_id = b.id) AS cnt
            FROM brands b WHERE b.category IS NOT NULL
        """)).mappings().all()
        peer_rows = [r for r in rows if category_family(r["category"]) == fam]
        basis = f"{fam} review voice"
    # Fall back to the primary_category bucket when the fine-category frame is degenerate
    _peers_with_voice = 0 if peer_rows is None else sum(1 for r in peer_rows if int(r["cnt"] or 0) > 0)
    if (peer_rows is None or _peers_with_voice <= 1) and brand.primary_category:
        rows = db.execute(text("""
            SELECT b.id, b.name, count(me.id) AS cnt
            FROM brands b
            JOIN mention_entities me ON me.entity_id = b.id AND me.entity_type = 'brand'
            WHERE b.primary_category = :pc
            GROUP BY b.id, b.name
        """), {"pc": brand.primary_category}).mappings().all()
        peer_rows = list(rows)
        lbl = next((c["label_fr"] for c in PRIMARY_CATEGORIES if c["code"] == brand.primary_category),
                   brand.primary_category)
        basis = f"{brand.primary_category} · {lbl} review voice"
    if peer_rows is not None:
        total = sum(int(r["cnt"] or 0) for r in peer_rows)
        my_cnt = next((int(r["cnt"] or 0) for r in peer_rows if r["id"] == bid), linked)
        peer_count = len(peer_rows)
        if peer_count <= 1 or total == 0:
            sole = {"value": None, "display": "Sole tracked brand",
                    "detail": f"only tracked brand with voice in {basis} — add peers for a real share"}
            out["mk_share_of_voice"] = dict(sole)
            out["bm_voice_share"] = dict(sole)
        else:
            sov = round(100 * my_cnt / total)
            sov_disp = "<1%" if (sov == 0 and my_cnt > 0) else f"{sov}%"
            # Ranked peer table (name + share), most-talked-about first.
            peers = sorted(
                ({"name": r["name"], "share": round(100 * int(r["cnt"] or 0) / total),
                  "is_self": r["id"] == bid} for r in peer_rows),
                key=lambda p: p["share"], reverse=True,
            )
            rank = next((i + 1 for i, p in enumerate(peers) if p["is_self"]), peer_count)
            # Show the top peers but always include self so the user sees their slot.
            display = peers[:8]
            if not any(p["is_self"] for p in display):
                self_p = next((p for p in peers if p["is_self"]), None)
                if self_p:
                    display = peers[:7] + [self_p]
            sov_card = {"value": sov,
                        "display": sov_disp,
                        "detail": f"of {basis} · #{rank} of {peer_count}",
                        "peers": display,
                        "peers_label": "Category mix",
                        "rank": rank,
                        "peer_count": peer_count}
            out["mk_share_of_voice"] = sov_card
            out["bm_voice_share"] = dict(sov_card)

    # ── Demand momentum (engine; may be sparse) ──────────────────────────────
    # Use the SAME 90-day window as the Brand Pulse "Demand momentum" panel
    # (search_intelligence._MOM_PERIOD) so the number can never diverge between
    # the panel and the "What this means" insight — one metric, one value.
    try:
        from intelligence.momentum import compute_momentum
        m = compute_momentum(db, "brand", bid, period="90d")
        total_vol = m.current_count + m.prev_count + m.prev_prev_count
        if total_vol > 0:
            if not m.has_signal:
                det = (f"recent {m.current_count} · prior {m.prev_count} · earlier "
                       f"{m.prev_prev_count} mentions — too few (n={total_vol}) for a momentum score")
                out["mk_search_momentum"] = {"value": None,
                    "display": f"{m.current_count} mention(s) (90d)", "detail": det, "confidence": "low"}
                out["mk_pivot_alert"] = {"value": None,
                    "display": f"{total_vol} mentions · low volume", "detail": det, "confidence": "low"}
            else:
                val = round(float(m.momentum_score))
                trend = "rising" if val >= 60 else "cooling" if val < 40 else "stable"
                out["mk_search_momentum"] = {"value": val, "display": f"{val}/100",
                    "detail": f"mention-volume momentum (n={total_vol})", "confidence": "ok"}
                out["mk_pivot_alert"] = {"value": val, "display": trend.capitalize(),
                    "detail": f"weak-signal momentum {val}/100 — {trend}", "confidence": "ok"}
    except Exception:
        pass

    # ── Launch readiness (brand_manager; partial — public legs only) ─────────
    try:
        from intelligence.launch_readiness import compute_launch_readiness
        h = _headline(compute_launch_readiness(db, bid))
        if h and (h.get("sample_size") or 0) > 0 and h.get("value") is not None:
            val = round(float(h["value"]))
            out["bm_launch_readiness"] = {
                "value": val, "display": f"{val}/100",
                "detail": h.get("label") or "composite (public legs only)",
            }
    except Exception:
        pass

    # ── Decision-shaped KPIs (action cues per role) ─────────────────────────
    rt2 = retail_meta(brand.name)
    stock = rt2.get("in_stock_pct")

    # Pharmacist · Availability risk → order ahead / substitute
    if stock is not None:
        lvl = "High" if stock < 20 else "Medium" if stock < 50 else "Low"
        cue = ("order ahead / propose a substitute" if lvl == "High"
               else "keep an eye on stock" if lvl == "Medium" else "readily available")
        out["ph_availability_risk"] = {"value": 100 - stock, "display": f"{lvl} risk",
                                       "detail": f"{stock}% of SKUs in stock online — {cue}"}

    # Pharmacist · Substitution options → who to recommend instead (same family)
    if brand.category:
        from core.framework_catalog import category_family
        fam = category_family(brand.category)
        all_peers = db.execute(text(
            "SELECT name, category FROM brands WHERE id <> :bid AND category IS NOT NULL"),
            {"bid": bid}).mappings().all()
        peers = [r["name"] for r in all_peers if category_family(r["category"]) == fam]
        in_stock = [p for p in peers if (retail_meta(p).get("in_stock_pct") or 0) >= 10]
        shown = in_stock or peers  # medicines aren't in the retail catalogue → list tracked alternatives
        suffix = " in stock" if in_stock else ""
        out["ph_substitution"] = {
            "value": len(shown),
            "display": f"{len(shown)} alternative" + ("" if len(shown) == 1 else "s") + suffix,
            "detail": (f"in {brand.category}: " + ", ".join(shown[:4])) if shown
                      else "no same-category alternatives tracked",
        }

    # Pharmacist · Patient out-of-pocket → flag cost
    price = (meta.get("price") or {}).get("avg") or (rt2.get("price") or {}).get("avg")
    if is_medicine and price:
        if (meta.get("reimbursed_packs") or 0) > 0:
            cp = (meta.get("reimbursement") or {}).get("copay")
            cat = "/".join((meta.get("reimbursement") or {}).get("categories") or [])
            out["ph_out_of_pocket"] = {"value": cp, "display": f"~€{cp} co-pay" if cp else "Reimbursed",
                                       "detail": f"RIZIV-reimbursed{(' cat ' + cat) if cat else ''} — low patient cost"}
        else:
            out["ph_out_of_pocket"] = {"value": price, "display": f"~€{price} (full price)",
                                       "detail": "not reimbursed — patient pays full price; suggest cheaper equivalents if cost-sensitive"}
    elif price:
        out["ph_out_of_pocket"] = {"value": price, "display": f"~€{price}",
                                   "detail": "parapharmacy — full retail price"}

    # Pharmacist · Safety watch → warn / counsel / clear
    if is_medicine:
        flags = []
        if meta.get("black_triangle"):
            flags.append("▲ additional EU monitoring")
        if fda > 0:
            flags.append(f"{fda} AE reports (BE)")
        if bcfi > 0:
            flags.append(f"{bcfi} BCFI notes")
        level = "Watch" if (meta.get("black_triangle") or fda >= 5) else "Monitor" if flags else "Clear"
        out["ph_safety_watch"] = {"value": level, "display": level,
                                  "detail": "; ".join(flags) if flags else "no active safety signals"}
    else:
        out["ph_safety_watch"] = {"value": None, "display": "n/a", "detail": "not a medicine"}

    # Brand manager · Distribution breadth → where it's leaking
    skus = rt2.get("skus") or 0
    packs = len(meta.get("cnk") or [])
    if skus or packs:
        base = max(skus, packs)
        unit = "retail SKUs" if skus >= packs else "SAM packs"
        breadth = "Broad" if base >= 50 else "Moderate" if base >= 15 else "Narrow"
        out["bm_distribution_breadth"] = {
            "value": base, "display": f"{breadth} · {base} {unit}",
            "detail": f"{packs} SAM packs · {skus} retail SKUs"
                      + (f" · {stock}% in stock" if stock is not None else ""),
        }

    # Brand manager · Promo pressure → match or hold
    if rt2.get("skus"):
        promo = rt2.get("promo_pct", 0)
        disc = rt2.get("avg_discount", 0)
        lvl = "High" if promo >= 40 else "Moderate" if promo >= 15 else "Low"
        out["bm_promo_pressure"] = {
            "value": promo, "display": f"{lvl} · {promo}% on promo",
            "detail": f"{promo}% of SKUs discounted, avg {disc}% off — "
                      + ("match or hold the line" if lvl == "High" else "pricing headroom"),
        }

    # Marketing · Claim consistency (claims vs evidence) → substantiate or soften
    benefits = rt2.get("benefits") or []
    if benefits:
        ev = pubmed + bcfi
        if ev >= 10:
            score, msg = 85, "well-substantiated by literature / clinical guidance"
        elif ev >= 3:
            score, msg = 60, "partially substantiated — strengthen the weaker claims"
        else:
            score, msg = 30, "claims outpace published evidence — substantiate or soften before a regulator/competitor does"
        out["mk_claims_consistency"] = {
            "value": score, "display": f"{score}/100",
            "detail": f"{len(benefits)} claim themes vs {ev} evidence items ({pubmed} papers, {bcfi} BCFI) — {msg}",
        }

    # ── NUT · Health-claim substantiation (EU Register of Health Claims) ───────
    # Supplements aren't medicines (no SAM/ATC), so the EU claims register is the
    # authoritative positioning/compliance signal. Substances are derived from the
    # brand's review/retail text (a proxy — honest about it in the detail copy).
    try:
        from intelligence.health_claims import substantiation_for_brand
        hc = substantiation_for_brand(db, brand)
        if hc:
            out["nut_claim_substantiation"] = hc
    except Exception:
        pass

    # ── OTC (cosmetic) · EU Safety Gate recall watch ──────────────────────────
    feed_live = db.execute(text(
        "SELECT EXISTS(SELECT 1 FROM mentions WHERE source_type='safety_gate' AND is_deleted=false)"
    )).scalar()
    if not feed_live:
        out["otc_safety_gate"] = {
            "value": None, "display": "Feed not connected",
            "detail": "EU Safety Gate (RAPEX) not ingested yet — can't assert a clean record",
        }
    else:
        out["otc_safety_gate"] = {
            "value": safety_gate,
            "display": "No EU recall on record" if safety_gate == 0 else f"{safety_gate} recall alert(s)",
            "detail": ("checked the full EU Safety Gate (RAPEX) cosmetics alert set — this brand is not listed"
                       if safety_gate == 0
                       else "EU Safety Gate (RAPEX) cosmetic safety alert(s) naming this brand"),
        }

    # ── Pharmacist · Belgian shortage watch — Belgium-first, from SAM supply data ──
    if is_medicine:
        sup = meta.get("supply") or {}
        active = sup.get("active_problems", 0)
        if active:
            end, reason = sup.get("expected_end"), sup.get("reason")
            out["ph_be_shortage"] = {
                "value": active,
                "display": f"Supply problem (BE) · {active} pack{'s' if active != 1 else ''}",
                "detail": "active SAM/FAGG supply problem"
                          + (f" — {reason}" if reason else "")
                          + (f"; expected back {end}" if end else ""),
            }
        elif sup.get("end_of_commercialisation") == "temporary":
            out["ph_be_shortage"] = {"value": 1, "display": "Temporary withdrawal (BE)",
                                     "detail": "temporarily out of commercialisation (SAM)"}
        elif sup.get("limited_availability"):
            out["ph_be_shortage"] = {"value": 1, "display": "Limited availability (BE)",
                                     "detail": "limited availability flagged in SAM"}
        elif fagg_short:
            out["ph_be_shortage"] = {"value": fagg_short,
                                     "display": f"{fagg_short} BE shortage notice(s)",
                                     "detail": "Belgian FAGG/AFMPS shortage register"}
        else:
            out["ph_be_shortage"] = {"value": 0, "display": "No BE supply issue",
                                     "detail": "no active supply problem in SAM/FAGG"}
        # French ANSM list — the cross-border complement for the FR-speaking market.
        out["ph_fr_availability"] = {
            "value": ansm_short,
            "display": "No FR shortage listed" if ansm_short == 0 else f"{ansm_short} FR shortage notice(s)",
            "detail": ("not on the French ANSM shortage/availability list"
                       if ansm_short == 0
                       else "listed on the French ANSM medicine shortage/availability register (substance match)"),
        }

        # ── Dispensing status (Rx vs OTC) — SAM DeliveryModus, REF-decoded ──
        deliv = meta.get("delivery")
        if deliv:
            status = deliv["status"]
            disp = {"otc": "OTC — no prescription",
                    "prescription": "Prescription-only (Rx)",
                    "mixed": "Mixed — Rx + OTC packs"}[status]
            out["ph_delivery_status"] = {
                "value": status, "display": disp,
                "detail": "Belgian SAM dispensing status (DeliveryModus): "
                          + (", ".join(deliv["otc_codes"] + deliv["rx_codes"])),
            }

        # ── Price position in the reimbursement cluster — SAM Cheapest/HeadOfTheCluster ──
        pp = meta.get("pricing_position")
        if pp and pp.get("cluster_packs"):
            ct, tot = pp["cheapest_packs"], pp["cluster_packs"]
            share = round(100 * ct / tot) if tot else 0
            if pp.get("all_cheapest"):
                disp = "Cheapest in every cluster"
            elif ct:
                disp = f"Cheapest in {share}% of packs"
            else:
                disp = "Above reference price"
            out["bm_price_position"] = {
                "value": share, "display": disp,
                "detail": f"{ct}/{tot} pack(s) flagged cheapest in their Belgian "
                          f"reference-reimbursement cluster (SAM)",
            }

        # ── Generic competition — molecule's marketer count (SAM, all MAHs) ──
        mc = meta.get("molecule_competition")
        if mc:
            n = mc["n_marketers"]
            if n <= 1:
                disp = "Sole-source — no generic competition"
            else:
                disp = f"Genericized — {mc['generics']} other marketer(s)"
            out["bm_generic_status"] = {
                "value": n, "display": disp,
                "detail": f"{n} marketing-authorisation holder(s) market {mc['molecule']} "
                          f"in Belgium (SAM)",
            }

    # ── Manufacturer / MAH + SAM-registered portfolio (B2B / supplier brands) ──
    company = meta.get("company")
    if company:
        out["bm_manufacturer"] = {
            "value": company, "display": company,
            "detail": "marketing-authorisation holder / producer (Belgian SAM/FAGG)",
        }
    pf = meta.get("sam_portfolio")
    if pf and (pf.get("medicines") or pf.get("parapharmacy")):
        tot = pf["medicines"] + pf["parapharmacy"]
        bits = []
        if pf["medicines"]:
            bits.append(f"{pf['medicines']} registered medicines")
        if pf["parapharmacy"]:
            bits.append(f"{pf['parapharmacy']} parapharmacy SKUs")
        atc = pf.get("atc_classes") or []
        sup_n = pf.get("supply_problems") or 0
        out["bm_sam_portfolio"] = {
            "value": tot, "display": f"{_human(tot)} SAM-registered products",
            "detail": "Belgian SAM/FAGG range: " + ", ".join(bits)
                      + (f" · {len(atc)} ATC class{'es' if len(atc) != 1 else ''}" if atc else "")
                      + (f" · {sup_n} with active BE supply problems" if sup_n else ""),
        }

    return out


# ATC (anatomical-therapeutic) → the Belgian prescriber specialty that drives it.
# Longest-prefix match. Used to make HCP targeting brand-specific from SAM's ATC.
_ATC_SPECIALTY = {
    "N03": "Neurologists (epilepsy)", "N04": "Neurologists", "N05": "Psychiatrists",
    "N06": "Psychiatrists / Neurologists", "N02": "GPs / Pain specialists",
    "M01": "Rheumatologists / GPs", "M05": "Rheumatologists", "M04": "GPs / Rheumatologists",
    "A02": "Gastroenterologists / GPs", "A07": "Gastroenterologists / GPs",
    "A10": "Endocrinologists (diabetes)", "A11": "GPs",
    "R03": "Pulmonologists", "R06": "Allergologists / GPs", "R02": "ENT / GPs", "R01": "ENT specialists",
    "L04": "Immunologists / Dermatologists / Rheumatologists", "L01": "Oncologists",
    "C": "Cardiologists", "D": "Dermatologists", "G": "Gynaecologists / Urologists",
    "S": "Ophthalmologists / ENT", "J": "Infectiologists / GPs", "B": "Haematologists",
}


def hcp_target(brand, meta: dict) -> Optional[dict]:
    """Brand-specific prescriber target derived from the SAM ATC code."""
    atc = (meta.get("atc") or [])
    if not atc:
        return None
    code = atc[0]["code"]
    spec = None
    for k in sorted(_ATC_SPECIALTY, key=len, reverse=True):
        if code.startswith(k):
            spec = _ATC_SPECIALTY[k]
            break
    substance = (meta.get("primary") or [None])[0]
    return {"specialty": spec or "Specialist prescribers", "atc": code,
            "atc_desc": atc[0].get("desc"), "substance": substance}


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 11 <= n % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def compute_insights(brand: Brand, live: Dict[str, dict], role: str) -> List[str]:
    """Plain-language "what this means" bullets derived from the live KPI values.

    Turns the raw numbers into the read a human would give them — leader vs
    laggard, where the growth lever is, and what's still blocked on a feed — so
    the dashboard interprets itself instead of leaving the user to.
    """
    out: List[str] = []

    sov = live.get("mk_share_of_voice") or live.get("bm_voice_share")
    if sov and sov.get("peers"):
        rank, n, share = sov["rank"], sov["peer_count"], sov["value"]
        leader = sov["peers"][0]
        if rank == 1:
            runner = sov["peers"][1] if len(sov["peers"]) > 1 else None
            tail = f" — {share - runner['share']} pts ahead of {runner['name']}." if runner else "."
            out.append(f"{brand.name} leads {brand.category} with {share}% of review voice ({n} brands tracked){tail}")
        else:
            out.append(
                f"{brand.name} holds {share}% of {brand.category} review voice — {_ordinal(rank)} of {n}; "
                f"{leader['name']} leads at {leader['share']}%. Closing that gap is the share-growth target."
            )

    sent = live.get("mk_sentiment_trend") or live.get("ph_patient_sentiment")
    if sent and sent.get("value") is not None:
        # value is None when the polar base is too thin (raw-counts mode) — no %
        # to interpret, so skip the sentiment headline rather than crash.
        p = sent["value"]
        if p >= 90:
            out.append(f"Sentiment is overwhelmingly positive ({p}%) — perception is a strength, so reach and availability are the growth levers, not the message.")
        elif p >= 75:
            out.append(f"Sentiment is solidly positive ({p}%); protect it as you scale spend.")
        else:
            out.append(f"Sentiment is only {p}% positive — investigate the negative drivers before pushing more spend.")

    rev = live.get("mk_review_trend") or live.get("ph_demand_signal")
    if rev and rev.get("count"):
        c = rev["count"]
        base = "a large, reliable base" if c >= 1000 else "a modest base — read trends with some caution" if c >= 100 else "a thin base — treat as directional only"
        out.append(f"{_human(c)} reviews analysed: {base}.")

    # The honest gap: roles whose core KPIs are proprietary still run on proxies.
    if role in ("brand_manager", "pharmacist"):
        out.append("Sales / sell-out KPIs are still on public proxies. Connecting a sell-out feed turns voice share into true market share and unlocks the locked cards above.")

    return out[:5]
