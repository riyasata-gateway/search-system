"""Datatopia Brand → Source → KPI Framework (Belgium) — the data layer.

This module is the single source of truth for the *Datatopia_Brand_Source_KPI_Belgium*
workbook: the four questions it answers are encoded here as structured data:

  1. WHICH brands to track          -> TOP_BRANDS
  2. WHERE their data comes from     -> DATA_SOURCES (with Tier A/B/C + DIA layer)
  3. WHAT each source gives us       -> DATA_TO_KPI (source -> per-role KPI matrix)
  4. WHICH KPI it drives per role    -> KPI_LIBRARY (logic, metric type, data, DIA layer)

It is reference/spec data, not transactional, so it lives in code (queryable via
`api/routers/catalog.py`) rather than a migration. The *brands* themselves are
additionally upserted into the `brands` table by `scripts/seed_brand_catalog.py`
so the existing intelligence engines (BPI, momentum, SoV, …) operate on them.

Honesty about data: every KPI carries a `data_status`:
  • "live"        — backed by real ingested data today (mentions, reviews, trends)
  • "partial"     — engine exists and runs, but the proprietary leg is sparse
  • "data_needed" — Tier-C proprietary feed (sell-out / IQVIA / wholesaler /
                    loyalty / Farmanet) not yet connected; the KPI is scaffolded
                    but the UI shows a "connect feed" badge rather than a number.

The three dashboard roles in the workbook map to our four app roles
(`admin` is a super-view that sees everything).
"""
from __future__ import annotations

from typing import Dict, List, Optional

# ── Primary supplier taxonomy (5-code, MECE) ─────────────────────────────────
# The Belgian supplier-categorisation workbook assigns every supplier ONE primary
# category. `code` is the stable join key stored on brands.primary_category;
# `label_fr` is the UI label (from the in-app category picker); `definition` is the
# classification rule that drove the assignment. Ordered as shown in the picker.
PRIMARY_CATEGORIES: List[Dict] = [
    {"code": "NUT", "label_fr": "Nutritionnel", "label_en": "Nutritional",
     "definition": "Nutritionals, food supplements, vitamins, dietetic products, clinical nutrition, probiotics."},
    {"code": "RX", "label_fr": "Prescription", "label_en": "Prescription",
     "definition": "Prescription/regulated medicines and pharmaceutical MAH/manufacturers. Veterinary pharma when explicitly pharmaceutical."},
    {"code": "PAC", "label_fr": "Soins Patient", "label_en": "Patient care",
     "definition": "Patient care, medical devices, diagnostics, dental/eye care, wound care, incontinence, homecare, pet/veterinary care products."},
    {"code": "PEC", "label_fr": "Soins Personnels", "label_en": "Professional / personal care",
     "definition": "Professional care: hospital, laboratory, gases, sterile/instrumentation, wholesale/distribution/logistics and institutional suppliers."},
    {"code": "OTC", "label_fr": "Vente Libre", "label_en": "Over-the-counter",
     "definition": "Non-prescription medicines, dermocosmetics, personal care, aromatherapy/herbal self-care and retail para-pharmacy brands."},
]
PRIMARY_CATEGORY_CODES = [c["code"] for c in PRIMARY_CATEGORIES]


# ── Data tiers ───────────────────────────────────────────────────────────────
# A = public web (commoditised, scrapeable) · B = Belgian official (registry/open)
# C = proprietary (pharmacy sell-out, wholesaler sell-in, loyalty) — the moat.
TIER_LABELS: Dict[str, str] = {
    "A": "Public web",
    "B": "Belgian official",
    "C": "Proprietary (sellable)",
}

# Workbook role labels -> our app UserRole values.
ROLE_LABELS: Dict[str, str] = {
    "pharmacist": "Pharmacist",
    "brand_manager": "Brand Manager",
    "marketing": "Marketing",
}

# The join key that makes cross-source aggregation clean (APB national code).
JOIN_KEY = "CNK code (APB national code) — pack-level identifier shared across pharmacies, wholesalers and manufacturers."

CORE_INSIGHT = (
    "Public data tells you what people TALK about; sell-out tells you what they BUY. "
    "The premium product is the CORRELATION between the two (e.g. 'buzz up 40%, "
    "sell-out flat = awareness not converting'). Only a platform holding both sides can sell this."
)


