# KPI Reference

This document explains **every KPI in the platform** — what it answers, which data
source(s) feed it, and exactly how it is computed today. It is generated against
the single source of truth, `core/framework_catalog.py` (`KPI_LIBRARY`,
`DATA_SOURCES`), and the live computation engines in `intelligence/`.

## How to read this

- **DIA layer** — the Datatopia decision stage a KPI serves: **Detect** (what's
  happening), **Interpret** (what it means), **Act** (what to do).
- **`data_status`**:
  - **live** — computed from already-ingested data *right now*.
  - **data_needed** — requires an external commercial feed (sell-out / IQVIA /
    wholesaler / loyalty) that isn't connected. These are **hidden by default in
    the UI and revealed by the "Upgrade" button** — see
    [Upgrade KPIs](#upgrade-kpis--need-an-external-feed).
- **Computation engines**:
  - `intelligence/framework_kpis.py` → `compute_live_values(db, brand)` computes
    all live per-brand KPI values.
  - `intelligence/brand_potential_index.py` → the Brand Potential Index + 4 sub-scores.
  - `intelligence/momentum.py`, `intelligence/launch_readiness.py` → composite scores.
- **Honest-data contract**: when a signal is missing, a KPI returns `n/a` / `—` /
  "Connect feed" / "Sole tracked brand" — it never fabricates a number. Degenerate
  values (e.g. a sole-brand 100% share) are flagged, not shown as real.

Totals today: **46 KPIs — 37 live, 9 behind Upgrade.**

---

## Data sources

### Tier A — public, free, real-time (the always-on signal layer)
| Source | What it gives | Access | Wired |
|---|---|---|---|
| Google Trends | Search interest by brand/molecule/symptom; FR vs NL split | Free | ✅ |
| Social (Meta, X, TikTok, IG) | Mentions, sentiment, reach, share of voice | Free / API | ⚠️ connector present, not licensed |
| Reddit / patient forums | Unmet needs, off-label chatter, side-effects | Free | ✅ |
| Online pharmacy reviews (Farmaline, Medi-Market, …) | Star ratings, review volume & sentiment per SKU | Free (scrape) | ✅ |
| App store / Play reviews | Patient-app sentiment | Free | ✅ |
| PubMed / ClinicalTrials.gov | Evidence base, active trials, pipeline | Free | ✅ |
| News / press (RSS) | Launches, recalls, regulatory & pricing events | Free | ✅ |

### Tier B — official Belgian / EU registries (the authoritative spine)
| Source | What it gives | Access | Wired |
|---|---|---|---|
| FAGG geneesmiddelendatabank | Product master: CNK, ATC, form, pack, Rx status | Open data | ✅ |
| SAM (authentic source, eHealth) | Authoritative medicine data (price, reimbursement, status, black-triangle) | Open data | ✅ |
| PharmaStatus (FAGG) | Availability / shortage status per pack | Open data | ✅ |
| RIZIV/INAMI Farmanet | Reimbursed dispensations (volume, spend) | Conditional | ❌ |
| KCE / Sciensano | HTA, epidemiology, TA sizing | Free | ✅ |
| EudraVigilance (EMA) | EU adverse-reaction monitoring by substance | Open data | ✅ |
| openFDA / FAERS | Adverse-event reports (BE-filtered via `occurcountry`) | Free | ✅ |
| BCFI / CBIP | Belgian prescribing-authority clinical notes | Free | ✅ |

### Tier C — proprietary commercial feeds (the "truth" / benchmark layer — **the Upgrade tier**)
| Source | What it gives | Access | Wired |
|---|---|---|---|
| Own pharmacy sell-out (`final_flat_file`) | Real units & value per CNK/pharmacy/day; margin | Owned — expand network | ❌ |
| IQVIA Belgium (Rx panel, Consumer Health, MIDAS) | Dispensed sell-out, market share, trend (~30% panel) | Paid licence | ❌ |
| Wholesaler sell-in (Febelco, CERP, Pharma Belgium) | Distribution wholesaler → pharmacy volumes | Partnership | ❌ |
| Pharmacy loyalty / basket | Co-purchase, repeat-buy, patient journeys | Partnership | ❌ |
| Store-level stock / OOS | Out-of-stock events driving substitution | Partnership | ❌ |
| HCP / KOL feedback (field CRM) | Prescriber sentiment, detailing response | Owned / partnership | ❌ |

---

## Composite indices (Brand Pulse headline scores)

These are not single-source KPIs but blended scores shown on the Brand Pulse page.

### Brand Potential Index (BPI) — `intelligence/brand_potential_index.py`
`BPI = geometric_mean(Awareness, Adoption, Sentiment, MarketFit) × 100` over a
365-day window. Each sub-score is 0–1 and carries an honest `component_status`
(`ok` / `no_data` / `sole_brand` / `no_signal` / `proxy`):

| Sub-score | How computed | Source |
|---|---|---|
| **Awareness** | brand mentions ÷ category-family mentions (share of voice) | Mentions |
| **Adoption** | pharmacy sell-out share; **proxy** (purchase-intent + review + recommendation mentions) when sell-out absent | Sell-out / proxy mentions |
| **Sentiment** | engagement-weighted share of positive/neutral classified mentions | Classified mentions |
| **MarketFit** | category-share within the brand's competitive family | Mentions |

> Competitive peers come from the `products` table by shared `category_id`, falling
> back to the brand's **category family** (`category_family()` strips parenthetical
> sub-types, e.g. `Dermocosmetics (sun)` → `Dermocosmetics`) so sub-typed brands
> aren't wrongly isolated. A brand that is genuinely the only one tracked in its
> family is flagged `sole_brand` (Awareness/Adoption/MarketFit are degenerate; only
> Sentiment stays real).

