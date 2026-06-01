# Per-Search Metrics — Data Model & Feature Engineering

_Goal: when a user runs a search and receives results, immediately compute and
auto-fill a **role-tailored dashboard** from that result set — no second request,
no waiting on the historical audit aggregates._

This is distinct from the existing **Analytics** page (which aggregates *all
past* searches from the audit log). This is **"metrics about the search you just
ran"**, computed from the live result rows.

---

## 1. The raw data a search returns (per result row)

| Field | Type | Cardinality / values | Notes |
|---|---|---|---|
| `source_type` | categorical | news, rss, youtube, pubmed, eudravigilance, belgium_health, ansm, reddit, forum, trustpilot, app_store, doctissimo, wikipedia, clinical_trials… | the channel |
| `country` | categorical | BE, FR (occasionally null) | geography |
| `language` | categorical | fr, nl, de, en | maps to BE language communities |
| `published_at` | datetime / null | — | the time dimension |
| `sentiment` | categorical | positive / neutral / negative | LLM-classified (live: rule pass) |
| `topic` | categorical | price, efficacy, side_effect, availability, packaging, recommendation, general | what it's about |
| `risk_type` | categorical | adverse_event, shortage, misinformation, counterfeit, none | safety/brand risk |
| `is_risk` | bool | — | `risk_type != none` |
| `engagement` | int / null | 0 … millions | reach (esp. YouTube views; `meta` has likes/comments) |
| `source_url`, `text`, `query` | free | — | identity / display |

Response-level: `total`, `expanded_terms`, `sources_queried`, `source_notices`,
`role`, `elapsed_ms`.

---

## 2. Linkable fields (the joins that create insight)

A single field is a count; the value is in **cross-tabulating** them. The pairs
that matter for pharma intelligence:

| Linked fields | Question it answers | Used by |
|---|---|---|
| `sentiment × topic` | *What* are people negative about? (e.g. negative + side_effect) | all |
| `sentiment × source_type` | Which channels carry the negativity? | marketing, brand |
| `risk_type × source_type` | Where do safety/brand-risk signals originate? | pharmacist, brand |
| `engagement × source_type` | Reach per channel = **share of voice** | marketing |
| `published_at → bucket × volume` | Momentum / trend / freshness | brand, marketing |
| `country × sentiment` | Market sentiment BE vs FR | brand |
| `language × volume` | FR/NL/DE community split | marketing |
| `topic × country` | Regional concern mix | pharmacist, brand |
| `is_risk × topic` | Safety-topic concentration | pharmacist |

These become the dashboard's charts and the "linked" cross-tab tables.

---

## 3. Feature engineering — derived metrics (computed once, shared by all roles)

- **`sentiment_index`** = `(positive − negative) / total` → net sentiment in **[-1, +1]**
  (a single brand-health number, not three bars).
- **`net_sentiment_label`** = Positive / Negative / Mixed / Neutral, from the index
  + whether pos & neg are both material (Mixed when polarised).
- **`reach_total`** = `Σ engagement` → total audience exposure.
- **`engagement_rate`** = `reach_total / total` → avg reach per mention.
- **`risk_share`** = `is_risk count / total`.
- **`official_coverage`** = share of rows from authoritative sources
  `{belgium_health, fagg/ansm shortage+safety, eudravigilance, bcfi_cbip, pubmed,
  clinical_trials, openfda, belgium_hcp, data_gov_be}` → trust/authority signal.
- **`source_diversity`** = distinct `source_type` count (breadth of coverage).
- **`share_of_voice`** = per-channel share of `engagement` (falls back to volume
  when no engagement data) → the marketing SoV metric.
- **`timeline`** = rows bucketed by `published_at::date` with pos/neg/neutral counts
  → momentum + a sentiment-over-time strip.
- **Cross-tabs**: `sentiment_by_topic` (stacked), `risk_by_source` (where risk lives).

---

