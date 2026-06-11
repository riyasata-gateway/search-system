"""Build an authoritative brand → SAM-data map from the SAM export.

SAM (Authentic Source of Medicines, FAGG/eHealth) is Belgium's official medicines
database — it maps every Belgian trade name (AMP = Actual Medicinal Product) to its
active substance(s), ATC, packs (CNK), price, reimbursement, market status, and the
marketing-authorisation holder (Company). The NONMEDICINAL table covers parapharmacy
/ cosmetics (CNK + producer). So SAM can enrich brands across ALL categories, not
just medicines.

Originally this matched only the ~31 framework brands. It now matches **every**
catalogue brand so the newly-imported supplier brands get their SAM data too. Output:
`data/sam/brand_inn.json` keyed by brand name; `data/sam/pack_index.json` keyed by CNK.

Matching: the brand is (almost) always the leading word(s) of the SAM OfficialName
("Nurofen 200 mg …"), so we test the leading 1–4 word n-grams of each product name
against the brand-candidate set — O(1) dict lookups, vs an O(AMP × brands) startswith
scan that doesn't scale to 2k brands.

Usage:  .venv/bin/python scripts/build_sam_inn.py [--zip data/sam/sam-12035.zip] [--framework-only]
"""
import argparse
import json
import os
import sys
import unicodedata
import zipfile
from collections import Counter, defaultdict
from datetime import date
from xml.etree import ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from core.config import settings
from models.brand import Brand

OUT = "data/sam/brand_inn.json"
_MAX_NGRAM = 4

# Salt / hydrate suffixes stripped so "Diclofenac Sodium" / "Ibuprofen Lysine"
# collapse to the base molecule — generics & originator share the base INN, not
# the salt, so molecule-competition must group on the base. (Mirrors inn_resolver.)
_SALT_SUFFIXES = [
    "phosphate hemihydrate", "hydrochloride", "diethylamine", "mononitrate",
    "hemihydrate", "phosphate", "carbonate", "sulfate", "sulphate", "citrate",
    "acetate", "maleate", "lysine", "sodium", "besilate", "mesilate", "tartrate",
]

# Excipient / mineral base-molecules that must NOT be treated as a brand's
# defining active for generic-competition (e.g. Gaviscon/Rennie were resolving to
# "calcium" — an antacid mineral — instead of their real active).
_DENY_MOLECULES = {
    "calcium", "magnesium", "sodium", "potassium", "aluminium", "aluminum",
    "sodium hydrogen", "sodium chloride", "water", "glucose", "lactose",
    "calcium phosphate", "silica", "talc",
}

# Belgian parallel importers — they hold many repackaged AMPs, so "most packs"
# wrongly returns them as the MAH (e.g. Voltaren → "PI Pharma"). Skip them when
# picking the marketing-authorisation holder.
_PARALLEL_IMPORTERS = {"pi pharma", "impexeco"}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _base_molecule(s: str) -> str:
    s = s.lower().strip()
    for suf in _SALT_SUFFIXES:
        if s.endswith(" " + suf):
            s = s[: -len(suf) - 1].strip()
    return s


