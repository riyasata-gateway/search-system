"""Build an authoritative brand → active-substance (INN) map from the SAM export.

SAM (Authentic Source of Medicines, FAGG/eHealth) is Belgium's official medicines
database — it maps every Belgian trade name (AMP = Actual Medicinal Product) to its
active substance(s). This replaces the curated/static INN guesses with ground truth.

The full export's AMP file is ~1.6 GB, so we **stream-parse** it (iterparse, clearing
each element) and keep only the substances for our tracked framework brands. Output:
`data/sam/brand_inn.json` = {brand_name: [substances...]}. Brands with no AMP match
are genuinely *not medicines* in Belgium (cosmetics/supplements) → correctly absent.

Usage:  .venv/bin/python scripts/build_sam_inn.py [--zip data/sam/sam-12035.zip]
"""
import argparse
import json
import os
import sys
import zipfile
from collections import defaultdict
from xml.etree import ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from core.config import settings
from models.brand import Brand

OUT = "data/sam/brand_inn.json"


import unicodedata


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _deaccent(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _brand_candidates(name: str):
    cands = {name}
    if "/" in name:
        cands.update(p.strip() for p in name.split("/"))
    if "(" in name:
        cands.add(name.split("(")[0].strip())
        # also names inside parens, e.g. "UCB brands (Keppra, Bimzelx)"
        inside = name[name.find("(") + 1:name.rfind(")")]
        cands.update(p.strip() for p in inside.replace(" brands", "").split(","))
    return sorted({c.lower() for c in cands if len(c) >= 3})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", default="data/sam/sam-12035.zip")
    args = ap.parse_args()

    engine = create_engine(settings.DATABASE_SYNC_URL)
    with Session(engine) as db:
        brands = db.execute(select(Brand).where(Brand.category.isnot(None))).scalars().all()
    # candidate(lower) -> brand.name
    cand_to_brand = {}
    for b in brands:
        for cand in _brand_candidates(b.name):
            cand_to_brand[cand] = b.name
    cands = sorted(cand_to_brand, key=len, reverse=True)  # longest first
    print(f"Matching {len(brands)} framework brands ({len(cands)} name candidates) against SAM AMP…")

    z = zipfile.ZipFile(args.zip)
    amp_entry = [n for n in z.namelist() if n.startswith("AMP-")][0]

    brand_data = defaultdict(lambda: {"subs": set(), "cnk": set(), "atc": {},
                                      "prices": [], "reimb": [], "bt": False, "mtype": None,
                                      "statuses": set(), "comm": set()})
    pack_index = {}  # cnk -> {fr, nl, brand, kind, substance, atc} — canonical pack backbone
    amp_count = 0
    with z.open(amp_entry) as f:
        for _, elem in ET.iterparse(f, events=("end",)):
            if _local(elem.tag) != "Amp":
                continue
            amp_count += 1
            official = None
            subs = []
            cnks, atcs = set(), {}
            prices, reimb = [], []
            bt, mtype = False, None
            statuses, comm = set(), set()
            for d in elem.iter():
                lt = _local(d.tag)
                if lt == "OfficialName" and d.text and official is None:
                    official = d.text
                elif lt == "Status" and d.text:
                    statuses.add(d.text.strip())
                elif lt == "Commercialization":
                    for c in d.iter():
                        if _local(c.tag) == "Data" and c.get("from"):
                            comm.add(c.get("from"))
                elif lt == "Dmpp" and (d.get("codeType") == "CNK") and d.get("code"):
                    cnks.add(d.get("code"))
                elif lt == "Price" and d.text:
                    try:
                        prices.append(float(d.text))
                    except ValueError:
                        pass
                elif lt == "Reimbursable" and d.text:
                    reimb.append(d.text.strip().lower() == "true")
                elif lt == "BlackTriangle" and (d.text or "").strip().lower() == "true":
                    bt = True
                elif lt == "MedicineType" and d.text and mtype is None:
                    mtype = d.text.strip()
                elif lt == "Atc" and d.get("code"):
                    desc = next((c.text.strip() for c in d if _local(c.tag) == "Description" and c.text), None)
                    atcs[d.get("code")] = desc or atcs.get(d.get("code"))
                elif lt == "RealActualIngredient":
                    rank = d.get("rank")
                    name_en = name_nl = None
                    is_active = False
                    for c in d.iter():
                        clt = _local(c.tag)
                        if clt == "Type" and (c.text or "").strip() == "ACTIVE_SUBSTANCE":
                            is_active = True
                        elif clt == "En" and name_en is None:
                            name_en = c.text
                        elif clt == "Nl" and name_nl is None:
                            name_nl = c.text
                    if is_active and (name_en or name_nl):
                        subs.append((rank, (name_en or name_nl).strip()))
            if official:
                ol = official.lower()
                for cand in cands:
                    if ol.startswith(cand):
                        bn = cand_to_brand[cand]
                        dat = brand_data[bn]
                        dat["subs"].update(subs); dat["cnk"].update(cnks)
                        dat["atc"].update(atcs); dat["prices"].extend(prices)
                        dat["reimb"].extend(reimb); dat["bt"] = dat["bt"] or bt
                        dat["statuses"].update(statuses); dat["comm"].update(comm)
                        if mtype:
                            dat["mtype"] = mtype
                        # Bilingual per-CNK pack index (canonical entity backbone).
                        nl_el = elem.find("{*}Data/{*}Name/{*}Nl")
                        name_nl = nl_el.text if nl_el is not None else None
                        prim = sorted({s for rk, s in subs if rk == "1"}) or sorted({s for _, s in subs})
                        for ck in cnks:
                            pack_index[ck.lstrip("0")] = {
                                "fr": official, "nl": name_nl, "brand": bn, "kind": "medicine",
                                "substance": prim[0] if prim else None,
                                "atc": (sorted(atcs)[0] if atcs else None),
                            }
                        break
            elem.clear()
            if amp_count % 80000 == 0:
                print(f"  …scanned {amp_count} AMPs")

    # ── Pass 2: NONMEDICINAL registry (parapharmacy/cosmetics) — CNK + producer ─
    nm_entry = [n for n in z.namelist() if n.startswith("NONMEDICINAL")][0]
    nm_data = defaultdict(lambda: {"cnk": set(), "producer": None, "count": 0})
    cands_da = {_deaccent(c): cand_to_brand[c] for c in cands}
    nm_cands = sorted(cands_da, key=len, reverse=True)
    with z.open(nm_entry) as f:
        for _, elem in ET.iterparse(f, events=("end",)):
            if _local(elem.tag) != "NonMedicinalProduct":
                continue
            code = elem.get("code")
            name_el = elem.find("{*}Data/{*}Name")
            fr_el = name_el.find("{*}Fr") if name_el is not None else None
            nl_el = name_el.find("{*}Nl") if name_el is not None else None
            name_fr = fr_el.text if fr_el is not None else None
            name_nl = nl_el.text if nl_el is not None else None
            name = name_fr or name_nl or next((d.text for d in elem.iter() if _local(d.tag) in ("Fr", "Nl") and d.text), None)
            producer = None
            for d in elem.iter():
                if _local(d.tag) == "Producer":
                    producer = next((c.text for c in d if c.text), None)
                    break
            if name:
                nl = _deaccent(name).lower()
                for cand in nm_cands:
                    if nl.startswith(cand):
                        bn = cands_da[cand]
                        if code:
                            nm_data[bn]["cnk"].add(code)
                            pack_index[code.lstrip("0")] = {
                                "fr": name_fr or name, "nl": name_nl, "brand": bn,
                                "kind": "parapharmacy", "substance": None, "atc": None}
                        nm_data[bn]["count"] += 1
                        nm_data[bn]["producer"] = nm_data[bn]["producer"] or producer
                        break
            elem.clear()

    # ── Pass 3: RMB reimbursement detail (category / co-pay / reference price) ─
    # RMB is keyed by CNK; map each framework brand's CNKs → reimbursement detail.
    cnk_to_brand = {}
    for b, dat in brand_data.items():
        for c in dat["cnk"]:
            cnk_to_brand[c.lstrip("0")] = b
    rmb_entry = [n for n in z.namelist() if n.startswith("RMB-")][0]
    reimb_detail = defaultdict(lambda: {"categories": set(), "ref_prices": [], "copays": []})
    with z.open(rmb_entry) as f:
        for _, elem in ET.iterparse(f, events=("end",)):
            if _local(elem.tag) != "ReimbursementContext":
                continue
            if elem.get("codeType") == "CNK":
                bn = cnk_to_brand.get((elem.get("code") or "").lstrip("0"))
                if bn:
                    for d in elem.iter():
                        lt = _local(d.tag)
                        if lt == "ReimbursementCriterion" and d.get("category"):
                            reimb_detail[bn]["categories"].add(d.get("category"))
                        elif lt == "ReferenceBasePrice" and d.text:
                            try:
                                reimb_detail[bn]["ref_prices"].append(float(d.text))
                            except ValueError:
                                pass
                        elif lt == "FeeAmount" and d.text:
                            try:
                                reimb_detail[bn]["copays"].append(float(d.text))
                            except ValueError:
                                pass
            elem.clear()

    # ── Merge into output ────────────────────────────────────────────────────
    result = {}
    for b in set(brand_data) | set(nm_data):
        dat = brand_data.get(b, {})
        nm = nm_data.get(b, {})
        prices = dat.get("prices") or []
        reimb = dat.get("reimb") or []
        is_med = bool(dat.get("subs") or dat.get("atc"))
        entry = {
            "is_medicine": is_med,
            "primary": sorted({s for rk, s in dat.get("subs", set()) if rk == "1"})
                       or sorted({s for _, s in dat.get("subs", set())}),
            "all": sorted({s for _, s in dat.get("subs", set())}),
            "atc": [{"code": k, "desc": v} for k, v in sorted(dat.get("atc", {}).items())],
            "cnk": sorted(set(dat.get("cnk", set())) | set(nm.get("cnk", set()))),
            "medicine_type": dat.get("mtype"),
            "black_triangle": bool(dat.get("bt")),
            "price": ({"min": round(min(prices), 2), "max": round(max(prices), 2),
                       "avg": round(sum(prices) / len(prices), 2)} if prices else None),
            "reimbursed_packs": sum(1 for r in reimb if r),
            "total_priced_packs": len(reimb),
            "nonmedicinal_skus": nm.get("count", 0),
            "producer": nm.get("producer"),
            # commercialisation / market status (AMP)
            "status": ("AUTHORIZED" if "AUTHORIZED" in dat.get("statuses", set())
                       else (sorted(dat.get("statuses", set()))[0] if dat.get("statuses") else None)),
            "ever_suspended": bool({"SUSPENDED", "WITHDRAWN", "REVOKED"} & dat.get("statuses", set())),
            "commercialised_since": (min(dat.get("comm")) if dat.get("comm") else None),
            # reimbursement detail (RMB)
            "reimbursement": ({
                "categories": sorted(reimb_detail[b]["categories"]),
                "reference_price": (round(min(reimb_detail[b]["ref_prices"]), 2)
                                    if reimb_detail[b]["ref_prices"] else None),
                "copay": (round(min(reimb_detail[b]["copays"]), 2)
                          if reimb_detail[b]["copays"] else None),
            } if b in reimb_detail else None),
        }
        result[b] = entry

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    pack_path = os.path.join(os.path.dirname(OUT), "pack_index.json")
    with open(pack_path, "w", encoding="utf-8") as fh:
        json.dump(pack_index, fh, ensure_ascii=False)
    print(f"Wrote {pack_path} ({len(pack_index)} CNK packs, FR/NL labels)")

    print(f"\nScanned {amp_count} AMPs + NONMEDICINAL. Resolved {len(result)} framework brands:")
    for b in sorted(result):
        r = result[b]
        kind = "medicine" if r["is_medicine"] else "parapharmacy"
        price = f"€{r['price']['min']}-{r['price']['max']}" if r["price"] else "—"
        print(f"  {b:30s} {kind:12s} INN={r['primary'] or '-'}  ATC={[a['code'] for a in r['atc']]}  "
              f"CNK={len(r['cnk'])}  price={price}  reimb={r['reimbursed_packs']}/{r['total_priced_packs']}  BT={r['black_triangle']}")
    print(f"\nWrote {OUT}")


if __name__ == "__main__":
    main()
