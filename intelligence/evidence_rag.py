"""Evidence-insight RAG over ingested PubMed abstracts.

Turns the literature corpus (which today is only *counted* — "106 papers") into
answerable insight. Brand-linked PubMed abstracts are embedded with OpenAI
`text-embedding-3-small` (cheap, 8k context → a full abstract in one vector) into
a dedicated 1536-dim Qdrant collection. A brand/molecule-scoped question then
retrieves the most relevant abstracts and the LLM synthesises a grounded, cited
answer — strictly from our ingested text, never invented.

  • index_pubmed(db)            — embed + upsert brand-linked abstracts
  • retrieve(brand_id, query)   — filtered semantic search → mention hits
  • answer(db, brand_id, query) — retrieve → LLM synthesis with [PMID] citations
"""
import uuid
from functools import lru_cache
from typing import List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from core.config import settings
from core.logging import get_logger

logger = get_logger(__name__)

INSIGHT_COLLECTION = "pharmawatch_insight"   # OpenAI 1536-dim insight corpus
EMBED_MODEL = "text-embedding-3-small"
EMBED_DIM = 1536
MIN_TEXT_LEN = 12   # skip empty/degenerate rows; reviews are short by nature
# Per-vector char budget. The model caps at ~8191 tokens (~32k chars); we chunk
# below that so a LONG document is embedded COMPLETELY across several vectors —
# never truncated. Most docs are one chunk; long news articles split into a few.
EMBED_CHAR_BUDGET = 28000   # per-vector budget (model caps ~8191 tokens); long docs chunk


def _chunk(t: str, size: int = EMBED_CHAR_BUDGET, overlap: int = 200) -> List[str]:
    """Split text into ≤size char windows on whitespace boundaries (with a small
    overlap) so the whole document is embedded, not just the head."""
    t = (t or "").strip()
    if len(t) <= size:
        return [t]
    out, i = [], 0
    while i < len(t):
        end = min(i + size, len(t))
        if end < len(t):
            sp = t.rfind(" ", i + size - overlap, end)
            if sp > i:
                end = sp
        out.append(t[i:end])
        i = end
    return out

# Source sets behind each insight lens.
EVIDENCE_SOURCES = ("pubmed",)
VOICE_SOURCES = ("farmaline", "medimarket", "trustpilot")
PATIENT_SOURCES = ("forum", "doctissimo", "reddit", "carenity", "youtube")


@lru_cache(maxsize=1)
def _openai():
    from openai import OpenAI
    if not settings.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY not configured")
    return OpenAI(api_key=settings.OPENAI_API_KEY)


def embed_openai(texts: List[str]) -> List[List[float]]:
    """Embed a batch with text-embedding-3-small. Inputs are pre-chunked to the
    char budget by the caller, so no truncation here."""
    resp = _openai().embeddings.create(model=EMBED_MODEL, input=list(texts))
    return [d.embedding for d in resp.data]


@lru_cache(maxsize=1)
def _qdrant():
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, VectorParams
    try:
        client = QdrantClient(url=settings.QDRANT_URL, timeout=3.0)
        client.get_collections()
    except Exception as exc:
        import os
        logger.warning("evidence_qdrant_fallback_embedded", error=str(exc))
        os.makedirs(settings.QDRANT_PATH, exist_ok=True)
        client = QdrantClient(path=settings.QDRANT_PATH)
    names = [c.name for c in client.get_collections().collections]
    if INSIGHT_COLLECTION not in names:
        client.create_collection(
            collection_name=INSIGHT_COLLECTION,
            vectors_config=VectorParams(size=EMBED_DIM, distance=Distance.COSINE),
        )
    return client


