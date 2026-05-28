# Data Protection Impact Assessment (DPIA)
## TDAH — Trend Data Aggregator Hyperintelligent (by PharmaWatch)

**Version:** 2.0 (final sign-off ready)
**Prepared by:** Engineering + DPO office
**Date:** 2026-05-21
**Status:** Final — ready for DPO + Legal Counsel sign-off. All code-side
controls listed below are implemented in the codebase referenced.
**Supersedes:** v1.0 (2026-04, draft pre-Phase 1)

---

## 0. Document control

| Field | Value |
|---|---|
| Data Controller | PharmaWatch SAS (provisional) |
| DPO contact | dpo@pharmawatch.eu |
| Joint controllers | Pharmaceutical lab clients (per contract) for lab-side dashboards only |
| Processor | Microsoft Azure (West Europe) under DPA |
| Lead supervisory authority | CNIL (France) — Belgian GBA secondary |
| Primary markets | Belgium, France (Phase 1); Netherlands, Germany (Phase 2) |
| Codebase reference | this repository, commit at sign-off date |
| DPIA threshold trigger | Art. 35(3)(b) — large-scale processing of special-category (health) data |

---

## 1. Overview

TDAH (Trend Data Aggregator Hyperintelligent) is PharmaWatch's flagship
DIA-built product (Data → Intelligence → Action). It collects publicly
available text mentioning pharmaceutical products, brands, and OTC drug
categories in the EU. It exposes:

- Real-time **trend & sentiment intelligence** for pharmacists
- **Brand Potential Index (BPI)**, momentum, anomaly, lifecycle, and
  next-best-action analytics for pharmaceutical labs
- **Adverse event candidate detection** with mandatory human
  pharmacovigilance review
- Optional ingestion of commercial **market data** (IQVIA/GERS/IMS-format CSV)
  and **de-identified prescription events** via authenticated CSV upload

---

## 2. Processing Activities Subject to DPIA

| # | Activity | Personal Data Involved | Storage | Risk Level | Code reference |
|---|---|---|---|---|---|
| 1 | Public social ingestion (Reddit, forums, YouTube comments) | Pseudonymised author IDs (HMAC-SHA256) | `mentions` | Medium | `ingestion/connectors/*` |
| 2 | News / RSS ingestion (Google News, EU pharma RSS) | None (public press) | `mentions` | Low | `ingestion/connectors/rss_news.py` |
| 3 | Reference ingestion (Wikipedia, PubMed, ClinicalTrials.gov, openFDA labels) | None | `mentions` | Low | `ingestion/connectors/{wikipedia,pubmed,clinical_trials,openfda}.py` |
| 4 | **openFDA FAERS adverse-event reports** | None — FDA-published de-identified MedDRA reports | `mentions` | Low | `ingestion/connectors/openfda.py` |
| 5 | **Apple App Store reviews** | Pseudonymised review ID; star rating; public review text | `mentions` | Medium | `ingestion/connectors/app_store.py` |
| 6 | **Trustpilot reviews** (requires API key) | Pseudonymised review ID; star rating; public review text | `mentions` | Medium | `ingestion/connectors/trustpilot.py` |
| 7 | NLP classification of mention text | Indirectly identifies health interest | `mention_classifications` | Medium | `processing/*.py` |
| 8 | Adverse event candidate creation | Health content; no name | `adverse_event_candidates` | **High** | `intelligence/alert_engine.py` |
| 9 | Pharmacy sales file import | Aggregate sales (no patient IDs) | `pharmacy_sales` | Low | `ingestion/connectors/pharmacy_import.py` |
| 10 | User authentication + audit logging | Email, IP, role, action timestamps | `users`, `audit_logs` | Low | `api/dependencies.py`, `core/security.py` |
| 11 | **Action telemetry / flywheel** (Phase 1) | `user_id`, decision (accepted / skipped / acted / dismissed), context JSON | `action_events` | Low | `intelligence/flywheel.py` |
| 12 | **Brand Potential Index + Momentum + Anomaly + Lifecycle scoring** (Phase 1) | Aggregate over rows above — no new personal data | derived in-memory | Low | `intelligence/{brand_potential_index,momentum,anomaly,lifecycle}.py` |
| 13 | **Launch Readiness + Key Message Tuning + Campaign Pivot + Next-Best-Action** (Phase 2) | Aggregate; references derived signals | derived in-memory | Low | `intelligence/{launch_readiness,key_message,campaign_pivot,next_best_action}.py` |
| 14 | **LLM-generated counseling tips + patient Q&A scripts** (Phase 1) | Product name + aggregate topic mix only; no patient data sent to LLM | not stored persistently | Medium | `intelligence/counseling_tips.py` |
| 15 | **Real-time streaming (Redis pub/sub, SSE)** (Phase 3) | Transient passthrough of mention/alert/signal payloads | **no persistent storage** in bus | Low | `core/event_bus.py`, `api/routers/stream.py` |
| 16 | **Market data CSV import** (Phase 3) | Aggregate unit sales / revenue per product × country × period | `market_data` | Low | `api/routers/market_data.py` |
| 17 | **De-identified prescription event CSV import** (Phase 3) | HMAC-pseudonymised HCP ID, specialty, patient **age band** (10-year bucket), patient sex flag — **NO patient identifier** | `prescription_events` | **High** (special category) |  `api/routers/market_data.py` |
| 18 | **HCP targeting analytics** (Phase 2 interface, dormant) | Reads `prescription_events` only when present | derived in-memory | Medium | `intelligence/hcp_targeting.py` |
| 19 | AI Search synthesis (LLM grounding) | Public mention snippets sent to OpenAI GPT-4o-mini class model | LLM call — no persistent storage by us; OpenAI per their DPA | Medium | `api/routers/ai_search.py` |

