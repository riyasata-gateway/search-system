# Belgium Data Sources & Category-Aware KPIs

**Status:** design / proposal for review · **Scope:** the ~2,046 classified brands across the 5 primary categories (NUT, RX, PAC, PEC, OTC)

---

## Why this document exists

The platform's 20 catalogued sources and 47 KPIs were built around the original **31 medicine-centric framework brands**, so the data spine is `SAM/FAGG → ATC → RIZIV → EMA`. But of the ~2,015 newly-imported supplier brands, **~1,540 are not medicines** (NUT 106, PAC 189, PEC 406, and the cosmetic/parapharmacy slice of OTC 1067). For those, the ATC / reimbursement / EudraVigilance columns are structurally empty.

The KPI engine is **role-aware** (pharmacist / brand_manager / marketing) **but not category-aware**, so a food supplement, a hospital-gases distributor, and an Rx specialty are all offered the same (largely inapplicable) KPI menu. The endpoint has a single coarse gate today — `MEDICINE_ONLY` in `api/routers/catalog.py` (drops SAM/pharmacovigilance KPIs when `is_belgian_medicine()` is false).

This document does two things:
1. **Part 1** — category-native Belgian/EU sources that actually describe these brands.
2. **Part 2** — category-scoped KPIs those sources unlock.

Plus the implementation plan (Part 3), the connector status & "what to do" (Part 4), and the ingestion strategy (Part 5).

**Feasibility legend:** 🟢 free, connector already exists (dormant) · 🟩 free public API/dataset (new connector, low effort) · 🟡 free but scrape / notification DB (medium) · 🔴 paid / partnership (commercial, not engineering).

---

## Part 1 — New Belgium/EU sources, by category

### NUT — Nutritional / supplements (106 brands) — *not medicines, so SAM is empty*
| Source | What it adds | Feasibility |
|---|---|---|
| **FPS Health FOODSUP** notification DB (BE) | Every supplement legally sold in Belgium must be notified; public list of products notified/updated in the last 5 yrs, with notification code (a/b/c/d) and plant/nutrient flags | 🟡 scrape/portal |
| **EU Register of Nutrition & Health Claims** (Food & Feed Information Portal) | Which health claims an ingredient is *legally allowed* to make (authorised vs on-hold/rejected); searchable DB + PDF download | 🟩 public dataset |
| **Test-Aankoop / Test-Achats** | Belgian consumer-association comparative tests & scores | 🟡 scrape |
| Expand pharmacy review/price scrape to **Viata, Newpharma** (supplement-heavy e-tailers) | More review volume + pricing for NUT | 🟡 |

### RX — Prescription (278 brands) — *medicine spine already strong; add sell-out & EU layer*
| Source | What it adds | Feasibility |
|---|---|---|
| **RIZIV/INAMI Farmanet + MORSE** (already Tier B, *not wired*) | Reimbursed dispensation volume & expenditure → a real **sell-out / market-share proxy by ATC** (the single biggest data gap today) | 🟩 open aggregate / 🔴 granular |
| **EMA ESMP shortages + EPAR + additional-monitoring / critical-medicines lists** | Live EU shortage status, authorised-indication breadth, PRAC referrals | 🟩 download/API |
| **ANSM (FR)** + **Doctissimo (FR forum)** — *dormant connectors* | Cross-border FR-Belgium safety alerts & patient sentiment | 🟢 activate |

### PAC — Patient care / medical devices / diagnostics (189 brands) — *devices ≠ drugs, no ATC*
| Source | What it adds | Feasibility |
|---|---|---|
| **EUDAMED** (EU device DB; UDI/Device + Certificates modules become public & mandatory **28 May 2026**) | Device risk class (I/IIa/IIb/III), CE-certificate status, notified body, registration | 🟩 public module |
| **EUDAMED vigilance / FAGG FSCA** (field-safety corrective actions & recalls) | Active device safety actions — note Safety Gate explicitly *excludes* devices, so this is the correct channel | 🟩/🟡 |
| **TED / Belgium e-Procurement** | Hospital device-supply tender awards | 🟩 TED API |