# ── 1 · TOP BRANDS — Belgian pharmacy channel ────────────────────────────────
# kpi_roles = which roles primarily care about this brand (workbook "Primary KPI interest").
TOP_BRANDS: List[Dict] = [
    {"name": "La Roche-Posay", "category": "Dermocosmetics", "owner": "L'Oréal",
     "tier_a_signal": "Reviews (farmaline/medi-market/newpharma/viata), Google Trends, social, online price",
     "tier_bc_signal": "FAGG/SAM master, own sell-out, IQVIA Consumer Health",
     "kpi_roles": ["marketing", "brand_manager"], "country": ["BE", "FR"]},
    {"name": "Avène", "category": "Dermocosmetics", "owner": "Pierre Fabre",
     "tier_a_signal": "Reviews, Google Trends, social, online price",
     "tier_bc_signal": "SAM master, own sell-out, IQVIA",
     "kpi_roles": ["marketing", "brand_manager"], "country": ["BE", "FR"]},
    {"name": "Vichy", "category": "Dermocosmetics", "owner": "L'Oréal",
     "tier_a_signal": "Reviews, Google Trends, social, online price",
     "tier_bc_signal": "SAM master, own sell-out, IQVIA",
     "kpi_roles": ["marketing", "brand_manager"], "country": ["BE", "FR"]},
    {"name": "Bioderma", "category": "Dermocosmetics", "owner": "NAOS",
     "tier_a_signal": "Reviews, Google Trends, social, online price",
     "tier_bc_signal": "SAM master, own sell-out, IQVIA",
     "kpi_roles": ["marketing", "brand_manager"], "country": ["BE", "FR"]},
    {"name": "CeraVe", "category": "Dermocosmetics", "owner": "L'Oréal",
     "tier_a_signal": "Reviews, Google Trends, social (high TikTok)",
     "tier_bc_signal": "own sell-out, IQVIA",
     "kpi_roles": ["marketing"], "country": ["BE", "FR"]},
    {"name": "Eucerin", "category": "Dermocosmetics", "owner": "Beiersdorf",
     "tier_a_signal": "Reviews, Google Trends, online price",
     "tier_bc_signal": "SAM master, own sell-out, IQVIA",
     "kpi_roles": ["brand_manager", "marketing"], "country": ["BE", "FR"]},
    {"name": "Caudalie", "category": "Dermocosmetics", "owner": "Caudalie",
     "tier_a_signal": "Reviews, social, Google Trends",
     "tier_bc_signal": "own sell-out, IQVIA",
     "kpi_roles": ["marketing"], "country": ["BE", "FR"]},
    {"name": "ISDIN", "category": "Dermocosmetics (sun)", "owner": "ISDIN",
     "tier_a_signal": "Reviews, Google Trends (seasonal)",
     "tier_bc_signal": "own sell-out, IQVIA",
     "kpi_roles": ["brand_manager"], "country": ["BE", "FR"]},
    {"name": "Dafalgan", "category": "OTC analgesic", "owner": "Viatris / Upjohn",
     "tier_a_signal": "Google Trends, news, limited reviews",
     "tier_bc_signal": "SAM master, PharmaStatus, RIZIV/Farmanet, own sell-out, IQVIA Rx",
     "kpi_roles": ["pharmacist", "brand_manager"], "country": ["BE", "FR"]},
    {"name": "Perdolan", "category": "OTC analgesic", "owner": "Kenvue (J&J)",
     "tier_a_signal": "Google Trends, news",
     "tier_bc_signal": "SAM, PharmaStatus, own sell-out, IQVIA",
     "kpi_roles": ["pharmacist", "brand_manager"], "country": ["BE"]},
    {"name": "Nurofen", "category": "OTC analgesic", "owner": "Reckitt",
     "tier_a_signal": "Reviews, Google Trends, social",
     "tier_bc_signal": "SAM, PharmaStatus, own sell-out, IQVIA",
     "kpi_roles": ["brand_manager", "pharmacist"], "country": ["BE", "FR"]},
    {"name": "Voltaren", "category": "OTC topical NSAID", "owner": "Haleon",
     "tier_a_signal": "Reviews, Google Trends",
     "tier_bc_signal": "SAM, PharmaStatus, own sell-out, IQVIA",
     "kpi_roles": ["brand_manager"], "country": ["BE", "FR"]},
    {"name": "Strepsils", "category": "OTC throat", "owner": "Reckitt",
     "tier_a_signal": "Reviews, Google Trends (seasonal)",
     "tier_bc_signal": "SAM, own sell-out, IQVIA",
     "kpi_roles": ["pharmacist", "marketing"], "country": ["BE", "FR"]},
    {"name": "Imodium", "category": "OTC GI", "owner": "Kenvue (J&J)",
     "tier_a_signal": "Google Trends, reviews",
     "tier_bc_signal": "SAM, PharmaStatus, own sell-out",
     "kpi_roles": ["pharmacist", "brand_manager"], "country": ["BE", "FR"]},
    {"name": "Bepanthol / Bepanthen", "category": "Skin / wound care", "owner": "Bayer",
     "tier_a_signal": "Reviews, Google Trends",
     "tier_bc_signal": "SAM, own sell-out, IQVIA",
     "kpi_roles": ["brand_manager"], "country": ["BE", "FR"]},
    {"name": "Fenistil", "category": "OTC antihistamine", "owner": "Haleon",
     "tier_a_signal": "Google Trends (seasonal), reviews",
     "tier_bc_signal": "SAM, PharmaStatus, own sell-out",
     "kpi_roles": ["pharmacist", "marketing"], "country": ["BE", "FR"]},
    {"name": "Bion3", "category": "Supplements", "owner": "P&G",
     "tier_a_signal": "Reviews, Google Trends, social",
     "tier_bc_signal": "SAM, own sell-out, IQVIA Consumer Health",
     "kpi_roles": ["marketing", "brand_manager"], "country": ["BE", "FR"]},
    {"name": "D-Cure (vitamin D)", "category": "Supplements", "owner": "SMB Laboratoires (BE)",
     "tier_a_signal": "Google Trends (seasonal)",
     "tier_bc_signal": "SAM, RIZIV/Farmanet, own sell-out",
     "kpi_roles": ["pharmacist", "brand_manager"], "country": ["BE"]},
    {"name": "Davitamon", "category": "Supplements", "owner": "Perrigo / Omega Pharma",
     "tier_a_signal": "Reviews, Google Trends, social",
     "tier_bc_signal": "own sell-out, IQVIA",
     "kpi_roles": ["marketing"], "country": ["BE"]},
    {"name": "Solgar", "category": "Supplements", "owner": "Nestlé Health Science",
     "tier_a_signal": "Reviews, Google Trends",
     "tier_bc_signal": "own sell-out",
     "kpi_roles": ["brand_manager", "marketing"], "country": ["BE", "FR"]},
    {"name": "Metagenics", "category": "Supplements (HCP)", "owner": "Metagenics",
     "tier_a_signal": "Limited reviews, Google Trends",
     "tier_bc_signal": "own sell-out, HCP feedback",
     "kpi_roles": ["brand_manager"], "country": ["BE"]},
    {"name": "Aptamil", "category": "Infant nutrition", "owner": "Danone / Nutricia",
     "tier_a_signal": "Reviews, forums, Google Trends",
     "tier_bc_signal": "SAM, PharmaStatus (recall watch), own sell-out",
     "kpi_roles": ["pharmacist", "brand_manager"], "country": ["BE", "FR"]},
    {"name": "Mustela", "category": "Baby care", "owner": "Expanscience",
     "tier_a_signal": "Reviews, social, Google Trends",
     "tier_bc_signal": "own sell-out, IQVIA",
     "kpi_roles": ["marketing"], "country": ["BE", "FR"]},
    {"name": "UCB brands (Keppra, Bimzelx)", "category": "Rx specialty", "owner": "UCB (BE)",
     "tier_a_signal": "News, PubMed, ClinicalTrials",
     "tier_bc_signal": "RIZIV/Farmanet, SAM, IQVIA Rx panel, HCP/KOL feedback",
     "kpi_roles": ["brand_manager"], "country": ["BE"]},
    {"name": "Tilman (phyto)", "category": "Phytotherapy", "owner": "Tilman (BE)",
     "tier_a_signal": "Reviews, Google Trends",
     "tier_bc_signal": "SAM, own sell-out",
     "kpi_roles": ["pharmacist", "marketing"], "country": ["BE"]},
    {"name": "Rennie", "category": "OTC GI", "owner": "Bayer",
     "tier_a_signal": "Reviews, Google Trends",
     "tier_bc_signal": "SAM, PharmaStatus, own sell-out, IQVIA",
     "kpi_roles": ["pharmacist", "brand_manager"], "country": ["BE", "FR"]},
    {"name": "Gaviscon", "category": "OTC GI", "owner": "Reckitt",
     "tier_a_signal": "Reviews, Google Trends, social",
     "tier_bc_signal": "SAM, PharmaStatus, own sell-out, IQVIA",
     "kpi_roles": ["pharmacist", "brand_manager"], "country": ["BE", "FR"]},
    {"name": "Enterol", "category": "OTC GI", "owner": "Biocodex",
     "tier_a_signal": "Reviews, Google Trends",
     "tier_bc_signal": "SAM, PharmaStatus, own sell-out",
     "kpi_roles": ["pharmacist", "brand_manager"], "country": ["BE", "FR"]},
    {"name": "Otrivine", "category": "OTC cold / nasal", "owner": "Haleon",
     "tier_a_signal": "Reviews, Google Trends (seasonal), social",
     "tier_bc_signal": "SAM, PharmaStatus, own sell-out, IQVIA",
     "kpi_roles": ["pharmacist", "marketing"], "country": ["BE", "FR"]},
    {"name": "Arkopharma", "category": "Supplements (phyto)", "owner": "Arkopharma",
     "tier_a_signal": "Reviews, Google Trends, official brand catalogue",
     "tier_bc_signal": "Own sell-out, retail pack pages",
     "kpi_roles": ["brand_manager", "marketing"], "country": ["BE", "FR"]},
    {"name": "Puressentiel", "category": "Aromatherapy / supplements", "owner": "Puressentiel",
     "tier_a_signal": "Reviews, social, Google Trends, official brand catalogue",
     "tier_bc_signal": "Own sell-out, retail pack pages",
     "kpi_roles": ["marketing", "brand_manager"], "country": ["BE", "FR"]},
]