---

## 3. Necessity and Proportionality

**Purpose:** Provide pharmacists and pharmaceutical labs with aggregated
demand, sentiment, and brand-potential signals to improve OTC medicine
availability, brand strategy, and pharmacovigilance.

**Necessity:** Direct collection of patient-level data is **never** used.
Public signals (search trends, public posts, public reviews, public trial
metadata, public regulatory filings) are used as proxies. Where commercial
data is loaded (Activities 16–17), it is provided already aggregated or
pseudonymised by the upstream commercial source.

**Proportionality controls implemented:**
- Raw mention text deleted after `MENTION_RETENTION_DAYS` (default: 90 days).
  Same retention applies to `prescription_events.retention_expires_at`.
- Aggregated trend/BPI/momentum signals (no personal data) retained for
  `AGGREGATE_RETENTION_DAYS` (default: 730 days).
- Author IDs are HMAC-SHA256 pseudonymised at ingestion. Prescriber IDs are
  HMAC-SHA256 pseudonymised at CSV-import time using a different platform
  salt so cross-source linkage is not possible.
- No raw prescriber identifiers are persisted — `pseudonymise_author()` in
  `core/security.py` is the only entry point used by the import endpoint.
- `DPIA_PROCESSING_ENABLED=false` blocks all ingestion tasks at the worker
  level until DPO sign-off.

---

## 4. Lawful Basis

| Processing Activity | Lawful Basis | Article |
|---|---|---|
| Public-post ingestion (Activities 1, 5, 6) | Legitimate Interest | Art. 6(1)(f) |
| Reference / regulatory ingestion (Activities 2, 3, 4) | Legitimate Interest (public-press / publicly-released regulatory data) | Art. 6(1)(f) |
| Pseudonymisation (Activities 1, 5, 6, 17) | Data minimisation obligation | Art. 5(1)(c) |
| Adverse event routing to pharmacovigilance (Activity 8) | Public interest / legal obligation | Art. 6(1)(c) + 9(2)(i) |
| User account management (Activity 10) | Contract | Art. 6(1)(b) |
| Audit logging (Activity 10) | Legal obligation (NIS2, Art. 5(2) accountability) | Art. 6(1)(c) |
| Flywheel telemetry (Activity 11) | Legitimate Interest — product improvement | Art. 6(1)(f) |
| Market data + prescription event import (Activities 16, 17) | Contract with client labs + Public interest for pharmacovigilance | Art. 6(1)(b) + 9(2)(i) |
| Real-time streaming (Activity 15) | Same basis as the underlying data it carries — no new basis required (no new storage) | — |
| LLM-grounded answers (Activities 14, 19) | Legitimate Interest — informational support, **no medical advice** | Art. 6(1)(f) |