### PEC — Professional / hospital / distribution / gases (406 brands) — *B2B; consumer KPIs mostly N/A*
| Source | What it adds | Feasibility |
|---|---|---|
| **Belgium e-Procurement (Mercurius) + TED** | Hospital/public **tender awards & open notices** — who's winning B2B supply, contracting authorities reached, pipeline | 🟩 TED open data/API |
| **KBO/BCE** Belgian enterprise registry | Firmographics, NACE role (distributor vs manufacturer vs logistics), size | 🟩 open data |
| **Wholesaler sell-in** (Febelco, CERP, Pharma Belgium) (already Tier C) | Distribution flow into pharmacies | 🔴 partnership |

### OTC — Non-Rx meds + dermocosmetics + parapharmacy (1067 brands) — *biggest, most mixed bucket*
| Source | What it adds | Feasibility |
|---|---|---|
| **EU Safety Gate (RAPEX)** — filter by Belgium + cosmetics | Cosmetic/personal-care recalls & alerts (OpenDataSoft export/API mirror available) | 🟩 API/export |
| **Online pharmacy *pricing*** (source listed, *no connector*) across farmaline/newpharma/viata/24pharma/lloydspharma | Real cross-e-tailer price index, cheapest-rank, promo depth | 🟡 scrape |
| **Google Trends (BE, FR/NL split)** | True search momentum & seasonality (today `mk_search_momentum` uses internal mention-volume, not Trends) | 🟢 working |
| **Test-Aankoop**, **Reddit / Trustpilot** | Independent reviews / social sentiment for dermo | 🟢/🟡 |

---

## Part 2 — New category-scoped KPIs

The point is to **swap the empty ATC/reimbursement cards for category-native ones**.

| New KPI | Categories | Source | Role | Status |
|---|---|---|---|---|
| **Belgian notification status** (legally notified in FOODSUP) | NUT | FPS FOODSUP | pharmacist, BM | 🟡 |
| **Claim substantiation** (% of marketed benefits backed by an EU-*authorised* health claim) | NUT, OTC-cosmetic | EU Claims Register + retail text | marketing | 🟩 |
| **Reimbursed sell-out & market share by ATC** | RX | Farmanet/MORSE | BM, marketing | 🟩/🔴 |
| **Active EU shortage status** | RX, PAC | EMA ESMP / FAGG PharmaStatus | pharmacist, BM | 🟩 |
| **Authorised-indication breadth / PRAC referral** | RX | EMA EPAR | BM | 🟩 |
| **Device risk class + CE-certificate status** | PAC | EUDAMED | pharmacist, BM | 🟩 |
| **Field-safety notice / recall active** | PAC, OTC-cosmetic | EUDAMED vigilance / Safety Gate | pharmacist | 🟩 |
| **Hospital tender wins (12m) + open-notice pipeline** | PEC, RX-hospital, PAC | TED / e-Procurement | BM | 🟩 |
| **Channel role & firmographics** | PEC | KBO/BCE | BM | 🟩 |
| **Cosmetic safety-alert count (BE)** | OTC | Safety Gate | pharmacist, marketing | 🟩 |
| **Cross-e-tailer price index / cheapest rank** | OTC, NUT | Pharmacy pricing scrape | marketing, pharmacist | 🟡 |
| **Search-interest momentum & seasonality (FR/NL)** | OTC, NUT | Google Trends | marketing | 🟢 |

---

## Part 3 — Making KPIs category-aware (the architecture)

Small, clean change that reuses what already exists:

1. Add an optional `categories: ["NUT", ...]` field to each `KPI_LIBRARY` entry in `core/framework_catalog.py` (omitted = applies to all categories).
2. `/catalog/brand-kpis` already knows `brand.primary_category` — generalise the existing `MEDICINE_ONLY` gate into a single category filter, so a NUT brand never sees "Reimbursement (BE)" and a PEC brand sees tender KPIs instead.
3. `intelligence/framework_kpis.compute_live_values` gains the category-specific computations, fed by the new connectors. Each new KPI keeps the existing honest `live / partial / Connect feed` status pattern.

