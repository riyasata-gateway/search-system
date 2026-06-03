# PharmaWatch / TDAH — Roles, Access & Pharmacovigilance Reference

_Last updated: 2026-05-29 · branch `feature/role-based-analytics`_

This document covers two things requested for the demo:
1. **Which tabs each role can see** (+ the demo credentials), and
2. **What "Adverse Event Candidates" are**, why they exist, and how they make the
   platform valuable.

---

## 1. Roles & tab access

The platform has **four** roles (the generic `lab_user` was split into two business
personas):

| Role key | Who they are | Job-to-be-done |
|---|---|---|
| `pharmacist` | Community pharmacist (counter) | Dispensing & patient safety: shortages, side effects, dosage, OTC counseling |
| `marketing` | Brand communications team | Reach, sentiment, buzz, message resonance, campaign/content decisions |
| `brand_manager` | Brand / product owner | Market share, competitive positioning, demand, pricing/reimbursement, launch & brand risk |
| `admin` | Platform owner | Full oversight; can *view-as* any persona |

Access is enforced in two layers: **frontend** route guards + nav filtering
(`frontend/src/App.tsx`, `frontend/src/components/Layout.tsx`) and **backend** role
guards (`api/dependencies.py`: `require_pharmacist`, `require_marketing`,
`require_brand_manager`, `require_admin`, and the umbrella `require_lab` =
marketing + brand_manager + admin).

### Tab access matrix

| Tab (route) | pharmacist | marketing | brand_manager | admin |
|---|:--:|:--:|:--:|:--:|
| Pharmacist dashboard (`/pharmacist`) | ✅ | — | — | ✅ |
| Lab / Brand (`/lab`) | — | ✅ | ✅ | ✅ |
| Brand Potential (`/brand-potential`) | — | ✅ | ✅ | ✅ |
| Search (`/search`) | ✅ | ✅ | ✅ | ✅ |
| Analytics (`/analytics`) | ✅ | ✅ | ✅ | ✅ |
| Brand Setup (`/setup`) | — | ✅ | ✅ | ✅ |
| Alerts (`/alerts`) | ✅ | ✅ | ✅ | ✅ |
| Adverse Events (`/adverse-events`) | ✅ | ✅ | ✅ | ✅ |
| Admin (`/admin`) | — | — | — | ✅ |

**Role-aware behaviour inside shared tabs:**
- **Search** applies each role's lens automatically (result re-ranking + the AI
  answer's narrative). Admins additionally get an in-page **"view-as" switcher**.
- **Analytics** auto-scopes non-admins to *their own* role's data; **admin** gets a
  role **dropdown** (`all` / pharmacist / marketing / brand_manager / admin) plus a
  cross-role "usage by role" table.

### Demo credentials

Password (all accounts): **`demopass123`**

| Role | Email |
|---|---|
| Pharmacist | `pharmacist@pharmawatch.eu` |
| Marketing | `marketing@pharmawatch.eu` |
| Brand Manager | `brand_manager@pharmawatch.eu` |
| Admin | `admin@pharmawatch.eu` |

Re-create/refresh at any time with `python scripts/seed_demo.py` (idempotent — only
inserts missing accounts).

---

## 2. Adverse Event Candidates — what, why, and the value

### What it is

An **adverse event (AE)** is any harmful or unintended reaction associated with a
medicine — a side effect, a drug interaction, or a quality defect that causes harm.
**Pharmacovigilance** is the regulated discipline of detecting, assessing and
reporting them.

An **Adverse Event *Candidate*** in this platform is a mention that the system has
**automatically flagged as *possibly* describing an adverse event**, then parked in a
**human review queue** for triage. It is a *candidate*, not a conclusion.

**How a candidate is created (the pipeline):**
1. A mention is collected (connectors) or surfaced (live search → governed ingest).
2. `process_pending_mentions` runs the **regex risk detector** (`processing/risk_detector.py`)
   as a high-recall first pass, then an **LLM verification** (`verify_risk_with_llm`)
   to cut false positives.
3. If still flagged, `process_mention_alerts` creates an `AdverseEventCandidate`
   (status `pending`) + a critical alert.
4. A user can also **manually escalate** risk-flagged live-search results via the
   Search page's "Review queue →" button (`POST /adverse-events/from-search`).
5. A human reviewer triages it on the **Adverse Events** tab:
   `reviewed` / `escalated` / `reported` / `dismissed`, optionally attaching an
   external pharmacovigilance reference. **The system never makes the final call.**

Data model: `models/adverse_event.py` → `adverse_event_candidates`
(`mention_id`, `description`, `review_status`, `reviewed_by/at`,
`pharmacovigilance_ref`, `notification_sent_at`).

### Why it exists — the actual purpose

- **Regulatory obligation.** Under EU **GVP** (Good Pharmacovigilance Practices), a
  marketing-authorisation holder must screen *all* sources — including social media,
  forums, news — for adverse events and report qualifying cases to **EudraVigilance**
  within strict timelines (serious cases ≤ 15 days). A tool that surfaces candidates
  from Belgian/French web chatter directly supports that legal duty.
- **Patient safety.** Aggregating weak signals across many sources can reveal an
  emerging safety problem (e.g. a contaminated batch) earlier than spontaneous
  reporting alone.
- **Human-in-the-loop by design.** Automated systems must not *decide* on AEs; the
  queue enforces mandatory human review and an inspection-ready audit trail (every
  triage decision is written via `write_audit_log`).

### How it's fruitful for the platform

- **Compliance automation** — turns an otherwise-manual screening duty into a
  triaged queue, saving the pharmacovigilance officer hours and reducing miss risk.
- **Early signal detection** — the "weak signal before competitors/regulators" value
  proposition, grounded in BE/FR-localised sources (FAGG, ANSM, EudraVigilance,
  forums, reviews).
- **Per-role usefulness:**
  - *pharmacist* triages candidates at the safety coal-face;
  - *brand_manager* reads AE volume/trend as **brand risk**;
  - *admin* gets oversight and audit.
- **Surfaced in Analytics** — the dashboard's **risk-share** KPI and **risk-signals**
  breakdown are computed from these flags, so leadership sees safety exposure at a
  glance.
- **Defensible audit trail** — supports regulatory inspection and internal QA.

---

## Related code

| Concern | Location |
|---|---|
| Role definitions / enum | `models/user.py` (`UserRole`) |
| Role lens (re-rank + AI prompt) | `core/role_lens.py` |
| Backend guards | `api/dependencies.py` |
| Frontend routes / nav | `frontend/src/App.tsx`, `frontend/src/components/Layout.tsx` |
| Analytics (role-scoped) | `api/routers/search_analytics.py`, `frontend/src/pages/Analytics.tsx` |
| AE candidates model | `models/adverse_event.py` |
| AE queue + escalation API | `api/routers/adverse_events.py` |
| AE detection pipeline | `processing/risk_detector.py`, `workers/processing_worker.py`, `intelligence/alert_engine.py` |
| BE/FR shortage connectors | `ingestion/connectors/belgium_health_data.py` (FAGG/AFMPS), `ingestion/connectors/ansm.py` (ANSM FR) |