"""Datatopia Brand → Source → KPI catalog — the framework data layer.

Serves the *Datatopia_Brand_Source_KPI_Belgium* workbook as a role-aware API:

  GET /api/v1/catalog/summary        Overview-tab framing + counts
  GET /api/v1/catalog/brands         The 26 tracked brands (+ db id, role-filtered)
  GET /api/v1/catalog/sources        The 20 tiered data sources
  GET /api/v1/catalog/data-to-kpi    Source → per-role KPI matrix
  GET /api/v1/catalog/kpis           KPI library (role-filtered, with data_status)

Role handling mirrors the rest of the app: a non-admin caller is locked to their
own role's slice; admin may pass ?role= to inspect any role (default: all).

Brands are read from the `brands` table (so each carries its real `id` for
linking to /intelligence/* endpoints) and enriched with the workbook metadata
that seed_brand_catalog.py wrote onto the row. Sources / KPIs / matrix come
straight from core.framework_catalog (reference data, not transactional).
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from api.dependencies import get_current_user
from core.database import get_sync_db
from core.framework_catalog import (
    DATA_SOURCES,
    DATA_TO_KPI,
    PRIMARY_CATEGORIES,
    PRIMARY_CATEGORY_CODES,
    ROLE_LABELS,
    TIER_LABELS,
    TOP_BRANDS,
    catalog_summary,
    kpis_for_role,
)
from intelligence.brand_actions import compute_brand_actions
from intelligence.framework_kpis import compute_insights, compute_live_values
from models.brand import Brand
from models.mention import EntityType, MentionEntity
from models.user import User, UserRole

router = APIRouter()

# Workbook roles only (admin is a super-view, not a brand/KPI owner role).
_FRAMEWORK_ROLES = set(ROLE_LABELS.keys())


def _resolve_role(current_user: User, role: Optional[str]) -> str:
    """Admins may inspect any role (or all); everyone else is locked to self.

    Returns the effective role string ('admin' meaning the unfiltered all-roles
    view, or one of the three workbook roles).
    """
    if current_user.role == UserRole.admin:
        if role is None:
            return "admin"
        if role not in _FRAMEWORK_ROLES:
            raise HTTPException(status_code=400, detail=f"Unknown role '{role}'")
        return role
    # Non-admins ignore any ?role= and only ever see their own role.
    return current_user.role.value


@router.get("/summary")
def get_summary(current_user: User = Depends(get_current_user)):
    """Overview-tab framing + catalog counts (the workbook's purpose/insight)."""
    return catalog_summary()


@router.get("/brands")
def list_brands(
    role: Optional[str] = Query(None, description="Filter to a role's primary-interest brands (admin only)"),
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(get_current_user),
):
    """The tracked brands, each with db id + workbook metadata, role-filtered.

    Reads brand ids from the DB so the frontend can deep-link to the
    /intelligence/* endpoints; falls back to the static catalog entry for any
    brand that has not been seeded yet (id = None).
    """
    effective = _resolve_role(current_user, role)

    # Map db rows by name so we can attach real ids + any DB-side overrides.
    rows = {b.name: b for b in db.execute(select(Brand)).scalars().all()}

    out: List[dict] = []
    for b in TOP_BRANDS:
        if effective != "admin" and effective not in b["kpi_roles"]:
            continue
        row = rows.get(b["name"])
        out.append({
            "id": row.id if row else None,
            "name": b["name"],
            "category": b["category"],
            "owner": b["owner"],
            "tier_a_signal": b["tier_a_signal"],
            "tier_bc_signal": b["tier_bc_signal"],
            "kpi_roles": b["kpi_roles"],
            "country": b.get("country") or [],
            "seeded": row is not None,
        })
    return {"role": effective, "count": len(out), "brands": out}


@router.get("/my-brands")
def my_brands(
    role: Optional[str] = Query(None, description="Role whose primary-interest brands to list (admin only)"),
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(get_current_user),
):
    """The framework brands a role should browse, with a real db id + has_data flag.

    Role-scoped like the rest of the catalog: a non-admin sees only the brands
    whose workbook `kpi_roles` include their role; admin sees all framework
    brands (and may pass ?role= to preview one role's set). Used by the brand
    pickers on the Lab and Pharmacist dashboards.
    """
    effective = _resolve_role(current_user, role)

    brands = db.execute(
        select(Brand).where(Brand.category.isnot(None)).order_by(Brand.name)
    ).scalars().all()

    data_ids = set(
        db.execute(
            select(MentionEntity.entity_id)
            .where(MentionEntity.entity_type == EntityType.brand)
            .distinct()
        ).scalars().all()
    )

    from intelligence.inn_resolver import is_belgian_medicine
    out = []
    for b in brands:
        roles = b.kpi_roles or []
        # Every role can browse every tracked brand — the role only changes WHICH
        # KPIs are shown for the brand, not which brands are selectable. (kpi_roles
        # is kept in the payload as informational metadata.)
        out.append({
            "id": b.id,
            "name": b.name,
            "category": b.category,
            "manufacturer": b.manufacturer,
            "kpi_roles": roles,
            "has_data": b.id in data_ids,
            "is_medicine": is_belgian_medicine(b.name),
        })
    return {"role": effective, "count": len(out), "brands": out}


@router.get("/brand-catalog")
def brand_catalog(
    q: Optional[str] = Query(None, description="Case-insensitive name search"),
    category: Optional[str] = Query(None, description="Primary category code: NUT|RX|PAC|PEC|OTC"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(get_current_user),
):
    """Searchable, paginated catalog of every classified brand, with per-category
    facet counts. Backs the Brand Catalog page's category chips + search.

    Counts reflect the active *search* (so chips show how many matches per
    category) but not the active category filter, so the chips stay comparable.
    `has_data` flags brands that have linked mentions/reviews — i.e. whose KPI
    view will show live numbers rather than "Insufficient data".
    """
    if category is not None and category not in PRIMARY_CATEGORY_CODES:
        raise HTTPException(status_code=400, detail=f"Unknown category '{category}'")

    # Only classified brands belong in the catalog.
    base = select(Brand).where(Brand.primary_category.isnot(None))
    if q:
        base = base.where(Brand.name.ilike(f"%{q.strip()}%"))

    # Facet counts over the search-filtered set (ignoring the category filter).
    count_rows = dict(
        db.execute(
            base.with_only_columns(Brand.primary_category, func.count())
            .group_by(Brand.primary_category)
        ).all()
    )
    categories = [
        {**c, "count": int(count_rows.get(c["code"], 0))} for c in PRIMARY_CATEGORIES
    ]
    total_all = sum(count_rows.values())

    # Apply the category filter for the actual page.
    filtered = base
    if category:
        filtered = filtered.where(Brand.primary_category == category)
    total = db.execute(filtered.with_only_columns(func.count())).scalar_one()

    rows = db.execute(
        filtered.order_by(Brand.name).offset((page - 1) * page_size).limit(page_size)
    ).scalars().all()

    data_ids = set(
        db.execute(
            select(MentionEntity.entity_id)
            .where(MentionEntity.entity_type == EntityType.brand)
            .distinct()
        ).scalars().all()
    )
    from intelligence.inn_resolver import is_belgian_medicine

    brands = [{
        "id": b.id,
        "name": b.name,
        "primary_category": b.primary_category,
        "category": b.category,
        "confidence": b.category_confidence,
        "rationale": b.category_rationale,
        "manufacturer": b.manufacturer,
        "has_data": b.id in data_ids,
        "is_medicine": is_belgian_medicine(b.name),
    } for b in rows]

    return {
        "categories": categories,
        "total_all": total_all,
        "total": total,
        "page": page,
        "page_size": page_size,
        "category": category,
        "q": q,
        "brands": brands,
    }


@router.get("/brand-kpis")
def brand_kpis(
    brand_id: int = Query(..., description="Brand to resolve KPIs for"),
    role: Optional[str] = Query(None, description="Role lens (admin only)"),
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(get_current_user),
):
    """The role's workbook KPIs for one brand, with live values where we have them.

    Each KPI carries its `data_status`: live/partial KPIs come back with a real
    `value`/`display` computed from the ingested corpus; `data_needed` KPIs come
    back with `display = "Connect feed"` so the UI is honest about the missing
    Tier-C proprietary feed rather than inventing a number. Also returns the
    per-role data-source map (where the data comes from + what it tells *you*).
    """
    effective = _resolve_role(current_user, role)

    brand = db.get(Brand, brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="Brand not found")

    live = compute_live_values(db, brand)

    # Medicine-only KPIs (SAM drug-master + EU/BE pharmacovigilance) are
    # meaningless for a non-medicine — a cosmetic / supplement / infant-nutrition
    # product has no ATC, no RIZIV reimbursement, no adverse-event registry. They
    # are NOT "insufficient data", they simply don't apply, so we drop them from
    # the set for non-medicines rather than render a wall of "n/a" cards.
    from intelligence.inn_resolver import is_belgian_medicine
    is_med = is_belgian_medicine(brand.name)
    MEDICINE_ONLY = {
        "bm_atc_class", "bm_reimbursement", "bm_price",
        "ph_eu_safety", "ph_safety_signals", "ph_clinical_notes",
        "ph_adverse_reactions", "ph_safety_watch",
    }

    from core.framework_catalog import kpi_in_category

    kpis = []
    seen_names: set = set()   # admin aggregates all roles → dedupe shared KPIs
    for k in kpis_for_role(effective):
        # Category scope: a KPI that doesn't apply to this brand's primary
        # category (e.g. SAM/pharmacovigilance for a non-medicine category) is
        # dropped rather than shown as a wall of "n/a" cards.
        if not kpi_in_category(k["key"], brand.primary_category):
            continue
        # Belt-and-braces: even within a medicine-bearing category, a specific
        # brand may not be a registered medicine (e.g. a dermocosmetic in OTC).
        if k["key"] in MEDICINE_ONLY and not is_med:
            continue
        # The same metric is defined for >1 role (e.g. "Evidence base",
        # "Review momentum" for both brand_manager & marketing). In the admin
        # all-roles view that would render twice — show each KPI once.
        if k["kpi"] in seen_names:
            continue
        seen_names.add(k["kpi"])
        card = dict(k)
        vals = live.get(k.get("key"))
        if k["data_status"] == "data_needed":
            card.update({"value": None, "display": "Connect feed", "detail": None})
        elif vals:
            card.update(vals)
        else:
            # live/partial KPI but no data for this brand (e.g. momentum too sparse)
            card.update({"value": None, "display": "Insufficient data", "detail": None})
        kpis.append(card)

    insights = compute_insights(brand, live, effective)

    # Per-role data-source map: which sources feed this role + what they tell them.
    role_col = effective if effective in ROLE_LABELS else None
    sources = []
    for r in DATA_TO_KPI:
        use = r.get(role_col) if role_col else None
        if role_col and (not use or use == "n/a"):
            continue
        sources.append({"source": r["source"], "what_it_tells": r["what_it_tells"], "role_use": use})

    return {
        "role": effective,
        "brand": {"id": brand.id, "name": brand.name, "category": brand.category,
                  "is_medicine": is_med},
        "kpis": kpis,
        "insights": insights,
        "sources": sources,
    }


@router.get("/safety-profile")
def safety_profile(
    brand_id: int = Query(...),
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(get_current_user),
):
    """Product-safety profile ('Yuka for medicines'): four pillars (regulatory
    watch, side effects, supply, recent signal), each with source + confidence +
    honest 'insufficient data' — explains WHY, not just a score."""
    from intelligence.safety_profile import compute_safety_profile
    brand = db.get(Brand, brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="Brand not found")
    return compute_safety_profile(db, brand)


@router.get("/brand-packs")
def brand_packs(
    brand_id: int = Query(...),
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(get_current_user),
):
    """Canonical CNK packs for a brand (bilingual, pack-aware) — the brand →
    pack/SKU → substance drill-down, deduped across FR/NL and sources."""
    from models.pack import Pack
    packs = db.execute(
        select(Pack).where(Pack.brand_id == brand_id).order_by(Pack.in_stock.desc().nullslast(), Pack.cnk)
    ).scalars().all()
    return {
        "count": len(packs),
        "bilingual": sum(1 for p in packs if p.name_fr and p.name_nl),
        "packs": [{
            "cnk": p.cnk, "name_fr": p.name_fr, "name_nl": p.name_nl,
            "substance": p.active_substance, "atc": p.atc, "pharma_form": p.pharma_form,
            "price": float(p.price) if p.price is not None else None,
            "old_price": float(p.old_price) if p.old_price is not None else None,
            "in_stock": p.in_stock, "rating": float(p.rating) if p.rating is not None else None,
            "rating_count": p.rating_count, "is_prescription": p.is_prescription,
            "product_url": p.product_url, "sources": p.sources,
        } for p in packs],
    }


@router.get("/brand-actions")
def brand_actions(
    brand_id: int = Query(...),
    role: Optional[str] = Query(None),
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(get_current_user),
):
    """Analysis-driven Next-Best-Actions: generated from THIS brand's live KPIs
    (not a template), each citing the real numbers behind it."""
    from intelligence.inn_resolver import is_belgian_medicine
    effective = _resolve_role(current_user, role)
    brand = db.get(Brand, brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="Brand not found")
    live = compute_live_values(db, brand)
    actions = compute_brand_actions(brand, live, is_belgian_medicine(brand.name), effective)
    return {"brand": {"id": brand.id, "name": brand.name}, "count": len(actions), "actions": actions}


@router.get("/hcp-target")
def hcp_target_endpoint(
    brand_id: int = Query(...),
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(get_current_user),
):
    """Brand-specific HCP targeting: the prescriber specialty derived from the
    brand's authoritative SAM ATC code, plus the Belgian register to pull the
    named prescriber list from."""
    from intelligence.framework_kpis import hcp_target
    from intelligence.inn_resolver import is_belgian_medicine, sam_meta
    brand = db.get(Brand, brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="Brand not found")
    if not is_belgian_medicine(brand.name):
        return {"is_medicine": False, "target": None}
    return {"is_medicine": True, "target": hcp_target(brand, sam_meta(brand.name)),
            "register": "RIZIV/INAMI silverpages · Doctena (Belgian prescriber registers)"}


@router.get("/sources")
def list_sources(
    tier: Optional[str] = Query(None, regex="^[ABC]$", description="Filter by data tier A/B/C"),
    current_user: User = Depends(get_current_user),
):
    """The 20 data sources with tier, frequency, access, DIA layer, availability."""
    sources = DATA_SOURCES
    if tier:
        sources = [s for s in sources if s["tier"] == tier]
    return {
        "tier_labels": TIER_LABELS,
        "count": len(sources),
        "sources": [{**s, "tier_label": TIER_LABELS[s["tier"]]} for s in sources],
    }


@router.get("/data-to-kpi")
def get_data_to_kpi(
    role: Optional[str] = Query(None, description="Highlight one role's KPI column (admin only)"),
    current_user: User = Depends(get_current_user),
):
    """Source → per-role KPI matrix (the heart of the workbook)."""
    effective = _resolve_role(current_user, role)
    return {"role": effective, "rows": DATA_TO_KPI}


@router.get("/kpis")
def list_kpis(
    role: Optional[str] = Query(None, description="Filter to one role's KPIs (admin only)"),
    current_user: User = Depends(get_current_user),
):
    """KPI library, role-filtered, each tagged with honest data_status + endpoint.

    data_status: 'live' (real data today) · 'partial' (engine runs, proprietary
    leg sparse) · 'data_needed' (Tier-C feed not yet connected — UI shows a
    'connect feed' badge rather than a fabricated number).
    """
    effective = _resolve_role(current_user, role)
    kpis = kpis_for_role(effective)
    return {
        "role": effective,
        "count": len(kpis),
        "live": sum(1 for k in kpis if k["data_status"] == "live"),
        "data_needed": sum(1 for k in kpis if k["data_status"] == "data_needed"),
        "kpis": kpis,
    }