### Proposed category tags for existing KPIs (for sign-off)
| KPI keys | categories |
|---|---|
| `bm_atc_class`, `bm_reimbursement`, `bm_price`, `bm_market_status`, `ph_eu_safety`, `ph_safety_signals`, `ph_clinical_notes`, `ph_adverse_reactions`, `ph_safety_watch` | RX, OTC (medicines only; runtime `is_medicine` still gates) |
| `bm_clinical_pipeline`, `bm_evidence_base`, `mk_evidence_base`, `bm_trial_phases` | RX, OTC, NUT, PAC (evidence applies to supplements & devices too) |
| `ph_patient_sentiment`, `mk_review_trend`, `ph_demand_signal`, `mk_review_momentum`, `bm_review_momentum`, `ph_complaint_rate`, `bm_regional_split`, `mk_claims_profile`, `mk_price_competitiveness`, `bm_online_availability`, `ph_availability_risk`, `ph_substitution`, `bm_promo_pressure`, `bm_distribution_breadth` | OTC, NUT, PAC (consumer/retail signals; rarely meaningful for pure-B2B PEC) |
| `*_share_of_voice`, `*_voice_share`, `mk_sentiment_trend`, `mk_news_pr`, `mk_search_momentum` | all |
| (new) tender / firmographics KPIs | PEC, PAC, RX-hospital |

---

## Part 4 — Connector status & what to do

