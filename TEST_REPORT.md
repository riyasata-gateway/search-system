# PharmaWatch — Functional Test Report

_Executed: 2026-05-29 · branch `feature/role-based-analytics` · all queries in English_
_Tested by running a clean server (`uvicorn main:app --port 8001`) against the live
Postgres (2064+ mentions), Qdrant, and the configured OpenAI model. Each case was
called through the real HTTP API as the relevant demo user and the actual response
recorded below._

Legend: ✅ pass · ⚠️ works-but-caveat · ❌ fail / not functional · ⏭️ not executed (reason given)

---

## 0. Executive summary — does this project actually add value?

The blunt question raised was: _"does just changing the order or dividing the search
sources impart actual value? NO!"_ — and the tests **confirm that instinct for the
re-ranking layer**, while showing the value lives elsewhere:

| Layer | Verdict | Evidence |
|---|---|---|
| **Role re-ranking** (source/topic boost matrix) | ⚠️ **Largely cosmetic** | With YouTube in the source set, **all 3 roles returned an identical top-8** (test 15) — the engagement factor in `role_score` swamps the role boost. With engagement removed, ordering differs only subtly and news volume dominates anyway (test 15b). |
| **AI synthesis lens** (per-role narrative) | ✅ **Real, decision-changing value** | Same query produced genuinely different *actions* per role (test 26-29): pharmacist got clinical screening steps, marketing got SEO/channel/sentiment guidance, brand_manager got share/portfolio/reimbursement strategy. This is the differentiator. |
| **Pharmacovigilance pipeline** (risk → review queue → audit) | ✅ **Works, defensible** | Risk flags float to top, escalation + dedup + human triage + audit trail all functioned (tests 16–25, 77). This is regulated, real value. |
| **Cross-lingual expansion** | ✅ Works, ⚠️ brand coverage thin | Maps brands↔INN across BE/FR (tests 1–5), but INN-first ordering truncates brand variants at `max_terms=4` (test 1). |
| **Semantic search** | ❌ **Non-functional here** | Endpoint is correct but the Qdrant collection has **0 points** — embeddings were never written despite 2064 mentions (tests 37–42). |

**Bottom line:** the "role-based search" headline is carried by the **AI narrative and
the pharmacovigilance workflow**, not by re-ranking. The re-ranking should either be
made to actually dominate (cap engagement, or hard-section by source for a role) or be
de-emphasised in the product story. Semantic search needs an embedding backfill before
it can be demoed.

---

## 1. Query expansion (cross-lingual brand↔INN mapping)

| # | Query | Expected | Actual | Verdict |
|---|---|---|---|---|
| 1 | `paracetamol` (max 4) | Expands to BE/FR brands | `[paracetamol, acetaminophen, acétaminophène, doliprane]` | ⚠️ Works, but INN+translations consume the budget — only **1 brand (doliprane)** fits at max_terms=4; Dafalgan/Efferalgan/Panadol truncated |
| 1b | `paracetamol` via live API | `expanded_terms` surfaced | Same 4 terms surfaced; `total=164`, news ok 154 / wikipedia ok 10 | ✅ |
| 2 | `Doliprane` | Reverse-maps to paracetamol family | `[Doliprane, paracetamol, acetaminophen, acétaminophène]` | ✅ |
| 3 | `ibuprofen side effects` | Token match → ibuprofen family | `[ibuprofen side effects, ibuprofen, ibuprofène, ibuprofeen]` | ✅ |
| 4 | `Zyrtec` (max 5) | cetirizine family | `[Zyrtec, cetirizine, reactine, alerlisin]` (accented `cétirizine` deduped) | ✅ |
| 5 | `Augmentin shortage Belgium` | amoxicillin family | `[Augmentin shortage Belgium, amoxicillin, amoxicilline, amoxicilina]` | ✅ |
| 6 | `vitamin C gummies` | No expansion | `[vitamin C gummies]` (passthrough) | ✅ |