def _deaccent(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _brand_candidates(name: str):
    cands = {name}
    if "/" in name:
        cands.update(p.strip() for p in name.split("/"))
    if "(" in name:
        cands.add(name.split("(")[0].strip())
        inside = name[name.find("(") + 1:name.rfind(")")]
        cands.update(p.strip() for p in inside.replace(" brands", "").split(","))
    return sorted({c.lower() for c in cands if len(c) >= 3})


def _match(name_lower: str, cand_to_brand: dict):
    """Return the brand whose candidate is a leading word n-gram of name_lower."""
    words = name_lower.split()
    for n in range(min(_MAX_NGRAM, len(words)), 0, -1):  # longest leading n-gram first
        key = " ".join(words[:n])
        bn = cand_to_brand.get(key)
        if bn:
            return bn
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", default="data/sam/sam-12035.zip")
    ap.add_argument("--framework-only", action="store_true",
                    help="restrict to the workbook framework brands (legacy behaviour)")
    args = ap.parse_args()

    engine = create_engine(settings.DATABASE_SYNC_URL)
    with Session(engine) as db:
        q = select(Brand)
        if args.framework_only:
            q = q.where(Brand.category.isnot(None))
        brands = db.execute(q).scalars().all()
    # candidate(lower) -> brand.name  (longer brands processed last → win on collision)
    cand_to_brand = {}
    for b in sorted(brands, key=lambda x: len(x.name)):
        for cand in _brand_candidates(b.name):
            cand_to_brand[cand] = b.name
    cand_to_brand_da = {_deaccent(c): bn for c, bn in cand_to_brand.items()}
    print(f"Matching {len(brands)} brands ({len(cand_to_brand)} name candidates) against SAM…")

    z = zipfile.ZipFile(args.zip)
    amp_entry = [n for n in z.namelist() if n.startswith("AMP-")][0]

    brand_data = defaultdict(lambda: {"subs": set(), "cnk": set(), "atc": {},
                                      "prices": [], "reimb": [], "bt": False, "mtype": None,
                                      "statuses": set(), "comm": set(), "companies": Counter(),
                                      "supply": [], "limited": False, "eoc": set(),
                                      # Per-brand pack-weight of each base molecule
                                      # → the brand's DEFINING active (most packs):
                                      "mol_packs": Counter(),
                                      # Dispensing + pricing position (per-pack, summed):
                                      "deliv_codes": set(), "cheapest_true": 0,
                                      "cheapest_false": 0, "clustered": False})
    # Supplier/MAH portfolio: brands matched by Company/Producer name (not product
    # name) — the manufacturer's registered range. Key for B2B supplier brands,
    # which are companies, not trade names, so they never match a product OfficialName.
    portfolio = defaultdict(lambda: {"med_products": 0, "para_products": 0, "atc": set(),
                                     "supply": 0})
    pack_index = {}  # cnk -> {fr, nl, brand, kind, substance, atc}
    # Molecule competition index: base substance -> {company: earliest commercialisation
    # date}. Built across ALL AMPs (not just matched brands) so a matched brand can be
    # placed against every marketer of its molecule → competition intensity (how many
    # MAHs / generics) and a (cautious) first-to-market read.
    mol_index = defaultdict(dict)

    # DeliveryModus code → is-OTC ("free delivery") vs prescription, decoded from the
    # SAM REF reference table (the AMP itself carries only the bare code). A code is
    # OTC iff its official description is "free delivery / délivrance libre / vrije
    # aflevering"; everything else ("prescription médicale…", M*/TD) is Rx.
    delivery_is_otc = {}
    ref_entry = next((n for n in z.namelist() if n.startswith("REF-")), None)
    if ref_entry:
        with z.open(ref_entry) as rf:
            for _, rel in ET.iterparse(rf, events=("end",)):
                if _local(rel.tag) != "DeliveryModus" or not rel.get("code"):
                    continue
                txt = " ".join((c.text or "") for c in rel.iter()
                               if _local(c.tag) in ("Fr", "Nl", "En")).lower()
                if txt:
                    delivery_is_otc[rel.get("code")] = ("libre" in txt or "vrije aflevering" in txt
                                                        or "free delivery" in txt or "freie abgabe" in txt)
                rel.clear()
    print(f"Decoded {len(delivery_is_otc)} DeliveryModus codes from REF "
          f"({sum(delivery_is_otc.values())} OTC / free-delivery).")
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
            deliv_codes = set()
            cheapest_true = cheapest_false = 0
            clustered = False
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
                elif lt == "DeliveryModus" and d.get("code"):
                    deliv_codes.add(d.get("code"))
                elif lt == "Cheapest" and d.text:   # per-pack reimbursement-cluster flag
                    if d.text.strip().lower() == "true":
                        cheapest_true += 1
                    else:
                        cheapest_false += 1
                elif lt == "HeadOfTheCluster" and (d.text or "").strip():
                    clustered = True   # pack sits in a reference-reimbursement cluster
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
            # Belgian supply signal (the highest-value availability source we hold):
            # SupplyProblem → dated Data blocks {from, ExpectedEndOn, Reason, Impact};
            # plus LimitedAvailability and temporary/definitive end-of-commercialisation.
            supply_list = []
            limited = False
            eoc_set = set()
            for node in elem.iter():
                ln = _local(node.tag)
                if ln == "SupplyProblem":
                    for data in node:
                        if _local(data.tag) != "Data":
                            continue
                        frm = data.get("from")
                        end = reason = None
                        for child in data:
                            cl = _local(child.tag)
                            if cl == "ExpectedEndOn" and child.text:
                                end = child.text.strip()
                            elif cl == "Reason":
                                reason = next((g.text for g in child
                                               if _local(g.tag) == "En" and g.text), None)
                        supply_list.append({"from": frm, "end": end, "reason": reason})
                elif ln == "LimitedAvailability" and (node.text or "").strip() == "true":
                    limited = True
                elif ln == "EndOfCommercialization":
                    en = next((g.text for g in node if _local(g.tag) == "En" and g.text), None)
                    if en:
                        eoc_set.add(en)

            # Marketing-authorisation holder (Company → Denomination) — extracted
            # for every AMP so we can both stamp the matched brand's MAH and roll a
            # supplier brand's portfolio up by company.
            company_den = None
            comp = elem.find("{*}Data/{*}Company")
            if comp is not None:
                # Denomination is nested under Company's own dated Data block
                # (Company > Data > Denomination), not a direct child — find it
                # recursively, else the MAH is silently dropped for medicines.
                den = comp.find(".//{*}Denomination")
                if den is not None and den.text:
                    company_den = den.text.strip()
            # Molecule competition: for each rank-1 active substance (base molecule,
            # salt-stripped), record this MAH's earliest commercialisation. Keyed per
            # single base substance so generics/originator across all marketers of the
            # molecule are grouped (a brand's packs fragment across salts & combos).
            rank1_bases = {_base_molecule(s) for rk, s in subs if rk == "1"}
            rank1_bases.discard("")
            if rank1_bases and company_den:
                amp_comm = min(comm) if comm else None
                for base in rank1_bases:
                    mi = mol_index[base]
                    if company_den not in mi:
                        mi[company_den] = amp_comm
                    elif amp_comm and (mi[company_den] is None or amp_comm < mi[company_den]):
                        mi[company_den] = amp_comm
            # Supplier brand matched by its MAH/company name → portfolio roll-up.
            if company_den:
                pb = _match(company_den.lower(), cand_to_brand)
                if pb:
                    portfolio[pb]["med_products"] += 1
                    portfolio[pb]["atc"].update(atcs.keys())
                    if supply_list:
                        portfolio[pb]["supply"] += 1

            if official:
                bn = _match(official.lower(), cand_to_brand)
                if bn:
                    dat = brand_data[bn]
                    # Pack-weight each rank-1 base molecule (excipients excluded) so
                    # we can later pick the brand's DEFINING active, not the molecule
                    # with the most market marketers.
                    for _mb in rank1_bases:
                        if _mb and _mb not in _DENY_MOLECULES:
                            dat["mol_packs"][_mb] += 1
                    dat["subs"].update(subs); dat["cnk"].update(cnks)
                    dat["atc"].update(atcs); dat["prices"].extend(prices)
                    dat["reimb"].extend(reimb); dat["bt"] = dat["bt"] or bt
                    dat["statuses"].update(statuses); dat["comm"].update(comm)
                    if mtype:
                        dat["mtype"] = mtype
                    if company_den:
                        dat["companies"][company_den] += 1
                    dat["supply"].extend(supply_list)
                    dat["limited"] = dat["limited"] or limited
                    dat["eoc"].update(eoc_set)
                    dat["deliv_codes"].update(deliv_codes)
                    dat["cheapest_true"] += cheapest_true
                    dat["cheapest_false"] += cheapest_false
                    dat["clustered"] = dat["clustered"] or clustered
                    nl_el = elem.find("{*}Data/{*}Name/{*}Nl")
                    name_nl = nl_el.text if nl_el is not None else None
                    prim = sorted({s for rk, s in subs if rk == "1"}) or sorted({s for _, s in subs})
                    for ck in cnks:
                        pack_index[ck.lstrip("0")] = {
                            "fr": official, "nl": name_nl, "brand": bn, "kind": "medicine",
                            "substance": prim[0] if prim else None,
                            "atc": (sorted(atcs)[0] if atcs else None),
                        }
            elem.clear()
            if amp_count % 80000 == 0:
                print(f"  …scanned {amp_count} AMPs")

    # ── Pass 2: NONMEDICINAL registry (parapharmacy/cosmetics) — CNK + producer ─
    nm_entry = [n for n in z.namelist() if n.startswith("NONMEDICINAL")][0]
    nm_data = defaultdict(lambda: {"cnk": set(), "producer": None, "count": 0})
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
                bn = _match(_deaccent(name).lower(), cand_to_brand_da)
                if bn:
                    if code:
                        nm_data[bn]["cnk"].add(code)
                        pack_index[code.lstrip("0")] = {
                            "fr": name_fr or name, "nl": name_nl, "brand": bn,
                            "kind": "parapharmacy", "substance": None, "atc": None}
                    nm_data[bn]["count"] += 1
                    nm_data[bn]["producer"] = nm_data[bn]["producer"] or producer
            # Supplier brand matched by the product's Producer → parapharmacy portfolio.
            if producer:
                pb = _match(_deaccent(producer).lower(), cand_to_brand_da)
                if pb:
                    portfolio[pb]["para_products"] += 1
            elem.clear()

    # ── Pass 3: RMB reimbursement detail (category / co-pay / reference price) ─
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
    today = date.today().isoformat()

    def _supply_summary(dat):
        sp = dat.get("supply") or []
        # Active = started on/before today and not past its expected end.
        active = [s for s in sp
                  if (s.get("from") or "9999") <= today
                  and (not s.get("end") or s.get("end") >= today)]
        eoc = dat.get("eoc") or set()
        eoc_status = ("temporary" if any("Temporary" in e or "temporaire" in e.lower() for e in eoc)
                      else "definitive" if any("Definitive" in e or "définit" in e.lower() for e in eoc)
                      else None)
        if not (sp or dat.get("limited") or eoc_status):
            return None
        return {
            "active_problems": len(active),
            "reason": (active[0].get("reason") if active else None),
            "expected_end": min((s["end"] for s in active if s.get("end")), default=None),
            "limited_availability": bool(dat.get("limited")),
            "end_of_commercialisation": eoc_status,
        }

    def _delivery_summary(dat):
        """Rx-vs-OTC dispensing status from the brand's pack DeliveryModus codes.
        Codes unknown to the REF table default to prescription (conservative)."""
        codes = dat.get("deliv_codes") or set()
        if not codes:
            return None
        otc = sorted(c for c in codes if delivery_is_otc.get(c))
        rx = sorted(c for c in codes if not delivery_is_otc.get(c))
        status = "mixed" if (otc and rx) else "otc" if otc else "prescription"
        return {"status": status, "otc_codes": otc, "rx_codes": rx}

    def _pricing_position(dat):
        """Reimbursement-cluster pricing position: how many of the brand's packs are
        the cheapest in their reference cluster (Belgian reference-reimbursement)."""
        ct, cf = dat.get("cheapest_true", 0), dat.get("cheapest_false", 0)
        if not (ct or cf or dat.get("clustered")):
            return None
        total = ct + cf
        return {
            "cheapest_packs": ct,
            "cluster_packs": total,
            "clustered": bool(dat.get("clustered")),
            "all_cheapest": bool(total and ct == total),
        }

    def _molecule_competition(primary, company, mol_packs):
        """Place the brand against every MAH marketing its DEFINING molecule →
        originator (earliest to market) vs generic/follow-on, and competitor count.

        The defining molecule is the one the brand has the MOST of its own packs in
        (pack-weight) — NOT the molecule with the most market marketers, which let a
        minority combo or excipient hijack the signal (Otrivine→fluticasone,
        Gaviscon→calcium). Excipient/mineral bases are excluded entirely."""
        if not company:
            return None
        candidates = {_base_molecule(s) for s in (primary or [])} - {""} - _DENY_MOLECULES
        scored = []
        for base in candidates:
            comp_map = mol_index.get(base)
            if not comp_map or company not in comp_map:
                continue
            # rank by the brand's own pack-weight first, market size as tiebreaker
            scored.append((mol_packs.get(base, 0), len(comp_map), base, comp_map))
        if not scored:
            return None
        scored.sort(reverse=True)
        _, n, base, comp_map = scored[0]
        comms = [c for c in comp_map.values() if c]
        own = comp_map.get(company)
        return {
            "molecule": base,
            "n_marketers": n,
            "generics": max(0, n - 1),
            "is_originator": bool(own and comms and own == min(comms)),
            "own_since": own,
        }

    result = {}
    for b in set(brand_data) | set(nm_data) | set(portfolio):
        dat = brand_data.get(b, {})
        nm = nm_data.get(b, {})
        pf = portfolio.get(b)
        prices = dat.get("prices") or []
        reimb = dat.get("reimb") or []
        is_med = bool(dat.get("subs") or dat.get("atc"))
        prim_list = (sorted({s for rk, s in dat.get("subs", set()) if rk == "1"})
                     or sorted({s for _, s in dat.get("subs", set())}))
        # Marketing-authorisation holder = the company holding the most of the brand's
        # packs (the true MAH; parallel importers each hold only a few), not whichever
        # AMP happened to parse first.
        companies = dat.get("companies") or Counter()
        # Prefer the top holder that is NOT a known parallel importer (importers
        # repackage many AMPs and would otherwise win "most packs" — e.g. Voltaren
        # → "PI Pharma" instead of the originator).
        company_val = None
        for _cn, _ in companies.most_common():
            if _cn and _cn.lower() not in _PARALLEL_IMPORTERS:
                company_val = _cn
                break
        if company_val is None and companies:
            company_val = companies.most_common(1)[0][0]
        company_val = company_val or nm.get("producer")
        entry = {
            "is_medicine": is_med,
            "primary": prim_list,
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
            # Marketing-authorisation holder (medicines) or producer (parapharmacy) —
            # the manufacturer/owner, for B2B / manufacturer roll-ups.
            "company": company_val,
            # Supplier/MAH portfolio: the brand's registered SAM range when it was
            # matched as a manufacturer/producer (B2B supplier brands).
            "sam_portfolio": ({
                "medicines": pf["med_products"],
                "parapharmacy": pf["para_products"],
                "atc_classes": sorted({a[:3] for a in pf["atc"] if a}),
                "supply_problems": pf.get("supply", 0),
            } if pf and (pf["med_products"] or pf["para_products"]) else None),
            # Belgian supply / availability signal (SAM SupplyProblem + EoC).
            "supply": _supply_summary(dat),
            # Rx-vs-OTC dispensing status (SAM DeliveryModus, REF-decoded).
            "delivery": _delivery_summary(dat),
            # Reimbursement-cluster pricing position (SAM Cheapest/HeadOfTheCluster).
            "pricing_position": _pricing_position(dat),
            # Originator-vs-generic, from the molecule's MAH set + first-to-market date.
            "molecule_competition": _molecule_competition(prim_list, company_val, dat.get("mol_packs") or Counter()),
            "status": ("AUTHORIZED" if "AUTHORIZED" in dat.get("statuses", set())
                       else (sorted(dat.get("statuses", set()))[0] if dat.get("statuses") else None)),
            "ever_suspended": bool({"SUSPENDED", "WITHDRAWN", "REVOKED"} & dat.get("statuses", set())),
            "commercialised_since": (min(dat.get("comm")) if dat.get("comm") else None),
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

    n_med = sum(1 for r in result.values() if r["is_medicine"])
    n_para = sum(1 for r in result.values() if not r["is_medicine"] and r["nonmedicinal_skus"])
    n_company = sum(1 for r in result.values() if r["company"])
    print(f"\nScanned {amp_count} AMPs + NONMEDICINAL. Resolved {len(result)} brands "
          f"({n_med} medicines, {n_para} parapharmacy, {n_company} with a company/MAH).")
    print(f"Wrote {OUT} and {pack_path} ({len(pack_index)} CNK packs).")


if __name__ == "__main__":
    main()