# ── 2 · DATA SOURCES — reference ─────────────────────────────────────────────
# connector = the ingestion/connectors/* module that implements this source
# (None when the source is a proprietary feed we don't yet ingest).
DATA_SOURCES: List[Dict] = [
    {"name": "Google Trends", "tier": "A", "what_data": "Search interest by brand / molecule / symptom; FR vs NL regional split",
     "frequency": "Real-time / daily", "access": "Free", "dia_layer": "Detect", "connector": "google_trends", "available": True},
    {"name": "Social media (Meta, X, TikTok, Instagram)", "tier": "A", "what_data": "Mentions, sentiment, reach, share of voice, creator activity",
     "frequency": "Real-time", "access": "Free / API tiers", "dia_layer": "Detect", "connector": "licensed_api", "available": False},
    {"name": "Reddit / patient forums", "tier": "A", "what_data": "Unmet needs, off-label chatter, side-effect complaints (qualitative)",
     "frequency": "Continuous", "access": "Free", "dia_layer": "Detect", "connector": "reddit", "available": True},
    {"name": "Online pharmacy reviews (farmaline, medi-market, newpharma, viata, 24pharma)", "tier": "A",
     "what_data": "Star ratings, review volume, review sentiment per product page",
     "frequency": "Scrape daily", "access": "Free (scrape)", "dia_layer": "Detect / Interpret", "connector": "pharmacy_import", "available": True},
    {"name": "Online pharmacy pricing", "tier": "A", "what_data": "List price & promo price per SKU across e-tailers; cheapest-by-product",
     "frequency": "Scrape daily", "access": "Free (scrape)", "dia_layer": "Interpret", "connector": None, "available": False},
    {"name": "App store / Play reviews", "tier": "A", "what_data": "Patient-app sentiment & ratings (digital-health brands)",
     "frequency": "As posted", "access": "Free", "dia_layer": "Detect", "connector": "app_store", "available": True},
    {"name": "PubMed / ClinicalTrials.gov", "tier": "A", "what_data": "Evidence base, active trials, pipeline signals",
     "frequency": "Daily–weekly", "access": "Free", "dia_layer": "Detect (clinical credibility)", "connector": "pubmed", "available": True},
    {"name": "News / press", "tier": "A", "what_data": "Launches, recalls, regulatory & pricing events",
     "frequency": "Continuous", "access": "Free", "dia_layer": "Detect", "connector": "rss_news", "available": True},
    {"name": "FAGG geneesmiddelendatabank", "tier": "B", "what_data": "Product master: CNK, ATC, dosage form, pack size, Rx status, suspensions",
     "frequency": "Daily", "access": "Free / open data", "dia_layer": "Interpret (master spine)", "connector": "belgium_health_data", "available": True},
    {"name": "SAM (authentic source, eHealth)", "tier": "B", "what_data": "Authoritative medicine data fed real-time from FAGG; powers e-prescription",
     "frequency": "Real-time feed; viewer refreshes daily", "access": "Free / open data", "dia_layer": "Interpret", "connector": "belgium_health_data", "available": True},
    {"name": "PharmaStatus (FAGG)", "tier": "B", "what_data": "Availability / shortage status per pack",
     "frequency": "Near real-time", "access": "Free / open data", "dia_layer": "Detect / Act (substitution)", "connector": "belgium_health_data", "available": True},
    {"name": "RIZIV/INAMI Farmanet", "tier": "B", "what_data": "Reimbursed dispensations in community pharmacies (volume, expenditure)",
     "frequency": "Granular extract on request (lag); MORSE aggregate annual", "access": "Conditional access", "dia_layer": "Interpret", "connector": None, "available": False},
    {"name": "KCE / Sciensano", "tier": "B", "what_data": "HTA, epidemiology, public-health context for TA sizing",
     "frequency": "Periodic", "access": "Free", "dia_layer": "Interpret (context)", "connector": "belgium_health_data", "available": True},
    {"name": "OWN pharmacy sell-out (final_flat_file)", "tier": "C", "what_data": "Real units & value sold per CNK, per pharmacy, per day; transacted price; margin",
     "frequency": "Daily / weekly (your speed edge)", "access": "Owned — expand network", "dia_layer": "Interpret + Act (truth layer)", "connector": "pharmacy_import", "available": False},
    {"name": "IQVIA Belgium (Rx panel, Consumer Health, MIDAS)", "tier": "C", "what_data": "Dispensed-Rx & OTC sell-out, market share, trend (~30% panel)",
     "frequency": "Monthly", "access": "Paid licence", "dia_layer": "Interpret (benchmark)", "connector": "market_data", "available": False},
    {"name": "Wholesaler sell-in (Febelco, CERP, Pharma Belgium)", "tier": "C", "what_data": "Distribution wholesaler → pharmacy (sell-in volumes)",
     "frequency": "Daily / weekly", "access": "Partnership", "dia_layer": "Interpret", "connector": None, "available": False},
    {"name": "Pharmacy loyalty / basket data", "tier": "C", "what_data": "Co-purchase, repeat-buy, patient-journey baskets",
     "frequency": "Real-time", "access": "Partnership", "dia_layer": "Interpret + Act", "connector": None, "available": False},
    {"name": "Store-level stock / out-of-stock", "tier": "C", "what_data": "OOS events at store level driving substitution",
     "frequency": "Real-time", "access": "Partnership", "dia_layer": "Act", "connector": None, "available": False},
    {"name": "HCP / KOL feedback (field force CRM)", "tier": "C", "what_data": "Prescriber sentiment, detailing response, KOL signals",
     "frequency": "Continuous", "access": "Owned / partnership", "dia_layer": "Detect / Act (Rx brands)", "connector": None, "available": False},
]