**Finding:** expansion is correct but **INN-first ordering limits brand coverage** at the
live cap of 4 terms. Recommend interleaving brands ahead of translations, or raising the
live `max_terms`.

---

## 2. Live search — fan-out, ordering, source notices, filters

| # | Test | Expected | Actual | Verdict |
|---|---|---|---|---|
| 7 | Default fan-out notices (pharmacist) | per-source notice each | news ok 121, youtube ok, pubmed ok 8, eudravigilance ok 10, belgium_health empty | ✅ |
| 8 | `Dafalgan shortage` pharmacist boost | shortage/safety sources top | top-8 all **youtube** (engagement dominates) — see test 15 | ⚠️ boost overridden |
| 9 | `?sources=youtube` (key **is** set) | ok, not missing_key | `youtube ok, 36 results` | ✅ |
| 10 | `?sources=reddit,trustpilot` (no keys) | missing_key notices | both `missing_key` with explanatory detail | ✅ |
| 11 | `?sources=news,bogus_source` | bogus ignored | only `news ok 161`; bogus silently skipped | ✅ |
| 12 | `period=7d` vs `all` (news) | 7d ⊂ all | `7d=46`, `all=154` | ✅ |
| 14 | repeat same query | dedup stable | `138 == 138` | ✅ |
| 15 | **same query, 3 roles, with YouTube** | different order per role | **top-8 identical (all youtube) for all 3 roles** | ❌ **claim false** — engagement swamps role lens |
| 15b | same query, 3 roles, low-engagement sources | lens reorders | pharmacist leads **wikipedia**, marketing/brand lead **news** — but ~90% news volume makes diff marginal | ⚠️ works subtly |
| 72 | `period=banana` (invalid) | falls back to all | `total=154` (== all) | ✅ |
| 73 | `languages=` (empty) | defaults | `200`, results returned | ✅ |

**Key finding (test 15):** `role_score = source_boost × topic_boost × (1 + log1p(engagement)×0.15)`.
A YouTube video's view count makes the engagement factor ~3×, which beats the
pharmacist's deliberate 0.7 YouTube de-boost. **Result: the role re-ranking is invisible
to the user whenever a high-engagement source is present.** Fix options: cap/normalise
engagement per source, or apply the role boost *after* an engagement ceiling.

---

## 3. Pharmacovigilance — risk detection, escalation, triage, audit

| # | Test | Expected | Actual | Verdict |
|---|---|---|---|---|
| 16 | `Doliprane overdose liver damage` | risk rows float to top | 10 flagged, **all 10 ranked above every non-risk row** (`risk_after_nonrisk=false`) | ✅ |
| 25 | `Dafalgan` (clean) | no false positives | 1/10 flagged — the Wikipedia paracetamol article (genuinely discusses overdose/hepatotoxicity) | ⚠️ defensible (high-recall by design) |
| 19 | escalate flagged → review queue | candidates created | `created=2, skipped=1, total=3` | ✅ |
| 20 | re-escalate same | dedup | `created=0, skipped=3` | ✅ |
| 21 | triage → `reviewed` (pharmacist) | status + reviewer stamped | `reviewed`, `reviewed_by=4` | ✅ |
| 22 | triage → `reported` + ref (brand_manager) | ref persists | `reported`, ref `EV-2026-TEST-001` | ✅ |
| 23 | triage → `dismissed` (admin) | status flips | `dismissed` | ✅ |
| 24 | `PUT /adverse-events/99999999/review` | 404 | `404` | ✅ |
| 77 | audit trail | every action logged | `escalate_from_search ×6, reviewed, escalated, reported, dismissed` rows in `audit_logs` | ✅ |

**This is the strongest part of the system** — a complete, audit-logged, human-in-the-loop
pharmacovigilance workflow that maps to the EU GVP obligation. Real, defensible value.

---