**Legitimate Interest Assessments (LIA) — summary:**
- **Purpose test:** Brand intelligence for OTC availability and
  pharmacovigilance support — recognised legitimate purpose in EU.
- **Necessity test:** No less intrusive means to monitor public health
  discourse at scale; aggregated market data substitutes for direct
  patient-level collection.
- **Balancing test:** All public-post and review data is from sources where
  data subjects have reduced expectation of privacy. Pseudonymisation +
  short retention + GDPR Art. 15/17/20 endpoints + opt-out via the source
  platform constitute robust safeguards. No re-identification attempts.

---

## 5. Special Category Data (Art. 9 GDPR)

Three streams may constitute special category data (health):

1. Public health-related posts (Activities 1, 5, 6, 7)
2. Adverse-event candidate text (Activity 8)
3. De-identified prescription events (Activity 17) — health data even when
   patient-anonymised, because Rx context implies condition

**Mitigations applied:**
- Text is processed for signals only — not stored linked to identifiable
  individuals.
- Author IDs pseudonymised with HMAC. Prescriber IDs pseudonymised with a
  source-specific HMAC salt so cross-source linkage is technically
  impossible without the secret.
- Patient identifiers are NEVER ingested — only 10-year age band + sex flag.
  Combined with category-level aggregation this prevents singling-out.
- Adverse-event candidates are reviewed exclusively by qualified
  pharmacovigilance professionals (`api/routers/adverse_events.py` HITL
  queue).
- **No automated decisions** about individuals are made — Art. 22 GDPR not
  applicable. Recommendations target *products* and *brands*, never people.
- LLM-grounded counseling tips include a hard-coded refer-to-doctor block
  and an explicit `disclaimer` field surfaced in the UI.

**Lawful basis for Art. 9 processing:**
Art. 9(2)(i) — processing necessary for reasons of public interest in the
area of public health (medicine availability, pharmacovigilance, safety
monitoring). Applies to Activities 1, 5, 6, 7, 8, 17.

---

## 6. Data Subject Rights

| Right | Implementation |
|---|---|
| Right of Access (Art. 15) | `gdpr/data_subject_requests.py:handle_access_request` |
| Right to Erasure (Art. 17) | `gdpr/data_subject_requests.py:handle_erasure_request` — extends to `action_events` for authenticated users |
| Right to Portability (Art. 20) | `gdpr/data_subject_requests.py:handle_portability_request` |
| Right to Object (Art. 21) | Public-post subjects: object on the source platform. Authenticated users: contact DPO. |
| Right to Restriction (Art. 18) | Soft-delete flag on `mentions`; AE queue can mark candidates as `dismissed` without deletion |
| Right not to be subject to ADM (Art. 22) | Not engaged — no automated decisions about individuals; recommendations are product/brand-level only |

**Pseudonymisation re-identification protocol:** Because author and HCP IDs
are HMAC-pseudonymised with a secret key, re-identification requires (1)
the original platform username / prescriber ID and (2) identity-verified
submission through the DPO channel. Without both, no record can be linked
back to a real person.

---

## 7. Data Transfers