# ── 3 · DATA → KPI by role (the core mapping) ────────────────────────────────
DATA_TO_KPI: List[Dict] = [
    {"source": "Own pharmacy sell-out", "what_it_tells": "Actual units/value sold per CNK, per pharmacy, per week + margin",
     "pharmacist": "Top sellers in my region",
     "brand_manager": "Sell-out volume & value trend; regional penetration (FR/NL); distribution coverage",
     "marketing": "Share of Market (the 'buy' side); sell-out lift after a campaign"},
    {"source": "IQVIA panel / MIDAS", "what_it_tells": "Category & competitor sell-out, market share, monthly trend",
     "pharmacist": "How my shelf compares to category norms",
     "brand_manager": "Market share by ATC vs competitors; category growth; launch benchmark",
     "marketing": "Share of market vs share of voice gap; category momentum"},
    {"source": "Google Trends", "what_it_tells": "Search interest by brand/symptom, FR vs NL split, seasonality",
     "pharmacist": "Trending symptom → OTC counseling cue; seasonal demand heads-up",
     "brand_manager": "Demand leading indicator; regional interest skew",
     "marketing": "Search momentum; predicts sell-out with lag; campaign timing"},
    {"source": "Social media", "what_it_tells": "Mentions, sentiment, reach, share of voice, creator activity",
     "pharmacist": "Emerging product questions patients will ask",
     "brand_manager": "Brand perception vs competitors; reputation risk",
     "marketing": "Share of voice; sentiment trend; creator/UGC impact; channel mix"},
    {"source": "Online pharmacy reviews", "what_it_tells": "Ratings, review volume, sentiment per SKU",
     "pharmacist": "What customers complain about → counseling & alternatives",
     "brand_manager": "Product satisfaction vs competitors; quality-issue early warning",
     "marketing": "Review rating & volume trend; sentiment driver analysis; SEO/UGC"},
    {"source": "FAGG / SAM master", "what_it_tells": "CNK, ATC, pack, Rx status, dosage form — the product master",
     "pharmacist": "Correct product info & Rx/OTC status at counter",
     "brand_manager": "Clean catalogue & ATC roll-ups for share math",
     "marketing": "Accurate brand-to-SKU mapping for all signal joins"},
    {"source": "PubMed / ClinicalTrials", "what_it_tells": "Evidence, pipeline, active trials",
     "pharmacist": "Evidence to support OTC advice",
     "brand_manager": "Pipeline & competitive threat; lifecycle stage",
     "marketing": "Evidence-led claims & content; thought-leadership timing"},
    {"source": "Wholesaler sell-in", "what_it_tells": "Distribution wholesaler → pharmacy",
     "pharmacist": "What stock is flowing into pharmacies near me",
     "brand_manager": "Sell-in vs sell-out gap (channel inventory build/draw)",
     "marketing": "Pipeline-fill signal vs true demand"},
    {"source": "HCP / KOL feedback", "what_it_tells": "Prescriber sentiment, detailing response, KOL signals",
     "pharmacist": "n/a (counter role)",
     "brand_manager": "HCP targeting by prescribing momentum; MSL deployment; KOL mapping",
     "marketing": "Key-message tuning; HCP campaign feedback loop"},
]