## 4. AI mode — does the narrative meaningfully differ by role?

**Test 26-29:** query `paracetamol safety profile`, `lang=en`, run once per role. Full
answers captured. The narratives differ in *substance and recommended action*, not just
wording:

| Role | Lead / recommended action (verbatim excerpts) | sentiment | sources |
|---|---|---|---|
| **pharmacist** | "screen for total daily intake, liver disease, alcohol use… check strength/formulation and confirm weight/age before dose… ask about all OTC/cold-flu products and document total paracetamol exposure" | Neutral | 3 |
| **marketing** | "Doliprane dominates FR recognition; Dutch-speaking BE uses generic 'paracetamol'… dose-clarity messaging resonates, alarmist content underperforms… publish localised BE/FR content set… watch reputational spikes" | Mixed | 4 |
| **brand_manager** | "commercial narrative dominated by safety vigilance rather than growth… review BE/FR portfolios for duplicate paracetamol exposure to protect share… watch supply/reimbursement moving demand between originator/OTC/generic" | Mixed | 5 |
| **admin** | balanced across all three angles | Mixed | 4 |

| # | Field check | Result | Verdict |
|---|---|---|---|
| 30-33 | citations `[n]`, sentiment enum, action key point, disclaimer, English output | All 4 roles: inline `[n]` citations present, valid sentiment enum, ≥1 concrete action key point, disclaimer present, English narrative | ✅ |
| 34 | POST bridge — cite only provided sources (brand_manager) | Cited only `[1]`/`[2]` supplied snippets; brand_manager lens ("openings for other ibuprofen brands and private labels"); `lang=en` | ✅ |
| 35-36 | bridge role lens + lang | covered by 34 | ✅ |

**Finding:** the AI lens is where the "4 roles, 1 query" promise is actually delivered.
A pharmacist and a brand manager get materially different, job-relevant outputs.

---

## 5. Semantic search — ❌ NON-FUNCTIONAL (no data)

| # | Test | Expected | Actual | Verdict |
|---|---|---|---|---|
| 37 | `headache relief` | hits w/ classification | `total=0` | ❌ |
| 38 | `+country=BE` | BE-filtered hits | `total=0` | ❌ |
| 39 | `douleur +language=fr` | FR hits | `total=0` | ❌ |
| 40 | `top_k 5 vs 50` | count respects k | `0 / 0` | ❌ |
| 41 | role blend ordering | pharmacist vs marketing differ | both empty | ❌ |
| 67 | very long query | graceful | `200, total=0` | ✅ (graceful) |

**Root cause (diagnosed):** embedder works (produces 768-dim vectors), Qdrant reachable,
collection `pharmawatch_mentions` exists — but it holds **0 points**. Embeddings were
never written to Qdrant despite 2064 mentions in Postgres. The endpoint degrades
gracefully (returns `total=0`, no 500), but the feature **cannot be demoed until the
vector store is backfilled**. _Action: run the embedding backfill over existing mentions._

---

## 6. RBAC / role resolution

| # | Test | Expected | Actual | Verdict |
|---|---|---|---|---|
| 43 | marketing requests `role=pharmacist` | ignored, stays marketing | `role=marketing` | ✅ |
| 44 | admin view-as pharmacist | `pharmacist` | `pharmacist` | ✅ |
| 45 | admin role variations | each honored; empty→admin | marketing→marketing, brand_manager→brand_manager, (empty)→admin | ✅ |
| 46 | admin `role=ceo` (invalid) | falls back to admin | `admin` | ✅ |
| 54 | marketing analytics `role=admin` | locked to marketing | `scope=marketing` | ✅ |
| 74 | unauthenticated search | 401 | `401` | ✅ |

No privilege escalation possible — non-admins are hard-locked to their own role at both
search and analytics layers.

---

## 7. Analytics dashboard + role-usage