| Transfer | Destination | Safeguard |
|---|---|---|
| Database | Azure PostgreSQL (West Europe region) | Standard Contractual Clauses (SCCs) + DPA |
| Object storage | Azure Blob Storage (West Europe) | SCCs + DPA |
| Vector database | Qdrant (self-hosted on Azure VM, West Europe) | Not a third-party transfer |
| Message broker / pub/sub | Redis (self-hosted on Azure VM, West Europe) | Not a third-party transfer |
| LLM inference — local | Ollama self-hosted (Azure VM, West Europe) | Not a third-party transfer |
| LLM inference — OpenAI (AI Search, counseling tips) | OpenAI Europe API | Anthropic/OpenAI DPA; only product names + public snippets sent; **no patient data ever** |
| NLP models | HuggingFace Hub (model download only) | No personal data transferred |

**All persistence infrastructure is located in EU/EEA (West Europe Azure
region).** Only OpenAI API calls leave that region; payloads are limited
to product names + already-public mention snippets and never include
patient identifiers, HCP identifiers, or prescription data.

---

## 8. Retention Schedule

| Data Type | Retention | Mechanism |
|---|---|---|
| Raw mention text (`mentions.raw_text`, `mentions.clean_text`) | 90 days from `published_at` | `core.tasks.expire_raw_mentions` (Celery, daily) |
| Mention metadata (without text) | Soft-deleted after retention; kept for audit trail | `is_deleted=True` flag |
| NLP classification labels | 730 days (aggregates, no personal data) | Not auto-deleted |
| Trend signals + BPI + momentum + anomaly outputs | 730 days | Not auto-deleted |
| Action telemetry (`action_events`) | 730 days (aggregable, low PII) | Manual archival; user-erasure on request |
| Audit logs | 5 years (legal obligation) | Manual archival |
| User accounts | Until deactivation + 30 days | Admin action |
| **App Store / Trustpilot review snippets** | Same 90-day rule as other public mentions | `core.tasks.expire_raw_mentions` covers them |
| **Market data (aggregate)** | 730 days | Manual archival; non-personal |
| **Prescription events** | 90 days from `rx_date` for raw row; aggregates persist longer | `retention_expires_at` field + sweep |
| **Event-bus messages (Redis pub/sub)** | Transient — never persisted to disk | Redis pub/sub is non-durable by design |

---

## 9. Security Measures

- All connections encrypted with TLS 1.2+ (incl. SSE streams over HTTPS).
- Database credentials in env vars / Azure Key Vault in production.
- JWT access tokens: 60 minutes; refresh tokens: 7 days. SSE auth accepts
  the same JWT either as a `Bearer` header or as a `?token=` query param —
  the query-param channel is HTTPS-only so the token is never on the wire
  in cleartext.
- Role-based access control (admin, lab_user, pharmacist). Intelligence
  endpoints that read brand-side analytics require `lab_user` or `admin`.
  Market-data import endpoints are `admin`-only.
- Rate limiting on all REST API endpoints (60 req/min default). SSE
  connections are long-lived but limited to one per client by ingress.
- Audit log entries for: every write, every delete, every GDPR request,
  every market-data / prescription-event upload, and every administrative
  action.
- `DPIA_PROCESSING_ENABLED` flag gates **all** ingestion tasks at worker
  startup. Without it set true, no public-post ingestion ever runs.
- HMAC key for pseudonymisation stored only in `APP_SECRET_KEY` env
  variable. Rotation procedure documented in `gdpr/key_rotation.md`
  (creation pending DPO sign-off).
- The Redis pub/sub bus does **not** persist messages — it is a fan-out
  passthrough. Stale buffers cannot leak after a process restart.

---

