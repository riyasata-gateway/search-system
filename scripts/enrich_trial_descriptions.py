"""Enrich brand-linked clinical-trial mentions with the full study DESCRIPTION
(brief + detailed summary + conditions + primary outcomes) via the
ClinicalTrials.gov v2 API. We store only the trial title today; this folds the
rich text into clean_text so it's embeddable. Idempotent (skips already-long).
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import httpx
from sqlalchemy import create_engine, text
from core.config import settings

API = "https://clinicaltrials.gov/api/v2/studies"
BATCH = 30
DONE_LEN = 500


def _fetch(ncts):
    fields = ("protocolSection.identificationModule.nctId,"
              "protocolSection.descriptionModule,"
              "protocolSection.conditionsModule,"
              "protocolSection.outcomesModule.primaryOutcomes")
    r = httpx.get(API, params={"filter.ids": ",".join(ncts), "fields": fields,
                               "pageSize": len(ncts)}, timeout=30)
    r.raise_for_status()
    out = {}
    for s in r.json().get("studies", []):
        ps = s.get("protocolSection", {})
        nct = ps.get("identificationModule", {}).get("nctId")
        desc = ps.get("descriptionModule", {})
        parts = [desc.get("briefSummary", ""), desc.get("detailedDescription", "")]
        conds = ps.get("conditionsModule", {}).get("conditions") or []
        if conds:
            parts.append("Conditions: " + ", ".join(conds))
        outs = [o.get("measure", "") for o in ps.get("outcomesModule", {}).get("primaryOutcomes") or []]
        if outs:
            parts.append("Primary outcomes: " + "; ".join(o for o in outs if o))
        body = " ".join(p for p in parts if p).strip()
        if nct and body:
            out[nct] = body
    return out


def main():
    eng = create_engine(settings.DATABASE_SYNC_URL)
    with eng.begin() as conn:
        rows = conn.execute(text("""
            SELECT DISTINCT m.id::text mid, m.raw_metadata->>'nct_id' nct,
                   coalesce(m.clean_text, m.raw_text) body
            FROM mentions m JOIN mention_entities me ON me.mention_id = m.id AND me.entity_type='brand'
            WHERE m.source_type='clinical_trials' AND m.is_deleted=false
              AND m.raw_metadata->>'nct_id' IS NOT NULL
        """)).fetchall()
        todo = [(r[0], r[1], r[2]) for r in rows if len(r[2] or "") < DONE_LEN]
        print(f"linked trials: {len(rows)} | to enrich: {len(todo)}")
        by_nct = {}
        for mid, nct, body in todo:
            by_nct.setdefault(nct, []).append((mid, (body or "").split("\n")[0]))
        ncts = list(by_nct)
        done = 0
        for i in range(0, len(ncts), BATCH):
            batch = ncts[i:i+BATCH]
            try:
                desc = _fetch(batch)
            except Exception as e:
                print(f"  batch {i//BATCH} error: {e}"); continue
            for nct, body in desc.items():
                for mid, title in by_nct.get(nct, []):
                    conn.execute(text("UPDATE mentions SET clean_text=:t WHERE id::text=:id"),
                                 {"t": title + "\n\n" + body, "id": mid})   # store COMPLETE text
                    done += 1
            if (i//BATCH) % 10 == 0:
                print(f"  {min(i+BATCH,len(ncts))}/{len(ncts)} NCTs · {done} enriched")
            time.sleep(0.3)
        print(f"DONE: enriched {done} trial mentions.")


if __name__ == "__main__":
    main()