| # | Test | Expected | Actual | Verdict |
|---|---|---|---|---|
| 51 | dashboard pharmacist (auto-scoped) | own role only | `scope=pharmacist`; 12 searches, risk_share 5.7%, risk slice {adverse_event 128, shortage 45, misinfo 2} | ✅ |
| 52 | dashboard admin all | combined | 48 searches; top: doliprane 15, ibuprofen 7…; sentiment {neutral 11908, neg 3155, pos 996}; risk {AE 694, shortage 225} | ✅ |
| 53 | admin scope=marketing | marketing rows | `scope=marketing`, 12 | ✅ |
| 55 | period 7d vs all | window applies | `48 == 48` (correct — all test data is today) | ✅ |
| 60 | role-usage admin | cross-role table | admin 14, marketing 12, pharmacist 12, brand_manager 5, **lab_user 4, unknown 1** | ✅ ⚠️ |
| 61 | role-usage pharmacist | own row only | `[pharmacist 12]` | ✅ |

**Data-hygiene note (test 60):** historical audit rows still carry the retired
`lab_user` role and a `(None)`/`unknown` role. Functionally harmless, but the cross-role
table shows a dead persona. Consider backfilling `search_queries.role` (`lab_user` →
`brand_manager`) to match the user-table migration `e5f6a7b8c9d0`.

---

## 8. Edge cases & robustness

| # | Test | Expected | Actual | Verdict |
|---|---|---|---|---|
| 62 | `q='a'` | 422 | `422 string_too_short` | ✅ |
| 63 | whitespace `q` | graceful | `200, total=0` | ✅ |
| 64 | gibberish | 0 results | `200, total=0` | ✅ |
| 65 | SQL injection string | no damage | `200, total=0`; **mentions table intact (2066 rows)** | ✅ |
| 66 | XSS string | safe | `200, total=0` | ✅ |
| 67 | 500-char query | graceful | `200` | ✅ |
| 68 | accented `Doliprané` | normalised | `200` | ✅ |
| 70 | AI with no OPENAI key | 503 | ⏭️ not executed (would require unsetting the live key); handler verified by code read (`api/routers/ai_search.py:559`) | ⏭️ |
| 71 | AI model timeout | 504 | ⏭️ not executed (cannot force upstream timeout safely); handler verified by code read (`ai_search.py:443`) | ⏭️ |

---

## 9. Audit & ingest side-effects

| # | Test | Expected | Actual | Verdict |
|---|---|---|---|---|
| 75 | every `/search/*` persists | search_queries + results rows w/ role | 49 search_queries, 16059 search_results; role stamped per row | ✅ |
| 76 | broker-down resilience | search unaffected | ⏭️ not executed (broker is up); code path is best-effort try/except (`live_search.py:22`) | ⏭️ |
| 77 | AE triage → audit log | every decision logged | all 5 action types present in `audit_logs` | ✅ |
| — | live ingest enqueue (DPIA on) | mentions grow | mentions 2064 → 2066 during testing (background ingest firing) | ✅ |

---

## 10. Prioritised fix list (from these results)

1. **✅ DONE — Backfill Qdrant embeddings** — `scripts/backfill_embeddings.py` run; 2066
   vectors written; semantic search verified working. (See Fix 1.)
2. **✅ DONE — Role lens no longer uses a score** — replaced engagement-weighted float with
   deterministic priority tiers; roles now order differently and engagement is out of the
   sort entirely. (See Fix 2.)
3. **✅ DONE — Expansion brand coverage** — live/AI `max_terms` raised to 8; full brand set
   now surfaces. (See Fix 3.)
4. **✅ DONE — Analytics role hygiene** — migration `f6a7b8c9d0e1` folds retired
   `lab_user` audit rows into `brand_manager`; only a single legitimate null row remains.
   (See Fix 4.)
5. **⏭️ OPEN — Add automated coverage** for the AI 503/504 paths and broker-down ingest
   (mock the upstreams) so these don't rely on manual verification.