# ── 4 · KPI LIBRARY by role ──────────────────────────────────────────────────
# data_status: live | partial | data_needed   (see module docstring)
# endpoint:    API path that serves the KPI today (None when not yet wired)
KPI_LIBRARY: List[Dict] = [
    # Pharmacist
    {"key": "ph_regional_top_sellers", "role": "pharmacist", "kpi": "Regional top-sellers", "logic": "Rank CNKs by units/value sold in my area this week",
     "metric_type": "ABS", "data_sources": ["Own sell-out"], "dia_layer": "Interpret",
     "data_status": "data_needed", "endpoint": "/pharmacist/dashboard"},
    {"key": "ph_peer_assortment_gap", "role": "pharmacist", "kpi": "Peer assortment gap", "logic": "Products comparable pharmacies stock that I don't",
     "metric_type": "ABS", "data_sources": ["Own sell-out (network)"], "dia_layer": "Interpret",
     "data_status": "data_needed", "endpoint": None},
    {"key": "ph_patient_sentiment", "role": "pharmacist", "kpi": "Patient review sentiment", "logic": "Share of positive vs negative patient reviews for this brand (counter cue)",
     "metric_type": "%", "data_sources": ["Online pharmacy reviews"], "dia_layer": "Detect",
     "data_status": "live", "endpoint": "/catalog/brand-kpis"},
    {"key": "ph_brand_trust", "role": "pharmacist", "kpi": "Brand trust", "logic": "Pharmacist-perception index: 60% patient-review positivity + 40% recommendation density (share of opinions that actively recommend the brand)",
     "metric_type": "SCORE", "data_sources": ["Online pharmacy reviews"], "dia_layer": "Interpret",
     "data_status": "live", "endpoint": "/catalog/brand-kpis"},
    {"key": "ph_demand_signal", "role": "pharmacist", "kpi": "Public demand signal", "logic": "Review volume as a proxy for what patients are asking about",
     "metric_type": "ABS", "data_sources": ["Online pharmacy reviews", "Google Trends"], "dia_layer": "Detect",
     "data_status": "live", "endpoint": "/catalog/brand-kpis"},
    {"key": "ph_eu_safety", "role": "pharmacist", "kpi": "EU pharmacovigilance", "logic": "EudraVigilance (EMA) adverse-reaction monitoring for the brand's active substance — the EU-native safety signal that's relevant in Belgium",
     "metric_type": "ABS", "data_sources": ["EudraVigilance (EMA)"], "dia_layer": "Detect",
     "data_status": "live", "endpoint": "/catalog/brand-kpis"},
    {"key": "ph_safety_signals", "role": "pharmacist", "kpi": "Adverse-event reports (BE)", "logic": "Adverse-event reports that occurred in Belgium for the active substance (openFDA/FAERS, filtered to occurcountry=BE) — falls back to global only when there are no BE reports",
     "metric_type": "ABS", "data_sources": ["openFDA / FAERS (BE-filtered)"], "dia_layer": "Detect",
     "data_status": "live", "endpoint": "/catalog/brand-kpis"},
    {"key": "ph_patient_questions", "role": "pharmacist", "kpi": "Patient forum discussion", "logic": "Patient-forum threads naming the brand — what customers ask and worry about, to pre-empt at the counter",
     "metric_type": "ABS", "data_sources": ["Patient forums"], "dia_layer": "Detect",
     "data_status": "live", "endpoint": "/catalog/brand-kpis"},
    {"key": "ph_clinical_notes", "role": "pharmacist", "kpi": "BCFI clinical guidance", "logic": "Count of BCFI/CBIP (Belgian prescribing authority) clinical-commentary notes on the active substance — interactions, older-patient guidance, safety warnings to apply at the counter",
     "metric_type": "ABS", "data_sources": ["BCFI/CBIP"], "dia_layer": "Interpret",
     "data_status": "live", "endpoint": "/catalog/brand-kpis"},
    {"key": "ph_availability_risk", "role": "pharmacist", "kpi": "Availability risk", "logic": "Decision cue: how likely you are to be unable to dispense this brand. Low online stock → order ahead / propose a substitute now. From Belgian retail stock levels.",
     "metric_type": "SCORE", "data_sources": ["Farmaline (BE retail)"], "dia_layer": "Act",
     "data_status": "live", "endpoint": "/catalog/brand-kpis"},
    {"key": "ph_substitution", "role": "pharmacist", "kpi": "Substitution options", "logic": "Decision cue: if this brand is out, how many same-category brands are in stock to recommend instead.",
     "metric_type": "ABS", "data_sources": ["Farmaline (BE retail)"], "dia_layer": "Act",
     "data_status": "live", "endpoint": "/catalog/brand-kpis"},
    {"key": "ph_out_of_pocket", "role": "pharmacist", "kpi": "Patient out-of-pocket", "logic": "Decision cue: what the patient actually pays — full price if not reimbursed, co-pay if reimbursed — so you can flag cost and suggest cheaper equivalents. From SAM price + RIZIV reimbursement.",
     "metric_type": "ABS", "data_sources": ["SAM (FAGG)", "Farmaline"], "dia_layer": "Act",
     "data_status": "live", "endpoint": "/catalog/brand-kpis"},
    {"key": "ph_safety_watch", "role": "pharmacist", "kpi": "Safety watch", "logic": "Decision cue: a single flag combining EU additional-monitoring (▲), adverse-event reports and BCFI safety notes — warn / counsel or all-clear.",
     "metric_type": "SCORE", "data_sources": ["EudraVigilance", "openFDA", "BCFI", "SAM"], "dia_layer": "Act",
     "data_status": "live", "endpoint": "/catalog/brand-kpis"},
    {"key": "ph_complaint_rate", "role": "pharmacist", "kpi": "Complaint rate", "logic": "Share of negative patient reviews — a quality / counseling early-warning for the counter",
     "metric_type": "%", "data_sources": ["Online pharmacy reviews"], "dia_layer": "Detect",
     "data_status": "live", "endpoint": "/catalog/brand-kpis"},
    {"key": "ph_adverse_reactions", "role": "pharmacist", "kpi": "Top adverse reactions", "logic": "Most-reported adverse-reaction terms from openFDA reports naming this brand — what to watch for and counsel on",
     "metric_type": "ABS", "data_sources": ["openFDA / FAERS"], "dia_layer": "Detect",
     "data_status": "live", "endpoint": "/catalog/brand-kpis"},
    # Brand Manager
    {"key": "bm_sellout_share", "role": "brand_manager", "kpi": "Sell-out market share", "logic": "Brand units/value ÷ ATC-class total",
     "metric_type": "%", "data_sources": ["Own sell-out", "IQVIA"], "dia_layer": "Interpret",
     "data_status": "data_needed", "endpoint": "/intelligence/bpi/{brand_id}"},
    {"key": "bm_sellout_trend", "role": "brand_manager", "kpi": "Sell-out trend", "logic": "Units/value growth WoW / MoM vs prior period",
     "metric_type": "%", "data_sources": ["Own sell-out", "IQVIA"], "dia_layer": "Interpret",
     "data_status": "data_needed", "endpoint": "/intelligence/momentum/brand/{brand_id}"},
    {"key": "bm_regional_penetration", "role": "brand_manager", "kpi": "Regional penetration", "logic": "Sell-out split FR vs NL vs DE; % pharmacies stocking",
     "metric_type": "%", "data_sources": ["Own sell-out"], "dia_layer": "Interpret",
     "data_status": "data_needed", "endpoint": None},
    {"key": "bm_regional_split", "role": "brand_manager", "kpi": "Regional split (FR/NL)", "logic": "Review volume & rating across Belgium's two language regions (FR vs NL) — a public proxy for regional strength until sell-out is connected",
     "metric_type": "%", "data_sources": ["Online pharmacy reviews"], "dia_layer": "Interpret",
     "data_status": "live", "endpoint": "/catalog/brand-kpis"},
    {"key": "bm_review_momentum", "role": "brand_manager", "kpi": "Review momentum", "logic": "Review volume in the last 90 days vs the prior 90 — a consumer-demand trend (sell-out proxy)",
     "metric_type": "%", "data_sources": ["Online pharmacy reviews"], "dia_layer": "Interpret",
     "data_status": "live", "endpoint": "/catalog/brand-kpis"},
    {"key": "bm_voice_share", "role": "brand_manager", "kpi": "Share of Voice", "logic": "Brand review mentions ÷ category review mentions (public-side share proxy)",
     "importance": "Voice share = your brand's review mentions ÷ every tracked brand's mentions in the same category. It shows how much of the category conversation you own — a proxy for mind-share and an early indicator of market share. The gap between voice share and actual sell-out is the signal to act: high voice + low sales = awareness not converting; low voice + high sales = an under-marketed strength.",
     "metric_type": "%", "data_sources": ["Online pharmacy reviews"], "dia_layer": "Interpret",
     "data_status": "live", "endpoint": "/catalog/brand-kpis"},
    {"key": "bm_clinical_pipeline", "role": "brand_manager", "kpi": "Clinical pipeline", "logic": "Registered / active clinical trials naming the brand — lifecycle & competitive-threat signal",
     "metric_type": "ABS", "data_sources": ["ClinicalTrials.gov"], "dia_layer": "Detect",
     "data_status": "live", "endpoint": "/catalog/brand-kpis"},
    {"key": "bm_evidence_base", "role": "brand_manager", "kpi": "Evidence base", "logic": "PubMed publications naming the brand — depth of clinical evidence behind it",
     "metric_type": "ABS", "data_sources": ["PubMed"], "dia_layer": "Detect",
     "data_status": "live", "endpoint": "/catalog/brand-kpis"},
    {"key": "bm_atc_class", "role": "brand_manager", "kpi": "Therapeutic class (ATC)", "logic": "WHO ATC classification of the brand's active substance, from the Belgian SAM drug master — the authoritative therapeutic grouping",
     "metric_type": "ABS", "data_sources": ["SAM (FAGG)"], "dia_layer": "Interpret",
     "data_status": "live", "endpoint": "/catalog/brand-kpis"},
    {"key": "bm_pack_count", "role": "brand_manager", "kpi": "Tracked SKUs (CNK)", "logic": "Number of distinct pharmacy packs (CNK codes) for the brand in SAM — distribution breadth, and the join key to sell-out / Farmanet data when connected",
     "metric_type": "ABS", "data_sources": ["SAM (FAGG)"], "dia_layer": "Interpret",
     "data_status": "live", "endpoint": "/catalog/brand-kpis"},
    {"key": "bm_trial_phases", "role": "brand_manager", "kpi": "Trial & study mix", "logic": "Registered studies naming the brand, classified by drug-trial phase (1–4) or — for non-drug brands — by study type (interventional efficacy vs observational). Shows how research-backed and how late-stage the brand is.",
     "metric_type": "ABS", "data_sources": ["ClinicalTrials.gov"], "dia_layer": "Interpret",
     "data_status": "live", "endpoint": "/catalog/brand-kpis"},
    {"key": "bm_reimbursement", "role": "brand_manager", "kpi": "Reimbursement (BE)", "logic": "Share of the brand's packs that are RIZIV/INAMI-reimbursed in Belgium, from the SAM drug master — Rx specialties are largely reimbursed, OTC typically not",
     "metric_type": "%", "data_sources": ["SAM (FAGG)"], "dia_layer": "Interpret",
     "data_status": "live", "endpoint": "/catalog/brand-kpis"},
    {"key": "bm_price", "role": "brand_manager", "kpi": "List price (BE)", "logic": "Official Belgian list price range across the brand's packs, from the SAM drug master",
     "metric_type": "ABS", "data_sources": ["SAM (FAGG)"], "dia_layer": "Interpret",
     "data_status": "live", "endpoint": "/catalog/brand-kpis"},
    {"key": "bm_market_status", "role": "brand_manager", "kpi": "Market status (BE)", "logic": "Marketing-authorisation status and time on the Belgian market, from the SAM drug master",
     "metric_type": "ABS", "data_sources": ["SAM (FAGG)"], "dia_layer": "Detect",
     "data_status": "live", "endpoint": "/catalog/brand-kpis"},
    {"key": "bm_online_availability", "role": "brand_manager", "kpi": "Online availability", "logic": "Share of the brand's retail SKUs in stock online, and how many SKUs are listed, from the Belgian pharmacy retail catalogue (Farmaline)",
     "metric_type": "%", "data_sources": ["Farmaline (BE retail)"], "dia_layer": "Detect",
     "data_status": "live", "endpoint": "/catalog/brand-kpis"},
    {"key": "bm_distribution_breadth", "role": "brand_manager", "kpi": "Distribution breadth", "logic": "Decision cue: how widely the brand is carried in the Belgian pharmacy channel — listed SKUs × in-stock share. Where breadth is thin or stock is low, distribution is leaking.",
     "metric_type": "SCORE", "data_sources": ["SAM (FAGG)", "Farmaline (BE retail)"], "dia_layer": "Interpret",
     "data_status": "live", "endpoint": "/catalog/brand-kpis"},
    {"key": "bm_promo_pressure", "role": "brand_manager", "kpi": "Promo pressure", "logic": "Decision cue: how heavily the range is discounted online (% of SKUs on promo × average discount). High = margin/price-war pressure to match or hold; low = pricing headroom.",
     "metric_type": "SCORE", "data_sources": ["Farmaline (BE retail)"], "dia_layer": "Interpret",
     "data_status": "live", "endpoint": "/catalog/brand-kpis"},
    {"key": "bm_sellin_sellout_gap", "role": "brand_manager", "kpi": "Sell-in vs sell-out gap", "logic": "Channel inventory build or draw-down",
     "metric_type": "% / ABS", "data_sources": ["Wholesaler sell-in", "own sell-out"], "dia_layer": "Interpret",
     "data_status": "data_needed", "endpoint": None},
    # Marketing
    {"key": "mk_share_of_voice", "role": "marketing", "kpi": "Share of Voice", "logic": "Brand mentions ÷ category mentions",
     "importance": "Share of Voice = your brand's mentions ÷ all mentions across the category's tracked brands. It tells you how much of the category conversation you own — a proxy for mind-share and a leading indicator of market share. Watch the gap vs sell-out: high voice + low sales = awareness not converting; low voice + high sales = an under-marketed strength worth funding.",
     "metric_type": "%", "data_sources": ["Social", "news", "reviews"], "dia_layer": "Interpret",
     "data_status": "live", "endpoint": "/catalog/brand-kpis"},
    {"key": "mk_sov_som_gap", "role": "marketing", "kpi": "SoV vs SoM gap", "logic": "Share of voice minus share of market (headline KPI)",
     "metric_type": "%", "data_sources": ["Social", "own sell-out", "IQVIA"], "dia_layer": "Interpret",
     "data_status": "data_needed", "endpoint": None},
    {"key": "mk_buzz_conversion", "role": "marketing", "kpi": "Buzz-to-sell-out conversion", "logic": "Correlation/lag between buzz spike and sell-out lift",
     "metric_type": "SCORE", "data_sources": ["Social", "Google Trends", "own sell-out"], "dia_layer": "Interpret",
     "data_status": "data_needed", "endpoint": None},
    {"key": "mk_sentiment_trend", "role": "marketing", "kpi": "Sentiment trend", "logic": "Net sentiment over time; driver breakdown",
     "metric_type": "% / SCORE", "data_sources": ["Social", "reviews"], "dia_layer": "Detect",
     "data_status": "live", "endpoint": "/catalog/brand-kpis"},
    {"key": "mk_review_trend", "role": "marketing", "kpi": "Review rating & volume trend", "logic": "Avg rating and review count trajectory per SKU",
     "metric_type": "ABS / %", "data_sources": ["Online pharmacy reviews"], "dia_layer": "Detect",
     "data_status": "live", "endpoint": "/catalog/brand-kpis"},
    {"key": "mk_news_pr", "role": "marketing", "kpi": "News & PR volume", "logic": "Press / news articles naming the brand (launches, recalls, regulatory & pricing events)",
     "metric_type": "ABS", "data_sources": ["News", "RSS"], "dia_layer": "Detect",
     "data_status": "live", "endpoint": "/catalog/brand-kpis"},
    {"key": "mk_evidence_base", "role": "marketing", "kpi": "Evidence base", "logic": "PubMed publications naming the brand — fuel for evidence-led claims & content",
     "metric_type": "ABS", "data_sources": ["PubMed"], "dia_layer": "Detect",
     "data_status": "live", "endpoint": "/catalog/brand-kpis"},
    {"key": "mk_claims_profile", "role": "marketing", "kpi": "Claims & benefit profile", "logic": "The benefit themes the brand's range is positioned on (hydration, anti-aging, sensitive skin, SPF, immunity…), mined from Belgian retail product descriptions + official brand sites — the dermo/supplement equivalent of a positioning map",
     "metric_type": "%", "data_sources": ["Farmaline (BE retail)", "Official brand sites"], "dia_layer": "Interpret",
     "data_status": "live", "endpoint": "/catalog/brand-kpis"},
    {"key": "mk_claims_consistency", "role": "marketing", "kpi": "Claim consistency (claims vs evidence)", "logic": "Decision cue: are the brand's marketing claims backed by published evidence? Compares the breadth of benefit claims (retail + official sites) against the depth of supporting literature (PubMed) + clinical guidance (BCFI). Low = substantiate or soften claims before a regulator/competitor does.",
     "metric_type": "SCORE", "data_sources": ["Official brand sites", "Farmaline", "PubMed", "BCFI"], "dia_layer": "Interpret",
     "data_status": "live", "endpoint": "/catalog/brand-kpis"},
    {"key": "mk_review_momentum", "role": "marketing", "kpi": "Review momentum", "logic": "Review volume in the last 90 days vs the prior 90 — is consumer demand accelerating or fading?",
     "metric_type": "%", "data_sources": ["Online pharmacy reviews"], "dia_layer": "Detect",
     "data_status": "live", "endpoint": "/catalog/brand-kpis"},
    {"key": "mk_search_momentum", "role": "marketing", "kpi": "Demand momentum", "logic": "Rate of change in interest / mention volume; seasonality",
     "metric_type": "%", "data_sources": ["Google Trends"], "dia_layer": "Detect",
     "data_status": "live", "endpoint": "/intelligence/momentum/brand/{brand_id}"},
    {"key": "mk_price_competitiveness", "role": "marketing", "kpi": "Online price & promo", "logic": "Retail price range and how much of the range is on promotion, from the Belgian pharmacy retail catalogue (Farmaline)",
     "metric_type": "%", "data_sources": ["Farmaline (BE retail)"], "dia_layer": "Interpret",
     "data_status": "live", "endpoint": "/catalog/brand-kpis"},
    {"key": "mk_pivot_alert", "role": "marketing", "kpi": "Emerging-signal / pivot alert", "logic": "Anomaly detection on weak signals to trigger campaign pivot",
     "metric_type": "SCORE", "data_sources": ["Social", "Google Trends", "reviews"], "dia_layer": "Act",
     "data_status": "live", "endpoint": "/intelligence/anomalies"},
    {"key": "mk_crosssell_segment", "role": "marketing", "kpi": "Cross-sell / CRM segment", "logic": "Basket affinity & segments for targeting",
     "metric_type": "SCORE", "data_sources": ["Loyalty/basket", "own sell-out"], "dia_layer": "Act",
     "data_status": "data_needed", "endpoint": None},
    # ── Category-native KPIs (non-medicine categories) ───────────────────────
    {"key": "nut_claim_substantiation", "role": "marketing", "kpi": "Health-claim substantiation (EU)",
     "logic": "Share of the brand's associated health-claim substances that carry an EU-authorised claim (Reg. 1924/2006). Substances are derived from the brand's review/retail text — the authoritative positioning/compliance signal for food supplements, which have no SAM/ATC spine.",
     "metric_type": "%", "data_sources": ["EU Register of Health Claims"], "dia_layer": "Interpret",
     "data_status": "live", "endpoint": "/catalog/brand-kpis"},
    {"key": "otc_safety_gate", "role": "pharmacist", "kpi": "EU cosmetic recall watch (Safety Gate)",
     "logic": "EU Safety Gate (RAPEX) cosmetic/personal-care safety alerts naming this brand. Safety Gate covers cosmetics but not medicines/devices, so it's the recall channel for the dermocosmetic/parapharmacy slice. Usually clean for reputable brands — itself a reassurance signal.",
     "metric_type": "ABS", "data_sources": ["EU Safety Gate (RAPEX)"], "dia_layer": "Detect",
     "data_status": "live", "endpoint": "/catalog/brand-kpis"},
    {"key": "bm_manufacturer", "role": "brand_manager", "kpi": "Manufacturer / MAH (SAM)",
     "logic": "The marketing-authorisation holder (medicines) or producer (parapharmacy) behind the brand, from the Belgian SAM/FAGG register — identifies the company for manufacturer roll-ups and B2B supplier mapping.",
     "metric_type": "ABS", "data_sources": ["SAM (FAGG)"], "dia_layer": "Interpret",
     "data_status": "live", "endpoint": "/catalog/brand-kpis"},
    {"key": "bm_sam_portfolio", "role": "brand_manager", "kpi": "SAM-registered portfolio (BE)",
     "logic": "How many products this brand/company has registered in the Belgian SAM/FAGG database (medicines + parapharmacy SKUs, with ATC-class breadth) — the manufacturer's range, the core signal for B2B supplier brands (PEC/PAC/NUT) that have no consumer footprint.",
     "metric_type": "ABS", "data_sources": ["SAM (FAGG)"], "dia_layer": "Interpret",
     "data_status": "live", "endpoint": "/catalog/brand-kpis"},
    {"key": "ph_be_shortage", "role": "pharmacist", "kpi": "Belgian shortage watch (FAGG)",
     "logic": "Whether the brand's active substance is on the Belgian FAGG/AFMPS medicine-shortage register — the Belgium-native supply signal at the dispensing counter. Complemented by the French ANSM list for the FR-speaking market.",
     "metric_type": "ABS", "data_sources": ["FAGG/AFMPS (BE)"], "dia_layer": "Detect",
     "data_status": "live", "endpoint": "/catalog/brand-kpis"},
    {"key": "ph_fr_availability", "role": "pharmacist", "kpi": "French availability (ANSM)",
     "logic": "Whether the brand's active substance is on the French ANSM shortage/availability register — a cross-border supply read for the FR-speaking market, complementing the Belgian FAGG/PharmaStatus shortage signal.",
     "metric_type": "ABS", "data_sources": ["ANSM (FR)"], "dia_layer": "Detect",
     "data_status": "live", "endpoint": "/catalog/brand-kpis"},
    {"key": "ph_delivery_status", "role": "pharmacist", "kpi": "Dispensing status (Rx/OTC)",
     "logic": "Whether the brand's packs are dispensed on medical prescription or as free delivery (OTC), from the Belgian SAM drug master's DeliveryModus — the counter cue for how it's supplied, and the rule that gates public advertising (Rx can't be advertised to the public in BE).",
     "metric_type": "ABS", "data_sources": ["SAM (FAGG)"], "dia_layer": "Detect",
     "data_status": "live", "endpoint": "/catalog/brand-kpis"},
    {"key": "bm_price_position", "role": "brand_manager", "kpi": "Reference-price position",
     "logic": "Share of the brand's packs that are the cheapest in their Belgian reference-reimbursement cluster (SAM Cheapest/HeadOfTheCluster). Above the reference price means a patient top-up — a direct pricing-competitiveness signal vs the generic field.",
     "metric_type": "%", "data_sources": ["SAM (FAGG)"], "dia_layer": "Interpret",
     "data_status": "live", "endpoint": "/catalog/brand-kpis"},
    {"key": "bm_generic_status", "role": "brand_manager", "kpi": "Generic competition",
     "logic": "How many marketing-authorisation holders market the brand's molecule in Belgium (SAM): a sole-source molecule is on-patent / single-supplier; many marketers signal an off-patent, price-competitive market — the peer-set and pricing-pressure context.",
     "metric_type": "ABS", "data_sources": ["SAM (FAGG)"], "dia_layer": "Interpret",
     "data_status": "live", "endpoint": "/catalog/brand-kpis"},
]