### Demand momentum — `intelligence/momentum.py`
Mention-volume momentum (recent vs prior period), 0–100. Shown only when sample
size > 0; otherwise "No signal".

### Launch readiness — `intelligence/launch_readiness.py`
Composite of **public legs only** (buzz, evidence, availability). Shown only with
recent mentions; otherwise "Not scored yet". The proprietary leg (sell-out) is the
Upgrade.

---

## Live KPIs by role

Computation references are to functions in `intelligence/framework_kpis.py`.

### Pharmacist (12 live)
| KPI | Answers | Source(s) | How computed | DIA |
|---|---|---|---|---|
| Patient review sentiment (`ph_patient_sentiment`) | Are patients happy with it? | Pharmacy reviews | `% = 100·positive ÷ classified` reviews linked to brand | Detect |
| Public demand signal (`ph_demand_signal`) | What are patients asking about? | Reviews / Trends | Linked review volume; falls back to news+social+forum count for Rx (no reviews) | Detect |
| EU pharmacovigilance (`ph_eu_safety`) | Is the substance under EU safety watch? | EudraVigilance + SAM | Count of EudraVigilance mentions; ▲ if SAM black-triangle flag | Detect |
| Adverse-event reports BE (`ph_safety_signals`) | Any BE adverse events? | openFDA/FAERS (BE) | Count of openFDA reports (occurcountry=BE) linked to brand | Detect |
| Patient forum discussion (`ph_patient_questions`) | What do customers worry about? | Patient forums | Count of forum threads naming the brand | Detect |
| BCFI clinical guidance (`ph_clinical_notes`) | Any prescribing cautions? | BCFI/CBIP | Count of BCFI clinical notes on the substance (medicines only) | Interpret |
| Availability risk (`ph_availability_risk`) | Will I fail to dispense it? | Farmaline | `100 − in_stock_pct`; High <20%, Medium <50%, else Low | Act |
| Substitution options (`ph_substitution`) | What to recommend if out? | Farmaline | Count of same category-family brands in stock (else tracked alternatives) | Act |
| Patient out-of-pocket (`ph_out_of_pocket`) | What does the patient pay? | SAM + Farmaline | RIZIV co-pay if reimbursed, else full SAM/retail price | Act |
| Safety watch (`ph_safety_watch`) | Warn / counsel / clear? | EudraVigilance+openFDA+BCFI+SAM | Flag: Watch if ▲ or ≥5 AE reports; Monitor if any flag; else Clear | Act |
| Complaint rate (`ph_complaint_rate`) | Quality early-warning? | Pharmacy reviews | `% = 100·negative ÷ classified` reviews | Detect |
| Top adverse reactions (`ph_adverse_reactions`) | What to counsel on? | openFDA/FAERS | Top reaction terms from openFDA `reactions` metadata (medicines only) | Detect |

### Brand Manager (14 live)
| KPI | Answers | Source(s) | How computed | DIA |
|---|---|---|---|---|
| Regional split FR/NL (`bm_regional_split`) | Where is it strong? | Pharmacy reviews | Review volume & rating split by `language` (fr vs nl) | Interpret |
| Review momentum (`bm_review_momentum`) | Is demand accelerating? | Pharmacy reviews | Reviews last 90d vs prior 90d, % change | Interpret |
| Category voice share (`bm_voice_share`) | How much mind-share? | Pharmacy reviews | brand mentions ÷ category-family mentions; ranked peer table | Interpret |
| Clinical pipeline (`bm_clinical_pipeline`) | Research-backed / threats? | ClinicalTrials.gov | Count of trials naming the brand | Detect |
| Evidence base (`bm_evidence_base`) | How much evidence? | PubMed | Count of PubMed papers naming the brand | Detect |
| Therapeutic class ATC (`bm_atc_class`) | What class is it? | SAM | Best single-substance ATC code from SAM | Interpret |
| Tracked SKUs CNK (`bm_pack_count`) | Distribution breadth / join key | SAM / packs | Count of canonical CNK packs (FR/NL-deduped) | Interpret |
| Trial & study mix (`bm_trial_phases`) | How late-stage is research? | ClinicalTrials.gov | Trials grouped by phase (1–4) or study type (non-drug) | Interpret |
| Reimbursement BE (`bm_reimbursement`) | Is it reimbursed? | SAM (RMB) | `% = reimbursed packs ÷ priced packs`; RIZIV category A/B/C | Interpret |
| List price BE (`bm_price`) | Official price range? | SAM | min–max–avg list price across packs | Interpret |
| Market status BE (`bm_market_status`) | Authorised? Since when? | SAM | Authorisation status + commercialised-since year | Detect |
| Online availability (`bm_online_availability`) | In stock online? | Farmaline | `in_stock_pct` + listed SKU count + online rating | Detect |
| Distribution breadth (`bm_distribution_breadth`) | Where is it leaking? | SAM + Farmaline | `max(retail SKUs, SAM packs)`; Broad ≥50, Moderate ≥15, else Narrow | Interpret |
| Promo pressure (`bm_promo_pressure`) | Match or hold price? | Farmaline | `% SKUs on promo` × avg discount; High ≥40%, Moderate ≥15% | Interpret |