def index_corpus(db: Session, source_types, batch: int = 128) -> int:
    """Embed every brand-linked mention from `source_types` into the insight
    collection (OpenAI), tagging each point with source_type + brand_ids so the
    retrieval lenses can filter. Idempotent (re-upserts by mention-id point)."""
    from qdrant_client.models import PointStruct
    rows = db.execute(text("""
        SELECT m.id::text AS mid, m.source_type,
               coalesce(m.clean_text, m.raw_text) AS body,
               m.raw_metadata->>'pmid' AS pmid, m.raw_metadata->>'journal' AS journal,
               array_agg(DISTINCT me.entity_id) AS brand_ids
        FROM mentions m
        JOIN mention_entities me ON me.mention_id = m.id AND me.entity_type = 'brand'
        WHERE m.source_type = ANY(:src) AND m.is_deleted = false
          AND length(coalesce(m.clean_text, m.raw_text)) >= :minlen
        GROUP BY m.id, m.source_type, body, pmid, journal
    """), {"src": list(source_types), "minlen": MIN_TEXT_LEN}).fetchall()
    client = _qdrant()
    # Expand to (text, payload) units — long docs become several chunks so the
    # WHOLE document is embedded, not just the head. Chunk-point ids are
    # deterministic UUID5s (idempotent re-runs), payload carries the mention_id.
    units = []   # (text, point_id, payload)
    for r in rows:
        for j, ch in enumerate(_chunk(r.body)):
            pid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{r.mid}:{j}"))
            units.append((ch, pid, {
                "mention_id": r.mid, "source_type": r.source_type,
                "pmid": r.pmid, "journal": r.journal, "chunk": j,
                "brand_ids": [int(b) for b in r.brand_ids],
            }))
    n = 0
    for i in range(0, len(units), batch):
        block = units[i:i + batch]
        vecs = embed_openai([u[0] for u in block])
        pts = [PointStruct(id=pid, vector=v, payload=pl)
               for (_txt, pid, pl), v in zip(block, vecs)]
        client.upsert(collection_name=INSIGHT_COLLECTION, points=pts)
        n += len(pts)
        if (i // batch) % 20 == 0:
            logger.info("insight_indexing", points=n, total_units=len(units))
    logger.info("insight_indexed", points=n, docs=len(rows), sources=list(source_types))
    return n


def retrieve(brand_id: int, query: str, source_types=None, top_k: int = 6) -> List[dict]:
    """Top-k brand mentions semantically ranked against `query`, optionally
    restricted to a source set (the lens)."""
    from qdrant_client.models import Filter, FieldCondition, MatchValue, MatchAny
    qv = embed_openai([query])[0]
    must = [FieldCondition(key="brand_ids", match=MatchValue(value=brand_id))]
    if source_types:
        must.append(FieldCondition(key="source_type", match=MatchAny(any=list(source_types))))
    # Over-fetch: a long doc has several chunk-points, so fetch extra and dedup
    # to distinct mentions (best-scoring chunk wins).
    hits = _qdrant().search(
        collection_name=INSIGHT_COLLECTION, query_vector=qv, limit=top_k * 5,
        query_filter=Filter(must=must),
    )
    seen: dict = {}
    for h in hits:
        mid = h.payload.get("mention_id")
        if mid in seen:
            continue
        seen[mid] = {"mention_id": mid, "source_type": h.payload.get("source_type"),
                     "pmid": h.payload.get("pmid"), "journal": h.payload.get("journal"),
                     "score": round(h.score, 3)}
        if len(seen) >= top_k:
            break
    return list(seen.values())


_SYNTH_SYSTEM = """You are a pharmaceutical market analyst for PharmaWatch (Belgium/EU).
Answer the question STRICTLY from the provided source texts about the brand.
- Ground every claim in the texts; when a bracketed source id is shown (e.g. [PMID]), cite it.
- If the texts don't address the question, say so plainly — do NOT use outside knowledge.
- Be concise (3–6 sentences), neutral and specific. No marketing language."""


def reset_collection() -> None:
    """Drop + recreate the insight collection (used for a clean full re-embed so
    every point uses the same chunked scheme)."""
    from qdrant_client.models import Distance, VectorParams
    client = _qdrant()
    client.delete_collection(INSIGHT_COLLECTION)
    client.create_collection(
        collection_name=INSIGHT_COLLECTION,
        vectors_config=VectorParams(size=EMBED_DIM, distance=Distance.COSINE),
    )
    logger.info("insight_collection_reset")


def answer(db: Session, brand_id: int, query: Optional[str] = None,
           source_types=EVIDENCE_SOURCES, top_k: int = 6) -> dict:
    """Retrieve relevant mentions for the brand (within the lens's source set) and
    synthesise a cited answer grounded strictly in them."""
    from models.brand import Brand
    brand = db.get(Brand, brand_id)
    if brand is None:
        return {"error": "brand not found"}
    q = (query or "").strip() or (
        f"Summarise the clinical evidence on the efficacy, safety and tolerability of {brand.name}."
    )
    hits = retrieve(brand_id, q, source_types=source_types, top_k=top_k)
    if not hits:
        return {"brand": brand.name, "query": q, "answer": None,
                "sources": [], "note": "No indexed PubMed abstracts for this brand yet."}
    ids = [h["mention_id"] for h in hits]
    bodies = {str(r[0]): r[1] for r in db.execute(text(
        "SELECT id::text, coalesce(clean_text, raw_text) FROM mentions WHERE id::text = ANY(:ids)"
    ), {"ids": ids}).fetchall()}
    context = "\n\n".join(
        f"[{h['pmid'] or '?'}] ({h.get('journal') or 'journal n/a'})\n{bodies.get(h['mention_id'], '')[:6000]}"
        for h in hits
    )
    try:
        resp = _openai().chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[{"role": "system", "content": _SYNTH_SYSTEM},
                      {"role": "user", "content": f"QUESTION: {q}\n\nABSTRACTS:\n{context}"}],
            max_completion_tokens=400, temperature=0,
        )
        synthesis = (resp.choices[0].message.content or "").strip()
    except Exception as exc:
        logger.warning("evidence_synth_failed", error=str(exc))
        synthesis = None
    return {
        "brand": brand.name, "query": q, "answer": synthesis,
        "sources": [{"pmid": h["pmid"], "journal": h["journal"], "score": h["score"]} for h in hits],
    }