# Brand → active substance(s) / INN. The EU/BE + FDA pharmacovigilance and drug
# databases are indexed by *substance*, not trade name, so we must resolve the
# molecule to pull per-brand safety data. EU INN first (for EudraVigilance/BCFI),
# US synonym included where it differs (openFDA/FAERS uses e.g. "acetaminophen").
# Cosmetics / supplements / infant nutrition are NOT medicines → no INN → no
# pharmacovigilance signal (correctly empty).
BRAND_INN: Dict[str, List[str]] = {
    "Dafalgan": ["paracetamol", "acetaminophen"],
    "Perdolan": ["paracetamol", "acetaminophen"],
    "Nurofen": ["ibuprofen"],
    "Voltaren": ["diclofenac"],
    "Imodium": ["loperamide"],
    "Fenistil": ["dimetindene"],
    "Strepsils": ["flurbiprofen"],
    "Bepanthol / Bepanthen": ["dexpanthenol"],
    "D-Cure (vitamin D)": ["cholecalciferol", "colecalciferol"],
    "UCB brands (Keppra, Bimzelx)": ["levetiracetam", "bimekizumab"],
}


def category_family(category: Optional[str]) -> Optional[str]:
    """Normalise a brand category to its COMPETITIVE family for peer-matching.

    The taxonomy carries sub-type qualifiers in parentheses — 'Dermocosmetics
    (sun)', 'Supplements (phyto)', 'Supplements (HCP)' — which would otherwise
    isolate a brand as the sole member of its label and make share/peer KPIs read
    a meaningless 100%. Stripping the qualifier groups a sub-type with its parent
    family so genuine competitors are compared. Distinct families (different OTC
    therapeutic areas, Infant nutrition, Baby care …) are left untouched.
    """
    if not category:
        return category
    base = category.split("(")[0].strip()
    return base or category