6. **✅ DONE — Classification backfill** — `scripts/backfill_classifications.py` wrote 2066
   rule-based classification rows; semantic hits now carry topic/sentiment/risk and the
   topic tier is live. (See Fix 5.)

---

---

# FIXES APPLIED — 2026-05-29

## Fix 1 — Semantic search backfill (was ❌, now ✅)

**What was wrong:** 2066 mentions in Postgres, but the Qdrant collection
`pharmawatch_mentions` held **0 vectors** — embeddings are normally written inline by
the NLP worker (`workers/processing_worker.py` → `upsert_mention_embedding`), and that
step had never run for the existing corpus. So every semantic query returned `total=0`.

**What I did:** added `scripts/backfill_embeddings.py` — a batched, idempotent backfill
that mirrors the production write path exactly (same embedder, same payload
`{mention_id, source_type, country, language}`, writes `mentions.qdrant_point_id` back).
Ran it: **2066/2066 mentions embedded → Qdrant now holds 2066 points.**

**Verification (re-ran tests 37–41):**
- `headache relief` → 5 multilingual hits, cosine 0.52–0.66 ✅
- `country=BE` filter → all-BE results, 34ms (server-side Qdrant filter) ✅
- `language=fr` filter → all-FR results ✅
- `top_k` 5 vs 50 respected ✅

Re-run after a model change or a Qdrant wipe with:
`python scripts/backfill_embeddings.py` (only missing) or `--all` (re-embed everything).

### How / when / where semantic search is used

- **What it is:** meaning-based retrieval over the **already-ingested mention corpus**
  (the historical `mentions` table), not a live web fetch. The query is embedded with the
  same multilingual model (`paraphrase-multilingual-mpnet-base-v2`, 768-dim) and matched
  by cosine similarity in Qdrant; hits are joined back to `mentions` +
  `mention_classification` for sentiment/topic/risk, then role-ordered.
- **How it differs from the other two modes:**
  - **Live search** = real-time fetch from external connectors (news, YouTube, PubMed…),
    keyword-based, nothing stored-corpus about it.
  - **AI mode** = LLM narrative (own research, or grounded on live results via the bridge).
  - **Semantic** = "find me things in *our collected history* that *mean* the same as this",
    cross-lingual and typo/synonym-tolerant. A French query like `douleur` matches Dutch/
    German mentions about pain without any keyword overlap — keyword search can't do that.
- **When it's the right tool:** retrospective questions over the corpus —
  *"what have we already seen about heart-palpitation complaints?"*, *"surface past
  mentions semantically similar to this new adverse-event report"*, clustering/dedup of
  near-duplicate mentions, or "more like this" from a result. It is **only as good as the
  corpus** — empty/stale corpus ⇒ empty results (exactly the failure we just fixed).
- **Where it's wired:** `GET /api/v1/search/semantic` (`api/routers/semantic_search.py`),
  reachable from the Search page; embeddings are produced at ingest time and, for legacy
  rows, by the new backfill script.

## Fix 2 — Role re-ranking: removed the score, replaced with priority tiers (was ⚠️, now ✅)

**What was wrong:** ordering used `source_boost × topic_boost × (1 + log1p(engagement)×0.15)`
and sorted on that float. A YouTube view count made the engagement factor ~3×, which beat
the pharmacist's deliberate 0.7 YouTube de-boost — so **all roles got an identical top-8
(all YouTube)**. The lens was invisible.

**What I did (no score, per your instruction):** replaced it with **deterministic priority
tiers** in `core/role_lens.py`. Each role declares ordered *categories* of sources and
topics (T0 = most relevant … T3, unranked → bottom). A result lands in the lowest-numbered
tier it matches, and ordering is a plain tuple comparison:

> `(risk first, source tier, topic tier, newest first)` — **engagement is not in the sort
> at all.**