| Connector | State | What to do |
|---|---|---|
| **Google Trends** (`google_trends.py`) | ✅ **Working** (pytrends, no key) | Add `"google_trends"` to the ingestion `CONNECTORS` registry (it's missing) so the batch actually runs it; repoint `mk_search_momentum` to real Trends data. |
| **Reddit** (`reddit.py`) | ⚠️ Needs creds | `is_available()` is false without `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` / `REDDIT_USER_AGENT`. Create a free "script" app at reddit.com/prefs/apps, set the 3 env vars, add to the registry. Mind 60 req/min OAuth limit. *Belgian pharma chatter on Reddit is thin → medium priority.* |
| **Trustpilot** (`trustpilot.py`) | ⚠️ Needs key, API largely closed | Requires `TRUSTPILOT_API_KEY`; Trustpilot's free public API is effectively partner/paid now. **Recommend deprioritising** — farmaline/medimarket pharmacy reviews already cover BE consumer sentiment far better for pharma. Activate only if a Business API key already exists. |
| **ANSM** (`ansm.py`) | ⚠️ Keyless scraper, selectors may drift | Public FR endpoints, no key. The Drupal CSS selectors need verifying against the live DOM (documented inline). Re-tune selectors, add to the registry. FR cross-border value for RX shortages/safety. |
| **EU Safety Gate (RAPEX)** | ❌ No connector | **Build a new connector.** Easiest path: the OpenDataSoft mirror (`public.opendatasoft.com` → `healthref-europe-rapex-en`) exposes a keyless REST API + export. Query by `country=Belgium` + product category (cosmetics), map each alert → `RawMention(source_type="safety_gate")`. No key, low-medium effort. |
| **EU Health Claims Register** | ❌ No connector | **Build a reference-data loader, not a per-brand scraper.** Ingest the register (PDF/portal dataset from the EC Food & Feed Information Portal) into a lookup table keyed by ingredient/substance + claim status. The "Claim substantiation" KPI then joins a brand's marketed benefit themes (already mined by `mk_claims_profile`) against authorised claims. One-time/periodic load. |

**Note:** `reddit`, `trustpilot`, `ansm`, `google_trends`, and `doctissimo` connectors all exist but are **absent from the `CONNECTORS` dict in `scripts/ingest_framework_brands.py`**, so the batch never runs them regardless of availability. Registering them is the first step.

---

## Part 5 — Ingestion strategy: batch pre-fetch + store

Chosen approach (matches the live-fetch batch already run for all brands):

- **Per-brand mention sources** (Google Trends, Reddit, ANSM, Safety Gate): register in the `CONNECTORS` dict and run `scripts/ingest_framework_brands.py --all-brands` so every brand is populated up front into `mentions` + linked via `mention_entities`. Idempotent (text-hash dedup) and resumable.
- **Reference datasets** (EU Health Claims Register, FOODSUP list, EUDAMED, TED awards, KBO/BCE): build separate periodic loaders that populate dedicated lookup tables; the category KPIs join brands against them at compute time (like the existing SAM/retail layers). These don't fit the per-brand mention model.
- Keep the honest status pattern: a KPI shows `live` / `partial` / `Connect feed` exactly as today.

---

## Recommended sequencing

- **Phase 1 — quick wins:** register + run Google Trends (working); build **EU Safety Gate** and **EU Health-Claims Register** loaders (both 🟩, no key); re-tune **ANSM**. Immediately gives NUT/OTC real category-native KPIs.
- **Phase 2 — Belgian regulatory spine:** **FOODSUP** (NUT), **EUDAMED** (PAC), **EMA ESMP/EPAR** (RX), **TED/e-Procurement** (PEC). Where the non-medicine brands finally get a real data story.
- **Phase 3 — commercial truth layer (🔴):** Farmanet granular + IQVIA + wholesaler sell-in — blocked on licences/partnerships, not engineering.
- **Cross-cutting:** the category-aware KPI plumbing (Part 3) underpins all phases and should land first.

---

## Part 6 — Implementation status & coverage analysis (build pass)

What got built/wired this pass, and an honest read of whether each source's
"what it adds" is actually fulfilled for *our* Belgian brand set.

| Source | What it adds | Built | "What it adds" fulfilled? |
|---|---|---|---|
| **Belgium FAGG/AFMPS** (`belgium_health`) | BE medicine shortages + BCFI/CBIP guidance + data.gov.be | ✅ now in the batch (was the Belgium gap — it had been live-search only) | **Yes** — Belgium-first shortage KPI (`ph_be_shortage`) + BCFI notes folded into `ph_clinical_notes` (Dafalgan: 48 notes). |
| **ANSM (FR)** | FR cross-border shortage/safety by molecule | ✅ rewritten (full 268-row table, cached, matched in-Python) | **Yes, partial** — 72 notices linked across 23 medicine brands. Cross-border complement (`ph_fr_availability`), Belgium FAGG is primary. |
| **EU Health Claims** | % of marketed benefits backed by an EU-authorised claim (NUT) | ✅ loader + `intelligence/health_claims.py` + `nut_claim_substantiation` KPI | **Yes, proxy** — real per-brand substantiation for supplement brands *that have review/retail text* (Davitamon 5/8, Solgar 11/17). Gap: text-less brands get nothing (no ingredient list in DB) → derive by ingesting brand-site/retail descriptions for NUT brands. |
| **EU Safety Gate (RAPEX)** | Cosmetic recall alerts (OTC) | ✅ connector (ODS API, 5,447 cosmetics alerts) + `otc_safety_gate` KPI | **No (structural)** — our reputable pharmacy brands essentially never appear (alerts skew to counterfeits/cheap perfumes); 0 matches. Reframed as a **"clean record / no EU recalls" assurance KPI**, which is honest and useful. For real cosmetic-safety signal, lean on review complaints (have it) + FAGG cosmetovigilance (no public per-product feed). |
| **Google Trends (BE)** | BE search momentum / seasonality | ✅ bug fixed (`method_whitelist` urllib3 v2) + region set to `geo=BE`, `hl=fr-BE` | **Blocked by rate limit** — now reaches Google but returns HTTP 429 from this IP at scale. Needs `GOOGLE_TRENDS_PROXY` or throttled/scheduled ingestion. Code is correct. |
| **Reddit** | Patient/consumer chatter | ✅ registered in batch | **Blocked — no credentials** (`REDDIT_CLIENT_ID/SECRET` empty in settings). Add real API creds; note BE pharma chatter is thin even then. |
| **Doctissimo (FR)** | FR patient-forum sentiment | ✅ registered in batch | **Returns nothing** — scraper selectors stale / site blocks. Low ROI (FR forum); deprioritised, needs selector re-tuning. |
| **Trustpilot** | — | 🗑️ **removed** (free API closed) | n/a |

### Where "what it adds" is NOT fully met — what to do
1. **Cosmetic safety for OTC** (Safety Gate yields ~0 for premium brands): use it as a clean-record signal; for real signal, mine existing review complaints and add FAGG cosmetovigilance / Test-Aankoop (scrape — no API).
2. **NUT substantiation coverage** (limited to brands with text): run the existing `brand_site` connector for NUT brands to pull product/ingredient descriptions, widening substance matches against the claims register.
3. **Search momentum** (Trends 429): configure `GOOGLE_TRENDS_PROXY` or move Trends to a low-rate scheduled job rather than the 2k-brand batch.
4. **Social voice** (Reddit/Doctissimo): provide Reddit creds; re-tune or drop Doctissimo. Neither is high-yield for Belgian pharmacy brands.
5. **The structural gap remains commercial sell-out** (IQVIA / Farmanet granular) — Tier-C, blocked on licences, not engineering.

### New KPIs wired this pass (category-scoped)
- `ph_be_shortage` (FAGG, BE) + `ph_fr_availability` (ANSM, FR) — medicines.
- `nut_claim_substantiation` (EU Health Claims) — NUT/OTC.
- `otc_safety_gate` (RAPEX clean-record) — OTC.

## Part 7 — Coverage by category, B2B answer & KPI-role importance (build pass 2)

### Did every category get sources + flowing data + KPIs?
| Category | Sources now flowing | Data (this build) | Category KPIs |
|---|---|---|---|
| **NUT** (106) | farmaline/medimarket reviews, brand_site, **EU Health Claims**, **SAM NONMEDICINAL portfolio** | claim-substantiation match for **33/106**; SAM portfolio e.g. Nutricia 716 SKUs | `nut_claim_substantiation`, `bm_sam_portfolio`, sentiment/review set |
| **RX** (278) | **SAM (now ALL brands** — ATC/price/reimbursement/status/MAH), BCFI (213 brands), ANSM FR shortages (23), EudraVigilance/openFDA | SAM index 31→**1,440 brands**; medicine KPIs now populate for new Rx brands | `bm_atc_class/reimbursement/price/market_status`, `ph_be_shortage`*, `ph_fr_availability`, safety set, `bm_manufacturer` |
| **PAC** (189) | **SAM NONMEDICINAL portfolio**, reviews (consumer devices) | wound-care/device suppliers now covered: Lohmann & Rauscher 1,535 · Paul Hartmann 1,330 | `bm_sam_portfolio`, SoV, `bm_manufacturer` |
| **PEC** (406, B2B) | **SAM Company/Producer portfolio** (the B2B fix) | **1,410 supplier brands** got a SAM portfolio + MAH/producer | `bm_sam_portfolio`, `bm_manufacturer`, SoV |
| **OTC** (1067) | reviews + retail pricing, **Safety Gate** (clean-record), SAM, Google Trends (proxy) | full consumer set; Safety Gate ~0 hits (premium brands not recalled) | full consumer set + `otc_safety_gate` |

\* `ph_be_shortage` is wired but its feed is empty — see data-quality note below.

### B2B / supplier coverage — answered
Previously the B2B categories (PEC, and supplier-classified PAC/NUT) had **no** category-native source. They're now covered by mining **SAM's Company (MAH) + NONMEDICINAL Producer** fields → a per-supplier **portfolio** (registered medicines + parapharmacy SKUs + ATC breadth) and the **manufacturer/MAH** identity. 1,410 supplier brands now carry this. Remaining B2B gaps (not yet built): **TED / e-Procurement** hospital tender awards and **KBO/BCE** firmographics — recommended next.

### KPI importance, judged from each role's PoV
| KPI | Pharmacist | Brand manager | Marketing | Verdict |
|---|---|---|---|---|
| `ph_be_shortage` / `ph_fr_availability` | **High** (dispense / substitute) | Med (supply risk to revenue) | Low | Keep — pharmacist-critical |
| `nut_claim_substantiation` | Low–Med (advice) | **High** (compliance risk) | **High** (positioning) | Keep — marketing/BM |
| `otc_safety_gate` | Med (recall awareness) | Low | Med (reputation) | Keep as clean-record; low hit-rate |
| `bm_manufacturer` (MAH) | Low | **High** (ownership, roll-ups) | Med | Keep — BM, B2B |
| `bm_sam_portfolio` | Low | **High** (range/scale) | Med | Keep — BM, esp. B2B suppliers |

### Additional KPIs worth adding (from still-unused SAM fields)
- **Rx-vs-OTC delivery status** (SAM `DeliveryModus`) — pharmacist + marketing, **high** (not derived today at all).
- **Belgium-native supply-problem flag** (SAM `SupplyProblem`/`EndOfCommercialization`) — pharmacist **high**; would properly feed `ph_be_shortage` from data we already hold.
- **Cheapest / reference-price status** (SAM `Cheapest`/`HeadOfTheCluster`) — marketing/BM pricing, **high**.
- **Leaflet / SPC / DHPC deep-links** (SAM) — pharmacist/medical, medium.
- **Generic-vs-originator** (SAM VMP) — BM peer-set, medium.

### Data-quality findings (honest)
- **FAGG shortage feed was wrong** (`FAGG_SHORTAGE_URL` pointed at a *news* page → 0 results). **RESOLVED** by extracting SAM's own `SupplyProblem` / `LimitedAvailability` / end-of-commercialisation fields (data we already hold) — dated, with reason + expected-return. `ph_be_shortage` now shows e.g. *Gaviscon: "Supply problem (BE) — Delay in production; expected back 2026-07-06"*. Covers the trade-name medicine brands (supply is per-product); BCFI (213 brands) and ANSM (FR) also flow. A PharmaStatut connector remains a possible future complement.
- **Google Trends**: code now correct (region BE, throttle + 429 backoff + cache) but **429-blocked from this datacenter IP** → set `GOOGLE_TRENDS_PROXY` (residential) for bulk use.
- **Reddit**: `REDDIT_CLIENT_ID/SECRET` are empty → add real creds.
- **Doctissimo**: **fixed** — now indexes ~800 recent threads and returns real FR patient posts.
- **Safety Gate**: works, but premium pharmacy brands aren't in RAPEX → near-zero hits (clean-record signal).

## Part 8 — Final data audit (verdict)

End-to-end audit against the live DB + code. **Pipeline is correct and robust; data renders for all 5 categories.**
- **Linking integrity**: 0 orphan links, 0 duplicate (mention,brand) links, 0 review-mentions missing a classification. 1,823/2,046 brands linked.
- **KPI wiring**: 52 KPI_LIBRARY keys, 44 produced; **0 live/partial KPIs left unproduced**; all MEDICINE_ONLY + category-scope keys valid. (`bm_launch_readiness` is computed but shown via `/intelligence/launch-readiness`, not the framework grid — intentional.)
- **source_type ↔ KPI reads**: consistent; the only unmatched `cmap` reads (`ansm`, `news`) are harmless OR-adds. `bcfi`+`bcfi_cbip` correctly summed.
- **Robustness**: 0 crashes across a per-category sweep; per-brand KPI latency cut from ~5.2s→~1.6s by replacing the SoV correlated subquery with an indexed GROUP BY.
- **Fixes applied during audit**: (1) Doctissimo + Reddit now feed `ph_patient_questions`/demand-attention (were emitted but unread); (2) SoV peer query optimised.
- **Known empties (documented, not bugs)**: `safety_gate` (premium brands not in RAPEX → clean-record), `google_trends` (IP 429 → needs proxy), `doctissimo` (connector fixed; batch not yet run), `data_gov_be`/`fagg_shortage` news-page (superseded by SAM supply data). Medicine-spine KPIs populate for the ~49 trade-name medicine brands; the rest are suppliers covered by SAM portfolio (correct).

## Part 9 — SAM-field KPIs (build pass 3)

Three more KPIs mined from SAM fields we already download (no new source) — the
non-supply items from Part 7's "still-unused SAM fields" list. All medicine-spine
(scoped to RX/OTC/PAC + gated by `is_medicine`), so non-medicine brands never see them.

| New KPI | Role | SAM field(s) | What it shows |
|---|---|---|---|
| **Dispensing status (Rx/OTC)** `ph_delivery_status` | pharmacist | `DeliveryModus` (REF-decoded) | Free-delivery (FD/TF → OTC) vs medical-prescription (M*/TD → Rx); also the rule that gates public advertising. **18/18 SAM medicines.** |
| **Reference-price position** `bm_price_position` | brand_manager | `Cheapest` + `HeadOfTheCluster` | % of packs that are cheapest in their Belgian reference-reimbursement cluster. Populates for the **4** brands whose packs sit in a cluster (OTC packs outside the cluster system → "Insufficient data", honest). |
| **Generic competition** `bm_generic_status` | brand_manager | molecule → all MAHs | How many marketing-authorisation holders market the molecule (sole-source = on-patent/single-supplier; many = off-patent, price-competitive). **18/18.** e.g. paracetamol = 37 marketers, loperamide = 12. |

**Originator note:** SAM's commercialisation dates bottom out at the data horizon (paracetamol reads "2007"), so a hard originator/first-to-market claim is unreliable for old molecules. The KPI reports **competition intensity** (marketer count), not an originator flag — that's the defensible read.

**Data-integrity fix found during this pass:** the MAH `Denomination` sits at `Company > Data > Denomination`, but extraction used a direct-child `find`, so `company` was silently `None` for every product-matched **medicine** (`bm_manufacturer` was empty for them; only supplier/parapharmacy producers populated). Fixed with a recursive find, and the MAH is now chosen by **majority vote** across the brand's packs (the true holder owns the most packs; parallel importers each hold a few) — e.g. Dafalgan now resolves to UPSA, not the first-seen parallel importer. Medicine MAH coverage 235 → 250.

## Sources

- [FPS Health — food supplement notification](https://www.health.belgium.be/en/notification-file-food-supplement)
- [EU Register of nutrition & health claims (Food & Feed Information Portal)](https://ec.europa.eu/food/food-feed-portal/screen/health-claims/eu-register) · [EC overview](https://food.ec.europa.eu/food-safety/labelling-and-nutrition/nutrition-and-health-claims/eu-register-health-claims_en)
- [EUDAMED overview (European Commission)](https://health.ec.europa.eu/medical-devices-eudamed/overview_en) · [Mandatory 28 May 2026 (Obelis)](https://www.obelis.net/news/eudamed-becomes-mandatory-on-28-may-2026-deadlines-for-actor-device-and-certificate-registrations/)
- [RIZIV/INAMI MORSE report](https://www.riziv.fgov.be/SiteCollectionDocuments/morse_report_2021.pdf)
- [EU Safety Gate alerts](https://ec.europa.eu/safety-gate-alerts/) · [FPS Economy Safety Gate (BE)](https://economie.fgov.be/en/themes/quality-and-safety/safety-products-and-services/hazardous-products/safety-gate) · [OpenDataSoft RAPEX mirror](https://public.opendatasoft.com/explore/assets/healthref-europe-rapex-en/)
- [Belgium e-Procurement / public medical & pharmaceutical contracts](https://www.gpcgov.be/en/public-medical-pharmaceutical-contracts-in-belgium) · [TED — Tenders Electronic Daily](https://ted.europa.eu)
- [EMA — download medicine data (EPAR)](https://www.ema.europa.eu/en/medicines/download-medicine-data) · [European Shortages Monitoring Platform (ESMP)](https://www.ema.europa.eu/en/human-regulatory-overview/post-authorisation/medicine-shortages-availability-issues/european-shortages-monitoring-platform-esmp)