## 4. Role KPI mapping (the headline cards each persona sees)

Same result set → different headline metrics, because each role's
job-to-be-done differs. (Consistent with `core/role_lens.py`.)

### pharmacist — dispensing & patient safety
1. **Safety signals** — `adverse_event` risk count _(danger tone if > 0)_
2. **Supply signals** — `shortage` risk + `availability` topic count _(warn)_
3. **Official-source coverage** — `official_coverage` % _(good if high, warn if < 30%)_
4. **Side-effect chatter** — `side_effect` topic count
5. **Risk share** — `risk_share` %

### marketing — reach, buzz & resonance
1. **Total reach** — `reach_total`
2. **Top channel (SoV)** — leading channel + its share-of-voice %
3. **Engagement rate** — `engagement_rate` (avg reach/mention)
4. **Net sentiment** — `net_sentiment_label` + `sentiment_index`
5. **Advocacy** — `recommendation` topic count

### brand_manager — market & strategy
1. **Net sentiment index** — `sentiment_index` (brand health)
2. **Risk exposure** — `risk_share` % _(danger if elevated)_
3. **BE vs FR** — geographic volume split
4. **Authority mix** — `official_coverage` % (evidence/regulatory weight)
5. **Misinformation** — `misinformation` risk count _(reputational watch)_

### admin — balanced oversight
Total mentions · net sentiment · risk share · source diversity · total reach.

---

## 5. Architecture (as built — confirmed with stakeholder)

**Two tiers**, both attached to every search response (`live`, `semantic`, **`ai`**)
as `metrics: SearchIntelligence` and persisted to the **`search_metrics`** table:

- **Snapshot tier** (always): `core/search_metrics.compute_metrics(items, role)` —
  pure function over the result batch (sentiment/topic/source/reach/risk + cross-tabs).
- **Framework tier** (when the query resolves to a known brand): the **existing**
  DIA intelligence modules, reused — `brand_potential_index` (BPI), `momentum`,
  `lifecycle`, `launch_readiness`. Orchestrated by `intelligence/search_intelligence.py`,
  which resolves the query→brand via the deterministic `entity_resolution` dictionary
  and runs the role's modules.

**Role → framework modules:** pharmacist → momentum; marketing → SoV + momentum;
brand_manager → BPI + SoV + momentum + lifecycle + launch-readiness; admin → BPI +
SoV + momentum. SoV = the brand's share of category mentions (= BPI Awareness), since
`competitor_groups` is empty.

**Data prerequisites (done):**
- `scripts/backfill_entities.py` populates `mention_entities` (the join the framework
  modules need). *Note:* the seeded corpus is general health news, so only a handful
  of mentions name a seeded brand — framework metrics are real but low-sample until
  the flywheel (live-search → governed ingest) enriches the corpus.
- **Proxy Adoption** (confirmed: equal weights) replaces empty `pharmacy_sales` in BPI:
  `adoption_signal = purchase_intent + review-source (app_store/trustpilot) +
  recommendation mentions`, shared vs category peers; flagged `adoption_is_proxy`,
  confidence reduced. No fabricated sales.

**Storage:** `search_metrics` table (migration `a7b8c9d0e1f2`), one row per query —
typed scalar columns (bpi, bpi components, sov_percent, momentum_score, lifecycle_stage,
launch_readiness + the snapshot scalars) for cross-search aggregation, plus jsonb
(`framework`, `snapshot`, `headline`) for full detail. Written by the existing
`log_search_query` background task.

**Frontend:** `Search.tsx` `InsightPanel` renders `data.metrics` automatically —
the combined role headline (framework KPIs first when resolved, then snapshot), a
`FrameworkPanel` (BPI + momentum + lifecycle + launch-readiness cards) for resolved
brands, and the snapshot charts/cross-tabs.

- **Why backend, not frontend**: one source of truth, reuses the framework modules,
  testable, persisted; the client only renders.