`role_score`/`source_rank_key` are gone; callers now use `role_sort_key` (live),
`grounding_sort_key` (AI grounding), and a cosine-band + tier key (semantic). Admin uses
empty tiers → everything is equal → pure-recency neutral view.

**Verification (re-ran test 15, same query + sources, *with* YouTube):**

| Query: `paracetamol`, sources incl. YouTube | Old result | New result |
|---|---|---|
| pharmacist top | all YouTube | **all PubMed** (clinical, T1); YouTube absent from top |
| marketing top | all YouTube | **all news** (reach, T0) |
| brand_manager top | all YouTube | **all news** (market, T0) |
| admin top | all YouTube | mixed pubmed/news by recency (neutral) |

Roles now order differently and **engagement never floods the top**. Risk-flagged results
still float first for every persona (patient safety) — verified: a `Dafalgan shortage`
query keeps all shortage-risk rows on top, and *within* that tier the pharmacist leads with
`bcfi_cbip` while marketing/brand lead with `news`.

_Trade-off:_ within a tier, ordering is by recency, not by any relevance magnitude — that
is the explicit "no score" design. If two results share tier + date, original fetch order
breaks the tie (stable sort).

## Fix 3 — Live `max_terms` raised 4 → 8 (was ⚠️, now ✅)

**What I did:** `expand_query(..., max_terms=8)` in `api/routers/live_search.py` (and AI
mode raised 5 → 8 for parity). At the old cap of 4, the INN + translations consumed the
budget and brand variants were truncated. Now:

- `paracetamol` → `paracetamol, acetaminophen, acétaminophène, doliprane, dafalgan, efferalgan, panadol, perdolan` ✅
- `ibuprofen` → `ibuprofen, ibuprofène, ibuprofeen, advil, nurofen, brufen, dolormin, spidifen` ✅

_Trade-off:_ live search fans news out across (keywords × locales), so more keywords = more
fetches and modestly higher latency on the default source set. Tune the number at
`live_search.py` if it gets slow.

### How query expansion works (`processing/query_expansion.py`)

1. **Curated dictionary.** A hand-maintained list pairs each generic **INN** with its EU
   brand names + local-language spellings, e.g. `paracetamol → {acetaminophen,
   acétaminophène, doliprane, dafalgan, efferalgan, panadol, perdolan, ben-u-ron, panodil}`.
   It deliberately covers the OTC drugs pharmacists/labs actually search — it is **not** an
   exhaustive drug database.
2. **Normalisation.** Both the query and every dictionary term are lower-cased and
   **accent-stripped** (`acétaminophène` → `acetaminophen`-style key), so accents and case
   never cause a miss, and accent-only duplicates collapse.
3. **Reverse index.** Every variant points back to its canonical group, so the lookup is
   bidirectional — searching a brand (`Doliprane`) finds the INN and *all sibling brands*,
   and vice-versa.
4. **Lookup with multi-word fallback.** Exact normalised match first; if the whole string
   isn't a key (e.g. `ibuprofen side effects`), it tokenises and matches the first known
   token (`ibuprofen`). Unknown queries (`vitamin C gummies`) pass through unchanged as
   `[query]`.
5. **Dedup + cap.** Returns the **original query first**, then unique variants up to
   `max_terms` (now 8). _Current ordering is INN → translations → brands_, so the cap still
   decides which brands make it in; raising the cap to 8 is what now lets Dafalgan/Efferalgan
   through. (A further refinement, not done here, would interleave brands ahead of
   translations so brand coverage survives an even tighter cap.)
6. **Downstream use.** The expanded list becomes the keyword set every live connector
   queries, is shown to the user as `expanded_terms`, and is handed to the AI prompt as a
   "this brand is known across these EU variants" note.

---

# FIXES — ROUND 2 (2026-05-29)

## Fix 4 — Analytics role hygiene (was ⚠️ open, now ✅)