def brands_for_role(role: str) -> List[Dict]:
    """Brands whose primary KPI interest includes `role` (admin → all)."""
    if role == "admin":
        return TOP_BRANDS
    return [b for b in TOP_BRANDS if role in b["kpi_roles"]]


def kpis_for_role(role: str) -> List[Dict]:
    """KPI library entries for `role` (admin → all roles)."""
    if role == "admin":
        return KPI_LIBRARY
    return [k for k in KPI_LIBRARY if k["role"] == role]


# ── Category-aware KPI scope ─────────────────────────────────────────────────
# Which primary categories (NUT|RX|PAC|PEC|OTC) a KPI is relevant to. A KPI key
# absent here applies to ALL categories — that's the safe default for universal
# signals (share-of-voice, sentiment, news, momentum) and for any consumer/retail
# KPI, because primary_category doesn't perfectly predict data availability (e.g.
# an RX-classified brand can still carry pharmacy reviews). We only scope the
# medicine-spine KPIs — SAM drug-master + EU/BE pharmacovigilance — which are
# structurally meaningless outside the medicine-bearing categories. This
# generalises the endpoint's old hard-coded MEDICINE_ONLY gate and gives new
# category-native KPIs (FOODSUP, EUDAMED, tenders…) a place to declare their scope.
_MEDICINE_BEARING = {"RX", "OTC", "PAC"}
KPI_CATEGORY_SCOPE: Dict[str, set] = {
    "bm_atc_class": _MEDICINE_BEARING,
    "bm_reimbursement": _MEDICINE_BEARING,
    "bm_price": _MEDICINE_BEARING,
    "bm_market_status": _MEDICINE_BEARING,
    "ph_eu_safety": _MEDICINE_BEARING,
    "ph_safety_signals": _MEDICINE_BEARING,
    "ph_clinical_notes": _MEDICINE_BEARING,
    "ph_adverse_reactions": _MEDICINE_BEARING,
    "ph_safety_watch": _MEDICINE_BEARING,
    # Category-native KPIs.
    "nut_claim_substantiation": {"NUT", "OTC"},   # food-supplement / cosmetic positioning
    "otc_safety_gate": {"OTC"},                    # cosmetics recalls
    "ph_be_shortage": _MEDICINE_BEARING,           # Belgian FAGG shortage (Belgium-first)
    "ph_fr_availability": _MEDICINE_BEARING,       # FR ANSM shortage cross-border read
    "ph_delivery_status": _MEDICINE_BEARING,       # SAM DeliveryModus (Rx vs OTC)
    "bm_price_position": _MEDICINE_BEARING,        # SAM reference-reimbursement cluster
    "bm_generic_status": _MEDICINE_BEARING,        # SAM molecule marketer count
}


def kpi_in_category(key: str, primary_category: Optional[str]) -> bool:
    """True if KPI `key` should be shown for a brand in `primary_category`.

    Unscoped keys (most KPIs) apply everywhere; an unknown/None category also
    passes (don't hide on missing classification)."""
    scope = KPI_CATEGORY_SCOPE.get(key)
    if not scope or not primary_category:
        return True
    return primary_category in scope


def catalog_summary() -> Dict:
    """High-level counts + the Overview-tab framing, for dashboard headers."""
    return {
        "brand_count": len(TOP_BRANDS),
        "source_count": len(DATA_SOURCES),
        "kpi_count": len(KPI_LIBRARY),
        "tiers": TIER_LABELS,
        "join_key": JOIN_KEY,
        "core_insight": CORE_INSIGHT,
        "live_kpis": sum(1 for k in KPI_LIBRARY if k["data_status"] == "live"),
        "data_needed_kpis": sum(1 for k in KPI_LIBRARY if k["data_status"] == "data_needed"),
    }