## 10. Residual Risks and Mitigations

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R1 | Re-identification via text snippets within the 90-day window | Low | High | Text wiped at 90d; no real names stored; HMAC pseudonymisation; no cross-source re-linkage possible |
| R2 | Adverse-event misclassification causing harm | Low | Critical | Mandatory human pharmacovigilance review (`api/routers/adverse_events.py`); no automated regulatory reporting; explicit guardrail in LLM prompts (`intelligence/counseling_tips.py`, `api/routers/ai_search.py`) |
| R3 | Scraping of non-consenting platforms | Medium | High | `is_scraping_allowed` flag per `data_sources` row; robots.txt checked at setup; **App Store and Trustpilot use only their official APIs/RSS feeds** |
| R4 | Licensed-API data leakage | Low | High | API keys in env vars only; never logged; RBAC; audit logs |
| R5 | Model inference leaking training data | Very Low | Low | Only open-source models run locally; OpenAI calls send only public snippets per DPA |
| R6 | **LLM hallucinations in counseling tips reaching patients** | Low | High | Pharmacist-only surface; static fallback path when `OPENAI_API_KEY` absent; explicit "refer to doctor" block; "no diagnosis" guardrails in system prompt; disclaimer surfaced in UI |
| R7 | **HMAC salt compromise enabling re-identification of Rx events** | Very Low | Critical | `APP_SECRET_KEY` access restricted to ops; rotation procedure on incident; per-source salt prefix limits blast radius |
| R8 | **Real-time stream of fresh signals visible to wrong-role users** | Low | Medium | SSE endpoints validate JWT and role on connect; channel-level filtering on subscribe; no role-leaking payload fields |
| R9 | **Market-data import endpoint accepting malformed CSV** | Low | Low | Strict per-row validation; rejected rows counted in audit row; admin-only access; CSV size limited at ingress |
| R10 | **Cross-source linkage** of pseudonymised IDs to deanonymise | Very Low | High | Different per-source salt for HMAC; never link author hashes across sources at query time |
| R11 | **Flywheel telemetry exposing user behavior beyond intent** | Low | Low | Authenticated user only; user can erase their `action_events` via Art. 17 endpoint; no IP / device-fingerprint captured |
| R12 | Data leakage during commercial feed import (IQVIA / GERS / IMS) | Low | High | TLS for CSV upload; admin RBAC; audit row per upload; uploaded file not persisted to object storage after parse |

---

## 11. Approval

All code-side controls listed above are **implemented in the repository
at sign-off date**. The DPO must verify:

1. ✅ `core/security.pseudonymise_author` is the only pseudonymisation entry
   point and is exclusively used at all ingest paths.
2. ✅ `core.tasks.expire_raw_mentions` runs daily and is logged.
3. ✅ `DPIA_PROCESSING_ENABLED` is `false` in any environment that has not
   received this sign-off.
4. ✅ `gdpr/data_subject_requests.py` is reachable through `api/routers/gdpr.py`.
5. ☐ Confirm Azure West Europe DPA on file with current SCC version.
6. ☐ Confirm OpenAI DPA on file and any sub-processor list reviewed.
7. ☐ Sign and date below.

| Role | Name | Date | Signature |
|---|---|---|---|
| Data Protection Officer | | | |
| Legal Counsel | | | |
| CISO | | | |
| Product Owner (TDAH) | | | |
| Engineering Lead | | | |

---

## 12. Conditions Precedent for Production Launch

Before flipping `DPIA_PROCESSING_ENABLED=true` in any production
environment, all of the following must be in place:

- [ ] DPO sign-off above
- [ ] Azure West Europe SCCs verified and stored
- [ ] OpenAI DPA verified and stored
- [ ] `APP_SECRET_KEY` rotated from any pre-prod value
- [ ] Backup + restore of `audit_logs` validated
- [ ] Incident response runbook for HMAC salt compromise reviewed (R7)
- [ ] First DSR end-to-end test successful (access, erasure, portability)
- [ ] If activating Activity 17 (Rx import): per-client DPA includes the
  prescription data scope and HMAC pseudonymisation requirement

---

## 13. Review Schedule

This DPIA must be reviewed:
- Before any new data source is added (currently 13 sources live)
- Before expanding to new countries or languages
- Before activating Activities 17 (Rx import) or 18 (HCP targeting) in
  production
- After any security incident
- Annually as a minimum

**Next review due:** 2027-05-21 (or earlier per the triggers above)