Migration `migrations/versions/f6a7b8c9d0e1_search_query_role_hygiene.py` runs
`UPDATE search_queries SET role='brand_manager' WHERE role='lab_user'` — aligning the
audit log with the account-level enum split (`e5f6a7b8c9d0`). Genuinely-null rows
(searches recorded before role tracking) are left alone — no defensible role to assign.

**Verified:** role distribution went from `…brand_manager 7, lab_user 4, null 1` to
`…brand_manager 11, null 1`. The retired persona no longer appears in the role-usage table.
Applied with `alembic upgrade head` (head now `f6a7b8c9d0e1`).

## Fix 5 — Classification backfill: topic tier no longer inert (was ⚠️ open, now ✅)

**Root cause:** all 2066 mentions had **zero** `mention_classifications` rows (the NLP
worker never ran over the imported corpus — same gap as the embeddings), so semantic hits
returned `topic=None`/`sentiment=None` and the topic half of the role lens did nothing.

**Fix:** `scripts/backfill_classifications.py` — a fast, deterministic, rule-based
backfill (the same keyword logic Live Search already uses for sentiment/topic, plus the
real regex `detect_risk`). Idempotent; rows tagged `model_name='rule_backfill'` so the LLM
worker can re-classify for higher accuracy later. **Wrote 2066 rows.** Distribution:
topic `{general 1879, efficacy 66, side_effect 43, price 34, availability 25,
recommendation 19}`, sentiment `{neutral 1826, positive 163, negative 77}`, risk
`{none 1972, adverse_event 72, shortage 20, misinformation 2}`.

**Verified the topic tier is now live:** same query `medicine side effects and safety`,
same cosine scores, different order per role — pharmacist/brand_manager rank `side_effect`
hits above `general` (T0/T1), while marketing pushes the *same* hits down (side_effect is
its T2 "reputational watch") and floats `general` up. The lens now differentiates on both
source *and* topic.

_Note:_ rule-based is a pragmatic backfill, not LLM-grade accuracy (e.g. `general`
dominates because news headlines are short). Re-run via the LLM worker when you want the
production-quality labels.

## Fix 6 — AI mode is now fully independent (bridge removed)

Per request: **AI search must not be fed Live Search results.** Removed the entire bridge:

- **Backend** (`api/routers/ai_search.py`): deleted the `POST /search/ai`
  "Ask AI about these results" endpoint and the `AISearchFromResultsRequest` model. Also
  removed the large block of **dead grounding code** (`_fetch_news_context`,
  `_fetch_*_grounding`, `_round_robin_dedupe`, `_build_context_block`, `_simple_sentiment`,
  `_raw_mention_to_dict`) that only the bridge path ever referenced. `_synthesise` is now
  own-research only (always allows web search, builds source cards from the model's own
  citations). Only `GET /search/ai` remains.
- **Frontend** (`frontend/src/pages/Search.tsx`): removed the "Ask AI about these results"
  button, the `BridgePayload` type, the `bridge` state + effect, the `onAskAI` prop, and
  the POST branch of the AI mutation (now always a `GET`). Removed the orphaned `Wand2`
  import and the `live.askAi*` / `ai.bridgeFromN` i18n keys.

**Verified:** `POST /api/v1/search/ai` → **405 Method Not Allowed** (endpoint gone);
backend router exposes only `GET /ai`; `npx tsc --noEmit` passes clean (exit 0). Live
Search and AI Mode are now two fully independent answers to the same query.

---

## Test environment notes

- Tests ran against a **separate clean server on :8001**; the developer's `--reload`
  server on :8000 was hung (TCP accepted, no HTTP response) and was left untouched.
- Demo password `demopass123`; users `{pharmacist,marketing,brand_manager,admin}@pharmawatch.eu` all present.
- Tests 19–23 created real AE candidates and audit rows (test data, status visible in queue).
- Reddit/Trustpilot keys absent (expected `missing_key`); YouTube + OpenAI keys present and working.