### Marketing (11 live)
| KPI | Answers | Source(s) | How computed | DIA |
|---|---|---|---|---|
| Share of Voice (`mk_share_of_voice`) | How much conversation? | Social/news/reviews | brand mentions ÷ category-family mentions; ranked peers | Interpret |
| Sentiment trend (`mk_sentiment_trend`) | Net perception? | Social/reviews | `% = 100·positive ÷ classified` mentions | Detect |
| Review rating & volume (`mk_review_trend`) | SKU satisfaction trajectory? | Pharmacy reviews | Avg rating + review count across linked reviews | Detect |
| News & PR volume (`mk_news_pr`) | Press footprint? | News/RSS | Count of news articles naming the brand | Detect |
| Evidence base (`mk_evidence_base`) | Claim fuel? | PubMed | Count of PubMed papers | Detect |
| Claims & benefit profile (`mk_claims_profile`) | What is it positioned on? | Farmaline + brand sites | Benefit themes mined from retail descriptions (% of range) | Interpret |
| Claim consistency (`mk_claims_consistency`) | Claims backed by evidence? | Brand sites+Farmaline+PubMed+BCFI | **Rubric** (not measured): claim-theme breadth vs evidence depth (PubMed+BCFI): ≥10→85, ≥3→60, else 30 | Interpret |
| Review momentum (`mk_review_momentum`) | Demand accelerating? | Pharmacy reviews | Reviews last 90d vs prior 90d | Detect |
| Search momentum (`mk_search_momentum`) | Search interest trend? | Google Trends / momentum | Momentum-engine score 0–100 (rising ≥60 / cooling <40) | Detect |
| Online price & promo (`mk_price_competitiveness`) | Price positioning? | Farmaline | Retail price range + % of range on promo | Interpret |
| Emerging-signal / pivot alert (`mk_pivot_alert`) | Time to pivot a campaign? | Social/Trends/reviews | Momentum-trend classification: Rising / Stable / Cooling | Act |

> **`mk_claims_consistency` is a designed rubric, not a measured value** — its
> 85/60/30 bands come from evidence-item counts; the basis is always shown in the
> card's detail line.

---

## Upgrade KPIs — need an external feed

These 9 KPIs require a Tier-C commercial feed and are **hidden until the "Upgrade"
button is clicked** on the Brand Pulse / dashboard page. They never show a fake
number — only the feed that unlocks them.

| KPI | Role | What it would answer | Feed required |
|---|---|---|---|
| Regional top-sellers (`ph_regional_top_sellers`) | Pharmacist | Top CNKs by units/value in my area this week | Own sell-out |
| Peer assortment gap (`ph_peer_assortment_gap`) | Pharmacist | Products peer pharmacies stock that I don't | Own sell-out (network) |
| Sell-out market share (`bm_sellout_share`) | Brand Manager | Brand units/value ÷ ATC-class total | Own sell-out + IQVIA |
| Sell-out trend (`bm_sellout_trend`) | Brand Manager | Units/value growth WoW/MoM | Own sell-out + IQVIA |
| Regional penetration (`bm_regional_penetration`) | Brand Manager | Sell-out FR/NL/DE; % pharmacies stocking | Own sell-out |
| Sell-in vs sell-out gap (`bm_sellin_sellout_gap`) | Brand Manager | Channel inventory build/draw-down | Wholesaler sell-in + own sell-out |
| SoV vs SoM gap (`mk_sov_som_gap`) | Marketing | Share of voice minus share of market | Social + own sell-out + IQVIA |
| Buzz-to-sell-out conversion (`mk_buzz_conversion`) | Marketing | Does buzz convert to sales (and with what lag)? | Social + Trends + own sell-out |
| Cross-sell / CRM segment (`mk_crosssell_segment`) | Marketing | Basket affinity & targeting segments | Loyalty/basket + own sell-out |

**Why gated:** every one of these needs *transacted sales* (sell-out), a *paid
market panel* (IQVIA), *wholesaler* or *loyalty* partnership data. Until one of
those is connected, the honest answer is "feed required" — which is exactly what
the Upgrade panel surfaces, alongside the public-proxy KPIs (voice share, review
momentum, search momentum) that approximate them today.
